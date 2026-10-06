"""A phone call takes the microphone — M11's EC-11.12.

What is pinned: the clock stops while the device has the microphone and runs
again when it gives it back; no pause is spent and no reconnect is counted —
however the student comes back, by the room saying so or by simply
answering; and a second report either way is nothing new.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus

from .stubs import BankQuestions, StubLLM, verdict
from .test_engine import make


class Clock:
    def __init__(self, engine):
        self.now = engine.clock()

    def __call__(self):
        return self.now


def live(db):
    engine = make(db, llm=StubLLM([verdict(band="at")] * 10), m05=BankQuestions())
    clock = Clock(engine)
    engine.clock = clock
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=20
    )
    engine.start(row.id)
    return engine, row, clock


def test_the_clock_stops_for_a_call_and_no_pause_is_spent(db):
    engine, row, clock = live(db)
    used = engine.state(row.id).time_used_s(clock.now)
    state = engine.interrupted(row.id, away=True)
    assert state.flags.away_since is not None and state.status is SessionStatus.live
    clock.now += timedelta(minutes=3)
    assert abs(state.time_used_s(clock.now) - used) < 1, "three minutes of call cost nothing"
    state = engine.interrupted(row.id, away=False)
    assert state.flags.away_since is None
    assert state.flags.pauses_used == 0, "a call is not the student's pause"
    assert state.flags.reconnect_count == 0, "nor a connection that dropped"
    assert state.flags.interruptions == 1


def test_answering_after_a_call_is_coming_back_not_reconnecting(db):
    engine, row, clock = live(db)
    engine.interrupted(row.id, away=True)
    clock.now += timedelta(seconds=40)
    state = engine.answer(row.id, engine.state(row.id).open_turn_id, "It hashes the key.")
    assert state.flags.away_since is None
    assert state.flags.reconnect_count == 0


def test_a_second_report_either_way_is_nothing_new(db):
    engine, row, _ = live(db)
    first = engine.interrupted(row.id, away=True)
    assert engine.interrupted(row.id, away=True).last_seq == first.last_seq
    back = engine.interrupted(row.id, away=False)
    assert engine.interrupted(row.id, away=False).last_seq == back.last_seq


def test_the_route_takes_it_from_the_sessions_student(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    away = client.post(
        f"/v1/interviews/{sid}/interruption", json={"away": True}, headers=as_student
    )
    assert away.status_code == 200
    back = client.post(
        f"/v1/interviews/{sid}/interruption", json={"away": False}, headers=as_student
    )
    assert back.status_code == 200 and back.json()["status"] == "live"
