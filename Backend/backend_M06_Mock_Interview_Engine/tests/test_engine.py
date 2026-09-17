"""Whole sessions through the engine — drills, mocks, recovery, degradation."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import AnswerRejected, Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.models import Checkpoint, LLMCall

from .stubs import BankQuestions, DownQuestions, StubLLM, drill_body, verdict


def make(db, llm=None, **upstreams) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(**upstreams),
        llm=llm or NullLLM(),
        thetas=ThetaCache(),
    )


def drill(engine: Engine, candidate=None):
    body = drill_body(candidate or uuid.uuid4())
    row, _ = engine.create_drill(
        candidate_id=uuid.UUID(body["candidate_id"]),
        claim_id=body["claim_id"],
        claim_text=body["claim_text"],
        probes=body["probes"],
        source_module="M01",
    )
    return row


def mock(engine: Engine, minutes=10, candidate=None):
    row, _ = store.create_session(
        engine.db, candidate_id=candidate or uuid.uuid4(), kind="mock", mode="mock", minutes=minutes
    )
    return row


def say(engine: Engine, row, text: str):
    state = engine.state(row.id)
    assert state.open_turn_id is not None, "nothing is open"
    return engine.answer(row.id, state.open_turn_id, text)


def interviewer_lines(state):
    return [t.text for t in state.transcript if t.role == "interviewer"]


# ── drills (FR-6.23) ─────────────────────────────────────────────────────


def test_a_drill_opens_with_its_first_probe_and_waits(db):
    engine = make(db)
    row = drill(engine)
    state = engine.state(row.id)
    assert state.status is SessionStatus.planned
    assert state.drill["claim_id"] == "c-7"
    assert state.plan is not None and state.plan.segments[0].source == "m01_claims"

    state = engine.start(row.id)
    assert state.status is SessionStatus.live
    first = interviewer_lines(state)[0]
    assert first.endswith("Walk me through the classifier.")
    assert "Two minutes" in first
    assert state.open_turn_id is not None


def test_a_drill_that_breaks_exits_gracefully_and_ends(db):
    engine = make(db)
    row = drill(engine)
    engine.start(row.id)
    state = say(engine, row, "I don't know, honestly")
    assert state.status is SessionStatus.ended
    assert state.end_reason == "drill_complete"
    closing = interviewer_lines(state)[-1]
    assert closing.startswith("Okay, let's leave that there.")
    assert state.break_depths == {"claim:c-7": 0}


def test_a_drill_climbs_its_own_probes_with_a_model(db):
    llm = StubLLM(
        [verdict(), verdict(), verdict(band="below", justification="failed")],
        probe="So how exactly was the split done?",
    )
    engine = make(db, llm=llm)
    row = drill(engine)
    engine.start(row.id)
    state = say(engine, row, "A ResNet-50 on PlantVillage images.")
    # The adapted line contained "exactly" → the guard swapped in the template.
    assert interviewer_lines(state)[-1] == "How did you split the data?"
    state = say(engine, row, "80/20 random split, test set held out.")
    assert interviewer_lines(state)[-1] == "What baseline does 94% beat?"
    state = say(engine, row, "Not sure there was one.")
    assert state.status is SessionStatus.ended
    assert state.break_depths == {"claim:c-7": 2}


def test_a_drill_is_never_scored_and_never_moves_theta(db):
    llm = StubLLM([verdict()] * 5)
    engine = make(db, llm=llm)
    row = drill(engine)
    engine.start(row.id)
    say(engine, row, "A ResNet-50.")
    assert engine.upstreams.m05.observed == []
    for turn in engine.state(row.id).transcript:
        assert turn.rubric_round_type is None


# ── mocks ────────────────────────────────────────────────────────────────


def test_a_mock_opens_with_a_greeting_and_a_verbatim_stem(db):
    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    state = engine.start(row.id)
    first = interviewer_lines(state)[0]
    assert first.startswith("Hello. Let's begin. First question.")
    assert "single loop over an array" in first
    assert state.transcript[0].question_source == "m05_bank"
    assert state.transcript[0].rubric_round_type == "dsa_verbal"


def test_a_mock_runs_to_its_budget_and_closes(db):
    engine = make(db, m05=BankQuestions())
    row = mock(engine, minutes=8)  # (8*60 - 60) // 210 = 2 questions
    engine.start(row.id)
    for _ in range(10):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live:
            break
        say(engine, row, "I don't know")
    state = engine.state(row.id)
    assert state.status is SessionStatus.ended
    assert state.end_reason == "plan_complete"
    assert state.questions_asked == 2
    assert interviewer_lines(state)[-1].endswith("That's time. Your report is being prepared.")


def test_rule_verdicts_never_reach_m05(db):
    bank = BankQuestions()
    engine = make(db, m05=bank)
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "A hash map, because lookups are cheap.")
    assert bank.observed == []


@pytest.mark.gate
def test_model_verdicts_reach_m05_and_theta_stays_in_memory(db):
    """FR-6.25 end to end: observed, cached in memory, absent from the checkpoint."""
    bank = BankQuestions()
    engine = make(db, llm=StubLLM([verdict(band="above")] * 5), m05=bank)
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "Linear, because the body runs n times at constant cost.")
    assert len(bank.observed) == 1
    _sid, concept, outcome = bank.observed[0]
    assert concept == "concept:time_complexity"
    assert outcome["band"] == "above"
    assert engine.thetas.get(row.id) == {"concept:time_complexity": 0.4}
    raw = json.dumps(db.get(Checkpoint, row.id).state_json)
    assert "theta" not in raw.lower()


def test_theta_is_forgotten_when_the_session_ends(db):
    engine = make(db, llm=StubLLM([verdict()] * 5), m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    engine.end(row.id, "ended_by_student")
    assert engine.thetas.get(row.id) == {}


def test_selection_carries_theta_and_what_was_already_asked(db):
    bank = BankQuestions()
    candidate = uuid.uuid4()
    engine = make(db, m05=bank)
    first = mock(engine, candidate=candidate, minutes=8)
    engine.start(first.id)
    engine.end(first.id, "ended_by_student")
    second = mock(engine, candidate=candidate)
    engine.start(second.id)
    request = bank.selected[-1]
    assert request["session_id"] == str(second.id)
    assert request["is_first_of_round"] is True
    asked_before = engine.state(first.id).transcript[0].question_id
    assert str(asked_before) in request["seen_item_ids"]
    assert "theta_provisional" in request


def test_model_calls_are_recorded_for_the_trace(db):
    engine = make(db, llm=StubLLM([verdict()] * 5), m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    calls = db.exec(select(LLMCall).where(LLMCall.session_id == row.id)).all()
    jobs = sorted(c.job for c in calls)
    assert jobs == ["interviewer_phrasing", "probe_strategist"]
    strategist = next(c for c in calls if c.job == "probe_strategist")
    assert strategist.prompt_version == "strategist-2"
    assert strategist.reasoning_tokens == 20
    assert strategist.cached_tokens is None


def test_decisions_are_on_the_trace_but_not_in_the_state(db):
    engine = make(
        db, llm=StubLLM([verdict(band="below", justification="partial")] * 3), m05=BankQuestions()
    )
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    decided = [e for e in store.events_for(db, row.id) if e.kind == "probe.decided"]
    assert decided[0].payload["verdict"]["band"] == "below"
    state_json = json.dumps(engine.state(row.id).model_dump(mode="json"))
    assert '"band"' not in state_json


# ── degraded ─────────────────────────────────────────────────────────────


def test_m05_down_falls_back_to_the_local_playlist_and_says_so(db):
    engine = make(db, m05=DownQuestions())
    row = mock(engine)
    state = engine.start(row.id)
    assert state.transcript[0].question_source == "local_fallback"
    assert state.transcript[0].rubric_round_type is None
    assert "M05" in state.flags.degraded


def test_m05_down_never_repeats_a_fallback_question_in_one_session(db):
    engine = make(db, m05=DownQuestions())
    row = mock(engine, minutes=20)
    engine.start(row.id)
    for _ in range(12):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live:
            break
        say(engine, row, "I don't know")
    asked = [
        t.question_id
        for t in engine.state(row.id).transcript
        if t.role == "interviewer" and t.probe_move is None and t.question_id
    ]
    assert len(asked) == len(set(asked))
    assert engine.state(row.id).end_reason in ("plan_complete", "fallback_exhausted")


def test_no_consent_is_recorded_and_said(db):
    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    state = engine.start(row.id)
    assert state.flags.consent_id is None
    assert [e.kind for e in store.events_for(db, row.id)][:3] == [
        "session.created",
        "consent.resolved",
        "session.started",
    ]


# ── answering, and carrying on after a crash (AC-6.16) ───────────────────


def test_an_answer_to_a_question_that_is_not_open_is_refused(db):
    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    first = engine.state(row.id).open_turn_id
    engine.answer(row.id, first, "I don't know")
    with pytest.raises(AnswerRejected):
        engine.answer(row.id, uuid.uuid4(), "stray")


@pytest.mark.gate
def test_a_retried_answer_does_nothing_twice(db):
    engine = make(db, llm=StubLLM([verdict()] * 5), m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    first = engine.state(row.id).open_turn_id
    engine.answer(row.id, first, "Linear.")
    before = len(store.events_for(db, row.id))
    engine.answer(row.id, first, "Linear.")
    engine.start(row.id)
    assert len(store.events_for(db, row.id)) == before
    assert len(engine.llm.structured_calls) == 1


def test_a_step_that_crashed_after_the_answer_is_finished_by_the_next_request(db, monkeypatch):
    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    first = engine.state(row.id).open_turn_id

    def crash(*_a, **_k):
        raise RuntimeError("worker died")

    monkeypatch.setattr(engine, "continue_session", crash)
    with pytest.raises(RuntimeError):
        engine.answer(row.id, first, "I don't know")
    monkeypatch.undo()
    state = engine.state(row.id)
    assert state.open_turn_id is None and state.transcript[-1].role == "candidate"

    state = engine.start(row.id)
    assert state.open_turn_id is not None
    assert state.questions_asked == 2
    engine.start(row.id)
    assert engine.state(row.id).questions_asked == 2


def test_a_decision_already_on_the_log_is_followed_not_remade(db, monkeypatch):
    llm = StubLLM([verdict(band="below", justification="failed")])
    engine = make(db, llm=llm, m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    first = engine.state(row.id).open_turn_id

    real_say = engine._say
    monkeypatch.setattr(
        engine, "_say", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("died"))
    )
    with pytest.raises(RuntimeError):
        engine.answer(row.id, first, "Linear.")
    monkeypatch.setattr(engine, "_say", real_say)
    assert len(llm.structured_calls) == 1

    llm.verdicts = [verdict()]  # a second opinion would differ — it must not be asked
    state = engine.start(row.id)
    assert len(llm.structured_calls) == 1
    assert interviewer_lines(state)[-1].startswith("Okay, let's leave that there.")


def test_a_paused_session_takes_no_answers(db):
    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    open_turn = engine.state(row.id).open_turn_id
    store.record(db, row, "session.paused", step="pause")
    with pytest.raises(AnswerRejected, match="paused"):
        engine.answer(row.id, open_turn, "x")


def test_repeating_a_question_does_not_repeat_the_hand_off(db):
    """The first live run said: "That's a different question. Here's mine
    again. Okay, let's leave that there. Next question. Two keys hash to the
    same bucket." A repeat repeats the question, not the turn it arrived in."""
    engine = make(db, llm=StubLLM([verdict(off_question=True)]), m05=BankQuestions())
    row = mock(engine)
    state = engine.start(row.id)
    asked = interviewer_lines(state)[-1]
    stem = state.current_item["stem"]
    assert asked.startswith("Hello. Let's begin. First question.")  # the lead is in the turn

    state = say(engine, row, "Something about a different question entirely.")
    repeat = interviewer_lines(state)[-1]
    assert state.transcript[-1].probe_move == "redirect_once"
    assert repeat == f"That's a different question. Here's mine again. {stem}"
    assert "First question." not in repeat
    assert "Hello" not in repeat
    # And the turn keeps the two apart, so a second repeat is the same repeat.
    assert state.transcript[-1].question_text == stem


def test_ending_early_still_gets_a_closing_line(db):
    """The first live run ended on a repeated question: the student pressed End
    and the interviewer said nothing. EC-6.10 — leaving early is allowed, and
    being left mid-sentence is not what it should feel like."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock(engine)
    engine.start(row.id)
    say(engine, row, "Buckets, and a load factor.")

    state = engine.end(row.id, "ended_by_student")
    assert state.status is SessionStatus.ended
    assert interviewer_lines(state)[-1] == "That's time. Your report is being prepared."
    assert state.transcript[-1].turn_index == state.next_turn_index - 1

    # A session nobody started has nothing to close, and says so in the report.
    never = mock(engine)
    aborted = engine.end(never.id, "ended_by_student")
    assert aborted.status is SessionStatus.aborted
    assert aborted.transcript == []


def test_a_drill_gets_the_drills_own_closing_line(db):
    engine = make(db, llm=StubLLM([verdict()] * 4))
    row = drill(engine)
    engine.start(row.id)
    state = engine.end(row.id, "ended_by_student")
    assert interviewer_lines(state)[-1] == "That's the drill."
