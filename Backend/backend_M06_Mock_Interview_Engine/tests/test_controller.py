"""The 2026-10-22 controller: what an answer IS decides what the interviewer
does next — one case per answer type in the user's list (A–X), decision level.

Pure functions (`ladder.decide`, `difficulty.update`): no model, no database.
The phrasing of each move is `test_reactions.py`; the whole loop through the
engine is `test_answer_types.py`.
"""

from __future__ import annotations

import pytest

from backend_M06_Mock_Interview_Engine import difficulty
from backend_M06_Mock_Interview_Engine.contracts import (
    ProbeLadderState,
    StrategistVerdict,
    TopicState,
    legacy_fields,
    quality_of,
)
from backend_M06_Mock_Interview_Engine.items import Part
from backend_M06_Mock_Interview_Engine.ladder import Context, LadderConfig, decide


def said(category: str, **kw) -> StrategistVerdict:
    """A strategist-5 verdict, its band and justification derived as the
    strategist derives them."""
    severity = kw.pop("severity", "none")
    band, justification = legacy_fields(category, severity, bool(kw.get("beyond")))
    return StrategistVerdict(
        band=band,
        justification=justification,
        confidence=0.8,
        category=category,
        severity=severity,
        **kw,
    )


def thread(depth: int = 0, *, moves=(), challenges: int = 0, categories=(), evidence: int = 0):
    state = ProbeLadderState(concept_id="concept:hashing", depth=depth, moves=list(moves))
    state.challenges = challenges
    state.categories = list(categories)
    state.evidence_asks = evidence
    return state


CFG = LadderConfig(max_generic_rungs=2)


def go(state, verdict, *, config=CFG, ctx=None, own=0, hints=0):
    return decide(
        state,
        verdict,
        config=config,
        has_own_rung=lambda d: d <= own,
        hints_left=hints,
        ctx=ctx,
    )


# ── A–X ──────────────────────────────────────────────────────────────────


def test_a_correct_but_incomplete_asks_about_what_it_missed_once():
    ctx = Context(key_points={"kp2": "Names a bounded load factor."}, required=frozenset())
    out = go(thread(0), said("correct_incomplete", key_points_missing=["kp2"]), ctx=ctx)
    assert out.move.kind == "probe_missing" and out.success is True
    assert out.move.other == "Names a bounded load factor."
    assert out.quality == pytest.approx(0.75)


def test_b_partly_right_is_pushed_back_on_with_what_was_right_first():
    out = go(
        thread(0),
        said(
            "partial",
            severity="material",
            correct_points=["hashes the key to a bucket"],
            error_quote="lookup is always O(1)",
        ),
    )
    assert out.move.kind == "challenge" and out.move.tone == "challenge"
    assert out.move.credit == "hashes the key to a bucket"
    assert out.move.focus == "lookup is always O(1)"
    assert out.success is False


def test_c_confidently_wrong_is_challenged_then_simplified_then_left():
    wrong = said("incorrect", severity="fundamental", error_quote="a thread has its own heap")
    first = go(thread(0), wrong)
    assert first.move.kind == "challenge" and first.move.severity == "fundamental"
    second = go(thread(0, moves=["challenge"], challenges=1, categories=["incorrect"]), wrong)
    assert second.move.kind == "simplify"
    third = go(
        thread(0, moves=["challenge", "simplify"], challenges=1, categories=["incorrect"] * 2),
        wrong,
    )
    assert third.move.kind == "move_on" and third.move.graceful
    assert third.left == "gap:misunderstanding"


def test_c_final_boss_offers_no_simpler_question():
    wrong = said("incorrect", severity="fundamental")
    out = go(
        thread(0, moves=["challenge"], challenges=1),
        wrong,
        config=LadderConfig(simplify=False),
    )
    assert out.move.kind == "move_on" and out.left == "gap:misunderstanding"


def test_d_vague_asks_for_the_mechanism_once_then_leaves_it():
    vague = said("vague", error_quote="it uses hashing for speed")
    first = go(thread(0), vague)
    assert first.move.kind == "probe_specifics" and first.move.focus == "it uses hashing for speed"
    second = go(thread(0, moves=["probe_specifics"], categories=["vague"]), vague)
    assert second.move.kind == "move_on" and second.left == "gap:surface"


