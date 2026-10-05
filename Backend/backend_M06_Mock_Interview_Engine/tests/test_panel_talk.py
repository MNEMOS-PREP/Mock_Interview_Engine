"""The panel talks — FR-6.3, master plan §26.

What a student hears from a panel: everyone introduced before the first
question; a hand-over in two voices at a round's end; an expert's follow-up,
and the asker taking the question back; a long answer cut short by whoever on
the panel ran out of patience first; and the lead saying goodbye. Every line
records who said it, part by part, so the room can show and voice each.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import panel as seating
from backend_M06_Mock_Interview_Engine import personas as personas_module
from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.personas import persona
from backend_M06_Mock_Interview_Engine.state import fold

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make, say

LONG = " ".join(["word"] * 190)
HELD = "It hashes the key to a bucket and reads that bucket."


def session(db, mode="mock", minutes=10, llm=None):
    engine = make(db, llm=llm or StubLLM([verdict()] * 60), m05=BankQuestions())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=minutes
    )
    engine.start(row.id)
    return engine, row


def run(engine, row, answer, until=lambda state: False, limit=30):
    for _ in range(limit):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live or until(state):
            return state
        say(engine, row, answer)
    return engine.state(row.id)


def asked(state):
    return [t for t in state.transcript if t.role == "interviewer"]


def panel_of(state) -> list[str]:
    return list(dict.fromkeys(s.persona_id for s in state.plan.segments if s.persona_id))


def runs(state, turn) -> str:
    return next(s.persona_id for s in state.plan.segments if s.index == turn.segment_index)


def speaker_now(state) -> str:
    return asked(state)[-1].speaker_id


def closing_of(state):
    return [t for t in asked(state) if t.question_source == "closing"]


# ── the opening ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["practice", "mock", "real_drive", "final_boss"])
def test_everyone_on_the_panel_is_introduced_before_the_first_question(db, mode):
    engine, row = session(db, mode=mode, minutes=30)
    state = engine.state(row.id)
    seated = panel_of(state)
    opening = asked(state)[0]
    if len(seated) < 2:
        assert not opening.parts, "one interviewer just greets"
        return
    voices = [part.speaker_id for part in opening.parts]
    # The lead greets, the others say hello in the order the student will
    # meet them, and the lead asks.
    assert voices == [seated[0], *seated[1:], seated[0]]
    assert persona(seated[0]).name in opening.parts[0].text
    assert all(persona(p).name in opening.parts[0].text for p in seated[1:])


# ── hand-overs ────────────────────────────────────────────────────────────


def test_a_hand_over_is_two_voices_the_leaving_one_naming_the_arriving_one(db):
    engine, row = session(db)
    state = run(engine, row, "I don't know")
    turns = asked(state)
    handovers = [
        (before, turn)
        for before, turn in zip(turns, turns[1:], strict=False)
        if len({p.speaker_id for p in turn.parts}) == 2
    ]
    assert handovers, "a mock with two interviewers hands over at least once"
    for before, turn in handovers:
        leaving, arriving = persona(turn.parts[0].speaker_id), persona(turn.parts[-1].speaker_id)
        assert leaving.id == before.speaker_id, "the one who asked last hands over"
        assert arriving.id == turn.speaker_id == runs(state, turn), "the round's own asks"
        assert arriving.name in turn.parts[0].text
        assert turn.parts[-1].text.startswith(arriving.said().take_over.format(name=leaving.name))
        # Introduced at the opening, so a bridge — not a second hello.
        assert arriving.said().greeting not in turn.parts[-1].text


def test_every_question_is_shown_under_the_interviewer_who_asks_it(db):
    """Until 2026-10-06 the first question of a new round went out under the
    previous interviewer's name: the selector named who asked LAST."""
    engine, row = session(db)
    state = run(engine, row, "I don't know")
    for turn in asked(state):
        if turn.question_source is not None:
            assert turn.speaker_id == runs(state, turn), turn.text


def test_a_panel_closes_as_we(db):
    engine, row = session(db)
    state = run(engine, row, "I don't know", until=lambda s: bool(closing_of(s)))
    lead = persona(panel_of(state)[0])
    closing = closing_of(state)[0]
    assert lead.said().panel_to_closing in closing.text
    assert closing.speaker_id == lead.id


def test_the_lead_says_goodbye_whoever_was_asking(db):
    engine, row = session(db)
    lead = panel_of(engine.state(row.id))[0]
    state = run(engine, row, "I don't know", until=lambda s: speaker_now(s) != lead)
    assert speaker_now(state) != lead, "the run reached someone else's round"
    state = engine.end(row.id, "ended_by_student")
    goodbye = asked(state)[-1]
    assert goodbye.speaker_id == lead
    assert goodbye.text == persona(lead).said().session_close


# ── interjections ─────────────────────────────────────────────────────────


