"""Pacing — FR-6.17, spec §6.9, §2.3's pace check, EC-6.9. Pure arithmetic.

§3.2's first hard part: "time budgeting is a scheduling problem. Rounds
overrun; students ramble … the supervisor must continuously re-allocate
remaining time, and must always reserve the closing round."

    at 70%   a time warning; and if coverage debt is high, the interviewer
             narrows the focus out loud — "we've got about 12 minutes, I'll
             focus on DBMS" — and the plan narrows with it (Practice only
             says it; nothing is forced there)
    at 90%   the closing: whatever is left of the plan gives way to it
    a round  over its budget by the mode's allowance (25%, and 0% in Final
             Boss — EC-6.9, FR-6.9's hard clock) ends at the next question
             boundary. Never mid-ladder: a hard cut is §6.9's one prohibition

Nothing here reads an M13 score (§6.4): the inputs are the clock, the plan,
and what M06 itself has asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import PlannedSegment
from .planner import MINUTES_PER_VERBAL_QUESTION, live_segments
from .state import SessionState

#: §6.9's checkpoints, as fractions of the session's budget.
WARN_AT = (70, 90)
FOCUS_AT = 0.70
CLOSING_AT = 0.90


@dataclass(frozen=True)
class Reading:
    """Where the session stands against its clock and its plan."""

    used_s: float
    budget_s: float
    #: Live seconds left in the session.
    remaining_s: float
    #: Seconds the closing needs, kept back from everything else.
    closing_reserve_s: float
    #: Planned questions not yet asked, over the segments still to run.
    questions_owed: int
    #: How far the session is ahead of its plan, in questions: positive is
    #: ahead, negative behind. Measured against the minutes each question
    #: was priced at.
    ahead_by: float

    @property
    def fraction(self) -> float:
        return self.used_s / self.budget_s if self.budget_s else 1.0

    @property
    def time_for_questions_s(self) -> float:
        """What is left before the closing has to start."""
        return max(self.remaining_s - self.closing_reserve_s, 0.0)

    @property
    def coverage_debt(self) -> bool:
        """§2.3: more planned than the time left can hold."""
        return self.questions_owed * MINUTES_PER_VERBAL_QUESTION * 60 > self.time_for_questions_s

    @property
    def closing_due(self) -> bool:
        """§6.9's 90%, or the moment the reserve is all that is left."""
        return self.fraction >= CLOSING_AT or self.remaining_s <= self.closing_reserve_s


def closing_segment(state: SessionState) -> PlannedSegment | None:
    if state.plan is None:
        return None
    return next((s for s in live_segments(state.plan) if s.kind == "closing"), None)


def remaining_segments(state: SessionState) -> list[PlannedSegment]:
    """The live segments from the current one on, the closing excluded."""
    if state.plan is None:
        return []
    live = live_segments(state.plan)
    position = next((i for i, s in enumerate(live) if s.index == state.current_segment), 0)
    return [s for s in live[position:] if s.kind != "closing"]


def read(state: SessionState, now: datetime) -> Reading:
    used = state.time_used_s(now)
    budget = state.requested_minutes * 60.0
    closing = closing_segment(state)
    in_closing = closing is not None and state.current_segment == closing.index
    owed = 0
    for segment in remaining_segments(state):
        asked = state.questions_in_segment(segment.index)
        owed += max(segment.question_budget - asked, 0)
    planned_s = sum(
        s.minutes * 60
        for s in (live_segments(state.plan) if state.plan else [])
        if s.kind != "closing"
    )
    planned_questions = sum(
        s.question_budget
        for s in (live_segments(state.plan) if state.plan else [])
        if s.kind != "closing"
    )
    # Where the plan says we should be by now, in questions, against where
    # we are. Only meaningful while the plan still has questions in it.
    expected = (min(used / planned_s, 1.0) * planned_questions) if planned_s else 0.0
    return Reading(
        used_s=used,
        budget_s=budget,
        remaining_s=max(budget - used, 0.0),
        closing_reserve_s=0.0 if (closing is None or in_closing) else closing.minutes * 60,
        questions_owed=owed,
        ahead_by=round(state.questions_asked - expected, 2),
    )


def warnings_due(state: SessionState, now: datetime) -> list[int]:
    """The §6.9 checkpoints crossed and not yet announced."""
    fraction = read(state, now).fraction * 100
    return [mark for mark in WARN_AT if fraction >= mark and mark not in state.time_warnings]


def segment_elapsed_s(state: SessionState, now: datetime) -> float:
    return max(state.time_used_s(now) - state.segment_started_used_s, 0.0)


def segment_overrun(
    state: SessionState, segment: PlannedSegment, now: datetime, allowance: float
) -> float:
    """How far over its budget the round is, as a fraction; 0 when inside it.

    EC-6.9: a round may run `allowance` over (25%, 0% in Final Boss) before
    the clock moves it on.
    """
    if segment.minutes <= 0:
        return 0.0
    limit = segment.minutes * 60 * (1 + allowance)
    elapsed = segment_elapsed_s(state, now)
    return max((elapsed - limit) / (segment.minutes * 60), 0.0) if elapsed > limit else 0.0


def over_time(
    state: SessionState, segment: PlannedSegment, now: datetime, allowance: float
) -> bool:
    if segment.kind in ("closing", "warmup"):
        # The warm-up is one question by construction and the closing is
        # the student's; neither is cut short by its own clock.
        return False
    if segment.minutes <= 0:
        return False
    return segment_elapsed_s(state, now) > segment.minutes * 60 * (1 + allowance)


__all__ = [
    "CLOSING_AT",
    "FOCUS_AT",
    "WARN_AT",
    "Reading",
    "closing_segment",
    "over_time",
    "read",
    "remaining_segments",
    "segment_elapsed_s",
    "segment_overrun",
    "warnings_due",
]
