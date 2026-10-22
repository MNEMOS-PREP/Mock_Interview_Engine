"""Hints, and what they cost — FR-6.7, master plan §32.5.

The rule this file is about: **the deduction is published before it is
taken.** A student who discovers afterwards that a hint cost 15% has been
penalised; a student who was told first has made a choice. Everything below
is a way of asking whether that promise holds.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache, hint_offer
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox
from backend_M06_Mock_Interview_Engine.state import InvalidTransition

from .stubs import BankQuestions, NoClaims, StubLLM, close, verdict


def make(db, llm=None, **upstreams) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(**upstreams),
        llm=llm or NullLLM(),
        thetas=ThetaCache(),
    )


def live(engine: Engine, mode="mock"):
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=30
    )
    engine.start(row.id)
    return row


def lines(state):
    return [t.text for t in state.transcript if t.role == "interviewer"]


# ── the price, before the hint ────────────────────────────────────────────


@pytest.mark.gate
def test_the_price_of_a_hint_is_published_before_it_is_taken(db):
    """§32.5. The factor is M13's, and it reaches the student on every read of
    the session rather than on a separate call they might not make."""
    engine = make(db, m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    offer = hint_offer(engine.state(row.id))

    assert offer.available is True
    assert offer.level == 1
    # The fixture M13's published table: level 1 credits at 85%.
    assert offer.credit == 0.85
    assert offer.hints_left >= 1
    assert offer.unavailable_reason is None


def test_the_factor_is_m13s_and_is_frozen_when_the_plan_is_built(db):
    """A price quoted is a price paid. A rubric reloaded mid-session must not
    change what a hint cost the student who already took it."""
    engine = make(db, m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    state = engine.state(row.id)
    assert state.plan.hint_penalty == {1: 0.85, 2: 0.7, 3: 0.5, 0: 1.0}

    # M13 republishes a harsher table. The session in flight keeps its own,
    # because the student was quoted 85% and has not taken the hint yet.
    engine.upstreams.m13.hint_penalty = {"1": 0.10}
    assert hint_offer(engine.state(row.id)).credit == 0.85

    # A session planned after the change is quoted the new price.
    later = live(engine)
    assert hint_offer(engine.state(later.id)).credit == 0.10


def test_an_unlisted_level_credits_fully(db):
    """M13's own rule (`Rubric.credit`): unlisted levels credit at 1.0. The
    honest default for "we never priced this" is not "free of charge to us"."""
    engine = make(db, m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    state = engine.state(row.id)
    state.plan.hint_penalty = {}
    assert hint_offer(state).credit == 1.0


# ── taking one ────────────────────────────────────────────────────────────


@pytest.mark.gate
def test_taking_a_hint_says_it_and_records_what_it_cost(db):
    """A hint recorded but never shown is a deduction the student paid for
    and did not receive."""
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    open_before = engine.state(row.id).open_turn_id

    state = engine.hint(row.id)
    said = lines(state)[-1]
    assert said, "the hint is in the transcript, not only in the log"
    assert state.transcript[-1].probe_move == "hint"
    assert state.hint_level == 1

    # It re-opens the SAME question, so the answer that follows still belongs
    # to the question the hint was about.
    assert state.open_turn_id != open_before
    asked = state.turn(state.open_turn_id)
    original = state.turn(open_before)
    assert asked.question_id == original.question_id
    assert asked.probe_depth == original.probe_depth

    given = next(e for e in store.events_for(db, row.id) if e.kind == "hint.given")
    assert given.payload == {"level": 1, "credit": 0.85}


def test_the_answer_after_a_hint_carries_the_level_to_m13(db):
    """M13 applies the credit ONCE, from `hint_level_used` on the turn. If M06
    does not carry it, the deduction the student was quoted never happens."""
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    engine.hint(row.id)
    state = engine.state(row.id)
    engine.answer(row.id, state.open_turn_id, "Buckets, and a bounded load factor.")
    close(engine, row)

    queued = db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)).all()
    assert [r.payload["hint_level_used"] for r in queued] == [1]


def test_hints_run_out_and_say_so(db):
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    ladder = list((engine.state(row.id).current_item or {}).get("hint_ladder") or [])
    assert ladder, "the fixture question has a ladder to exhaust"

    for expected in range(1, len(ladder) + 1):
        assert hint_offer(engine.state(row.id)).level == expected
        engine.hint(row.id)

    spent = hint_offer(engine.state(row.id))
    assert spent.available is False
    assert spent.unavailable_reason == "No more hints on this one."
    with pytest.raises(InvalidTransition, match="No more hints"):
        engine.hint(row.id)


def test_final_boss_offers_no_hints_and_says_why(db):
    """§6.1's mode table. Told, not left to wonder whether the button broke."""
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions(), m01=NoClaims())
    row = live(engine, mode="final_boss")
    offer = hint_offer(engine.state(row.id))
    assert offer.available is False
    assert offer.unavailable_reason == "Final Boss runs without hints."


def test_nothing_open_means_nothing_to_hint_about(db):
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions(), m01=NoClaims())
    row = live(engine)
    engine.end(row.id, "ended_by_student")
    offer = hint_offer(engine.state(row.id))
    assert offer.available is False
    assert offer.unavailable_reason == "Nothing is open to hint about."
    assert engine.state(row.id).status is SessionStatus.ended


# ── over HTTP ─────────────────────────────────────────────────────────────


def test_the_hint_price_is_on_every_read_of_the_session(client, as_student):
    created = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()
    sid = created["id"]
    assert created["hint"]["available"] is False, "nothing is open before it starts"

    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    assert started["hint"]["available"] is True
    assert started["hint"]["credit"] == 0.85

    taken = client.post(f"/v1/interviews/{sid}/hint", headers=as_student)
    assert taken.status_code == 200
    assert taken.json()["hint"]["level"] == 2, "the next one is dearer"
    assert taken.json()["transcript"][-1]["probe_move"] == "hint"
