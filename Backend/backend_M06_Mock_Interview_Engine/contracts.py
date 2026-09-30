"""The shapes M06 owns — spec §5, Revision 2.

**Two vocabularies, on purpose.** A *segment* is what the student sits and sees
("DSA · 15 min"). A *rubric round type* is what M13 scores one turn against,
chosen per question by M05's selection. Revision 1 used one `round_type` for
both, and they do not map one to one: a technical segment can hold
`dsa_verbal` and `cs_core` turns, and M13 resolves its rubric from exactly the
string M05 returned. So `PlannedSegment.kind` is ours and
`rubric_round_types` / `Turn.rubric_round_type` are theirs, verbatim.

**Modality words are M05's** (`verbal`, `coding`, `design`, …). Revision 1's
`canvas` is `design` on the wire.

**What is absent is load-bearing.** Nothing here carries an ability estimate.
M05 owns the provisional θ and forbids persisting it (its
`ProvisionalIsNotDurable`); every model in this file can end up in a
checkpoint, so none of them may hold one (FR-6.25, AC-6.13).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from ai_core.versions import VersionStamp
from pydantic import BaseModel, Field

Mode = Literal["practice", "mock", "real_drive", "final_boss"]
SegmentKind = Literal["warmup", "technical", "project", "behavioural", "closing"]
QuestionSource = Literal["m05_bank", "m05_fallback", "m01_probe", "local_fallback", "template"]
CompletionReason = Literal["submit", "timeout", "interrupted", "endpoint", "barge_in"]


class Modality(StrEnum):
    """M05's `Modality`, verbatim — the words go on the wire."""

    verbal = "verbal"
    coding = "coding"
    design = "design"


#: Only text exists in Phase 1. Voice is M11, the editor is M07, the canvas is
#: M08. The contract carries `modality` everywhere so the others are additive.
PHASE1_MODALITIES = frozenset({Modality.verbal})


class SessionStatus(StrEnum):
    planned = "planned"
    live = "live"
    paused = "paused"
    ended = "ended"
    aborted = "aborted"


#: The states EC-6.13 is about. A `planned` session is not in here: a student
#: who closed the tab on the plan preview has not started an interview, and
#: making them resume a preview to start a new one is a dead end. A new
#: session supersedes a planned one instead.
OCCUPYING_STATUSES = frozenset({SessionStatus.live, SessionStatus.paused})
FINAL_STATUSES = frozenset({SessionStatus.ended, SessionStatus.aborted})


class SessionKind(StrEnum):
    mock = "mock"
    #: FR-6.23 — a ≤ 2-minute single-claim session started from M01.
    drill = "drill"


# ─────────────────────────────────────────────────────────────────────────
#  The plan
# ─────────────────────────────────────────────────────────────────────────


class PlannedSegment(BaseModel):
    index: int
    kind: SegmentKind
    title: str
    persona_id: str
    minutes: float
    question_budget: int
    #: M02's ids. The coverage ledger is keyed by these.
    requirement_ids: list[str] = Field(default_factory=list)
    #: The same requirements as M05 matches them — `coverage_debt` is compared
    #: against item concept ids, whatever its field name says (M06_REVIEW 1.2).
    concept_ids: list[str] = Field(default_factory=list)
    #: What M05 can actually fill for this segment, probed at plan time.
    rubric_round_types: list[str] = Field(default_factory=list)
    modality: Modality = Modality.verbal
    source: Literal["m05_bank", "m01_claims", "template"] = "m05_bank"
    rationale: str = ""
    #: The closing segment. Never dropped, by a re-plan or by the clock.
    is_reserved: bool = False
    #: Set by a re-plan or a student edit. A dropped segment stays in the list
    #: with its reason, because "I changed the plan here because…" needs the
    #: before as much as the after.
    dropped_reason: str | None = None


