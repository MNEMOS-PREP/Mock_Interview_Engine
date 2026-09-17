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

from sqlmodel import Session

from . import outbox
from .adapters import Upstreams
from .engine import Engine, ThetaCache

log = logging.getLogger("uvicorn.error")

#: Seconds between sweeps. `0` turns the sweeper off, which is what a demo
#: wants when it is showing the queue filling up.
SWEEP_S = float(os.getenv("M06_OUTBOX_SWEEP_S", "30"))

#: Sessions per sweep. A backlog is cleared by sweeping again, not by one long
#: sweep holding the write lock while a student is mid-answer.
SESSIONS_PER_SWEEP = 5

SessionFactory = Callable[[], Session]


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


__all__ = ["SESSIONS_PER_SWEEP", "SWEEP_S", "run_forever", "running", "sweep_once"]
