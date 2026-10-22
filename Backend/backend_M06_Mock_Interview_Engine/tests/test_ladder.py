"""The probe ladder — spec §6.5, Revision 2. A pure function, tested as one."""

from __future__ import annotations

import random

import pytest

from backend_M06_Mock_Interview_Engine.contracts import (
    DEPTH_CAP,
    ProbeLadderState,
    StrategistVerdict,
)
from backend_M06_Mock_Interview_Engine.ladder import LadderConfig, decide


def v(**kw) -> StrategistVerdict:
    base = {"band": "at", "justification": "held", "confidence": 0.8}
    base.update(kw)
    return StrategistVerdict(**base)


def ladder(depth=0, successes=0, moves=()) -> ProbeLadderState:
    return ProbeLadderState(
        concept_id="concept:hashing",
        depth=depth,
        consecutive_successes=successes,
        moves=list(moves),
    )


def own_to(n: int):
    return lambda d: d <= n


CFG = LadderConfig()


def test_a_held_answer_climbs_one_rung():
    out = decide(ladder(0), v(), config=CFG, has_own_rung=own_to(3))
    assert out.move.kind == "rung" and out.move.depth == 1
    assert out.success is True


def test_a_failed_justification_is_the_graceful_exit():
    """A verdict of band and justification only — what every verdict was
    before strategist-5 — keeps the policy it was written for."""
    out = decide(
        ladder(2), v(band="below", justification="failed"), config=CFG, has_own_rung=own_to(5)
    )
    assert out.move.kind == "move_on"
    assert out.move.graceful is True
    assert out.break_depth == 2
    assert out.success is False


def test_a_wrong_answer_is_challenged_once_then_it_is_the_graceful_exit():
    """2026-10-22. Until then a failed justification moved straight on — and
    one judged "partial" went a rung DEEPER, as if it had been right. A wrong
    answer is now pointed at once, with a chance to reconsider; still wrong
    after that, the question is left, and the break recorded."""
    wrong = v(band="below", justification="failed", category="incorrect", severity="material")
    first = decide(ladder(2), wrong, config=CFG, has_own_rung=own_to(5))
    assert first.move.kind == "challenge"
    assert first.move.tone == "challenge"
    assert first.success is False and first.break_depth is None
    challenged = ladder(2, moves=["rung", "rung", "challenge"])
    challenged.challenges = 1
    second = decide(challenged, wrong, config=CFG, has_own_rung=own_to(5))
    assert second.move.kind == "move_on"
    assert second.move.graceful is True
    assert second.break_depth == 2
    assert second.success is False
    assert second.left == "gap:misunderstanding"


def test_two_clears_at_depth_four_is_the_ceiling():
    out = decide(ladder(4, successes=1), v(band="above"), config=CFG, has_own_rung=own_to(5))
    assert out.move.kind == "move_on"
    assert out.ceiling == 4
    assert out.move.graceful is False


def test_the_cap_ends_the_ladder():
    out = decide(ladder(DEPTH_CAP), v(), config=CFG, has_own_rung=own_to(9))
    assert out.move.kind == "move_on"


def test_ambiguity_clarifies_once_without_consuming_depth():
    first = decide(ladder(1), v(ambiguous=True), config=CFG, has_own_rung=own_to(5))
    assert first.move.kind == "clarify"
    assert first.success is None
    second = decide(
        ladder(1, moves=["rung", "clarify"]), v(ambiguous=True), config=CFG, has_own_rung=own_to(5)
    )
    assert second.move.kind == "rung" and second.move.depth == 2


def test_off_question_redirects_once_then_is_judged():
    first = decide(ladder(0), v(off_question=True), config=CFG, has_own_rung=own_to(5))
    assert first.move.kind == "redirect_once"
    second = decide(
        ladder(0, moves=["redirect_once"]), v(off_question=True), config=CFG, has_own_rung=own_to(5)
    )
    assert second.move.kind != "redirect_once"


def test_a_question_to_the_interviewer_gets_a_brief_answer():
    """EC-6.3."""
    out = decide(ladder(1), v(asks_interviewer=True), config=CFG, has_own_rung=own_to(5))
    assert out.move.kind == "answer_briefly"
    assert out.success is None