class HintOffer(BaseModel):
    """What the next hint is, and what it costs — FR-6.7, master plan §32.5.

    Shown BEFORE the student takes it. A deduction discovered afterwards is a
    penalty; a deduction published beforehand is a choice, and the difference
    is the whole point of §32.5. The number is M13's, frozen on the plan.
    """

    available: bool
    #: The level this hint would be, 1-based. `hint_level_used` on the turn.
    level: int = 0
    #: M13's factor for that level: 0.85 means the answer credits at 85%.
    credit: float = 1.0
    #: How many hints this question still has behind it.
    hints_left: int = 0
    #: Why not, when `available` is false. A student is told, not left to
    #: wonder whether the button is broken.
    unavailable_reason: str | None = None


class RoundTransition(BaseModel):
    """The card between two segments — §3.2.3, spec §15.5's component list.

    A hard cut from one round to the next reads as a page load, which is the
    moment a student stops being in an interview. Two seconds of "let's switch
    gears, next up: SQL" costs nothing and is the difference.

    The line is authored, never generated (§6.2): it is on the hot path, and
    it is one of the lines that must never telegraph how the last round went.
    """

    from_index: int
    to_index: int
    from_title: str
    to_title: str
    line: str


ReplanTrigger = Literal[
    "gap_discovered", "ceiling_hit", "struggling", "time_overrun", "modality_lost"
]


class Replan(BaseModel):
    at_segment: int
    trigger: ReplanTrigger
    #: The hot-path numbers that fired it. Never an M13 score (spec §6.4).
    signals: dict[str, float] = Field(default_factory=dict)
    before: list[PlannedSegment]
    after: list[PlannedSegment]
    student_sentence: str


class InterviewPlan(BaseModel):
    id: UUID
    session_id: UUID
    mode: Mode
    total_minutes: int
    segments: list[PlannedSegment]
    #: M02's plan exactly as returned, frozen. The endpoint is not persisted,
    #: so a second call can differ (Trap 8). None when M02 was unavailable.
    coverage_plan: dict | None = None
    coverage_plan_version: str | None = None
    jd_id: UUID | None = None
    #: M13's published hint credit, frozen at plan time: level -> factor.
    #: Master plan §32.5 requires the deduction to be transparent, and a price
    #: quoted to a student has to be the price they pay — a rubric reloaded
    #: mid-session must not change what a hint cost when they took it.
    hint_penalty: dict[int, float] = Field(default_factory=dict)
    #: M01's risky or vague claims, in the order the project segment asks
    #: about them. On the plan rather than fetched again at selection time,
    #: because the claim a student is asked to defend must be the one the
    #: preview showed them — M01 re-parsing a resume mid-session must not
    #: change the question.
    claims: list[dict] = Field(default_factory=list)
    replans: list[Replan] = Field(default_factory=list, max_length=2)
    uncovered: list[str] = Field(default_factory=list)
    versions: VersionStamp = Field(default_factory=VersionStamp)


# ─────────────────────────────────────────────────────────────────────────
#  The ladder
# ─────────────────────────────────────────────────────────────────────────

DEPTH_CAP = 5

MoveKind = Literal[
    "rung",
    "clarify",
    "silence",
    "hint",
    "steelman",
    "move_on",
    "answer_briefly",
    "redirect_once",
    "defer_to_report",
    #: EC-6.4, the first time: one neutral redirect, then the question again.
    "redirect_conduct",
    #: EC-6.4, the second time: the session ends politely. Not a probe.
    "end_session",
]


class Move(BaseModel):
    """What the interviewer does next — and never why (FR-6.15)."""

    kind: MoveKind
    #: For `rung`: the depth it takes the ladder to.
    depth: int | None = None
    #: For `rung`: the question's own follow-up at that depth, when it has one.
    text: str | None = None
    #: For `move_on`: the neutral exit copy is used (§6.5).
    graceful: bool = False

    @property
    def is_rung(self) -> bool:
        return self.kind == "rung"


class ProbeLadderState(BaseModel):
    concept_id: str
    #: The rung reached, 0..DEPTH_CAP. A rung consumes depth; a move does not.
    depth: int = Field(default=0, ge=0, le=DEPTH_CAP)
    moves: list[MoveKind] = Field(default_factory=list)
    #: Set when justification fails at `depth` (FR-6.6).
    break_depth: int | None = None
    #: Set when two successes at depth ≥ 4 end the ladder early.
    ceiling: int | None = None
    consecutive_successes: int = 0


