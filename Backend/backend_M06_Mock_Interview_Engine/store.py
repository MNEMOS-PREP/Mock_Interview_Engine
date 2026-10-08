"""`record()` — the only way a session changes. Spec §6.8.

Everything that happens to a session is an event, and this file is the one
place an event is written. The order is deliberate:

    read     state at seq N-1  (checkpoint, then any events after it)
    validate apply(state, event) — an impossible transition never reaches disk
    in tx    insert the event at seq N
    in tx    update the projections: session status, the turn row
    commit
    after    write the checkpoint, best effort

**The event log is the compare-and-swap.** `(session_id, seq)` is unique, so
two tabs that both read seq N-1 cannot both write seq N: the loser's insert
fails, it re-reads, and re-validates against what the winner did — which is
how "this question was already answered in another tab" becomes a 409 rather
than a second answer.

**`(session_id, turn_index, step)` is the idempotency key.** A retried request
finds its own event already written and returns it instead of acting twice
(AC-6.16). `attempt` is not in the key; Revision 1 put it there, which gave
every retry a fresh key.

**The checkpoint is a cache, written after the commit.** It is only ever moved
forward (`last_seq` must increase), and a missing, stale or unreadable one is
re-folded from the log. So a failed checkpoint write costs a slower next read
and nothing else — §10's "checkpoint write fails → continue, report from the
event log" is true by construction rather than by a fallback path.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ai_core.timeutil import utcnow
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .contracts import OCCUPYING_STATUSES, SessionStatus
from .models import Checkpoint, InterviewSession, SessionEvent, TurnRecord
from .state import SessionState, apply, fold

log = logging.getLogger(__name__)

#: M05's freshness window (FR-5.x, `FRESHNESS_DAYS`). M06 holds the only
#: durable record of what a student was asked, so it supplies the ids.
FRESHNESS_DAYS = 90

#: Re-read and re-validate this many times when another writer took our seq.
MAX_APPEND_RETRIES = 3


#: Called with every event this process writes, immediately after it commits.
#: The app points it at the token broker so the live stream is push-driven:
#: polling the log for them instead means a reader blocked behind the writer's
#: SQLite lock, and a "live" preview that arrives after the answer it previews.
#: None in tests and in any process with no stream attached.
NOTIFY: Callable[[SessionEvent], None] | None = None


def notify(event: SessionEvent) -> None:
    if NOTIFY is None:
        return
    try:
        NOTIFY(event)
    except Exception:  # noqa: BLE001 - a subscriber must never fail a write
        log.warning("event notify failed for %s", event.session_id)


class LiveSessionExists(Exception):
    """EC-6.13. The student already has a live or paused session."""

    def __init__(self, session_id: uuid.UUID, status: str = "live"):
        self.session_id = session_id
        self.status = status
        # Named, because "live" for a session the student PAUSED sent them
        # looking for an interview that was not running.
        super().__init__(f"candidate already has a {status} session {session_id}")


class ConcurrentWrite(Exception):
    """Another writer kept winning the same seq. Surfaces as a 409."""


@dataclass
class Recorded:
    state: SessionState
    event: SessionEvent
    #: False when the idempotency key already existed — nothing was done.
    created: bool


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────
#  Reading
# ─────────────────────────────────────────────────────────────────────────


def events_for(db: Session, session_id: uuid.UUID, *, after_seq: int = 0) -> list[SessionEvent]:
    return list(
        db.exec(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .where(SessionEvent.seq > after_seq)
            .order_by(SessionEvent.seq)
        ).all()
    )


def load_state(db: Session, session_id: uuid.UUID) -> SessionState:
    """The checkpoint, brought up to date — or a full re-fold if it is unusable."""
    checkpoint = db.get(Checkpoint, session_id)
    base: SessionState | None = None
    if checkpoint is not None and checkpoint.state_json:
        try:
            base = SessionState.model_validate(checkpoint.state_json)
        except ValidationError:
            # The state shape changed since this was written. A cache that
            # cannot be read is a cache miss, not an error.
            log.info("checkpoint for %s unreadable; re-folding", session_id)
            base = None
    after = base.last_seq if base is not None else 0
    tail = events_for(db, session_id, after_seq=after)
    if base is not None and not tail:
        return base
    if base is None:
        return fold(tail)
    return fold(tail, start=base)


def replay(db: Session, session_id: uuid.UUID) -> SessionState:
    """FR-6.19. A fold from nothing, ignoring any checkpoint."""
    return fold(events_for(db, session_id))


def get_session_row(db: Session, session_id: uuid.UUID) -> InterviewSession | None:
    return db.get(InterviewSession, session_id)


def sessions_for(
    db: Session, candidate_id: uuid.UUID, *, limit: int = 50
) -> list[InterviewSession]:
    return list(
        db.exec(
            select(InterviewSession)
            .where(InterviewSession.candidate_id == candidate_id)
            .order_by(InterviewSession.created_at.desc())
            .limit(limit)
        ).all()
    )


def occupying_session(db: Session, candidate_id: uuid.UUID) -> InterviewSession | None:
    return db.exec(
        select(InterviewSession).where(InterviewSession.occupying_key == str(candidate_id))
    ).first()


def occupied_sessions(db: Session) -> list[InterviewSession]:
    """Every session holding a candidate's one slot — live or paused.

    EC-6.13 blocks a second session while one of these exists, which is right
    while somebody is in the room and a lockout once they have gone. See
    `sweeper.close_abandoned`.
    """
    return list(
        db.exec(select(InterviewSession).where(InterviewSession.occupying_key.is_not(None))).all()
    )


def seen_item_ids(
    db: Session, candidate_id: uuid.UUID, *, now: datetime | None = None, days: int = FRESHNESS_DAYS
) -> set[uuid.UUID]:
    """Items this student was actually asked — M05 has no durable record of it."""
    since = (now or utcnow()) - timedelta(days=days)
    rows = db.exec(
        select(TurnRecord.question_id)
        .where(TurnRecord.candidate_id == candidate_id)
        .where(TurnRecord.role == "interviewer")
        .where(TurnRecord.question_id.is_not(None))
        .where(TurnRecord.at >= since)
    ).all()
    return {row for row in rows if row is not None}


#: How long a question the student skipped stays out of their interviews.
SKIPPED_KEPT_OUT_DAYS = 180


def skipped_item_ids(
    db: Session,
    candidate_id: uuid.UUID,
    *,
    now: datetime | None = None,
    days: int = SKIPPED_KEPT_OUT_DAYS,
) -> set[uuid.UUID]:
    """Questions this student skipped, in any interview of the last `days`
    (2026-10-08). Not freshness, which M05 may relax when the bank runs thin:
    the student said no to these, and being handed one again in the next
    interview is the repetition they called irritating. Sent as a hard
    exclusion, like a question already asked in this interview."""
    since = (now or utcnow()) - timedelta(days=days)
    sessions = db.exec(
        select(InterviewSession.id).where(InterviewSession.candidate_id == candidate_id)
    ).all()
    if not sessions:
        return set()
    events = db.exec(
        select(SessionEvent)
        .where(SessionEvent.session_id.in_(sessions))  # type: ignore[attr-defined]
        .where(SessionEvent.kind == "question.skipped")
        .where(SessionEvent.at >= since)
    ).all()
    turn_ids = set()
    for event in events:
        try:
            turn_ids.add(uuid.UUID(str(event.payload.get("question_turn"))))
        except (TypeError, ValueError):
            continue
    if not turn_ids:
        return set()
    rows = db.exec(
        select(TurnRecord.question_id)
        .where(TurnRecord.id.in_(turn_ids))  # type: ignore[attr-defined]
        .where(TurnRecord.question_id.is_not(None))  # type: ignore[union-attr]
    ).all()
    return {row for row in rows if row is not None}


def recent_panelists(
    db: Session,
    candidate_id: uuid.UUID,
    *,
    exclude: uuid.UUID | None = None,
    sessions: int = 3,
) -> frozenset[str]:
    """Who this student met in their last few interviews: everyone the plans
    of those that started seated (2026-10-07). The panel seats others first,
    so the same two people do not run every interview."""
    ids = db.exec(
        select(InterviewSession.id)
        .where(InterviewSession.candidate_id == candidate_id)
        .where(InterviewSession.started_at.is_not(None))  # type: ignore[union-attr]
        .order_by(InterviewSession.created_at.desc())  # type: ignore[attr-defined]
        .limit(sessions + 1)
    ).all()
    met: set[str] = set()
    for session_id in [i for i in ids if i != exclude][:sessions]:
        event = db.exec(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
            .where(SessionEvent.kind == "plan.set")
            .order_by(SessionEvent.seq.desc())  # type: ignore[attr-defined]
        ).first()
        plan = (event.payload or {}).get("plan") or {} if event is not None else {}
        met.update(str(p) for p in plan.get("panel") or [])
        met.update(str(s["persona_id"]) for s in plan.get("segments") or [] if s.get("persona_id"))
    return frozenset(met)


# ─────────────────────────────────────────────────────────────────────────
#  Writing
# ─────────────────────────────────────────────────────────────────────────


def _existing(
    db: Session, session_id: uuid.UUID, turn_index: int, step: str
) -> SessionEvent | None:
    return db.exec(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .where(SessionEvent.turn_index == turn_index)
        .where(SessionEvent.step == step)
    ).first()


def _project(db: Session, row: InterviewSession, state: SessionState, event: SessionEvent) -> None:
    """Derived rows, updated in the same transaction as the event."""
    row.status = state.status.value
    row.occupying_key = str(state.candidate_id) if state.status in OCCUPYING_STATUSES else None
    row.started_at = state.started_at
    row.ended_at = state.ended_at
    row.end_reason = state.end_reason
    db.add(row)

    if event.kind in ("question.asked", "answer.received"):
        turn = state.turn(uuid.UUID(str(event.payload["turn_id"])))
        if turn is not None:
            db.add(
                TurnRecord(
                    id=turn.turn_id,
                    session_id=state.session_id,
                    candidate_id=state.candidate_id,
                    turn_index=turn.turn_index,
                    segment_index=turn.segment_index,
                    role=turn.role,
                    text=turn.text,
                    text_sha256=sha256(turn.text),
                    modality=turn.modality.value,
                    question_id=turn.question_id,
                    question_source=turn.question_source,
                    rubric_round_type=turn.rubric_round_type,
                    probe_depth=turn.probe_depth,
                    probe_move=turn.probe_move,
                    hint_level_used=turn.hint_level_used,
                    deliberately_false=turn.deliberately_false,
                    completion_reason=event.payload.get("completion_reason"),
                    at=turn.at,
                )
            )


def write_checkpoint(db: Session, state: SessionState) -> bool:
    """Move the cache forward, never back. Best effort; False when it did not move."""
    try:
        payload = state.model_dump(mode="json")
        existing = db.get(Checkpoint, state.session_id)
        if existing is None:
            db.add(
                Checkpoint(
                    session_id=state.session_id,
                    version=1,
                    last_seq=state.last_seq,
                    state_json=payload,
                    updated_at=utcnow(),
                )
            )
            db.commit()
            return True
        result = db.exec(
            update(Checkpoint)
            .where(Checkpoint.session_id == state.session_id)
            .where(Checkpoint.last_seq < state.last_seq)
            .values(
                version=Checkpoint.version + 1,
                last_seq=state.last_seq,
                state_json=payload,
                updated_at=utcnow(),
            )
        )
        db.commit()
        db.expire_all()
        return result.rowcount == 1
    except Exception:  # noqa: BLE001 - §10: a checkpoint failure is not a session failure
        db.rollback()
        log.warning("checkpoint write failed for %s; the event log is intact", state.session_id)
        return False


def record(
    db: Session,
    row: InterviewSession,
    kind: str,
    *,
    step: str,
    turn_index: int = 0,
    payload: dict | None = None,
    at: datetime | None = None,
) -> Recorded:
    """Append one event, or return the one already written under this key."""
    payload = payload or {}
    for _attempt in range(MAX_APPEND_RETRIES):
        existing = _existing(db, row.id, turn_index, step)
        if existing is not None:
            return Recorded(state=load_state(db, row.id), event=existing, created=False)

        prior = None if kind == "session.created" else load_state(db, row.id)
        # The seq comes from the state we validate against, NOT from max(seq)
        # read afterwards. Read afterwards, a writer that lost the race would
        # take N+1 and commit an event validated against a state missing the
        # winner's — the second answer to an already-answered question.
        seq = (prior.last_seq if prior is not None else 0) + 1
        when = at or utcnow()
        # Validate BEFORE writing: an impossible transition raises here and
        # nothing reaches the log.
        state = apply(prior, kind, payload, when, seq)

        event = SessionEvent(
            session_id=row.id,
            seq=seq,
            turn_index=turn_index,
            step=step,
            kind=kind,
            payload=payload,
            at=when,
        )
        db.add(event)
        _project(db, row, state, event)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            db.expire_all()
            if "occupying_key" in str(exc.orig):
                live = occupying_session(db, state.candidate_id)
                raise LiveSessionExists(live.id if live else row.id) from exc
            # Somebody else took this seq, or wrote this step. Re-read and let
            # the loop decide which.
            continue
        db.refresh(event)
        notify(event)
        try:
            write_checkpoint(db, state)
        except Exception:  # noqa: BLE001 - the event is committed; the cache can lag
            db.rollback()
            log.warning("checkpoint write raised for %s; continuing from the log", row.id)
        return Recorded(state=state, event=event, created=True)
    raise ConcurrentWrite(f"could not append {kind} to {row.id}")


def create_session(
    db: Session,
    *,
    candidate_id: uuid.UUID,
    kind: str,
    mode: str,
    minutes: int,
    jd_id: uuid.UUID | None = None,
    source_module: str | None = None,
    source_ref: str | None = None,
    drill: dict | None = None,
    focus_concepts: list[str] | None = None,
    focus_label: str | None = None,
    track: str | None = None,
    include_resume: bool = False,
    resume_id: uuid.UUID | None = None,
) -> tuple[InterviewSession, SessionState]:
    """A new session in `planned`. Refused while one is live or paused (EC-6.13).

    A `planned` session is superseded rather than blocking: a student who
    closed the tab on the plan preview has not started an interview.
    """
    live = occupying_session(db, candidate_id)
    if live is not None:
        raise LiveSessionExists(live.id, load_state(db, live.id).status.value)

    stale = db.exec(
        select(InterviewSession)
        .where(InterviewSession.candidate_id == candidate_id)
        .where(InterviewSession.status == SessionStatus.planned.value)
    ).all()
    for old in stale:
        record(db, old, "session.aborted", step="abort", payload={"reason": "superseded"})

    row = InterviewSession(
        candidate_id=candidate_id,
        kind=kind,
        mode=mode,
        requested_minutes=minutes,
        jd_id=jd_id,
        source_module=source_module,
        source_ref=source_ref,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    created = record(
        db,
        row,
        "session.created",
        step="created",
        payload={
            "session_id": str(row.id),
            "candidate_id": str(candidate_id),
            "kind": kind,
            "mode": mode,
            "requested_minutes": minutes,
            "jd_id": str(jd_id) if jd_id else None,
            "source_module": source_module,
            "source_ref": source_ref,
            "drill": drill,
            "focus_concepts": list(focus_concepts or []),
            "focus_label": focus_label,
            "track": track,
            "include_resume": include_resume,
            "resume_id": str(resume_id) if resume_id else None,
        },
    )
    return row, created.state


__all__ = [
    "FRESHNESS_DAYS",
    "ConcurrentWrite",
    "LiveSessionExists",
    "Recorded",
    "create_session",
    "events_for",
    "get_session_row",
    "load_state",
    "occupying_session",
    "record",
    "replay",
    "seen_item_ids",
    "sessions_for",
    "sha256",
    "write_checkpoint",
]
