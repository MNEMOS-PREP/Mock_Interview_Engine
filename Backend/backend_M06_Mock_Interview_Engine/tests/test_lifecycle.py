"""A session's end, and what may happen after it (2026-10-22).

The user's report: practising a resume claim, closing the interview did not
completely end it. Reproduced: a drill the student walked away from stayed
live, holding their one session slot; the next "Practise defending this" was
refused (409), and M01 told them the engine "did not accept the drill" — for
half an hour, the sweeper's grace for a full interview. These hold the fix.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from backend_M06_Mock_Interview_Engine import store, sweeper
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import AnswerRejected

from .stubs import BankQuestions, StubLLM, drill_body, verdict
from .test_engine import make, mock


def start_drill(engine, candidate):
    body = drill_body(candidate)
    row, _ = engine.create_drill(
        candidate_id=candidate,
        claim_id=body["claim_id"],
        claim_text=body["claim_text"],
        probes=body["probes"],
        source_module="M01",
    )
    engine.start(row.id)
    return row


@pytest.mark.gate
def test_a_drill_left_live_never_blocks_the_next_one(db):
    """The bug, reproduced: the first drill is left mid-question."""
    engine = make(db, llm=StubLLM([verdict()]))
    student = uuid.uuid4()
    first = start_drill(engine, student)
    assert engine.state(first.id).status is SessionStatus.live

    second = start_drill(engine, student)  # was: LiveSessionExists → 409

    assert engine.state(first.id).status is SessionStatus.ended
    assert engine.state(first.id).end_reason == "superseded"
    assert engine.state(second.id).status is SessionStatus.live


def test_a_live_drill_gives_way_to_a_new_interview_too(db):
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions())
    student = uuid.uuid4()
    left = start_drill(engine, student)
    row = mock(engine, candidate=student)
    assert engine.state(left.id).status is SessionStatus.ended
    assert engine.state(row.id).status is SessionStatus.planned


def test_a_live_interview_still_blocks_a_drill(db):
    """EC-6.13 stands for an interview: two at once would overwrite each other."""
    engine = make(db, llm=StubLLM([verdict()]), m05=BankQuestions())
    student = uuid.uuid4()
    row = mock(engine, candidate=student)
    engine.start(row.id)
    with pytest.raises(store.LiveSessionExists):
        start_drill(engine, student)


def test_ending_twice_is_a_no_op_not_an_error(db):
    engine = make(db, llm=StubLLM([verdict()]))
    row = start_drill(engine, uuid.uuid4())
    first = engine.end(row.id, "ended_by_student")
    events = len(store.events_for(db, row.id))
    second = engine.end(row.id, "left")
    assert first.status is second.status is SessionStatus.ended
    assert second.end_reason == "ended_by_student", "the first end is the one that counts"
    assert len(store.events_for(db, row.id)) == events


def test_the_end_route_answers_twice_with_the_same_session(client, candidate_id, as_student):
    from .stubs import drill_body as body_for

    sid = client.post("/v1/drills", json=body_for(candidate_id), headers=as_student).json()[
        "session_id"
    ]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    first = client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    second = client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "ended"


def test_nothing_can_be_asked_or_answered_after_the_end(db):
    """A stale request — an answer sent as the student pressed End — cannot
    reopen the session or make it ask anything."""
    engine = make(db, llm=StubLLM([verdict()]))
    row = start_drill(engine, uuid.uuid4())
    open_turn = engine.state(row.id).open_turn_id
    engine.end(row.id, "ended_by_student")
    asked_before = sum(1 for t in engine.state(row.id).transcript if t.role == "interviewer")
    with pytest.raises(AnswerRejected):
        engine.answer(row.id, open_turn, "late answer")
    state = engine.continue_session(row.id)
    assert state.status is SessionStatus.ended
    assert sum(1 for t in state.transcript if t.role == "interviewer") == asked_before


def test_a_drill_walked_away_from_is_closed_in_minutes_not_half_an_hour(db):
    engine = make(db, llm=StubLLM([verdict()]))
    row = start_drill(engine, uuid.uuid4())
    state = engine.state(row.id)
    away = state.model_copy(deep=True)
    away.flags.away_since = engine.clock()
    four_min = engine.clock() + timedelta(minutes=4, seconds=5)
    assert sweeper._abandoned(away, four_min), "a drill's grace is its own length, twice"
    long = state.model_copy(deep=True, update={"requested_minutes": 45})
    long.flags.away_since = engine.clock()
    assert not sweeper._abandoned(long, four_min), "an interview keeps its half hour"