def test_asking_for_the_answer_gets_a_hint_while_hints_last():
    """EC-6.5."""
    with_hints = decide(
        ladder(0), v(asks_for_answer=True), config=CFG, has_own_rung=own_to(5), hints_left=1
    )
    assert with_hints.move.kind == "hint"
    none_left = decide(
        ladder(0), v(asks_for_answer=True), config=CFG, has_own_rung=own_to(5), hints_left=0
    )
    assert none_left.move.kind == "move_on" and none_left.move.graceful
    no_hints_mode = decide(
        ladder(0),
        v(asks_for_answer=True),
        config=LadderConfig(hints_available=False),
        has_own_rung=own_to(5),
        hints_left=3,
    )
    assert no_hints_mode.move.kind == "move_on"


def test_missing_key_points_do_not_force_a_deeper_probe():
    """Revision 1's `if rubric_gaps: return "deepen"` drilled past the break.
    Since 2026-10-22 a right-but-incomplete answer gets ONE question about the
    area it missed, at the same depth — never a rung deeper on it."""
    wrong = decide(
        ladder(2),
        v(band="below", justification="failed", key_points_missing=["kp1"]),
        config=CFG,
        has_own_rung=own_to(5),
    )
    assert wrong.move.kind == "move_on"
    wrong_now = decide(
        ladder(2),
        v(
            band="below",
            justification="failed",
            category="incorrect",
            key_points_missing=["kp1"],
        ),
        config=CFG,
        has_own_rung=own_to(5),
    )
    assert wrong_now.move.kind != "rung"
    from backend_M06_Mock_Interview_Engine.ladder import Context

    incomplete = decide(
        ladder(2),
        v(category="correct_incomplete", key_points_missing=["kp1"]),
        config=CFG,
        has_own_rung=own_to(5),
        ctx=Context(key_points={"kp1": "Names the load factor."}),
    )
    assert incomplete.move.kind == "probe_missing"
    assert incomplete.move.depth is None
    asked_once = decide(
        ladder(2, moves=["probe_missing"]),
        v(category="correct_incomplete", key_points_missing=["kp1"]),
        config=CFG,
        has_own_rung=own_to(5),
        ctx=Context(key_points={"kp1": "Names the load factor."}),
    )
    assert asked_once.move.kind != "probe_missing"


def test_a_rule_verdict_deepens_once_then_moves_on():
    """Spec §10: no judgement → one more rung is fair, a second is a guess."""
    rule = v(justification="partial", confidence=0.0, source="rule")
    assert decide(ladder(0), rule, config=CFG, has_own_rung=own_to(5)).move.kind == "rung"
    assert decide(ladder(1), rule, config=CFG, has_own_rung=own_to(5)).move.kind == "move_on"


def test_rungs_stop_when_only_generic_wording_is_left():
    """One generic rung is a fair probe; a second on a warm-up is noise."""
    out = decide(ladder(0), v(), config=CFG, has_own_rung=own_to(0))
    assert out.move.kind == "rung" and out.move.depth == 1
    out = decide(ladder(1, successes=1), v(), config=CFG, has_own_rung=own_to(0))
    assert out.move.kind == "move_on"
    assert out.ceiling is None


@pytest.mark.gate
@pytest.mark.parametrize("mode", ["practice", "mock", "real_drive", "final_boss"])
def test_no_steelman_in_any_mode_while_disabled(mode):
    """AC-6.14. Revision 1 reached `steelman` at depth 3 in every mode."""
    rng = random.Random(f"steelman-gate:{mode}")  # str seeds are reproducible; hash() is not
    config = LadderConfig(steelman_enabled=False, steelman_rate=1.0)
    bands = ["below", "at", "above"]
    justifications = ["held", "partial", "failed"]
    for _ in range(10_000):
        state = ladder(rng.randint(0, DEPTH_CAP), successes=rng.randint(0, 3))
        verdict = v(
            band=rng.choice(bands),
            justification=rng.choice(justifications),
            ambiguous=rng.random() < 0.1,
            off_question=rng.random() < 0.1,
            asks_interviewer=rng.random() < 0.05,
            asks_for_answer=rng.random() < 0.05,
            source=rng.choice(["model", "rule"]),
        )
        out = decide(
            state,
            verdict,
            config=config,
            has_own_rung=own_to(rng.randint(0, 5)),
            hints_left=rng.randint(0, 2),
            rng=rng.random,
        )
        assert out.move.kind != "steelman"


def test_steelman_is_reachable_only_through_the_flag():
    out = decide(
        ladder(1),
        v(),
        config=LadderConfig(steelman_enabled=True, steelman_rate=1.0),
        has_own_rung=own_to(5),
        rng=lambda: 0.0,
    )
    assert out.move.kind == "steelman"
