"""Tables — spec §5, Revision 2.

**The event log is the truth; everything else here is derived from it or
queued by it.** `m06_event` is append-only and unique on
`(session_id, turn_index, step)`, so a retried request replays nothing it
already did (§3.2.4 — Revision 1 put `attempt` in that key, which gave every
retry a fresh key and de-duplicated nothing). `m06_checkpoint` is a cache of
the fold over those events; `m06_turn` is a projection kept for the queries a
fold is bad at, such as "which items has this student seen in 90 days".

**One occupying session per student (EC-6.13), without a partial index.**
SQLite and Postgres both allow any number of NULLs in a unique column, so
`occupying_key` holds the candidate id while a session is live or paused and
NULL otherwise. The constraint is then an ordinary UNIQUE that behaves the same
on both stores — which a partial index, spelled differently on each, would not.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ai_core.outbox import OutboxRow
from ai_core.timeutil import utcnow
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class InterviewSession(SQLModel, table=True):
    __tablename__ = "m06_session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(index=True)
    kind: str = Field(default="mock", index=True)
    mode: str = "mock"
    status: str = Field(default="planned", index=True)
    #: The candidate id while `status` is live or paused; NULL otherwise.
    occupying_key: str | None = Field(default=None, unique=True)
    jd_id: uuid.UUID | None = None
    requested_minutes: int = 45
    #: Drills only: where the session came from and what it defends.
    source_module: str | None = None
    source_ref: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None


class SessionEvent(SQLModel, table=True):
    """Append-only. `SessionState` is a fold over these rows (§6.8)."""

    __tablename__ = "m06_event"
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", "step", name="uq_m06_event_step"),
        UniqueConstraint("session_id", "seq", name="uq_m06_event_seq"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(index=True)
    seq: int
    turn_index: int = 0
    #: With `session_id` and `turn_index`, the idempotency key.
    step: str
    kind: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    #: A counter, NOT part of the key.
    attempt: int = 1
    at: datetime = Field(default_factory=utcnow)


class Checkpoint(SQLModel, table=True):
    """The fold, cached. Compare-and-swap on `version` (§6.8)."""

    __tablename__ = "m06_checkpoint"

    session_id: uuid.UUID = Field(primary_key=True)
    version: int = 0
    #: The highest event `seq` folded into `state_json`. A checkpoint behind
    #: the log is re-folded rather than trusted.
    last_seq: int = 0
    state_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class TurnRecord(SQLModel, table=True):
    """A projection of the event log, for queries. Rebuildable from events."""

    __tablename__ = "m06_turn"

    id: uuid.UUID = Field(primary_key=True)
    session_id: uuid.UUID = Field(index=True)
    candidate_id: uuid.UUID = Field(index=True)
    turn_index: int
    segment_index: int = 0
    role: str
    text: str = ""
    #: sha256 of `text` as stored — the bytes M13 was sent. A highlight is
    #: refused when the two disagree (spec §5).
    text_sha256: str = ""
    modality: str = "verbal"
    question_id: uuid.UUID | None = Field(default=None, index=True)
    question_source: str | None = None
    rubric_round_type: str | None = None
    probe_depth: int = 0
    probe_move: str | None = None
    hint_level_used: int = 0
    deliberately_false: bool = False
    completion_reason: str | None = None
    at: datetime = Field(default_factory=utcnow)


class EvaluationOutbox(OutboxRow, table=True):
    """One M13 request per answered turn, written with the turn (FR-6.14).

    The delivery columns — state, attempts, failures, the claim, the backoff —
    are `ai_core.outbox.OutboxRow`'s since 2026-10-02. M06 wrote its own on
    day 4, and Platform_Core's was later written from them.
    """

    __tablename__ = "m06_eval_outbox"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: Unique: a turn is evaluated once. A re-score is M13's `supersedes`.
    turn_id: uuid.UUID = Field(unique=True)
    session_id: uuid.UUID = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class ArtifactOutbox(OutboxRow, table=True):
    """The answer text M04 resolves M13's evidence against (M04 §5.1).

    M13 quotes character spans of the answer and cites `artifact_id =
    turn_id`. M04 refuses any observation whose evidence does not resolve, and
    until M06 registers the turn there is nothing for it to resolve to — which
    is how a fully scored interview moved no mastery at all.

    M06 owns the transcript, so M06 registers it. Sent BEFORE the evaluation
    for the same turn, because the artifact has to be there before anything
    cites it.
    """

    __tablename__ = "m06_artifact_outbox"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    #: The artifact id itself, which is the turn id — M04 derives it the same
    #: way, so neither side carries an id the other has to be told.
    turn_id: uuid.UUID = Field(unique=True)
    session_id: uuid.UUID = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class LedgerOutbox(OutboxRow, table=True):
    """M02 coverage ledger rows M06 owes (FR-6.24)."""

    __tablename__ = "m06_ledger_outbox"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "turn_id", "requirement_id", "ledger_state", name="uq_m06_ledger_row"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(index=True)
    candidate_id: uuid.UUID
    jd_id: uuid.UUID
    requirement_id: str
    #: asked | answered | skipped
    ledger_state: str
    #: NULL only for `skipped` rows about a requirement no turn reached. SQL
    #: NULLs are distinct in a unique constraint, so those rows are guarded by
    #: the writer instead (store.enqueue_ledger).
    turn_id: uuid.UUID | None = None


class LLMCall(SQLModel, table=True):
    """Every model call a session made — the trace half of FR-6.19."""

    __tablename__ = "m06_llm_call"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID | None = Field(default=None, index=True)
    turn_index: int | None = None
    job: str
    tier: str
    model_id: str
    prompt_version: str
    ok: bool = True
    error: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    reasoning_tokens: int | None = None
    #: Recorded only when the provider reports it. AC-6.11 is "not measured"
    #: rather than passing while this is NULL (spec §6.6).
    cached_tokens: int | None = None
    latency_ms: int = 0
    first_token_ms: int | None = None
    at: datetime = Field(default_factory=utcnow)


__all__ = [
    "Checkpoint",
    "EvaluationOutbox",
    "InterviewSession",
    "LLMCall",
    "LedgerOutbox",
    "SessionEvent",
    "TurnRecord",
]
