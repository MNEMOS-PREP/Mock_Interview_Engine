"""What an interviewer says after an answer, before the next question (2026-10-21).

The user: "when my answer is correct it moves to the next question without
anything like hmm, good, well said — it should be a mix of all possible
words, and sometimes just the next question." And the second interviewer's
follow-ups were each taken back with "Thanks, Dr. Deshpande": "once in the
beginning and once at the end should be enough".
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.contracts import Move
from backend_M06_Mock_Interview_Engine.ladder import Outcome
from backend_M06_Mock_Interview_Engine.orchestration.graph import _acknowledgement
from backend_M06_Mock_Interview_Engine.personas import persona
from backend_M06_Mock_Interview_Engine.phrasebook import TELEGRAPHS
from backend_M06_Mock_Interview_Engine.state import SessionState

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make
from .test_panel_talk import HELD, asked, run

COUNTED = Outcome(move=Move(kind="move_on"), success=True)
NOT_COUNTED = Outcome(move=Move(kind="move_on"), success=False)


def said_after(outcome: Outcome, who: str, sessions: int = 300) -> list[str]:
    """What `who` says after `outcome`, over many sessions' draws."""
    out = []
    for _ in range(sessions):
        state = SessionState(
            session_id=uuid.uuid4(), candidate_id=uuid.uuid4(), kind="mock", mode="mock"
        )
        out.append(_acknowledgement(state, persona(who), outcome, "Next question."))
    return out


@pytest.mark.rotation  # the real draw: variety is the point
def test_a_good_answer_gets_a_mix_credit_plain_or_nothing():
    who = persona("methodical_engineer")
    said = said_after(COUNTED, who.id)
    assert "" in said, "sometimes just the next question"
    assert set(said) & set(who.credit), "sometimes a credit word"
    assert set(said) & set(who.acknowledgements), "sometimes a plain word"
    assert len(set(said) - {""}) >= 5, "a mix, not one word"


@pytest.mark.rotation  # the real draw: variety is the point
def test_an_answer_that_did_not_count_is_never_credited():
    who = persona("methodical_engineer")
    said = said_after(NOT_COUNTED, who.id)
    assert not set(said) & set(who.credit)
    assert set(said) <= {"", *who.acknowledgements}


@pytest.mark.rotation  # the real draw: variety is the point
def test_never_the_word_that_opens_what_follows():
    """ "Okay. Okay, here's the next one." is a stutter, not an acknowledgement."""
    who = persona("methodical_engineer")
    for _ in range(200):
        state = SessionState(
            session_id=uuid.uuid4(), candidate_id=uuid.uuid4(), kind="mock", mode="mock"
        )
        said = _acknowledgement(state, who, COUNTED, "Okay, here's the next one.")
        assert not said.lower().startswith("okay")


def test_every_word_is_screened_like_every_other_line():
    from backend_M06_Mock_Interview_Engine.personas import personas

    for p in personas().values():
        for word in (*p.acknowledgements, *p.credit):
            assert not any(term in word.lower() for term in TELEGRAPHS), (p.id, word)
        if p.speech == "bar_raiser":
            assert p.credit == (), "Final Boss is never warm"


def test_whoever_sat_in_is_thanked_once_then_once_more_at_the_close(db):
    engine = make(db, llm=StubLLM([verdict(band="at")] * 120), m05=BankQuestions(), m01=NoClaims())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15
    )
    engine.start(row.id)
    lead, sitter = engine.state(row.id).plan.panel
    thanks = persona(lead).said().take_over.format(name=persona(sitter).name)
    state = run(
        engine,
        row,
        HELD,
        until=lambda s: any(t.question_source == "closing" for t in asked(s)),
        limit=40,
    )
    came_in = [t for t in asked(state) if t.speaker_id == sitter]
    assert len(came_in) >= 2, "they came in more than once, so 'every time' would show"
    closing = next(t for t in asked(state) if t.question_source == "closing")
    assert thanks in closing.text, "once more at the end"
    assert sum(thanks in t.text for t in asked(state)) == 2, [t.text for t in asked(state)]


def test_after_an_answer_that_counted_the_next_question_opens_with_the_word(db, monkeypatch):
    """The wiring, not the choice: with the draw in the credit range, a new
    question after an answer that counted opens with its asker's credit word."""
    from backend_M06_Mock_Interview_Engine.orchestration import graph

    from .test_panel_talk import session

    monkeypatch.setattr(
        graph, "word_draw", lambda seed, key: 0.5 if key.startswith("ack:") else 0.0
    )
    engine, row = session(db, llm=StubLLM([verdict(band="at")] * 60))
    state = run(engine, row, HELD, limit=10)
    new = [
        t
        for t in asked(state)[1:]
        if t.probe_move is None and t.question_source not in (None, "closing")
    ]
    assert new, "the run reached a second question"
    credited = [
        t for t in new if any(w in t.text for p in t.parts for w in persona(p.speaker_id).credit)
    ]
    assert credited, [t.text for t in new]
