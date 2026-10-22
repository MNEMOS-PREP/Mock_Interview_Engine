"""Answer types through the whole engine (2026-10-22): what the interviewer
says, what is recorded, what M13 is sent, what M05 is asked, what is
remembered — with strategist-5 verdicts, a stub model, and nothing on the
network. The decision table itself is `test_controller.py`."""

from __future__ import annotations

import uuid

from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.models import (
    EvaluationOutbox,
    QuestionAttempt,
    SavedQuestion,
)

from .stubs import BankQuestions, NoClaims, StubLLM, answer, verdict


def said(category: str, **kw) -> dict:
    """A strategist-5 verdict as the model sends it."""
    return verdict(category=category, **kw)


WRONG = said(
    "incorrect",
    severity="material",
    error_quote="it is O(n squared)",
    error_note="One pass of constant work is linear.",
    misconception="counts nested work in a single loop",
)
RIGHT = said("correct", correct_points=["one pass, constant work"])


def live(db, *verdicts, mode="mock", minutes=30, probe=None):
    llm = StubLLM(list(verdicts) or [RIGHT], probe=probe or "Why is that, for a loop like this?")
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=llm,
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=minutes
    )
    engine.start(row.id)
    return engine, row


def reply(engine, row, text, **kw):
    return engine.answer(row.id, engine.state(row.id).open_turn_id, text, **kw)


def last_line(state):
    return next(t for t in reversed(state.transcript) if t.role == "interviewer")


def decided(engine, row) -> list[dict]:
    return [e.payload for e in store.events_for(engine.db, row.id) if e.kind == "probe.decided"]


# ── a wrong answer is not accepted ───────────────────────────────────────


def test_a_wrong_answer_is_pushed_back_on_in_the_students_own_words(db):
    """The user's report: the interviewer carried on as if a wrong answer was
    fine. It now challenges it — and when the model's line praises, the
    authored line says it, quoting what they said."""
    engine, row = live(db, WRONG, probe="Excellent! Can you say more?")
    state = reply(engine, row, "It is O(n squared) because of the loop.")
    line = last_line(state)
    assert line.probe_move == "challenge"
    assert "it is O(n squared)" in line.text
    assert "Excellent" not in line.text
    assert state.open_turn_id is not None, "they get the chance to reconsider"


def test_a_correction_after_the_challenge_is_recorded_as_one(db):
    engine, row = live(db, WRONG, RIGHT)
    reply(engine, row, "It is O(n squared).")
    reply(engine, row, "Sorry — one pass of constant work, so it is linear.")
    second = decided(engine, row)[-1]
    assert second["corrected"] == "prompted"
    assert second["quality"] == 0.6


def test_m13_is_sent_both_answers_and_the_help_the_correction_needed(db):
    """One question, one evaluation: the wrong answer and its correction, in
    order, never the interviewer's words — and the challenge counted."""
    engine, row = live(db, WRONG, RIGHT)
    reply(engine, row, "It is O(n squared).")
    reply(engine, row, "One pass of constant work, so it is linear.")
    engine.end(row.id, "ended_by_student")
    (scored,) = engine.db.exec(
        select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)
    ).all()
    text = scored.payload["answer_text"]
    assert text == "It is O(n squared).\n\nOne pass of constant work, so it is linear."
    assert "not sure" not in text.lower() and "Why" not in text
    assert scored.payload["prompts_used"] == 1


def test_a_wrong_answer_that_stands_is_left_honestly_and_remembered_as_hard(db):
    engine, row = live(db, WRONG, WRONG)
    reply(engine, row, "It is O(n squared).")
    state = reply(engine, row, "Still O(n squared).")
    exit_line = next(
        t.text
        for t in reversed(state.transcript)
        if t.role == "interviewer" and t.probe_move is None
    )
    assert "people usually look up" not in exit_line, "no false comfort after a misunderstanding"
    attempt = engine.db.exec(select(QuestionAttempt)).first()
    assert attempt.outcome == "gap:misunderstanding"
    assert attempt.misconception == "counts nested work in a single loop"
    flagged = engine.db.exec(select(SavedQuestion)).first()
    assert flagged is not None and flagged.flagged_at is not None and flagged.starred_at is None


