"""What M06 owes other modules, written with the turn — FR-6.14, FR-6.24.

Three obligations, one mechanism. An answered turn owes M13 an evaluation, and
the requirements behind a question owe M02 a coverage row. Both are written to
a table **in the same transaction as the turn** and delivered afterwards, by a
background task or by an explicit drain.

**Why not just call them.** M13's `POST /v1/evaluations` scores synchronously —
p95 15 s with the full ensemble — and Trap 2 is the module's most important
architectural decision: *evaluation never blocks the conversation*. Calling it
inline would put the frontier ensemble on the hot path. Calling it in a thread
and forgetting would lose the score when the process restarts. A row in the
same transaction is the only version that survives both.

**One sender at a time.** A row is *claimed* — moved to `sending` by a
conditional UPDATE that commits before the network call — so a background task
and an explicit drain racing over the same session cannot both post it. Without
that claim M13 re-scores the same turn concurrently with itself, which is how
one answer cost three ensembles and a 60 s timeout on the first live run. A
claim expires (`STALE_CLAIM_S`), because a process that dies mid-send must not
strand the row forever.

**Delivery is still at-least-once, and that is safe by design.** M13 keys an
evaluation on `turn_id`, M02's ledger is append-only with the newest state per
`(session, requirement, turn)` winning, and both were built to be replayed —
M13's own outbox to M04 works the same way. A row that we cannot prove was
delivered is retried; a row M13 already has is a no-op there.

**Nothing here decides anything about a student.** It moves already-decided
facts. The scores come back to M06 only as a status, never as a number: M13
owns the number and its display gate, and a copy here would be the one that
went stale (Rule 3).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from ai_core.timeutil import utcnow
from sqlalchemy import update as sql_update
from sqlmodel import Session, select

from .adapters import Upstreams, UpstreamUnavailable
from .contracts import SessionKind
from .items import Item
from .models import ArtifactOutbox, EvaluationOutbox, InterviewSession, LedgerOutbox
from .modes import ENSEMBLE_BY_MODE as _ENSEMBLE_BY_MODE
from .state import SessionState

log = logging.getLogger("uvicorn.error")

#: After this many failed attempts a row stops being retried automatically and
#: stays visible instead. A row nobody can see is a row nobody fixes.
MAX_ATTEMPTS = 5

#: How many rows one drain moves. A student's own request pays for its own
#: turn; a backlog is drained by repeating, not by one long request.
DRAIN_LIMIT = 10

#: A claim older than this belonged to a process that is not coming back. It
#: is longer than the M13 client's own timeout (60 s), so a row is never taken
#: from a request that is merely slow.
STALE_CLAIM_S = 180

PENDING, SENDING, SENT, HELD = "pending", "sending", "sent", "held"

#: M13's ensemble configs, per mode — `modes.py` is the one table, and this
#: name is kept because the fairness gate and the contract tests read it.
ENSEMBLE_BY_MODE = _ENSEMBLE_BY_MODE


# ─────────────────────────────────────────────────────────────────────────
#  The request M13 receives
# ─────────────────────────────────────────────────────────────────────────

#: Spec §6.3. Exactly these keys reach M13 — asserted by AC-6.2, because what
#: is ABSENT is the blind-scoring property: no interviewer text, no probe
#: intent, no steelman flag, no verdict, no other turn. `candidate_id` is the
#: one identity field, because M13 needs it to address the observation and
#: strips it before its own evaluator projection.
EVALUATION_KEYS = frozenset(
    {
        "turn_id",
        "session_id",
        "candidate_id",
        "question_id",
        "answer_text",
        "hint_level_used",
        "consent_id",
        "round_type",
        "ensemble",
    }
)


def evaluation_request(state: SessionState, turn, ensemble: str) -> dict:
    """What M13's `EvaluateRequest` accepts, and nothing more."""
    return {
        "turn_id": str(turn.turn_id),
        "session_id": str(state.session_id),
        "candidate_id": str(state.candidate_id),
        "question_id": str(turn.question_id) if turn.question_id else None,
        "answer_text": turn.text,
        "hint_level_used": turn.hint_level_used,
        "consent_id": str(state.flags.consent_id) if state.flags.consent_id else None,
        "round_type": turn.rubric_round_type,
        "ensemble": ensemble,
    }


