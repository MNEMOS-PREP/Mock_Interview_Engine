"""Whole sessions through the engine — drills, mocks, recovery, degradation."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, items, planner, report, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import (
    AnswerRejected,
    Engine,
    ThetaCache,
    bridge_line,
    question_budget,
)
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.models import (
    Checkpoint,
    EvaluationOutbox,
    LedgerOutbox,
    LLMCall,
)
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import (
    BankQuestions,
    DownPlanner,
    DownQuestions,
    NoClaims,
    StubLLM,
    answer,
    drill_body,
    verdict,
)


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


def mock(engine: Engine, minutes=10, candidate=None, include_resume=True):
    """A mock whose student opted in to resume questions — the fixture
    resume has one shaky claim, so it has a project round."""
    row, _ = store.create_session(
        engine.db,
        candidate_id=candidate or uuid.uuid4(),
        kind="mock",
        mode="mock",
        minutes=minutes,
        include_resume=include_resume,
    )
    return row


def say(engine: Engine, row, text: str):
    state = engine.state(row.id)
    assert state.open_turn_id is not None, "nothing is open"
    return answer(engine, row, text)


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
    # A drill is Practice, and Practice's interviewer is Meera (friendly):
    # the persona the drill plan has named since day 2, now actually heard.
    assert closing.startswith("That's fair — it's a detail people usually look up.")
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


def test_a_mock_opens_with_the_panel_and_a_verbatim_stem(db):
    """FR-6.3: a panel says who is in the room before anyone asks. The lead
    greets and names the others, each says hello in their own voice, and the
    lead asks the first question — M05's, word for word."""
    from backend_M06_Mock_Interview_Engine.personas import persona

    engine = make(db, m05=BankQuestions())
    row = mock(engine)
    state = engine.start(row.id)
    opening = state.transcript[0]
    lead = persona(state.plan.segments[0].persona_id)
    others = [
        persona(pid)
        for pid in dict.fromkeys(s.persona_id for s in state.plan.segments)
        if pid != lead.id
    ]
    assert others, "a ten-minute mock seats a panel"
    voices = [part.speaker_id for part in opening.parts]
    assert voices[0] == voices[-1] == opening.speaker_id == lead.id
    assert set(voices[1:-1]) == {p.id for p in others}
    assert opening.parts[0].text.startswith(f"Hello, I'm {lead.name}. I'm joined by")
    assert all(p.name in opening.parts[0].text for p in others)
    assert opening.parts[-1].text.startswith("First question.")
    assert "single loop over an array" in opening.parts[-1].text
    assert opening.text == " ".join(part.text for part in opening.parts)
    assert opening.question_source == "m05_bank"
    assert opening.rubric_round_type == "dsa_verbal"