# ── a right answer goes further, in its own topic only ───────────────────


def test_two_right_answers_raise_the_topic_and_m05_is_told_for_that_topic_only(db):
    engine, row = live(db, RIGHT, RIGHT, RIGHT)
    for _ in range(2):
        reply(engine, row, "One pass, constant work: linear in n.")
    state = engine.state(row.id)
    concept = state.ladder.concept_id
    assert state.topics[concept].level == 1
    assert "deeper" in state.topics[concept].last_decision
    # The next question is chosen with what the topic now says — asked here
    # the way the room asks ahead (`/upcoming`), which is the same request.
    engine.upcoming(row.id)
    request = engine.upstreams.m05.requests[-1]
    assert request["difficulty_offset"].get(concept) == 0.5
    assert set(request["difficulty_offset"]) == {concept}, "no other topic is pitched higher"
    assert request["difficulty_shift"] == 0.0


def test_the_follow_up_after_a_right_answer_is_a_harder_angle(db):
    engine, row = live(db, RIGHT, RIGHT)
    reply(engine, row, "Linear.")
    first = decided(engine, row)[-1]
    assert first["move"]["kind"] == "rung" and first["move"]["angle"]
    assert first["move"]["tone"] == "credit"


def test_practice_and_final_boss_shift_where_m05_pitches_every_question(db):
    for mode, shift in (("practice", -0.3), ("final_boss", 0.8)):
        engine, row = live(db, RIGHT, mode=mode)
        reply(engine, row, "Linear.")
        engine.end(row.id, "ended_by_student")
        assert engine.upstreams.m05.requests[-1]["difficulty_shift"] == shift


# ── the rest of the list ─────────────────────────────────────────────────


def test_a_dont_know_gets_a_simpler_question_before_the_interviewer_moves_on(db):
    engine, row = live(db)
    state = reply(engine, row, "I don't know.")
    assert last_line(state).probe_move == "simplify"
    state = reply(engine, row, "No idea, sorry.")
    assert last_line(state).probe_move is None, "then the next question"


def test_a_cut_off_answer_is_asked_to_finish_not_judged(db):
    engine, row = live(db, said("correct_incomplete"))
    state = reply(engine, row, "So the loop runs n times and", completion_reason="interrupted")
    assert last_line(state).probe_move == "resume_cut"
    assert decided(engine, row)[-1]["quality"] is None


def test_the_same_answer_twice_is_redirected_to_the_follow_up(db):
    engine, row = live(db, RIGHT, RIGHT)
    answer_text = "One pass over the array with constant work each time, so it is linear in n."
    reply(engine, row, answer_text)
    state = reply(engine, row, answer_text)
    assert last_line(state).probe_move == "redirect_repeat"


def test_an_unsupported_claim_is_asked_how_it_was_measured(db):
    engine, row = live(
        db,
        said("unsupported", unsupported_quote="made it 40% faster"),
        probe="How did you measure that?",
    )
    state = reply(engine, row, "I made it 40% faster in my project.")
    assert last_line(state).probe_move == "ask_evidence"


def test_the_trace_says_why_each_move_was_made(db):
    engine, row = live(db, WRONG)
    reply(engine, row, "It is O(n squared).")
    payload = decided(engine, row)[-1]
    assert payload["category"] == "incorrect"
    assert "pointed at once" in payload["reason"]
    assert payload["error_note"] == "One pass of constant work is linear."


def test_the_interviewer_never_sees_the_category_or_the_note(db):
    """FR-6.15, kept: the interviewer's model is told WHAT to do (the move and
    the student's words), never the verdict or the answer key."""
    engine, row = live(db, WRONG)
    reply(engine, row, "It is O(n squared).")
    system = engine.llm.stream_calls[-1]["system"]
    user = engine.llm.stream_calls[-1]["user"]
    for leaked in ("incorrect", "One pass of constant work is linear", "kp1", "band", "quality"):
        assert leaked not in system and leaked not in user, leaked