def test_e_and_f_long_or_short_a_right_answer_is_right():
    for verdict in (said("correct"), said("correct", beyond=True)):
        out = go(thread(0), verdict)
        assert out.move.kind == "rung" and out.success is True and out.quality == 1.0


def test_g_a_valid_alternative_is_judged_correct_by_the_strategist_and_climbs():
    """The strategist's prompt says a valid alternative is correct; the ladder
    only ever sees the category, so it climbs like any right answer."""
    out = go(thread(1), said("correct"))
    assert out.move.kind == "rung" and out.move.depth == 2


def test_h_off_the_question_is_put_again_once_then_left_as_avoided():
    first = go(thread(0), said("off_question"))
    assert first.move.kind == "redirect_once"
    second = go(thread(0, moves=["redirect_once"]), said("off_question"))
    assert second.move.kind == "move_on" and second.left == "avoided"


def test_i_a_contradiction_is_quoted_back_once():
    verdict = said(
        "contradiction",
        error_quote="we kept the sessions on the server",
        contradiction_quote="the service was stateless",
    )
    out = go(thread(1), verdict)
    assert out.move.kind == "confront" and out.move.tone == "challenge"
    assert out.move.other == "the service was stateless"
    again = go(thread(1, moves=["confront"]), verdict)
    assert again.move.kind != "confront"


def test_j_an_unsupported_claim_is_asked_about_twice_then_left():
    claim = said("unsupported", unsupported_quote="cut latency by 40%")
    first = go(thread(0), claim)
    assert first.move.kind == "ask_evidence" and first.move.focus == "cut latency by 40%"
    second = go(thread(0, moves=["ask_evidence"], evidence=1), claim)
    assert second.move.kind == "ask_evidence"
    third = go(thread(0, moves=["ask_evidence"] * 2, evidence=2), claim)
    assert third.move.kind == "move_on" and third.left == "unsupported"


def test_k_dont_know_gets_a_simpler_question_once():
    first = go(thread(0), said("dont_know"))
    assert first.move.kind == "simplify" and first.quality == 0.0
    second = go(thread(0, moves=["simplify"], categories=["dont_know"]), said("dont_know"))
    assert second.move.kind == "move_on" and second.left == "gap:complete"


def test_l_partial_recall_of_a_detail_is_left_kindly_without_a_break():
    out = go(thread(1), said("dont_know", partial_recall=True))
    assert out.move.kind == "move_on" and out.left == "gap:detail"
    assert out.break_depth is None
    assert out.quality == pytest.approx(0.4)


def test_m_a_self_correction_counts_as_the_corrected_answer():
    out = go(thread(0), said("incorrect", severity="material", self_corrected=True))
    assert out.move.kind != "challenge"
    assert out.success is True and out.corrected == "self"
    assert out.quality >= 0.75


def test_n_right_after_a_challenge_is_a_correction_with_help():
    out = go(
        thread(0, moves=["challenge"], challenges=1, categories=["incorrect"]), said("correct")
    )
    assert out.success is True and out.corrected == "prompted"
    assert out.quality == pytest.approx(0.6)


def test_o_a_repeated_misconception_is_not_pushed_on_again():
    verdict = said("incorrect", severity="material", misconception="threads have separate heaps")
    ctx = Context(seen_misconceptions=("thinks threads have separate heaps",))
    out = go(thread(0), verdict, ctx=ctx)
    assert out.move.kind == "move_on"
    assert "same misconception" in out.reason


def test_p_some_right_some_wrong_is_partial_with_credit():
    out = go(thread(0), said("partial", severity="minor", correct_points=["the index part"]))
    assert out.move.kind == "challenge" and out.move.severity == "minor"


def test_q_ambiguous_is_clarified_once():
    out = go(thread(0), said("ambiguous"))
    assert out.move.kind == "clarify" and out.success is None


def test_r_a_valid_objection_to_the_question_is_conceded_and_the_question_goes_on():
    out = go(thread(0), said("incorrect", challenges_question=True, challenge_valid=True))
    assert out.move.kind in ("rung", "probe_missing", "next_part", "move_on")
    assert out.move.kind != "challenge"
    assert out.success is True