def scoreable(state: SessionState, turn, item: Item | None) -> str | None:
    """None if this turn can be scored; otherwise the reason it cannot.

    The reason is the sentence the report shows, so it is written for a student
    rather than for a log.
    """
    if turn.role != "candidate":
        return "not an answer"
    if state.kind == SessionKind.drill.value:
        # M13 resolves a question package from M05, and a claim probe is not a
        # bank item. Minting grounded items from claims is M05's Phase 2 path.
        return "Practice drill — drills are not scored yet."
    if turn.deliberately_false:
        # Unreachable while FR-6.20 is blocked, and the guard belongs here too:
        # scored under the ordinary rubric, agreeing with a falsehood would be
        # scored as knowledge.
        return "A deliberately false probe needs M13's push_back rubric."
    if turn.question_id is None or turn.rubric_round_type is None:
        return "Asked from the backup set, so it was not scored."
    return None


# ─────────────────────────────────────────────────────────────────────────
#  Writing
# ─────────────────────────────────────────────────────────────────────────


def artifact_request(state: SessionState, turn) -> dict:
    """What M04's `POST /v1/candidates/{id}/artifacts` takes.

    The answer text and nothing else. M13 quotes character offsets into
    exactly this string, so what is registered here has to be what was scored
    — not a trimmed, joined or re-punctuated version of it.
    """
    return {
        "candidate_id": str(state.candidate_id),
        "session_id": str(state.session_id),
        "turn_id": str(turn.turn_id),
        "artifact_type": "transcript",
        "content": turn.text,
    }


def enqueue_artifact(db: Session, state: SessionState, turn) -> ArtifactOutbox | None:
    """Register the answer so M13's evidence can resolve against it.

    Queued on the same condition as the evaluation: an answer nobody will
    score is an artifact nobody will cite.
    """
    if not turn.text:
        return None
    existing = db.get(ArtifactOutbox, turn.turn_id)
    if existing is not None:
        return existing
    row = ArtifactOutbox(
        id=turn.turn_id,
        turn_id=turn.turn_id,
        session_id=state.session_id,
        payload=artifact_request(state, turn),
    )
    db.add(row)
    return row


def enqueue_evaluation(
    db: Session, state: SessionState, turn, item: Item | None
) -> EvaluationOutbox | None:
    """Written in the caller's transaction, with the turn. Never twice."""
    if scoreable(state, turn, item) is not None:
        return None
    existing = db.get(EvaluationOutbox, turn.turn_id)
    if existing is not None:
        return existing
    row = EvaluationOutbox(
        id=turn.turn_id,
        turn_id=turn.turn_id,
        session_id=state.session_id,
        payload=evaluation_request(state, turn, ENSEMBLE_BY_MODE.get(state.mode, "n3_het_v1")),
    )
    db.add(row)
    return row


def enqueue_ledger(
    db: Session,
    state: SessionState,
    *,
    requirement_ids: list[str],
    ledger_state: str,
    turn_id: uuid.UUID | None,
) -> list[LedgerOutbox]:
    """FR-6.24. One row per requirement, and only when a JD is behind them.

    M02's docstring says M05 writes these; M05 has no HTTP client, and a
    selected question is not an asked one — a session can end in between. M06
    is the only module that knows a question reached the student.
    """
    if state.jd_id is None or not requirement_ids:
        return []
    rows: list[LedgerOutbox] = []
    for requirement_id in requirement_ids:
        if _ledger_exists(db, state.session_id, turn_id, requirement_id, ledger_state):
            continue
        row = LedgerOutbox(
            session_id=state.session_id,
            candidate_id=state.candidate_id,
            jd_id=state.jd_id,
            requirement_id=requirement_id,
            ledger_state=ledger_state,
            turn_id=turn_id,
        )
        db.add(row)
        rows.append(row)
    return rows


def _ledger_exists(
    db: Session,
    session_id: uuid.UUID,
    turn_id: uuid.UUID | None,
    requirement_id: str,
    ledger_state: str,
) -> bool:
    """SQL NULLs are distinct in a UNIQUE constraint, so a `skipped` row with
    no turn is guarded here rather than by the index."""
    statement = (
        select(LedgerOutbox)
        .where(LedgerOutbox.session_id == session_id)
        .where(LedgerOutbox.requirement_id == requirement_id)
        .where(LedgerOutbox.ledger_state == ledger_state)
    )
    statement = (
        statement.where(LedgerOutbox.turn_id.is_(None))
        if turn_id is None
        else statement.where(LedgerOutbox.turn_id == turn_id)
    )
    return db.exec(statement).first() is not None