@pytest.fixture
def stack_expert(monkeypatch):
    """The professor, authored to know stacks and queues better than anyone:
    the bank's questions are about those."""
    table = dict(personas_module.personas())
    professor = table["professor"]
    table["professor"] = professor.model_copy(
        update={
            "domain_bias": [
                *professor.domain_bias,
                *("stack", "queue", "loop", "complexity", "recursion", "dictionary"),
            ]
        }
    )
    monkeypatch.setattr(personas_module, "personas", lambda: table)
    monkeypatch.setattr(seating, "personas", lambda: table)
    return table["professor"]


def cut_ins(state, who: str):
    return [t for t in asked(state) if t.speaker_id == who and t.probe_move == "rung"]


def test_an_expert_comes_in_once_a_round_and_the_asker_takes_it_back(db, stack_expert):
    engine, row = session(db, llm=StubLLM([verdict(band="at")] * 60))
    state = run(engine, row, HELD, until=lambda s: bool(cut_ins(s, stack_expert.id)), limit=8)
    cut_in = cut_ins(state, stack_expert.id)[0]
    owner = persona(runs(state, cut_in))
    assert owner.id != stack_expert.id
    assert cut_in.probe_depth == 2, "after the asker's own first follow-up"
    assert cut_in.text.startswith(stack_expert.said().interject)
    # The asker takes it back on the next line.
    state = run(engine, row, HELD, limit=1)
    after = asked(state)[-1]
    assert after.speaker_id == owner.id
    assert after.text.startswith(owner.said().take_over.format(name=stack_expert.name))
    # Once a round: the rest of this round is the asker's.
    state = run(
        engine,
        row,
        HELD,
        until=lambda s: asked(s)[-1].segment_index != cut_in.segment_index,
        limit=6,
    )
    same_round = [
        t for t in cut_ins(state, stack_expert.id) if t.segment_index == cut_in.segment_index
    ]
    assert len(same_round) == 1


def test_nobody_comes_in_who_does_not_know_it_better(db):
    """The shipped personas: nobody on a mock's panel knows the bank's DSA
    questions clearly better than the engineer asking them."""
    engine, row = session(db, llm=StubLLM([verdict(band="at")] * 60))
    state = run(engine, row, HELD, limit=6)
    for turn in asked(state):
        if turn.probe_move == "rung":
            assert turn.speaker_id == runs(state, turn)


# ── cut-ins ───────────────────────────────────────────────────────────────


def test_a_long_answer_is_cut_short_by_the_least_patient_on_the_panel(db):
    """Final Boss: the bar-raiser asks; the staff engineer beside them has
    less patience for a long answer, and says so."""
    engine, row = session(db, mode="final_boss", llm=StubLLM([verdict(band="at")] * 60))
    state = engine.state(row.id)
    seated = [persona(p) for p in panel_of(state)]
    least = min(seated, key=lambda p: p.long_answer_words)
    owner = persona(speaker_now(state))
    assert least.id != owner.id
    assert least.long_answer_words < len(LONG.split()) <= owner.long_answer_words
    state = run(engine, row, LONG, limit=1)
    turn = asked(state)[-1]
    assert turn.parts[0].speaker_id == least.id
    assert turn.parts[0].text == least.said().keep_moving
    assert turn.speaker_id == owner.id, "the asker still asks"


# ── the record ────────────────────────────────────────────────────────────


def test_a_line_written_before_speakers_were_recorded_reads_as_its_rounds(db):
    """Events from before 2026-10-06 carry no speaker: the fold reads it off
    the segment, which is who asked them."""
    engine, row = session(db)
    run(engine, row, "I don't know", limit=3)
    events = store.events_for(db, row.id)
    for event in events:
        if event.kind == "question.asked":
            event.payload = {
                k: v for k, v in event.payload.items() if k not in ("speaker_id", "parts")
            }
    state = fold(events)
    for turn in asked(state):
        if turn.question_source is not None:
            assert turn.speaker_id == runs(state, turn)
            assert turn.parts == []


# ── sitting in ────────────────────────────────────────────────────────────


def test_someone_sitting_in_says_hello_and_comes_in_every_other_question(db):
    """No resume claims and no job description: one round of the plan's own,
    so one interviewer runs it — and a second sits in, as at a real table."""
    engine = make(db, llm=StubLLM([verdict(band="at")] * 90), m05=BankQuestions(), m01=NoClaims())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=30
    )
    engine.start(row.id)
    state = engine.state(row.id)
    runners = {s.persona_id for s in state.plan.segments}
    assert len(runners) == 1, "the plan runs on one interviewer"
    lead, sitter = state.plan.panel
    assert sitter not in runners
    opening = asked(state)[0]
    assert [p.speaker_id for p in opening.parts] == [lead, sitter, lead]
    assert opening.parts[1].text == persona(sitter).said().panel_sitting_in

    state = run(engine, row, HELD, limit=16)
    came_in = [t for t in asked(state) if t.speaker_id == sitter]
    asked_new = [
        t
        for t in asked(state)
        if t.probe_move is None and t.question_source not in (None, "closing")
    ]
    assert came_in, "the second interviewer came in"
    assert all(t.probe_depth == 2 and t.probe_move == "rung" for t in came_in)
    assert len(came_in) <= (len(asked_new) + 1) // 2
