"""The probe ladder — spec §6.5, Revision 2, and the 2026-10-22 controller. Pure.

**Rungs and moves are different things.** A rung takes the ladder one level
deeper and consumes depth. A move — clarify, redirect, a challenge, a simpler
question, a brief answer to the student's own question, a hint — does not.
Revision 1 kept both in one list and indexed it by depth, which put
`steelman` on the ordinary fall-through at depth 3 in every mode: a Practice
session going well would have been told something false on purpose
(M06_REVIEW 2.4).

**Steelman is unreachable while `steelman_enabled` is false**, which it is in
every mode until M13 ships a `push_back` rubric (FR-6.20, AC-6.14). Scoring a
steelman turn under the ordinary rubric would reward agreeing with a falsehood.

**2026-10-22: the answer decides the move, by what it is.** Until today any
answer that was not an outright failure climbed a rung — so a wrong answer
judged "partial" got "can you say more about why that works?", as if it had
been right, and a student who could not answer the fundamental question was
asked something harder about it. The strategist now says what an answer IS
(`StrategistVerdict.category`), and the order below is the policy, readable
top to bottom, every branch with its reason:

    abuse                 one neutral redirect, then a polite end (EC-6.4)
    a request             answer briefly · hint · rephrase · a moment to think
    cut off               "you got cut off — you were saying?"
    ambiguous             clarify, once
    off the question      put it again once; then leave it (`avoided`)
    the same answer again "my question now is…", once
    contradiction         both statements quoted back, once
    unsupported claim     "how did you measure that?", up to twice per claim
    don't know            a simpler, diagnostic question once; then leave it
                          (partial recall of a detail: leave it, kindly)
    wrong / partly wrong  pointed at in their words, once ("a small issue" for a
                          slip); a fundamental error then gets the simpler
                          question; a slip that stands does not end the topic
    vague                 "what actually happens when…?", once; then leave it
    right, incomplete     the next part, or the area it did not reach — once
    right                 the next part; else one rung deeper, harder when the
                          topic is going well; the ceiling at two clears at ≥ 4

**Missing key points do not push deeper.** Revision 1's
`if rubric_gaps: return "deepen"` kept pushing on a point the student had not
reached — the "drilled past the break" experience the graceful exit exists to
prevent. An incomplete answer gets ONE question about the area it missed, at
the same depth (`probe_missing`); the rest is the notes' business.

**A rule verdict deepens once, then moves on** (spec §10): with no judgement
of the answer, one more rung is a fair question and a second is a guess.

**How deep is the persona's and the topic's** (§6.7, `difficulty.py`).
`max_depth` comes from `follow_up_aggression`; a topic going well allows one
rung more, one going badly one less. The verdict it is decided on is the same
prompt in every mode (AC-6.17).

**Conduct comes before the answer** (EC-6.4). Abuse is not an answer to
judge: the first time is one neutral redirect with the question again, the
second ends the session politely. Neither consumes depth or records a break —
the ladder is about knowledge, and this is not.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from . import difficulty
from .contracts import (
    DEPTH_CAP,
    JUDGED_CATEGORIES,
    Move,
    ProbeLadderState,
    StrategistVerdict,
    category_of,
    quality_of,
)
from .items import Part

#: Moves that help the student toward the answer. A right answer after one
#: of them is a correction made with help (`corrected="prompted"`).
ASSISTING = frozenset(
    {"challenge", "simplify", "hint", "probe_missing", "probe_specifics", "confront"}
)
#: Categories that are an error or a gap — what a later right answer corrects.
STRUGGLES = frozenset({"incorrect", "partial", "vague", "dont_know", "contradiction"})
#: Moves that only put the question again, or answer a request: no help, no
#: judgement, so they say nothing about whether a correction was helped.
RESTATING = frozenset(
    {
        "rephrase",
        "didnt_catch",
        "clarify_term",
        "reoffer",
        "give_time",
        "resume_cut",
        "clarify",
        "redirect_once",
        "redirect_repeat",
        "answer_briefly",
    }
)


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
    # ── 2026-10-22 ───────────────────────────────────────────────────────
    #: Whether a wrong answer may be met with a simpler, diagnostic question.
    #: Off in Final Boss, which keeps going until the reasoning runs out.
    simplify: bool = True
    #: Pushbacks on an error per question.
    max_challenges: int = 1
    #: "How did you measure that?" per claim.
    max_evidence_asks: int = 2
    #: The question is about the student's own resume: follow-ups are about
    #: what they built, why, and what it cost (`difficulty.RESUME`).
    resume: bool = False


@dataclass(frozen=True)
class Context:
    """What the ladder knows besides the answer — all of it from the session
    itself, assembled by `thread.context()`."""

    #: Parts of the question not asked yet, in order.
    parts_left: tuple[Part, ...] = ()
    #: The topic's level now (`difficulty.py`).
    topic_level: int = 0
    #: This answer is (nearly) an earlier answer in this question again.
    repeated_answer: bool = False
    #: The answer was cut off by the connection or the microphone.
    cut_off: bool = False
    #: Misconceptions already met in this topic in this interview.
    seen_misconceptions: tuple[str, ...] = ()
    #: The question's key points, id → statement (for `probe_missing`).
    key_points: dict[str, str] = field(default_factory=dict)
    required: frozenset[str] = frozenset()


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
    #: Why, in plain words — the trace, the notes, and the topic's
    #: `last_decision`. Never shown to the interviewer (FR-6.15).
    reason: str = ""
    #: What this answer showed, 0–1 (`QUALITY`); None when it was not judged.
    quality: float | None = None
    #: When this moves on: how the question was left — `held`, `ceiling`,
    #: `gap:minor`, `gap:detail`, `gap:incomplete`, `gap:surface`,
    #: `gap:misunderstanding`, `gap:complete`, `gap:advanced`, `unsupported`,
    #: `avoided`, `no_answer`.
    left: str | None = None
    #: `self` / `prompted` when this answer fixed an earlier error.
    corrected: str | None = None


def decide(
    ladder: ProbeLadderState,
    verdict: StrategistVerdict,
    *,
    config: LadderConfig,
    has_own_rung: Callable[[int], bool],
    hints_left: int = 0,
    conduct_warnings: int = 0,
    ctx: Context | None = None,
    rng: Callable[[], float] = random.random,
) -> Outcome:
    ctx = ctx or Context()
    depth = ladder.depth
    moves = ladder.moves
    category = category_of(verdict)

    # EC-6.4 first: abuse is not an answer, so nothing below applies to it.
    if verdict.abusive:
        if conduct_warnings == 0:
            return Outcome(
                Move(kind="redirect_conduct"),
                success=None,
                conduct=True,
                reason="conduct: one neutral redirect",
            )
        return Outcome(
            Move(kind="end_session"), success=None, conduct=True, reason="conduct, a second time"
        )

    # Moves that answer the student rather than the question. No depth.
    if verdict.asks_interviewer:
        return Outcome(
            Move(kind="answer_briefly"), success=None, reason="the student asked us something"
        )
    if verdict.asks_for_answer:
        if config.hints_available and hints_left > 0:
            return Outcome(Move(kind="hint"), success=None, reason="asked for help: a hint")
        return _leave(depth, "gap:complete", "asked for the answer; no hint to give")
    if verdict.asks_to_rephrase:
        # Twice a question, in other words; a third time it is a question
        # they cannot do yet, and a hint or the graceful exit is kinder.
        if moves.count("rephrase") < 2:
            return Outcome(
                Move(kind="rephrase"), success=None, reason="did not follow the question"
            )
        if config.hints_available and hints_left > 0:
            return Outcome(Move(kind="hint"), success=None, reason="still not following: a hint")
        return _leave(depth, "gap:complete", "still not following after two rephrasings")
    if verdict.asks_for_time and "give_time" not in moves:
        return Outcome(Move(kind="give_time"), success=None, reason="asked for a moment")
    if ctx.cut_off and "resume_cut" not in moves:
        return Outcome(Move(kind="resume_cut"), success=None, reason="the answer was cut off")
    if (verdict.ambiguous or category == "ambiguous") and "clarify" not in moves[-1:]:
        # Once. A second unclear answer is treated as the answer it is.
        return Outcome(Move(kind="clarify"), success=None, reason="could be read two ways: clarify")
    if verdict.off_question or category == "off_question":
        if "redirect_once" not in moves:
            return Outcome(
                Move(kind="redirect_once"), success=None, reason="answered a different question"
            )
        if verdict.category is not None:
            return Outcome(
                Move(kind="move_on", graceful=True),
                success=False,
                left="avoided",
                reason="stayed off the question after it was put again",
            )

    if verdict.category is None:
        # A verdict from before strategist-5 (an old event replayed, an older
        # prompt) says only band and justification — it gets the policy it was
        # written for, unchanged.
        return _legacy(ladder, verdict, config=config, has_own_rung=has_own_rung, rng=rng)

    if category in ("non_answer", "ambiguous"):
        if category == "non_answer" and "clarify" not in moves:
            return Outcome(Move(kind="clarify"), success=None, reason="no attempt yet: clarify")
        return _leave(depth, "no_answer", "no attempt at the question", break_=False)

    if ctx.repeated_answer and "redirect_repeat" not in moves and depth + len(moves) > 0:
        return Outcome(
            Move(kind="redirect_repeat"),
            success=None,
            reason="the same answer again, to a different follow-up",
        )

    if verdict.challenges_question and not verdict.challenge_valid and "redirect_once" not in moves:
        # They questioned the premise, and the premise stands: the question
        # is put again, as asked — not argued, and not judged.
        return Outcome(
            Move(kind="redirect_once"),
            success=None,
            reason="questioned the premise, which stands: the question again",
        )
    conceded = verdict.challenges_question and verdict.challenge_valid
    if conceded and category not in ("correct", "correct_incomplete"):
        # A flaw they found in OUR question is not a gap in their answer.
        category = "correct_incomplete"

    # A correction is the right answer that turns a struggle round — judged
    # answers only, so a request in between hides nothing — and it was helped
    # if the last move that did more than put the question again was help.
    # A later right answer is not a correction again: live, the next one
    # relabelled a correction made after a pushback "corrected yourself"
    # (2026-10-23).
    judged = [c for c in ladder.categories if c in JUDGED_CATEGORIES]
    turned = bool(judged) and judged[-1] in STRUGGLES
    helped = [m for m in moves if m not in RESTATING]
    assisted = bool(helped) and helped[-1] in ASSISTING
    if verdict.self_corrected and category in ("incorrect", "partial"):
        # They caught it themselves: what stands is the corrected answer.
        category = "correct_incomplete"
    corrected: str | None = None
    if category in ("correct", "correct_incomplete") and (turned or verdict.self_corrected):
        corrected = "prompted" if assisted and turned else "self"
    quality = quality_of(verdict, corrected=corrected == "prompted")
    if verdict.self_corrected and quality is not None:
        quality = max(quality, 0.75)

    if category == "contradiction":
        if "confront" not in moves and verdict.contradiction_quote:
            return Outcome(
                Move(
                    kind="confront",
                    focus=verdict.error_quote,
                    other=verdict.contradiction_quote,
                    tone="challenge",
                ),
                success=False,
                quality=quality,
                reason="this answer does not fit what they said earlier",
            )
        category = "partial" if verdict.correct_points else "incorrect"

    if category == "unsupported":
        if ladder.evidence_asks < config.max_evidence_asks:
            return Outcome(
                Move(kind="ask_evidence", focus=verdict.unsupported_quote or verdict.error_quote),
                success=None,
                quality=quality,
                reason="a claim with nothing behind it: how was it measured?",
            )
        return _leave(
            depth, "unsupported", "the claim stayed unsupported after two asks", quality=quality
        )

    if category == "dont_know":
        if verdict.partial_recall:
            return _leave(
                depth, "gap:detail", "knows the idea, not the detail", quality=quality, break_=False
            )
        if _may_simplify(ladder, config):
            return Outcome(
                Move(kind="simplify", angle="mechanism"),
                success=False,
                quality=quality,
                reason="does not know it: a simpler question, to find the fundamental",
            )
        left = "gap:complete" if depth == 0 or "simplify" in moves else "gap:advanced"
        return _leave(depth, left, "does not know it, after a simpler question", quality=quality)

    if category in ("incorrect", "partial"):
        severity = verdict.severity if verdict.severity != "none" else "material"
        repeated = bool(verdict.misconception) and any(
            difficulty.same_misconception(verdict.misconception or "", seen)
            for seen in ctx.seen_misconceptions
        )
        if ladder.challenges < config.max_challenges and not repeated:
            what = "a slip" if severity == "minor" else "an error"
            return Outcome(
                Move(
                    kind="challenge",
                    focus=verdict.error_quote,
                    credit=(verdict.correct_points or [None])[0] if category == "partial" else None,
                    tone="challenge",
                    severity=severity,
                ),
                success=False,
                quality=quality,
                reason=f"{what} in the answer, pointed at once so they can reconsider",
            )
        if severity == "minor":
            # A slip that stands is not a misunderstanding: noted, and the
            # question goes on as a partly right answer would.
            category = "correct_incomplete"
        elif severity == "fundamental" and _may_simplify(ladder, config):
            return Outcome(
                Move(kind="simplify", angle="mechanism"),
                success=False,
                quality=quality,
                reason="the core idea is confused: a simpler question on it",
            )
        else:
            why = (
                "the same misconception as earlier, so not pushed again"
                if repeated
                else "the error stood after one pushback"
            )
            return _leave(depth, "gap:misunderstanding", why, quality=quality)

    if category == "vague":
        if "probe_specifics" not in moves:
            return Outcome(
                Move(kind="probe_specifics", focus=verdict.error_quote),
                success=False,
                quality=quality,
                reason="terms without the mechanism: ask for the specifics",
            )
        return _leave(depth, "gap:surface", "stayed at the level of terms", quality=quality)

    # Right — fully, or as far as it went.
    streak = ladder.consecutive_successes + 1
    part = _next_part(ctx.parts_left, verdict.key_points_missing)
    if part is not None:
        return Outcome(
            Move(kind="next_part", text=part.text, part=part.index, tone="credit"),
            success=True,
            quality=quality,
            corrected=corrected,
            reason=f"held: the next part of the question ({part.index + 1})",
        )
    if category == "correct_incomplete" and "probe_missing" not in moves:
        missing = sorted(
            (k for k in verdict.key_points_missing if k in ctx.key_points),
            key=lambda k: k not in ctx.required,
        )
        if missing:
            return Outcome(
                Move(kind="probe_missing", other=ctx.key_points[missing[0]], tone="credit"),
                success=True,
                quality=quality,
                corrected=corrected,
                reason="right as far as it went: ask about what it did not reach",
            )

    if streak >= 2 and depth >= 4:
        # Don't punish success: two clears in a row at depth ≥ 4 is the ceiling.
        return Outcome(
            Move(kind="move_on"),
            success=True,
            ceiling=depth,
            quality=quality,
            corrected=corrected,
            left="ceiling",
            reason="two strong answers at depth four or more: the ceiling",
        )
    allowed = difficulty.allowed_depth(config.max_depth, ctx.topic_level)
    if depth >= allowed:
        return Outcome(
            Move(kind="move_on"),
            success=True,
            ceiling=depth,
            quality=quality,
            corrected=corrected,
            left="ceiling",
            reason=f"held to the depth this topic allows ({allowed})",
        )
    if config.steelman_enabled and rng() < config.steelman_rate:
        return Outcome(Move(kind="steelman"), success=True, quality=quality)

    target = depth + 1
    if not has_own_rung(target):
        generic_used = sum(1 for d in range(1, target) if not has_own_rung(d))
        budget = config.max_generic_rungs + (1 if ctx.topic_level >= 1 else 0)
        if generic_used >= budget:
            # Out of things worth asking. Not a ceiling — the student was not
            # stretched to one — so nothing is recorded beyond the success.
            return Outcome(
                Move(kind="move_on"),
                success=True,
                quality=quality,
                corrected=corrected,
                left="held",
                reason="held, and nothing deeper worth asking on this question",
            )
    angle = difficulty.angle_for(ctx.topic_level, ladder.angles, resume=config.resume)
    harder = " (harder: the topic is going well)" if ctx.topic_level >= 1 else ""
    return Outcome(
        Move(
            kind="rung",
            depth=target,
            angle=angle,
            tone="credit",
            credit="a fair point about the question's assumption" if conceded else None,
        ),
        success=True,
        quality=quality,
        corrected=corrected,
        reason=f"held: one level deeper, {angle.replace('_', ' ')}{harder}",
    )


def _leave(
    depth: int,
    left: str,
    reason: str,
    *,
    quality: float | None = None,
    break_: bool = True,
) -> Outcome:
    """The graceful exit: the question is left, and how it was left is kept."""
    return Outcome(
        Move(kind="move_on", graceful=True),
        success=False,
        break_depth=depth if break_ else None,
        quality=quality,
        left=left,
        reason=reason,
    )


def _may_simplify(ladder: ProbeLadderState, config: LadderConfig) -> bool:
    """A simpler question finds out whether the fundamental is there — so
    only while this question has not already shown that it is."""
    shown = any(c in ("correct", "correct_incomplete") for c in ladder.categories)
    return config.simplify and "simplify" not in ladder.moves and not shown


def _next_part(parts: tuple[Part, ...], missing: list[str]) -> Part | None:
    """The next part to ask: one covering a point the answer has not reached
    yet, in order — and none whose points the answer already covered."""
    if not parts:
        return None
    missing_set = set(missing)
    for part in parts:
        if not part.key_point_ids or set(part.key_point_ids) & missing_set:
            return part
    return None


def _legacy(
    ladder: ProbeLadderState,
    verdict: StrategistVerdict,
    *,
    config: LadderConfig,
    has_own_rung: Callable[[int], bool],
    rng: Callable[[], float],
) -> Outcome:
    """Revision 2's policy, for a verdict of band and justification only —
    and for the rule strategist with no reading of the answer (§10), whose one
    more rung is a fair question and whose second is a guess."""
    depth = ladder.depth
    success = verdict.band != "below" and verdict.justification != "failed"
    # The rule strategist has not read the answer: it may move on, never say
    # how the answer went. Until 2026-10-23 it said "held", and a live run
    # with the model down noted "Answered well" under every answer — the
    # wrong one and the "I'm not sure" ones too.
    read = verdict.source != "rule"
    held = ("ceiling" if success else "held") if read else "unjudged"
    if verdict.justification == "failed":
        # No `left`: an older verdict cannot say what kind of gap it was, so
        # the question closes on the persona's own graceful line, as it did.
        return Outcome(
            Move(kind="move_on", graceful=True),
            success=False,
            break_depth=depth,
            reason="the reasoning failed (an older verdict)",
        )
    streak = ladder.consecutive_successes + 1 if success else 0
    if read and success and streak >= 2 and depth >= 4:
        return Outcome(
            Move(kind="move_on"), success=True, ceiling=depth, left="ceiling", reason="the ceiling"
        )
    if depth >= min(config.max_depth, DEPTH_CAP):
        return Outcome(
            Move(kind="move_on"),
            success=success,
            ceiling=depth if success and read else None,
            left=held,
            reason="at the persona's depth",
        )
    if not read and depth >= 1:
        return Outcome(
            Move(kind="move_on"), success=None, left="unjudged", reason="no model: moved on"
        )
    if config.steelman_enabled and success and rng() < config.steelman_rate:
        return Outcome(Move(kind="steelman"), success=success)
    target = depth + 1
    if not has_own_rung(target):
        generic_used = sum(1 for d in range(1, target) if not has_own_rung(d))
        if generic_used >= config.max_generic_rungs:
            return Outcome(
                Move(kind="move_on"),
                success=success,
                left="held" if read else "unjudged",
                reason="nothing deeper to ask",
            )
    return Outcome(
        Move(
            kind="rung",
            depth=target,
            angle="mechanism",
            # No assent to an answer nobody read.
            tone="credit" if success and read else "neutral",
        ),
        success=success,
        reason="one rung deeper",
    )


__all__ = ["ASSISTING", "Context", "LadderConfig", "Outcome", "Part", "decide"]