def test_r_an_invalid_objection_gets_the_question_again():
    out = go(thread(0), said("incorrect", challenges_question=True, challenge_valid=False))
    assert out.move.kind == "redirect_once"


def test_s_a_request_for_a_moment_is_given_once():
    out = go(thread(0), said("non_answer", asks_for_time=True))
    assert out.move.kind == "give_time" and out.success is None
    again = go(thread(0, moves=["give_time"]), said("non_answer", asks_for_time=True))
    assert again.move.kind == "clarify"


def test_u_an_empty_answer_is_a_dont_know_by_the_rule():
    from backend_M06_Mock_Interview_Engine.agents.strategist import rule_verdict

    out = go(thread(0), rule_verdict("   "))
    assert out.move.kind == "simplify"


def test_v_the_same_answer_again_is_redirected_once():
    out = go(thread(1, moves=["rung"]), said("correct"), ctx=Context(repeated_answer=True))
    assert out.move.kind == "redirect_repeat"


def test_w_a_cut_off_answer_is_asked_to_finish():
    out = go(thread(0), said("correct_incomplete"), ctx=Context(cut_off=True))
    assert out.move.kind == "resume_cut" and out.success is None


def test_x_abuse_is_conduct_not_an_answer():
    out = go(thread(0), StrategistVerdict(band="below", justification="partial", abusive=True))
    assert out.move.kind == "redirect_conduct" and out.conduct


# ── decomposed questions ─────────────────────────────────────────────────


def test_the_next_part_is_asked_before_going_deeper():
    parts = (Part(1, "How do you handle cache invalidation?", ("kp2",)),)
    out = go(thread(0), said("correct", key_points_missing=["kp2"]), ctx=Context(parts_left=parts))
    assert out.move.kind == "next_part" and out.move.part == 1
    assert out.move.text == "How do you handle cache invalidation?"


def test_a_part_already_answered_is_skipped():
    parts = (Part(1, "How do you handle cache invalidation?", ("kp2",)),)
    out = go(thread(0), said("correct", key_points_missing=[]), ctx=Context(parts_left=parts))
    assert out.move.kind == "rung"


# ── the per-topic level ──────────────────────────────────────────────────


def test_two_strong_answers_raise_the_topic_and_two_weak_ones_lower_it():
    topic = None
    for quality in (1.0, 1.0):
        topic = difficulty.update(topic, "concept:hashing", quality=quality)
    assert topic.level == 1
    # The first weak answer walks the raise back; the second makes two weak
    # running, and the topic goes below where it started.
    topic = difficulty.update(topic, "concept:hashing", quality=0.0)
    assert topic.level == 0
    topic = difficulty.update(topic, "concept:hashing", quality=0.15)
    assert topic.level == -1
    for quality in (0.0, 0.0):
        topic = difficulty.update(topic, "concept:hashing", quality=quality)
    assert topic.level == -2


def test_one_answer_is_not_a_trend():
    assert difficulty.update(None, "c", quality=1.0).level == 0
    assert difficulty.update(None, "c", quality=0.0).level == 0


def test_a_raised_level_walks_back_when_the_answers_stop_agreeing():
    topic = TopicState(concept_id="c", level=2, recent=[1.0, 1.0])
    topic = difficulty.update(topic, "c", quality=0.45)
    assert topic.level == 1


def test_the_level_is_per_topic_and_changes_only_that_topic():
    """A strong run on hashing gives DBMS nothing (the user's spec, §3)."""
    topics: dict[str, TopicState] = {}
    for _ in range(3):
        topics["concept:hashing"] = difficulty.update(
            topics.get("concept:hashing"), "concept:hashing", quality=1.0
        )
    assert topics["concept:hashing"].level >= 1
    assert "concept:sql_joins" not in topics
    first_dbms = difficulty.update(
        topics.get("concept:sql_joins"), "concept:sql_joins", quality=0.5
    )
    assert first_dbms.level == 0


