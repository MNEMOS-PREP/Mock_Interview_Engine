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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ai_core.outbox import (
    HELD,
    PENDING,
    REJECTED,
    SENDING,
    SENT,
    VOID,
    Channel,
    Outcome,
    RetryPolicy,
    classify_status,
    deliver,
    due,
    summary,
)
from ai_core.outbox import requeue as requeue_rows
from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from .adapters import Upstreams, UpstreamUnavailable
from .contracts import SessionKind
from .items import Item
from .models import ArtifactOutbox, EvaluationOutbox, InterviewSession, LedgerOutbox
from .modes import ENSEMBLE_BY_MODE as _ENSEMBLE_BY_MODE
from .state import SessionState

log = logging.getLogger("uvicorn.error")

#: After this many ANSWERED failures a row is held for a person instead of
#: retried; it stays visible. An upstream that is down never counts — see
#: "Delivering" below.
MAX_ATTEMPTS = 5

#: How many rows one drain moves. A student's own request pays for its own
#: turn; a backlog is drained by repeating, not by one long request.
DRAIN_LIMIT = 10

#: A claim older than this belonged to a process that is not coming back. It
#: is longer than the M13 client's own timeout (60 s), so a row is never taken
#: from a request that is merely slow.
STALE_CLAIM_S = 180

