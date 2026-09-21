"""Sessions nobody is in — EC-6.14, EC-6.13.

A session holds its candidate's one slot while it is live or paused
(`occupying_key`), which is right while somebody is in the room. **Nothing
released it when they left.** A student who paused and closed the tab was
refused every future interview, permanently, with "candidate already has a
live session" — a door that locks behind you.

FR-6.12's five-minute pause cap did not help: it is applied by the student
coming *back*. EC-6.14 is the rule for when nobody does, and it was scheduled
for day 11 — which is eleven days of a lockout that one sweep fixes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from ai_core.timeutil import utcnow

from backend_M06_Mock_Interview_Engine import adapters, report, store, sweeper
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import NullLLM

from .stubs import BankQuestions, NoClaims


@pytest.fixture(name="platform")
def platform_fixture(engine_db):
    db, factory = engine_db
    upstreams = adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims())
    interviewer = Engine(db=db, upstreams=upstreams, llm=NullLLM(), thetas=ThetaCache())
    return db, factory, upstreams, interviewer


def started(interviewer: Engine, candidate: uuid.UUID):
    row, _ = store.create_session(
        interviewer.db, candidate_id=candidate, kind="mock", mode="mock", minutes=30
    )
    interviewer.start(row.id)
    return row


def later(minutes: float):
    """The clock, moved on. The sweep takes one rather than reading utcnow(),
    so a test can stand in the future instead of rewriting history — and
    rewriting history would not work anyway: `load_state` answers from a
    checkpoint, which an edited event row does not invalidate."""
    return utcnow() + timedelta(minutes=minutes)


# ── the lockout ───────────────────────────────────────────────────────────


@pytest.mark.gate
def test_a_pause_nobody_returns_to_does_not_lock_the_student_out(platform):
    """EC-6.14: auto-close after 30 min, partial report generated."""
    db, factory, upstreams, interviewer = platform
    candidate = uuid.uuid4()
    row = started(interviewer, candidate)
    store.record(db, row, "session.paused", step="pause")

    # Still theirs while they might come back.
    soon = later(sweeper.ABANDONED_PAUSE_S / 60 - 1)
    assert sweeper.close_abandoned(factory, upstreams, NullLLM(), now=soon) == []
    with pytest.raises(store.LiveSessionExists):
        store.create_session(db, candidate_id=candidate, kind="mock", mode="mock", minutes=30)

    # Past the cap, it is not.
    gone = later(sweeper.ABANDONED_PAUSE_S / 60 + 1)
    assert sweeper.close_abandoned(factory, upstreams, NullLLM(), now=gone) == [str(row.id)]

    db.expire_all()
    state = store.load_state(db, row.id)
    assert state.status is SessionStatus.ended
    assert state.end_reason == "abandoned"

    # The slot is free, and the student can sit another interview.
    again, _ = store.create_session(
        db, candidate_id=candidate, kind="mock", mode="mock", minutes=30
    )
    assert again.id != row.id


def test_the_abandoned_session_still_produces_its_report(platform):
    """EC-6.14 asks for a partial report, and AC-6.1 already guarantees one
    for any session with an event log. What was asked is not lost."""
    db, factory, upstreams, interviewer = platform
    row = started(interviewer, uuid.uuid4())
    store.record(db, row, "session.paused", step="pause")
    sweeper.close_abandoned(
        factory, upstreams, NullLLM(), now=later(sweeper.ABANDONED_PAUSE_S / 60 + 1)
    )

    db.expire_all()
    state = store.load_state(db, row.id)
    built = report.build(state, store.events_for(db, row.id), interviewer.clock())
    assert built.questions, "the question that was asked is still in the report"
    assert built.status is SessionStatus.ended


def test_a_live_session_is_closed_only_long_after_its_own_clock_ran_out(platform):
    """A student thinking for ten minutes is still in the room. One whose
    30-minute interview started three hours ago is not, and the turn loop
    never got a turn to notice on."""
    _db, factory, upstreams, interviewer = platform
    row = started(interviewer, uuid.uuid4())

    # Over its planned 30 minutes, but inside the grace.
    inside = later(30 + sweeper.ABANDONED_LIVE_GRACE_S / 60 - 5)
    assert sweeper.close_abandoned(factory, upstreams, NullLLM(), now=inside) == []

    past = later(30 + sweeper.ABANDONED_LIVE_GRACE_S / 60 + 5)
    assert sweeper.close_abandoned(factory, upstreams, NullLLM(), now=past) == [str(row.id)]


@pytest.mark.gate
def test_the_sweep_that_runs_in_production_is_the_one_that_frees_the_slot(monkeypatch, platform):
    """`close_abandoned` being right is worth nothing if `sweep_once` — the
    only thing the app actually runs — does not call it. Deleting the call
    left every other gate green, which is how wiring goes missing."""
    db, factory, upstreams, interviewer = platform
    candidate = uuid.uuid4()
    row = started(interviewer, candidate)
    store.record(db, row, "session.paused", step="pause")

    # `sweep_once` reads the real clock, so the cap is moved rather than time.
    monkeypatch.setattr(sweeper, "ABANDONED_PAUSE_S", -1)
    sweeper.sweep_once(factory, upstreams, NullLLM())

    db.expire_all()
    assert store.load_state(db, row.id).status is SessionStatus.ended
    store.create_session(db, candidate_id=candidate, kind="mock", mode="mock", minutes=30)


def test_a_session_somebody_is_in_is_left_alone(platform):
    """The sweep runs every 30 seconds. Closing a live interview under a
    student would be worse than the lockout it fixes."""
    db, factory, upstreams, interviewer = platform
    started(interviewer, uuid.uuid4())
    assert sweeper.close_abandoned(factory, upstreams, NullLLM()) == []
    assert sweeper.sweep_once(factory, upstreams, NullLLM()) is not None


def test_the_refusal_names_the_status_it_found(platform):
    """ "Live" for a session the student PAUSED sent them looking for an
    interview that was not running."""
    db, _factory, _upstreams, interviewer = platform
    candidate = uuid.uuid4()
    row = started(interviewer, candidate)
    store.record(db, row, "session.paused", step="pause")

    with pytest.raises(store.LiveSessionExists, match="paused session"):
        store.create_session(db, candidate_id=candidate, kind="mock", mode="mock", minutes=30)