def test_a_strong_topic_allows_one_rung_more_and_harder_angles():
    assert difficulty.allowed_depth(3, 1) == 4
    assert difficulty.allowed_depth(3, -1) == 2
    assert difficulty.allowed_depth(1, -2) == 1
    assert difficulty.angle_for(1, []) == "edge_case"
    assert difficulty.angle_for(-1, []) == "mechanism"
    assert difficulty.angle_for(1, ["edge_case"]) == "failure"
    assert difficulty.angle_for(0, [], resume=True) == "implementation"


def test_a_topic_going_well_takes_a_strong_answer_further():
    ctx = Context(topic_level=1)
    at_cap = thread(3, moves=["rung"] * 3)
    held = go(
        at_cap, said("correct"), config=LadderConfig(max_depth=3, max_generic_rungs=5), ctx=ctx
    )
    assert held.move.kind == "rung" and held.move.depth == 4
    plain = go(at_cap, said("correct"), config=LadderConfig(max_depth=3, max_generic_rungs=5))
    assert plain.move.kind == "move_on" and plain.left == "ceiling"


def test_the_selection_offset_is_half_a_logit_per_level():
    assert difficulty.selection_offset(2) == 1.0
    assert difficulty.selection_offset(-1) == -0.5


def test_misconceptions_seen_twice_are_marked_repeated():
    topic = difficulty.update(None, "c", quality=0.0, misconception="threads share the stack")
    topic = difficulty.update(topic, "c", quality=0.0, misconception="thinks threads share stack")
    assert topic.repeated == ["thinks threads share stack"]


# ── one judgement, read two ways ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("category", "severity", "band", "justification"),
    [
        ("correct", "none", "at", "held"),
        ("correct_incomplete", "none", "at", "held"),
        ("partial", "minor", "at", "partial"),
        ("partial", "material", "below", "partial"),
        ("incorrect", "minor", "below", "partial"),
        ("incorrect", "fundamental", "below", "failed"),
        ("dont_know", "none", "below", "failed"),
        ("vague", "none", "below", "partial"),
    ],
)
def test_band_and_justification_follow_the_category(category, severity, band, justification):
    assert legacy_fields(category, severity, False) == (band, justification)


def test_requests_are_never_a_quality():
    for category in ("ambiguous", "off_question", "non_answer"):
        assert quality_of(said(category)) is None


# ── found live, 2026-10-23: the model down ───────────────────────────────


def test_an_answer_nobody_read_is_never_said_to_have_held():
    """The rule strategist has not read the answer (§10). It may ask once
    more and then move on — without assent, and without saying the answer
    held, which the notes call "Answered well". A live run with a bad key
    noted "Answered well" under a wrong answer and two "I'm not sure"s."""
    unread = StrategistVerdict(band="at", confidence=0.0, justification="partial", source="rule")
    first = go(thread(0), unread)
    assert first.move.kind == "rung" and first.move.tone == "neutral"
    later = go(thread(1), unread)
    assert later.move.kind == "move_on" and later.left == "unjudged"
    capped = go(thread(5), unread, config=LadderConfig(max_depth=3))
    assert capped.left == "unjudged" and capped.ceiling is None
    out_of_rungs = go(thread(1), unread, config=LadderConfig(max_generic_rungs=0))
    assert out_of_rungs.left == "unjudged"


def test_a_correction_is_counted_once_on_the_answer_that_turned_it_round():
    """Live: wrong, a pushback, right — "prompted" — and then one more right
    answer relabelled it "corrected yourself"."""
    turned = go(thread(1, moves=["challenge"], categories=["incorrect"]), said("correct"))
    assert turned.corrected == "prompted"
    later = go(
        thread(2, moves=["challenge", "rung"], categories=["incorrect", "correct"]), said("correct")
    )
    assert later.corrected is None


def test_a_request_in_between_does_not_hide_that_the_correction_was_helped():
    out = go(
        thread(1, moves=["challenge", "rephrase"], categories=["incorrect", "non_answer"]),
        said("correct"),
    )
    assert out.corrected == "prompted"


def test_a_contradiction_settled_after_it_was_pointed_out_was_helped():
    """Live: a resume line's story, reconciled after "how do those fit
    together?", read "corrected yourself"."""
    out = go(thread(1, moves=["confront"], categories=["contradiction"]), said("correct"))
    assert out.corrected == "prompted"