# The row states are Platform_Core's (`ai_core.outbox`): pending, sending,
# sent, void, held, rejected. `void` is also §10's "everything fails" — a row
# from a session that failed on our side, never sent.
#: Quotes kept per dimension — the notes are for reading, not an audit.
FEEDBACK_QUOTES = 3

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
        # M11's FR-11.15: words the recogniser was unsure of — scored, never
        # quoted back as what the student said.
        **({"uncitable": [list(r) for r in turn.unsure]} if getattr(turn, "unsure", None) else {}),
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
    if turn.question_source == "closing":
        # FR-6.21: the student's own questions are recorded, and there is no
        # rubric to score a question with yet.
        return "Your questions for the interviewer are recorded, not scored."
    if getattr(turn, "retry", False):
        return "A retry — the first attempt is the one that counts."
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
    score is an artifact nobody will cite. (The docstring said so from day 4
    and the code did not check — every drill answer and every backup-set
    answer was being registered with M04 for nothing to cite.)
    """
    if not turn.text or scoreable(state, turn, None) is not None:
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
#  Delivering — on Platform_Core's `ai_core.outbox` since 2026-10-02
# ─────────────────────────────────────────────────────────────────────────
#
# M06 built this mechanism on day 4: claim before sending, a stale claim taken
# over, held rows kept visible. Platform_Core's outbox was written from it, and
# M13 moved onto that one first. M06 now does too, so the mechanism exists
# once. What M06 keeps is only what it alone knows: what each upstream is
# owed, that an evaluation waits for its answer text, and that M13's status
# becomes an event on the session.
#
# Three things the shared mechanism adds:
#   * **an outage is not the row's fault.** A row whose upstream did not answer
#     is retried and never held; `held` means the upstream answered and still
#     refused, which needs a person. M06 used to hold a row after five tries
#     even when M13 was simply down.
#   * **a 4xx is `rejected`**, not retried five times: the request will not
#     change on its own.
#   * **stuck rows are listed with their reasons** (`status()`), and
#     `requeue()` puts them back once the cause is fixed.

#: Why an evaluation is not sent yet: M04 refuses an observation whose
#: evidence does not resolve, so an evaluation that overtakes its own artifact
#: is scored into a rejection two modules downstream.
WAITING_ON_ARTIFACT = "its answer text has not reached M04 yet"

#: M06 drains a session's rows on the student's own requests (the answer, the
#: end) and on the sweeper's pass. The pass interval IS the backoff, so a row
#: carries none of its own: "it goes the moment M13 is back" stays true on
#: the next request rather than after a timer set during the outage.
POLICY = RetryPolicy(base_s=0.0, jitter=0.0, max_failures=MAX_ATTEMPTS, stale_claim_s=STALE_CLAIM_S)

MODELS = (ArtifactOutbox, EvaluationOutbox, LedgerOutbox)


@dataclass
class Drained:
    artifacts_sent: int = 0
    evaluations_sent: int = 0
    ledger_sent: int = 0
    #: Evaluations held back because M04 has not got the answer text yet.
    waiting_on_artifact: int = 0
    #: Rows that did not go this time, for whatever reason.
    failed: int = 0
    #: Rows newly waiting on a person: held (the upstream keeps answering with
    #: an error) or rejected (it said no).
    held: int = 0
    #: Rows somebody else is sending. Not a failure, and not work left undone
    #: — it is the difference between "nothing owed" and "wait a moment".
    in_flight: int = 0
    #: turn_id -> what M13 said about it. The engine records these as events.
    outcomes: dict[uuid.UUID, dict] = field(default_factory=dict)
    #: Each channel's pass, as Platform_Core reports it.
    passes: list[dict] = field(default_factory=list)

    @property
    def moved(self) -> int:
        return self.artifacts_sent + self.evaluations_sent + self.ledger_sent


def _call(send: Callable[[], Any]) -> Outcome:
    """An adapter call, as the outcome the shared mechanism settles a row on.

    The adapters raise `UpstreamUnavailable` either way; its `status` says
    whether anybody answered.
    """
    try:
        return Outcome.sent(body=send())
    except UpstreamUnavailable as exc:
        if exc.status is None:
            return Outcome.unreachable(exc.detail)
        return Outcome(classify_status(exc.status).kind, exc.detail)


def channels(
    upstreams: Upstreams,
    outcomes: dict[uuid.UUID, dict],
    session_id: uuid.UUID | None = None,
) -> list[tuple[str, Channel]]:
    """What M06 owes, in the order it must go: an artifact before the
    evaluation that cites it. Paired with the module each one needs."""

    def artifact(rows: list[ArtifactOutbox]) -> Outcome:
        return _call(lambda: upstreams.m04.register_artifact(rows[0].payload))

    def evaluation(rows: list[EvaluationOutbox]) -> Outcome:
        return _call(lambda: upstreams.m13.evaluate(rows[0].payload))

    def ledger(rows: list[LedgerOutbox]) -> Outcome:
        row = rows[0]
        return _call(
            lambda: upstreams.m02.record_coverage(
                row.session_id,
                row.candidate_id,
                jd_id=row.jd_id,
                requirement_id=row.requirement_id,
                state=row.ledger_state,
                turn_id=row.turn_id,
            )
        )

    def waits_for_its_artifact(db: Session) -> Callable[[EvaluationOutbox], str | None]:
        unresolved = _turns_without_an_artifact(db, session_id)
        return lambda row: WAITING_ON_ARTIFACT if row.turn_id in unresolved else None

    def scored(_db: Session, rows: list[EvaluationOutbox], outcome: Outcome) -> None:
        if outcome.kind != "sent":
            return
        answer = outcome.body if isinstance(outcome.body, dict) else {}
        for row in rows:
            # A status, not a number. M13 owns the number and the gate that
            # says whether anybody may see it.
            outcomes[row.turn_id] = {
                "status": str(answer.get("status", "unknown")),
                "has_number": answer.get("composite") is not None,
                "feedback": feedback(answer),
            }

    return [
        ("M04", Channel("m04.artifacts", ArtifactOutbox, artifact, policy=POLICY)),
        (
            "M13",
            Channel(
                "m13.evaluations",
                EvaluationOutbox,
                evaluation,
                waits_on=waits_for_its_artifact,
                after=scored,
                policy=POLICY,
            ),
        ),
        ("M02", Channel("m02.coverage", LedgerOutbox, ledger, policy=POLICY)),
    ]


def drain(
    db: Session,
    upstreams: Upstreams,
    *,
    session_id: uuid.UUID | None = None,
    limit: int = DRAIN_LIMIT,
) -> Drained:
    """Move what is owed — one session's rows, or everybody's. Never raises:
    a failure is a row, not an outage."""
    out = Drained()
    now = utcnow()
    # A snapshot, before this drain claims anything of its own: rows another
    # sender holds are not due, so the shared pass never sees them.
    out.in_flight = sum(_sending(db, model, session_id, now) for model in MODELS)
    sent_into = {
        ArtifactOutbox: "artifacts_sent",
        EvaluationOutbox: "evaluations_sent",
        LedgerOutbox: "ledger_sent",
    }
    for module, channel in channels(upstreams, out.outcomes, session_id):
        model = channel.model
        where = model.session_id == session_id if session_id is not None else None
        if not upstreams.available(module):
            # Known to be down: leave the rows exactly as they are.
            out.failed += len(due(db, model, now=now, policy=POLICY, limit=limit, where=where))
            continue
        report = deliver(db, channel, now=now, limit=limit, where=where)
        setattr(out, sent_into[model], getattr(out, sent_into[model]) + report.sent + report.void)
        out.waiting_on_artifact += report.waiting.get(WAITING_ON_ARTIFACT, 0)
        out.failed += report.deferred + report.retried + report.held + report.rejected
        out.held += report.held + report.rejected
        out.in_flight += report.in_flight
        out.passes.append(report.as_dict())
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


def requeue(db: Session, session_id: uuid.UUID | None = None) -> int:
    """Stuck rows back in the queue — after a person fixed what held them."""
    return sum(
        requeue_rows(
            db, model, where=model.session_id == session_id if session_id is not None else None
        )
        for model in MODELS
    )


def feedback(answer: dict) -> list[dict]:
    """M13's words about one answer, without its numbers.

    Per dimension: the evaluator's reasoning, the key points not reached, and
    the student's own sentences that counted — verified spans only, because an
    unverified quote captioned "what you said" is the one failure M13 exists
    to prevent. This is what M13's evidence drawer shows a student while its
    display gate holds the numbers back (M13 §6.7). No number is copied: M13
    owns them and the gate on them, and a copy here would be the one that
    went stale (Rule 3).
    """
    out: list[dict] = []
    for score in answer.get("aggregated") or []:
        quotes = [
            str(span["quote"])
            for ref in score.get("evidence") or []
            if (span := ref.get("span") or {}).get("verified") and span.get("quote")
        ]
        item = {
            "dimension": str(score.get("dimension_key") or ""),
            "reasoning": str(score.get("reasoning") or "").strip(),
            "missing": [str(m) for m in score.get("missing_key_points") or []],
            "quotes": quotes[:FEEDBACK_QUOTES],
        }
        if item["reasoning"] or item["missing"] or item["quotes"]:
            out.append(item)
    return out


def void_evaluations(db: Session, session_id: uuid.UUID, reason: str) -> int:
    """§10 "Everything fails": nothing still queued for this session is sent.

    Rows M13 already scored stand — they were answers given before anything
    failed, scored like any other. What is voided is what the failure would
    otherwise have sent on afterwards.
    """
    rows = db.exec(
        select(EvaluationOutbox)
        .where(EvaluationOutbox.session_id == session_id)
        .where(EvaluationOutbox.state.in_((PENDING, HELD, REJECTED)))
    ).all()
    for row in rows:
        row.state = VOID
        row.last_error = reason[:500]
    db.commit()
    return len(rows)


def sessions_owing(db: Session, *, limit: int) -> list[uuid.UUID]:
    """Sessions with a row that is due — what the sweeper works through.

    Oldest row first, so a session that has been waiting longest is retried
    first and a busy session cannot starve a finished one.
    """
    seen: list[uuid.UUID] = []
    for model in MODELS:
        for row in due(db, model, policy=POLICY, limit=limit):
            if row.session_id not in seen:
                seen.append(row.session_id)
    return seen[:limit]


def status(db: Session, session_id: uuid.UUID | None = None) -> dict:
    """What is queued, what is stuck and why — M13's `/v1/outbox`, for M06.

    Platform_Core's `summary()` per table: counts by state, how long the oldest
    owed row has waited, and every stuck row with its reason. A row nobody can
    see is a row nobody fixes.
    """

    def one(model) -> dict:
        where = model.session_id == session_id if session_id is not None else None
        s = summary(
            db,
            model,
            where=where,
            describe=lambda row: {
                "session_id": str(row.session_id),
                "turn_id": str(row.turn_id) if row.turn_id else None,
            },
        )
        return {
            "pending": s[PENDING],
            "sending": s[SENDING],
            "sent": s[SENT],
            "held": s[HELD],
            "rejected": s[REJECTED],
            "void": s[VOID],
            "owed": s["owed"],
            "stuck": s["stuck"],
            "oldest_owed_s": s["oldest_owed_s"],
            "errors": [e["error"] for e in s["errors"]],
            "stuck_rows": s["stuck_rows"],
        }

    return {
        "artifacts": one(ArtifactOutbox),
        "evaluations": one(EvaluationOutbox),
        "coverage": one(LedgerOutbox),
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
    "MODELS",
    "POLICY",
    "REJECTED",
    "WAITING_ON_ARTIFACT",
    "channels",
    "requeue",
    "SENDING",
    "STALE_CLAIM_S",
    "ENSEMBLE_BY_MODE",
    "EVALUATION_KEYS",
    "HELD",
    "MAX_ATTEMPTS",
    "PENDING",
    "SENT",
    "VOID",
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
    "void_evaluations",
    "feedback",
]