def test_a_session_ends_cleanly_after_all_of_it(db):
    engine, row = live(db, WRONG, RIGHT, RIGHT)
    for text in ("O(n squared).", "Linear, one pass.", "Linear."):
        if engine.state(row.id).open_turn_id is None:
            break
        reply(engine, row, text)
    state = engine.end(row.id, "ended_by_student")
    assert state.status is SessionStatus.ended


# ── found by the live run, 2026-10-22 ─────────────────────────────────────


def test_a_redirect_after_a_clarify_repeats_the_question_not_the_clarify(db):
    """Live: "That's a different question. Here's mine again. Can you
    rephrase that?" — the clarify had left itself as the open question."""
    engine, row = live(db, said("ambiguous"), said("off_question"))
    asked = last_line(engine.state(row.id)).question_text
    state = reply(engine, row, "It uses the standard technique.")
    assert last_line(state).probe_move == "clarify"
    state = reply(engine, row, "It uses the standard technique.")
    line = last_line(state)
    assert line.probe_move == "redirect_once"
    assert line.text.endswith(asked)
    assert line.question_text == asked


def test_a_focus_asks_only_its_concept_and_then_ends_the_round(db):
    """Live: "Focus: Hashing" heard "tell me about a time…". M05 is now told
    to keep to the focus (`only_concepts`) rather than steered toward it, and
    the round ends when the bank has no more — M06's playlist holds one
    hashing question among four."""
    m05 = BankQuestions()
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=m05, m01=NoClaims()),
        llm=StubLLM([RIGHT]),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        db,
        candidate_id=uuid.uuid4(),
        kind="mock",
        mode="mock",
        minutes=30,
        focus_concepts=["concept:hashing"],
        focus_label="Hashing",
    )
    engine.start(row.id)
    for _ in range(8):
        state = engine.state(row.id)
        if state.open_turn_id is None or engine.segment(state).kind == "closing":
            break
        answer(engine, row, "I do not know.")
    state = engine.state(row.id)
    part = next(s for s in state.plan.segments if s.title == "Focus: Hashing")
    asked = {
        t.concept_id
        for t in state.transcript
        if t.role == "interviewer" and t.segment_index == part.index and t.question_id
    }
    assert asked == {"concept:hashing"}
    sent = [r for r in m05.requests if r.get("only_concepts")]
    assert sent and all(r["only_concepts"] == ["concept:hashing"] for r in sent)
    assert engine.segment(state).kind == "closing"


def test_with_the_model_down_no_answer_is_called_good_or_bad(db):
    """Live, with a bad key: every question's notes read "Answered well",
    the wrong answer and the "I'm not sure" ones too. Nobody read them."""
    from backend_M06_Mock_Interview_Engine import report
    from backend_M06_Mock_Interview_Engine.llm import NullLLM

    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=NullLLM(),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=30
    )
    engine.start(row.id)
    for text in ["It is always O(n squared).", "Because of the loop.", "Linear.", "One pass."]:
        if engine.state(row.id).open_turn_id is None:
            break
        reply(engine, row, text)
    engine.end(row.id, "ended_by_student")
    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    assert built.questions
    assert all(q.outcome in (None, "unjudged", "ended") for q in built.questions)
    assert not any((q.outcome_words or "").startswith("Answered well") for q in built.questions)
    assert built.summary.held == []
    assert not any(
        line.text.startswith(("Right", "Good", "Exactly"))
        for line in engine.state(row.id).transcript
        if line.role == "interviewer" and line.probe_move == "rung"
    )


def test_a_give_up_in_other_words_is_read_without_the_model():
    """Live: "I'm not sure, I don't know this one." went unread, and so did
    "I don't remember". A longer answer with doubt in it is the model's, and
    "not sure what you're asking" is a request, not a give-up."""
    from backend_M06_Mock_Interview_Engine.agents.strategist import rule_verdict

    for said in (
        "I'm not sure, I don't know this one.",
        "Honestly, I don't remember how we measured that.",
        "I am not familiar with it.",
        "I don't know.",
    ):
        assert rule_verdict(said).category == "dont_know", said
    doubtful = "I don't know the exact figure, but the latency fell because we cached the summary."
    assert rule_verdict(doubtful).category is None
    assert rule_verdict("Not sure what you're asking.").asks_to_rephrase
