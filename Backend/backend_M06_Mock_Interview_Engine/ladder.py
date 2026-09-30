"""The probe ladder — spec §6.5, Revision 2. A pure function.

**Rungs and moves are different things.** A rung takes the ladder one level
deeper and consumes depth. A move — clarify, redirect, a brief answer to the
student's own question, a hint — does not. Revision 1 kept both in one list
and indexed it by depth, which put `steelman` on the ordinary fall-through at
depth 3 in every mode: a Practice session going well would have been told
something false on purpose (M06_REVIEW 2.4).

**Steelman is unreachable while `steelman_enabled` is false**, which it is in
every mode until M13 ships a `push_back` rubric (FR-6.20, AC-6.14). Scoring a
steelman turn under the ordinary rubric would reward agreeing with a falsehood.

**Missing key points do not force a deeper probe.** Revision 1's
`if rubric_gaps: return "deepen"` kept pushing on a point the student had not
reached — the "drilled past the break" experience the graceful exit exists to
prevent. Missing points are the report's business.

**A rule verdict deepens once, then moves on** (spec §10): with no judgement
of the answer, one more rung is a fair question and a second is a guess.

**How deep is the persona's, not the ladder's** (§6.7). `max_depth` comes from
`follow_up_aggression`: a friendly recruiter stops at two follow-ups, a
bar-raiser goes to five. That is the experience, which §6.7 allows to differ;
the verdict it is decided on is the same prompt in every mode (AC-6.17).

**Conduct comes before the answer** (EC-6.4). Abuse is not an answer to
judge: the first time is one neutral redirect with the question again, the
second ends the session politely. Neither consumes depth or records a break —
the ladder is about knowledge, and this is not.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from .contracts import DEPTH_CAP, Move, ProbeLadderState, StrategistVerdict


@dataclass(frozen=True)
class LadderConfig:
    steelman_enabled: bool = False
    steelman_rate: float = 0.0
    hints_available: bool = True
    #: The persona's `max_depth` (§6.7). Never above the spec's cap.
    max_depth: int = DEPTH_CAP
    #: Stop early when the question has no wording of its own past this depth
    #: AND the student has already cleared a rung. A generic "where else would
    #: you use it?" on a warm-up is noise, not depth.
    max_generic_rungs: int = 1


@dataclass(frozen=True)
class Outcome:
    move: Move
    #: What the fold records: whether this answer counted as a success, and
    #: the break or ceiling it established.
    success: bool | None
    break_depth: int | None = None
    ceiling: int | None = None
    #: EC-6.4. True when this move answers the student's conduct, which the
    #: fold counts and the second of which ends the session.
    conduct: bool = False


def decide(
    ladder: ProbeLadderState,
    verdict: StrategistVerdict,
    *,
    config: LadderConfig,
    has_own_rung: Callable[[int], bool],
    hints_left: int = 0,
    conduct_warnings: int = 0,
    rng: Callable[[], float] = random.random,
) -> Outcome:
    depth = ladder.depth
    success = verdict.band != "below" and verdict.justification != "failed"

    # EC-6.4 first: abuse is not an answer, so nothing below applies to it.
    if verdict.abusive:
        if conduct_warnings == 0:
            return Outcome(Move(kind="redirect_conduct"), success=None, conduct=True)
        return Outcome(Move(kind="end_session"), success=None, conduct=True)

    # Moves that answer the student rather than the question. No depth.
    if verdict.asks_interviewer:
        return Outcome(Move(kind="answer_briefly"), success=None)
    if verdict.asks_for_answer:
        if config.hints_available and hints_left > 0:
            return Outcome(Move(kind="hint"), success=None)
        return Outcome(Move(kind="move_on", graceful=True), success=None, break_depth=depth)
    if verdict.ambiguous and "clarify" not in ladder.moves[-1:]:
        # Once. A second unclear answer is treated as the answer it is.
        return Outcome(Move(kind="clarify"), success=None)
    if verdict.off_question and "redirect_once" not in ladder.moves:
        return Outcome(Move(kind="redirect_once"), success=None)

    # The graceful exit (§2.2). The ladder stops at the first failed rung.
    if verdict.justification == "failed":
        return Outcome(Move(kind="move_on", graceful=True), success=False, break_depth=depth)

    streak = ladder.consecutive_successes + 1 if success else 0

    # Don't punish success: two clears in a row at depth ≥ 4 is the ceiling.
    if success and streak >= 2 and depth >= 4:
        return Outcome(Move(kind="move_on"), success=True, ceiling=depth)
    if depth >= min(config.max_depth, DEPTH_CAP):
        return Outcome(Move(kind="move_on"), success=success, ceiling=depth if success else None)

    if verdict.source == "rule" and depth >= 1:
        return Outcome(Move(kind="move_on"), success=None)

    if config.steelman_enabled and success and rng() < config.steelman_rate:
        return Outcome(Move(kind="steelman"), success=success)

    target = depth + 1
    if not has_own_rung(target):
        generic_used = sum(1 for d in range(1, target) if not has_own_rung(d))
        if generic_used >= config.max_generic_rungs:
            # Out of things worth asking. Not a ceiling — the student was not
            # stretched to one — so nothing is recorded beyond the success.
            return Outcome(Move(kind="move_on"), success=success)
    return Outcome(Move(kind="rung", depth=target), success=success)


__all__ = ["LadderConfig", "Outcome", "decide"]