def test_a_mock_runs_to_its_budget_and_closes(db):
    engine = make(db, m05=BankQuestions())
    # No JD, so the plan is the warm-up, one round of what M05 can fill, and
    # a project segment because the fixture resume has a shaky line on it.
    row = mock(engine, minutes=8)
    engine.start(row.id)
    for _ in range(10):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live:
            break
        say(engine, row, "I don't know")
    state = engine.state(row.id)
    assert state.status is SessionStatus.ended
    assert state.end_reason == "plan_complete"
    assert state.questions_asked == 3 == question_budget(state)
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
    # Asked in an EARLIER interview: freshness, which M05 may relax and
    # announce — not the hard "never", which is this interview's own
    # questions (M05 §6.6; `test_no_repeats.py`).
    assert str(asked_before) in request["recent_item_ids"]
    assert str(asked_before) not in request["seen_item_ids"]
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
    assert strategist.prompt_version == "strategist-6"
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
    assert [e.kind for e in store.events_for(db, row.id)][:4] == [
        "session.created",
        "consent.resolved",
        "plan.set",
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

    def said(state) -> int:
        return sum(1 for t in state.transcript if t.role == "interviewer")

    # The step owed for that answer happens once, whatever it is — since
    # 2026-10-22 an "I don't know" at a question's opening is answered with a
    # simpler question rather than the next one.
    state = engine.start(row.id)
    assert state.open_turn_id is not None
    assert said(state) == 2
    engine.start(row.id)
    assert said(engine.state(row.id)) == 2


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
    lead = persona(state.plan.panel[0])
    assert asked.startswith(f"Hello, I'm {lead.name}.")  # the lead, with the panel

    state = say(engine, row, "Something about a different question entirely.")
    repeat = interviewer_lines(state)[-1]
    assert state.transcript[-1].probe_move == "redirect_once"
    assert repeat == f"{lead.said().redirect} {stem}"
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
    assert interviewer_lines(state)[-1] == "That's the drill. Your notes are ready."


# ── the plan, built at bootstrap (FR-6.1) ────────────────────────────────


def with_jd(engine: Engine, minutes=45):
    row, _ = store.create_session(
        engine.db,
        candidate_id=uuid.uuid4(),
        kind="mock",
        mode="mock",
        minutes=minutes,
        jd_id=uuid.uuid4(),
    )
    return row


@pytest.mark.gate
def test_starting_a_session_builds_a_plan_from_m02s(db):
    """FR-6.1. The plan exists before the greeting: a session that started
    without one would be asking questions off a plan the student never saw."""
    engine = make(db, llm=StubLLM([verdict()] * 6), m05=BankQuestions(), m01=NoClaims())
    row = with_jd(engine)
    state = engine.start(row.id)

    assert state.plan is not None
    assert [s.kind for s in state.plan.segments] == ["warmup", "technical", "closing"]
    # M02 was asked to price what is LEFT after the reserve, not the whole
    # budget: 45 − 4 warm-up − 5 closing.
    assert engine.upstreams.m02.plan_calls[0][2] == 36
    # And its arithmetic came back untouched.
    technical = state.plan.segments[1]
    assert (technical.minutes, technical.question_budget) == (14.0, 4)
    assert technical.requirement_ids == ["r1", "r2"]
    assert technical.concept_ids == ["concept:hashing", "concept:recursion"]


def test_the_plan_decides_how_many_questions_the_session_asks(db):
    """Two numbers for the same thing is how a session runs over (Trap 8)."""
    engine = make(db, llm=StubLLM([verdict()] * 6), m05=BankQuestions(), m01=NoClaims())
    state = engine.start(with_jd(engine).id)
    # 1 warm-up + M02's 4. Not the 45-minute arithmetic, which would say 12.
    assert question_budget(state) == 5


def test_the_segment_being_run_steers_what_m05_is_asked_for(db):
    """A plan that does not reach the selection request is a plan that only
    exists on the preview screen."""
    engine = make(db, llm=StubLLM([verdict()] * 6), m05=BankQuestions(), m01=NoClaims())
    row = with_jd(engine)
    engine.start(row.id)

    # The warm-up asks for nothing in particular — that is what it is for.
    warmup = engine.upstreams.m05.requests[-1]
    assert warmup["required_requirement_ids"] == []

    # One question is the warm-up's whole budget, so once its ladder exits
    # the next question is M02's.
    engine.llm.verdicts = [verdict(justification="failed", band="below")]
    state = say(engine, row, "I do not know.")
    assert state.current_segment == 1
    asked = engine.upstreams.m05.requests[-1]
    assert asked["round_type"] == "dsa_verbal"
    assert asked["required_requirement_ids"] == ["r1", "r2"]
    assert set(asked["coverage_debt"]) == {"concept:hashing", "concept:recursion"}


def test_a_session_walks_its_plan_and_stops_at_the_closing(db):
    """The budget is the plan's, and the closing asks nothing — it is where
    the student asks and the report is put together."""
    # Every answer ends its ladder, so each one costs exactly one question of
    # the plan's budget — the arithmetic under test is the plan's, not the
    # ladder's (which test_ladder.py owns).
    engine = make(
        db,
        llm=StubLLM([verdict(justification="failed", band="below")]),
        m05=BankQuestions(),
        m01=NoClaims(),
    )
    row = with_jd(engine)
    state = engine.start(row.id)
    seen = [state.current_segment]
    for _ in range(8):
        if state.status is not SessionStatus.live or state.open_turn_id is None:
            break
        state = say(engine, row, "I do not know.")
        seen.append(state.current_segment)

    # Warm-up (index 0, one question), then M02's round (index 1).
    assert seen[0] == 0
    assert 1 in seen
    # The plan bounds the session: never more questions than it priced, and
    # it stops for a reason it can name rather than running until something
    # breaks. Here the fixture bank runs dry first, which is EC-6.16's
    # honest ending and not a failure.
    assert state.questions_asked <= question_budget(state) == 5
    assert state.status is SessionStatus.ended
    assert state.end_reason in ("plan_complete", "bank_exhausted")
    # The closing is never the segment that asks: it is where the student asks.
    assert state.plan.segments[-1].question_budget == 0


def test_m02_being_down_leaves_a_plan_and_a_sentence(db):
    """Rule 2 — the session narrows to what M05 can fill, and says so."""
    engine = make(
        db, llm=StubLLM([verdict()] * 6), m05=BankQuestions(), m02=DownPlanner(), m01=NoClaims()
    )
    state = engine.start(with_jd(engine).id)
    assert state.plan is not None
    assert [s.kind for s in state.plan.segments] == ["warmup", "technical", "closing"]
    assert "M02" in state.flags.degraded
    assert state.plan.coverage_plan is None
    assert "Not tailored to a job description" in state.plan.segments[1].rationale


def test_a_dropped_segment_is_owed_to_m02_as_skipped(db):
    """FR-6.24. Planned, then dropped, so no turn will ever reach it — M02's
    ledger has to hear that from the module that dropped it."""
    engine = make(db, llm=StubLLM([verdict()] * 6), m05=BankQuestions(), m01=NoClaims())
    coding = {
        "rounds": [
            {
                "round_type": "coding",
                "minutes": 24.0,
                "question_count": 2,
                "requirement_ids": ["r1"],
            }
        ],
        "allocations": [],
        "uncovered": [],
        "plan_version": "greedy-log-v1",
    }
    engine.upstreams.m02._plan = coding
    row = with_jd(engine)
    state = engine.start(row.id)

    dropped = [s for s in state.plan.segments if s.dropped_reason is not None]
    assert len(dropped) == 1 and "coding round" in dropped[0].dropped_reason
    owed = db.exec(select(LedgerOutbox).where(LedgerOutbox.session_id == row.id)).all()
    assert [(r.requirement_id, r.ledger_state) for r in owed] == [("r1", "skipped")]


# ── between rounds (FR-6.3, §3.2.3) ──────────────────────────────────────


@pytest.mark.gate
def test_crossing_into_a_new_round_says_so(db):
    """§3.2.3: "the transition between rounds is where immersion breaks. A
    hard cut from DSA to HR feels like a page load." Until day 6 the segment
    advanced silently and the student was simply asked about something else."""
    engine = make(
        db,
        llm=StubLLM([verdict(justification="failed", band="below")]),
        m05=BankQuestions(),
        m01=NoClaims(),
    )
    row = with_jd(engine)
    engine.start(row.id)
    state = say(engine, row, "I do not know.")

    assert state.current_segment == 1
    said = interviewer_lines(state)[-1]
    # The bridge names what is coming, in M02's words for the requirement.
    assert "Let's move to the next part: Data structures and algorithms, Recursion" in said
    # And it replaces "Next question" rather than stacking on top of it —
    # three transitions for one crossing is worse than none.
    assert "Next question." not in said

    # The transition carries what the UI needs to draw the card (§15.5).
    crossing = next(
        e.payload for e in store.events_for(db, row.id) if e.kind == "segment.transition"
    )
    assert crossing["from_title"] == "Warm-up"
    assert crossing["to_title"] == "Data structures and algorithms, Recursion"
    assert crossing["line"] in said

    # Said once. The next question in the same round is an ordinary one.
    assert engine.state(row.id).pending_bridge is None


def test_the_bridge_into_the_closing_asks_the_student_for_theirs(db):
    """There is no next topic to name, so it gets its own line."""
    closing = next(
        s
        for s in planner.assemble(
            planner.PlanInputs(session_id=uuid.uuid4(), mode="mock", requested_minutes=30)
        ).segments
        if s.kind == "closing"
    )
    assert "Do you have any for me?" in bridge_line(closing)


# ── M05 running dry (EC-6.16, M05 §6.8) ──────────────────────────────────


@pytest.mark.gate
def test_a_thin_bank_ends_the_round_not_the_interview(db):
    """M05 answering "nothing left" is a known state with a behaviour, not a
    crash: end that round and open the next. Ending the session would throw
    away every segment behind it — a thin corner of the bank becoming a short
    interview about nothing."""
    engine = make(
        db,
        llm=StubLLM([verdict(justification="failed", band="below")]),
        m05=BankQuestions(),
        m01=NoClaims(),
    )
    two_rounds = {
        "rounds": [
            {
                "round_type": "verbal",
                "minutes": 7.0,
                "question_count": 2,
                "requirement_ids": ["r1"],
            },
            {
                "round_type": "verbal",
                "minutes": 7.0,
                "question_count": 2,
                "requirement_ids": ["r2"],
            },
        ],
        "allocations": [],
        "uncovered": [],
        "plan_version": "greedy-log-v1",
    }
    engine.upstreams.m02._plan = two_rounds
    row = with_jd(engine)
    state = engine.start(row.id)
    assert state.status is SessionStatus.live

    # The bank has nothing at all from here on — for M05 and for the local
    # playlist behind it, so there is genuinely nothing left to ask.
    engine.upstreams.m05.items = []
    engine.upstreams.local_questions.items = []
    state = say(engine, row, "I do not know.")

    # It walked off the end of the plan rather than stopping at segment 1.
    transitions = [
        e.payload for e in store.events_for(db, row.id) if e.kind == "segment.transition"
    ]
    assert [t["to"] for t in transitions] == [1, 2, 3]
    assert transitions[-1]["reason"] == "bank_exhausted"
    # Off the end of the plan is the closing, which is reserved (FR-6.17):
    # it still asks for the student's questions (FR-6.21) before it ends.
    assert state.status is SessionStatus.live
    assert state.transcript[-1].question_source == "closing"
    state = say(engine, row, "No, thanks.")
    assert state.status is SessionStatus.ended

    # And what nothing asked about is owed to M02 as skipped, because a ledger
    # still expecting them says coverage is coming when it is not.
    owed = {
        (r.requirement_id, r.ledger_state)
        for r in db.exec(select(LedgerOutbox).where(LedgerOutbox.session_id == row.id)).all()
    }
    assert ("r1", "skipped") in owed and ("r2", "skipped") in owed


# ── the project segment, live (§6.1) ─────────────────────────────────────


@pytest.mark.gate
def test_the_project_segment_asks_about_the_students_own_resume(db):
    """Its questions are M01's probes, not M05's items — and they are never
    scored, because M13 resolves a package from M05 and a claim probe is not
    a bank item."""
    engine = make(
        db, llm=StubLLM([verdict(justification="failed", band="below")]), m05=BankQuestions()
    )
    row = mock(engine, minutes=30)
    state = engine.start(row.id)
    assert [s.kind for s in state.plan.segments] == ["warmup", "project", "technical", "closing"]
    # The claim the preview showed is the claim on the plan, so M01 re-parsing
    # a resume mid-session cannot change the question.
    assert state.plan.claims[0]["text"].startswith("Built a crop-disease classifier")

    # An answer the stub model judges failed: one step ends each question,
    # which is the arithmetic this test is about.
    state = say(engine, row, "It overwrites the old value.")
    asked = state.transcript[-1]
    assert state.current_segment == 1
    assert asked.question_source == "m01_probe"
    assert asked.concept_id == "claim:c1"
    assert "classifier" in asked.text
    # Nothing scoreable: no rubric, so no evaluation is owed for the answer.
    assert asked.rubric_round_type is None

    state = say(engine, row, "It overwrites the old value.")

    # The warm-up's bank question IS owed an evaluation; the claim probe is
    # not, because M13 resolves a package from M05 and a probe is not a bank
    # item. Two answers, one of them scoreable, and it is the right one.
    assert sum(1 for t in state.transcript if t.role == "candidate") == 2
    queued = db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)).all()
    project_index = next(s.index for s in state.plan.segments if s.kind == "project")
    answered_in = {t.turn_id: t.segment_index for t in state.transcript if t.role == "candidate"}
    assert len(queued) == 1
    assert answered_in[queued[0].turn_id] != project_index
    assert queued[0].payload["round_type"] == "dsa_verbal"


