"""Presence — FR-6.13, EC-6.8, spec §6.8, and §8's "Disconnected: timer paused".

In text mode a student is in the room while their stage is open, and the stage
is open while its event stream is attached. So the stream is the presence
signal, and three facts follow from it:

* **Gone.** The last stream for a session detaches. This process notes when —
  in memory, and nothing is written yet, because a refresh or a network blip
  detaches and re-attaches inside a couple of seconds and the student never
  left. If nothing comes back within `LOST_AFTER_S`, the disconnect becomes
  `connection.lost`, dated when the stream went. The clock stops there. It is
  not a pause: the student's one pause (FR-6.12) is theirs to spend, and a
  dropped connection is not spending it.
* **Back.** A stream re-attaches, or the student does anything — answers, asks
  for a hint, pauses. `connection.resumed`: the reconnect is counted, and the
  clock restarts after `GRACE_S` ("a 30-second grace before the timer
  restarts"), or at once for an action, because a student who is answering
  is already going.
* **Never back.** The sweeper ends a session away longer than an abandoned
  pause (EC-6.14). A stopped clock must not hold a candidate's one slot for
  ever — that lockout was fixed once before day 9 and is not coming back
  through a side door.

Nothing here runs on a timer. A pending disconnect is written by whichever
comes first — the student's return or the sweeper's next pass — and is dated
from the moment the stream went either way. So the logic is plain functions of
`now`, and a test drives it without sleeping.

The pending notes live in this process, like the token broker beside them: one
API process in Phase 1. After a restart there are none, and a student who left
before it is caught by the session's own clock running out instead
(`sweeper.ABANDONED_LIVE_GRACE_S`).
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from ai_core.timeutil import as_utc
from sqlmodel import Session, select

from . import store
from .contracts import SessionStatus
from .models import InterviewSession, SessionEvent
from .state import InvalidTransition, SessionState

log = logging.getLogger(__name__)

#: A detach shorter than this is a refresh or a blip, not a disconnect.
LOST_AFTER_S = 5.0
#: §6.8: "a 30-second grace before the timer restarts".
GRACE_S = 30.0
#: §6.8: "> 2 reconnects triggers a modality-degradation suggestion".
SUGGEST_AFTER = 2


class Presence:
    """Streams attached per session, and when the last one went."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attached: dict[uuid.UUID, int] = {}
        self._gone_at: dict[uuid.UUID, datetime] = {}

    def attach(self, session_id: uuid.UUID) -> None:
        with self._lock:
            self._attached[session_id] = self._attached.get(session_id, 0) + 1

    def detach(self, session_id: uuid.UUID, at: datetime) -> None:
        with self._lock:
            left = self._attached.get(session_id, 0) - 1
            if left > 0:
                # Another tab is still open: the student has not gone anywhere.
                self._attached[session_id] = left
                return
            self._attached.pop(session_id, None)
            self._gone_at[session_id] = at

    def attached(self, session_id: uuid.UUID) -> int:
        with self._lock:
            return self._attached.get(session_id, 0)

    def take_gone(self, session_id: uuid.UUID) -> datetime | None:
        """The pending disconnect, removed — whoever takes it writes it."""
        with self._lock:
            return self._gone_at.pop(session_id, None)

    def pending(self) -> dict[uuid.UUID, datetime]:
        """Disconnects noted and not yet written, for sessions nobody is in."""
        with self._lock:
            return {sid: at for sid, at in self._gone_at.items() if not self._attached.get(sid)}


presence = Presence()


def back(
    db: Session,
    session_id: uuid.UUID,
    now: datetime,
    *,
    grace_s: float = GRACE_S,
) -> SessionState | None:
    """The student is here. Writes the disconnect that was pending, if it was
    long enough to be one, and then the return.

    Idempotent: both events are keyed by which disconnect they are (`away:N`,
    `back:N`), so two tabs re-attaching at once count one reconnect.
    """
    gone_at = presence.take_gone(session_id)
    row = store.get_session_row(db, session_id)
    if row is None:
        return None
    state = store.load_state(db, session_id)
    if state.status is not SessionStatus.live:
        return state
    if (
        gone_at is not None
        and state.flags.away_since is None
        and (now - gone_at).total_seconds() >= LOST_AFTER_S
    ):
        state = _lost(db, row, state, gone_at)
    if state.flags.away_since is None:
        return state
    away_s = max((now - state.flags.away_since).total_seconds(), 0.0)
    try:
        return store.record(
            db,
            row,
            "connection.resumed",
            step=f"back:{state.flags.reconnect_count + 1}",
            payload={"grace_s": grace_s, "away_s": round(away_s, 1)},
            at=now,
        ).state
    except (InvalidTransition, store.ConcurrentWrite):
        return store.load_state(db, session_id)


def sweep(session_factory: Callable[[], Session], now: datetime) -> list[str]:
    """Write the disconnects nobody came back from. Run by the sweeper."""
    written: list[str] = []
    for session_id, gone_at in presence.pending().items():
        if (now - gone_at).total_seconds() < LOST_AFTER_S:
            continue
        if presence.take_gone(session_id) is None:
            continue  # the student came back between the two reads
        try:
            with session_factory() as db:
                row = store.get_session_row(db, session_id)
                if row is None:
                    continue
                state = store.load_state(db, session_id)
                if state.status is SessionStatus.live and state.flags.away_since is None:
                    _lost(db, row, state, gone_at)
                    written.append(str(session_id))
        except Exception:  # noqa: BLE001 - one session must not stop the sweep
            log.warning("M06 presence: %s could not be marked away", session_id, exc_info=True)
    return written


def _lost(
    db: Session, row: InterviewSession, state: SessionState, gone_at: datetime
) -> SessionState:
    # Dated when the stream went — unless the log has moved on since (a step
    # that was already running finished), so the log's clock never runs
    # backwards.
    last = db.exec(
        select(SessionEvent.at)
        .where(SessionEvent.session_id == row.id)
        .order_by(SessionEvent.seq.desc())
    ).first()
    at = max(gone_at, as_utc(last)) if last is not None else gone_at
    try:
        return store.record(
            db,
            row,
            "connection.lost",
            step=f"away:{state.flags.reconnect_count + 1}",
            at=at,
        ).state
    except (InvalidTransition, store.ConcurrentWrite):
        return store.load_state(db, row.id)


def suggestion(state: SessionState) -> str | None:
    """§6.8's "> 2 reconnects" suggestion, for text mode.

    The spec's version degrades the modality — voice to text. Text is already
    the floor in Phase 1, so what a student whose connection keeps dropping
    can actually do is stop the clock or keep what they have.
    """
    count = state.flags.reconnect_count
    if count <= SUGGEST_AFTER or state.is_final:
        return None
    way_out = (
        "end here" if state.flags.pause_used else "pause once, for up to five minutes, or end here"
    )
    return (
        f"Your connection has dropped {count} times. If it keeps happening, you can "
        f"{way_out} — your notes keep everything you've answered."
    )


__all__ = [
    "GRACE_S",
    "LOST_AFTER_S",
    "SUGGEST_AFTER",
    "Presence",
    "back",
    "presence",
    "suggestion",
    "sweep",
]