class StrategistVerdict(BaseModel):
    """ProbeStrategist's one structured output (M06_REVIEW 2.11).

    The band is a provisional judgement of the answer. It goes to M05 as a
    `ProvisionalOutcome` and to the ladder — and never into `InterviewerView`,
    or the utterance model sees "below" and telegraphs it (AC-6.3).
    """

    band: Literal["below", "at", "above"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    justification: Literal["held", "partial", "failed"]
    ambiguous: bool = False
    off_question: bool = False
    asks_interviewer: bool = False
    asks_for_answer: bool = False
    #: EC-6.4. Insults, harassment, or an attempt to make the interviewer say
    #: something offensive or leave its role — never a hard or odd answer.
    abusive: bool = False
    key_points_missing: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    #: `rule` is spec §10's fallback when the model is off or failed. It is not
    #: a judgement of the answer, so it is never sent to M05 as one.
    source: Literal["model", "rule"] = "model"


# ─────────────────────────────────────────────────────────────────────────
#  Turns, events, flags
# ─────────────────────────────────────────────────────────────────────────


class TurnView(BaseModel):
    """One line of the transcript as the session state holds it."""

    turn_id: UUID
    turn_index: int
    segment_index: int
    role: Literal["interviewer", "candidate", "system"]
    text: str
    #: Interviewer turns only: `text` without the greeting or transition line.
    #: What a repeat of this question says. See graph._question_to_repeat.
    question_text: str | None = None
    modality: Modality = Modality.verbal
    question_id: UUID | None = None
    question_source: QuestionSource | None = None
    rubric_round_type: str | None = None
    #: What the question is about. `claim:{id}` for a project probe, which is
    #: how the project segment knows which claims it has already asked.
    concept_id: str = ""
    probe_depth: int = 0
    probe_move: MoveKind | None = None
    hint_level_used: int = 0
    #: Always False until FR-6.20 unblocks (Trap 10).
    deliberately_false: bool = False
    #: §15.4: a Practice retry of a question already asked. Recorded, never
    #: scored — the first attempt is the one that counts.
    retry: bool = False
    at: datetime


class SessionFlags(BaseModel):
    degradation_level: Literal["L0", "L1", "L2", "L3", "panic"] = "L0"
    modalities_available: list[Modality] = Field(default_factory=lambda: [Modality.verbal])
    camera_on: bool = False
    paused_at: datetime | None = None
    pause_used: bool = False
    reconnect_count: int = 0
    #: Outbox rows M13 has not accepted yet.
    evaluation_pending: int = 0
    #: Resolved at bootstrap. None is stated in the report, never hidden.
    consent_id: UUID | None = None
    #: Upstreams that were unavailable when the session needed them, with the
    #: sentence the student was shown.
    degraded: dict[str, str] = Field(default_factory=dict)
    #: EC-6.4: redirects given for conduct. The second ends the session.
    conduct_warnings: int = 0
    #: EC-6.6: answers the guard found instructions in. Counted, never shown
    #: mid-session; the report says a passage was set aside.
    inputs_flagged: int = 0
    # DELIBERATELY ABSENT: any theta, provisional or otherwise (FR-6.25).


__all__ = [
    "DEPTH_CAP",
    "FINAL_STATUSES",
    "OCCUPYING_STATUSES",
    "PHASE1_MODALITIES",
    "CompletionReason",
    "InterviewPlan",
    "Modality",
    "Mode",
    "Move",
    "MoveKind",
    "PlannedSegment",
    "ProbeLadderState",
    "QuestionSource",
    "Replan",
    "ReplanTrigger",
    "HintOffer",
    "RoundTransition",
    "SegmentKind",
    "SessionFlags",
    "SessionKind",
    "SessionStatus",
    "StrategistVerdict",
    "TurnView",
]