def test_the_notes_open_after_a_question_about_the_resume(db):
    """M01 sends each rung's `expects` as a list of points. M06 stored them as
    one string per rung, so "what a strong answer covers" became a list of
    lists, and every session that asked about the resume ended in a 500 where
    its notes should be (found live, 2026-10-05)."""
    engine = make(
        db, llm=StubLLM([verdict(justification="failed", band="below")]), m05=BankQuestions()
    )
    row = mock(engine, minutes=30)
    engine.start(row.id)
    say(engine, row, "I do not know.")
    say(engine, row, "I do not know.")
    engine.end(row.id, "ended_by_student")

    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    probe = next(q for q in built.questions if q.source == "m01_probe")
    assert probe.strong_answer_covers[0] == "names the model and the data"
    assert all(isinstance(point, str) for point in probe.strong_answer_covers)


def test_a_rung_stored_as_one_string_still_reads():
    """Events written before the fix hold the old shape; they still open."""
    old = items.from_dict({"stem": "q", "source": "m01_probe", "expects": {"0": "a baseline"}})
    new = items.from_dict(
        {"stem": "q", "source": "m01_probe", "expects": {"0": ["a baseline", " "]}}
    )
    assert old.expected_at(0) == new.expected_at(0) == ["a baseline"]
    assert items.expected_statements({"1": ["b", "a"], "0": ["a"]}) == ["a", "b"]
