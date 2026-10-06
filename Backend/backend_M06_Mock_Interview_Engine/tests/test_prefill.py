"""Thinking while the student pauses — M11's FR-11.6, strictly (`prefill.py`).

What is pinned is the user's rule: "the reply should be based on what the
answer is — not assume what he or she is going to say". A prefill writes
nothing and says nothing. Its model answers are used only by an answer of
the exact same words, and then the interviewer's step asks the model nothing
it already asked and comes out exactly as it would have without one. Any
other words, and every request goes to the model as before. Each answer
records how many prefills its question had and whether one was used.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import prefill, store

from .stubs import BankQuestions, StubLLM, verdict
from .test_engine import make

SAID = "It hashes the key to find a bucket, then reads that bucket."


def live(db, llm):
    engine = make(db, llm=llm, m05=BankQuestions())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=10
    )
    engine.start(row.id)
    prefill.forget(row.id)
    return engine, row


def calls(llm: StubLLM) -> int:
    return len(llm.structured_calls) + len(llm.stream_calls)


def lines_after(state, n: int) -> list[tuple[str, str | None]]:
    return [(t.text, t.probe_move) for t in state.transcript[n:]]


def test_a_prefill_writes_nothing_and_says_nothing(db):
    llm = StubLLM([verdict(band="at")] * 10)
    engine, row = live(db, llm)
    before = len(store.events_for(db, row.id))
    open_turn = engine.state(row.id).open_turn_id
    assert engine.prefill(row.id, open_turn, SAID)
    assert len(store.events_for(db, row.id)) == before
    assert engine.state(row.id).open_turn_id == open_turn
    assert calls(llm) > 0, "it thought about what was said"


def test_the_same_words_are_answered_from_the_prefill_and_come_out_the_same(db):
    """With a prefill: no model request is made twice, and the step's line is
    exactly the line a session without one says."""
    plain_llm = StubLLM([verdict(band="at")] * 10)
    plain, plain_row = live(db, plain_llm)
    n = len(plain.state(plain_row.id).transcript)
    plain_state = plain.answer(plain_row.id, plain.state(plain_row.id).open_turn_id, SAID)
    expected = lines_after(plain_state, n)

    llm = StubLLM([verdict(band="at")] * 10)
    engine, row = live(db, llm)
    open_turn = engine.state(row.id).open_turn_id
    engine.prefill(row.id, open_turn, SAID)
    thought = calls(llm)
    state = engine.answer(row.id, open_turn, SAID)
    assert calls(llm) == thought, "every request was one the prefill had made"
    assert lines_after(state, n) == expected
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    assert said.prefill == {"tried": 1, "used": True}


def test_other_words_ask_the_model_as_before(db):
    """One word more and nothing kept is used: the reply is to what was said."""
    llm = StubLLM([verdict(band="at")] * 10)
    engine, row = live(db, llm)
    open_turn = engine.state(row.id).open_turn_id
    engine.prefill(row.id, open_turn, SAID)
    thought = calls(llm)
    state = engine.answer(row.id, open_turn, SAID + " Collisions go in a list.")
    assert calls(llm) > thought, "the model was asked about the words actually said"
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    assert said.prefill == {"tried": 1, "used": False}


def test_a_newer_prefill_replaces_the_one_before_and_is_counted(db):
    llm = StubLLM([verdict(band="at")] * 10)
    engine, row = live(db, llm)
    open_turn = engine.state(row.id).open_turn_id
    engine.prefill(row.id, open_turn, "It hashes the key.")
    engine.prefill(row.id, open_turn, SAID)
    state = engine.answer(row.id, open_turn, SAID)
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    assert said.prefill == {"tried": 2, "used": True}


def test_a_prefill_for_a_question_no_longer_open_is_nothing(db):
    llm = StubLLM([verdict(band="at")] * 10)
    engine, row = live(db, llm)
    stale = uuid.uuid4()
    assert not engine.prefill(row.id, stale, SAID)
    state = engine.answer(row.id, engine.state(row.id).open_turn_id, SAID)
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    assert said.prefill is None


def test_the_route_takes_a_prefill_and_returns_nothing(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    response = client.post(
        f"/v1/interviews/{sid}/prefill",
        json={"question_turn_id": started["open_turn_id"], "text": SAID},
        headers=as_student,
    )
    assert response.status_code == 204 and not response.content
