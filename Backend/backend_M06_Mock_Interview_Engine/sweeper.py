"""The worker the outbox docstring promises — FR-6.14.

`outbox.drain` moves what is owed, and two things call it: the request that
created the work (a background task) and an explicit drain. Neither is enough
on its own. A send that fails puts its row back to `pending`, and if the
student has gone home nothing ever asks again — the first live run left an
answer queued for M13 for three minutes and counting, because the evaluation
that timed out had nobody left to retry it.

So one task per process sweeps every session that still owes something. It is
deliberately dull: no scheduling, no priorities, no backoff curve. A row is
tried again, `MAX_ATTEMPTS` times, and then held where somebody can see it.

**It runs in a thread.** `drain` is synchronous — SQLite and `urlopen` both
are — and the event loop is serving a conversation. `asyncio.to_thread` keeps
the sweep off it.

**It is off in tests.** The suite never starts the lifespan, and `sweep_once`
is a plain function so the behaviour can be tested without a loop at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable, Iterator
from datetime import datetime

from ai_core.timeutil import utcnow
from sqlmodel import Session

from . import outbox, store
from .adapters import Upstreams
from .contracts import SessionStatus
from .engine import Engine, ThetaCache

log = logging.getLogger("uvicorn.error")

#: Seconds between sweeps. `0` turns the sweeper off, which is what a demo
#: wants when it is showing the queue filling up.
SWEEP_S = float(os.getenv("M06_OUTBOX_SWEEP_S", "30"))

#: Sessions per sweep. A backlog is cleared by sweeping again, not by one long
#: sweep holding the write lock while a student is mid-answer.
SESSIONS_PER_SWEEP = 5

#: EC-6.14 — "student pauses and never returns: auto-close after 30 min,
#: partial report generated". FR-6.12 caps the pause at five, but that cap is
#: only applied by a student coming BACK; this is the one that applies when
#: nobody does.
ABANDONED_PAUSE_S = 30 * 60

#: A live session nobody is in. Its own clock already says the interview is
#: over — the turn loop just never got a turn to notice on. Generous, because
#: a student thinking for ten minutes is still in the room, and the session's
#: own planned length is already counted before this is added.
ABANDONED_LIVE_GRACE_S = 30 * 60

SessionFactory = Callable[[], Session]


def close_abandoned(
    session_factory: SessionFactory,
    upstreams: Upstreams,
    llm,
    *,
    now: datetime | None = None,
) -> list[str]:
    """End sessions nobody is in — EC-6.14, and a lockout until now.

    A session holds its candidate's one slot while it is live or paused
    (EC-6.13's `occupying_key`), which is right while somebody is in the room.
    Nothing released it when they left: a student who paused and closed the
    tab was refused **every future interview**, permanently, with "candidate
    already has a live session". That is not a missing feature, it is a door
    that locks behind you.

    Ending the session frees the slot and produces a report, because a report
    exists for every session that has an event log (AC-6.1) — so an abandoned
    interview becomes the partial record EC-6.14 asks for rather than a row
    nobody can get past.
    """
    closed: list[str] = []
    now = now or utcnow()
    with session_factory() as db:
        candidates = [
            row.id
            for row in store.occupied_sessions(db)
            if _abandoned(store.load_state(db, row.id), now)
        ]
    for session_id in candidates:
        try:
            with session_factory() as db:
                engine = Engine(db=db, upstreams=upstreams, llm=llm, thetas=ThetaCache())
                engine.end(session_id, "abandoned")
        except Exception:  # noqa: BLE001 - one stuck session must not stop the rest
            log.warning("M06 sweep: %s could not be closed", session_id, exc_info=True)
            continue
        closed.append(str(session_id))
    if closed:
        log.info("M06 sweep: closed %d abandoned session(s)", len(closed))
    return closed


def _abandoned(state, now) -> bool:
    """True when nobody is coming back to this one."""
    if state.status is SessionStatus.paused:
        paused_at = state.flags.paused_at
        return paused_at is not None and (now - paused_at).total_seconds() > ABANDONED_PAUSE_S
    if state.status is SessionStatus.live:
        # Its own clock ran out, and then some. Measured on `time_used_s`
        # rather than on what is left, because `time_remaining_s` clamps at
        # zero — "overdue by an hour" and "just finished" look identical
        # through it, which made the first version of this check dead code.
        return state.time_used_s(now) > state.requested_minutes * 60 + ABANDONED_LIVE_GRACE_S
    return False


def sweep_once(
    session_factory: SessionFactory,
    upstreams: Upstreams,
    llm,
    *,
    thetas: ThetaCache | None = None,
) -> outbox.Drained:
    """Retry every session that still owes something. Never raises.

    Delivery goes through `Engine.deliver` rather than `outbox.drain` so that
    what M13 said is recorded as an event here too — a score that arrived on a
    sweep has to reach the report the same way as one that arrived on a turn.
    """
    total = outbox.Drained()
    close_abandoned(session_factory, upstreams, llm)
    with session_factory() as db:
        owing = outbox.sessions_owing(db, limit=SESSIONS_PER_SWEEP)
    for session_id in owing:
        try:
            with session_factory() as db:
                engine = Engine(db=db, upstreams=upstreams, llm=llm, thetas=thetas or ThetaCache())
                one = engine.deliver(session_id)
        except Exception:  # noqa: BLE001 - a sweep failure is a queued row
            log.warning("M06 sweep: %s could not be drained; its rows stay queued", session_id)
            continue
        total.evaluations_sent += one.evaluations_sent
        total.ledger_sent += one.ledger_sent
        total.failed += one.failed
        total.held += one.held
        total.in_flight += one.in_flight
    if total.moved or total.held:
        log.info(
            "M06 sweep: %d delivered, %d held, %d still waiting",
            total.moved,
            total.held,
            total.failed,
        )
    return total


async def run_forever(
    session_factory: SessionFactory, upstreams: Callable[[], Upstreams], llm: Callable[[], object]
) -> None:
    """Sweep until cancelled. The upstreams and the model are resolved per
    sweep, so a module that came back up is used on the next one."""
    while True:
        await asyncio.sleep(SWEEP_S)
        try:
            await asyncio.to_thread(sweep_once, session_factory, upstreams(), llm())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the sweeper outlives its failures
            log.warning("M06 sweep failed; the next one will try again", exc_info=True)


@contextlib.contextmanager
def running(
    session_factory: SessionFactory, upstreams: Callable[[], Upstreams], llm: Callable[[], object]
) -> Iterator[asyncio.Task | None]:
    """Start the sweeper for the life of the app, and stop it on shutdown."""
    if SWEEP_S <= 0:
        log.info("M06 outbox sweeper off (M06_OUTBOX_SWEEP_S=%s)", SWEEP_S)
        yield None
        return
    task = asyncio.get_running_loop().create_task(run_forever(session_factory, upstreams, llm))
    log.info("M06 outbox sweeper on — every %.0fs", SWEEP_S)
    try:
        yield task
    finally:
        task.cancel()


__all__ = [
    "ABANDONED_LIVE_GRACE_S",
    "ABANDONED_PAUSE_S",
    "SESSIONS_PER_SWEEP",
    "SWEEP_S",
    "close_abandoned",
    "run_forever",
    "running",
    "sweep_once",
]