# ─────────────────────────────────────────────────────────────────────────
#  Delivering
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class Drained:
    artifacts_sent: int = 0
    evaluations_sent: int = 0
    ledger_sent: int = 0
    #: Evaluations held back because M04 has not got the answer text yet.
    waiting_on_artifact: int = 0
    failed: int = 0
    held: int = 0
    #: Rows somebody else is sending. Not a failure, and not work left undone
    #: — it is the difference between "nothing owed" and "wait a moment".
    in_flight: int = 0
    #: turn_id -> what M13 said about it. The engine records these as events.
    outcomes: dict[uuid.UUID, dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.outcomes is None:
            self.outcomes = {}

    @property
    def moved(self) -> int:
        return self.artifacts_sent + self.evaluations_sent + self.ledger_sent


def _claim(db: Session, model, row, now: datetime) -> bool:
    """Take this row for sending. False when another drain got there first.

    The UPDATE carries its own WHERE on the state we read, so the database —
    not this process's memory of it — decides who owns the row. It commits
    before the call returns, which is what makes the claim visible to the
    other drain.
    """
    statement = sql_update(model).where(model.id == row.id)
    # The condition is the state we read. A queued row is claimed by its state;
    # a row whose claim went stale is claimed by that claim's timestamp, so two
    # drains reclaiming the same abandoned row cannot both win.
    statement = (
        statement.where(model.state == PENDING)
        if row.state == PENDING
        else statement.where(model.state == SENDING).where(model.claimed_at == row.claimed_at)
    )
    result = db.execute(statement.values(state=SENDING, claimed_at=now))
    if not result.rowcount:
        db.rollback()
        return False
    db.commit()
    db.refresh(row)
    return True


def _fail(row, error: str, now: datetime) -> bool:
    """Record the failure on the row. True when it has been held."""
    row.attempts += 1
    row.last_error = error[:500]
    row.claimed_at = None
    row.state = HELD if row.attempts >= MAX_ATTEMPTS else PENDING
    return row.state == HELD


def drain(
    db: Session,
    upstreams: Upstreams,
    *,
    session_id: uuid.UUID | None = None,
    limit: int = DRAIN_LIMIT,
) -> Drained:
    """Move what is pending. Never raises: a failure is a row, not an outage."""
    out = Drained()
    now = utcnow()
    # A snapshot, before this drain claims anything of its own.
    out.in_flight = sum(
        _sending(db, model, session_id, now)
        for model in (ArtifactOutbox, EvaluationOutbox, LedgerOutbox)
    )

    # Artifacts first, and in their own pass: M04 refuses an observation whose
    # evidence does not resolve, so an evaluation that overtakes its own
    # artifact is scored into a rejection two modules downstream.
    for row in _pending(db, ArtifactOutbox, session_id, limit):
        if not upstreams.available("M04"):
            out.failed += 1
            continue
        if not _claim(db, ArtifactOutbox, row, now):
            continue
        try:
            upstreams.m04.register_artifact(row.payload)
        except UpstreamUnavailable as exc:
            out.held += int(_fail(row, str(exc), now))
            out.failed += 1
            db.commit()
            continue
        row.state, row.sent_at, row.last_error, row.claimed_at = SENT, now, None, None
        out.artifacts_sent += 1
    db.commit()

    unresolved = _turns_without_an_artifact(db, session_id)
    for row in _pending(db, EvaluationOutbox, session_id, limit):
        if row.turn_id in unresolved:
            # Its artifact has not landed. Next drain, or the sweeper.
            out.waiting_on_artifact += 1
            continue
        if not upstreams.available("M13"):
            out.failed += 1
            continue
        if not _claim(db, EvaluationOutbox, row, now):
            out.in_flight += 1
            continue
        try:
            answer = upstreams.m13.evaluate(row.payload)
        except UpstreamUnavailable as exc:
            out.held += int(_fail(row, str(exc), now))
            out.failed += 1
            db.commit()
            continue
        row.state, row.sent_at, row.last_error, row.claimed_at = SENT, now, None, None
        out.evaluations_sent += 1
        # A status, not a number. M13 owns the number and the gate that says
        # whether anybody may see it.
        out.outcomes[row.turn_id] = {
            "status": str(answer.get("status", "unknown")),
            "has_number": answer.get("composite") is not None,
        }

    for row in _pending(db, LedgerOutbox, session_id, limit):
        if not upstreams.available("M02"):
            out.failed += 1
            continue
        if not _claim(db, LedgerOutbox, row, now):
            out.in_flight += 1
            continue
        try:
            upstreams.m02.record_coverage(
                row.session_id,
                row.candidate_id,
                jd_id=row.jd_id,
                requirement_id=row.requirement_id,
                state=row.ledger_state,
                turn_id=row.turn_id,
            )
        except UpstreamUnavailable as exc:
            out.held += int(_fail(row, str(exc), now))
            out.failed += 1
            db.commit()
            continue
        row.state, row.sent_at, row.last_error, row.claimed_at = SENT, now, None, None
        out.ledger_sent += 1

    db.commit()
    if out.failed:
        log.info("M06 outbox: %d moved, %d still waiting", out.moved, out.failed)
    return out


def _turns_without_an_artifact(db: Session, session_id: uuid.UUID | None) -> set[uuid.UUID]:
    """Turns whose answer text M04 has not accepted yet."""
    statement = select(ArtifactOutbox).where(ArtifactOutbox.state != SENT)
    if session_id is not None:
        statement = statement.where(ArtifactOutbox.session_id == session_id)
    return {row.turn_id for row in db.exec(statement).all()}


def _sending(db: Session, model, session_id: uuid.UUID | None, now: datetime) -> int:
    """Rows claimed by a sender that has not yet given up or finished."""
    statement = (
        select(model)
        .where(model.state == SENDING)
        .where(model.claimed_at >= now - timedelta(seconds=STALE_CLAIM_S))
    )
    if session_id is not None:
        statement = statement.where(model.session_id == session_id)
    return len(list(db.exec(statement).all()))


def _pending(db: Session, model, session_id: uuid.UUID | None, limit: int):
    """Rows nobody is sending: queued, or claimed by a process that is gone."""
    stale = utcnow() - timedelta(seconds=STALE_CLAIM_S)
    statement = select(model).where(
        (model.state == PENDING) | ((model.state == SENDING) & (model.claimed_at < stale))
    )
    if session_id is not None:
        statement = statement.where(model.session_id == session_id)
    return list(db.exec(statement.order_by(model.created_at).limit(limit)).all())


def sessions_owing(db: Session, *, limit: int) -> list[uuid.UUID]:
    """Sessions with a row nobody is sending — what the sweeper works through.

    Oldest row first, so a session that has been waiting longest is retried
    first and a busy session cannot starve a finished one.
    """
    seen: list[uuid.UUID] = []
    for model in (ArtifactOutbox, EvaluationOutbox, LedgerOutbox):
        for row in _pending(db, model, None, limit):
            if row.session_id not in seen:
                seen.append(row.session_id)
    return seen[:limit]


def status(db: Session, session_id: uuid.UUID | None = None) -> dict:
    """What is queued, and why anything failed — M13's `/v1/outbox`, for M06."""

    def rows(model) -> list:
        statement = select(model)
        if session_id is not None:
            statement = statement.where(model.session_id == session_id)
        return list(db.exec(statement).all())

    def summarise(items: list) -> dict:
        return {
            "pending": sum(1 for r in items if r.state == PENDING),
            "sending": sum(1 for r in items if r.state == SENDING),
            "sent": sum(1 for r in items if r.state == SENT),
            "held": sum(1 for r in items if r.state == HELD),
            "errors": sorted({r.last_error for r in items if r.last_error}),
        }

    return {
        "artifacts": summarise(rows(ArtifactOutbox)),
        "evaluations": summarise(rows(EvaluationOutbox)),
        "coverage": summarise(rows(LedgerOutbox)),
    }


def pending_count(db: Session, session_id: uuid.UUID) -> int:
    """How many answers this session still owes M13 — in flight counts."""
    statement = (
        select(EvaluationOutbox)
        .where(EvaluationOutbox.session_id == session_id)
        .where(EvaluationOutbox.state.in_((PENDING, SENDING)))
    )
    return len(list(db.exec(statement).all()))


def session_of(db: Session, session_id: uuid.UUID) -> InterviewSession | None:
    return db.get(InterviewSession, session_id)


__all__ = [
    "DRAIN_LIMIT",
    "SENDING",
    "STALE_CLAIM_S",
    "ENSEMBLE_BY_MODE",
    "EVALUATION_KEYS",
    "HELD",
    "MAX_ATTEMPTS",
    "PENDING",
    "SENT",
    "Drained",
    "drain",
    "artifact_request",
    "enqueue_artifact",
    "enqueue_evaluation",
    "enqueue_ledger",
    "evaluation_request",
    "pending_count",
    "sessions_owing",
    "scoreable",
    "status",
]
