"""Chaos — spec §12's five, and AC-6.16 [chaos test].

"Do these, they find real bugs." Each one breaks something a real session
will meet — a worker dying, a stream dropping, a provider failing, a student
refreshing, a long pause — and asserts the two things that matter afterwards:
the session carries on from exactly where it was, and nothing was done twice.
Nothing done twice means: no question asked twice, no M02 ledger row written
twice, no evaluation queued twice (AC-6.16).
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import presence, report, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import welcome_line
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox, LedgerOutbox

from .day10 import Clock, deep_bank, events, make, rounds_plan, say, session
from .stubs import StubLLM, verdict

ROUNDS = rounds_plan(("r1", 4, 12.0), ("r2", 4, 12.0), ("r3", 4, 12.0))
HELD = "A stack is last in, first out — push and pop at one end, both O(1)."


def held_engine(db, clock=None, **kw):
    return make(
        db, plan=ROUNDS, verdicts=[verdict()], m05=deep_bank(), clock=clock or Clock(), **kw
    )


def drive_to_turn(engine, row, turn: int, text: str = HELD):
    state = engine.state(row.id)
    for _ in range(200):
        if state.next_turn_index >= turn or state.open_turn_id is None:
            break
        state = say(engine, row, text)
    assert state.next_turn_index >= turn, "the session ended before the turn"
    return state


def nothing_twice(db, engine, row) -> None:
    """AC-6.16's three, read straight off the tables and the log."""
    asked = Counter(p["turn_index"] for p in events(engine, row, "question.asked"))
    assert all(n == 1 for n in asked.values()), f"a turn asked twice: {asked}"
    evaluations = Counter(
        str(r.turn_id) for r in db.exec(select(EvaluationOutbox)).all() if r.session_id == row.id
    )
    assert all(n == 1 for n in evaluations.values()), "an evaluation queued twice"
    ledger = Counter(
        (r.requirement_id, r.ledger_state, str(r.turn_id))
        for r in db.exec(select(LedgerOutbox)).all()
        if r.session_id == row.id
    )
    assert all(n == 1 for n in ledger.values()), f"a ledger row written twice: {ledger}"


# ── 1. Kill the worker mid-turn → session resumes, no double-charge ──────


@pytest.mark.gate
@pytest.mark.parametrize("dies_in", ["continue_session", "_say", "_record_calls"])
def test_a_worker_killed_mid_turn_resumes_without_double_charging(db, monkeypatch, dies_in):
    """The answer is on the log; the worker dies at three points after it —
    before the step, after the decision, while recording the model calls.
    A fresh process (a new Engine, an empty θ cache) carries on from the log:
    the strategist is not asked again for a decision already written, and
    nothing is written twice."""
    from backend_M06_Mock_Interview_Engine.engine import ThetaCache

    engine = held_engine(db)
    row = session(engine, minutes=45)
    state = drive_to_turn(engine, row, 6)
    open_turn = state.open_turn_id

    def died(*_a, **_k):
        raise RuntimeError("worker killed")

    monkeypatch.setattr(engine, dies_in, died)
    with pytest.raises(RuntimeError):
        engine.answer(row.id, open_turn, HELD)
    monkeypatch.undo()

    restarted = held_engine(db, clock=engine.clock)
    restarted.thetas = ThetaCache()
    decided_before = len(events(restarted, row, "probe.decided"))
    state = restarted.start(row.id)  # what a reconnecting client calls
    restarted.start(row.id)
    state = restarted.state(row.id)

    assert state.status is SessionStatus.live and state.open_turn_id not in (None, open_turn)
    assert len(events(restarted, row, "probe.decided")) <= decided_before + 1
    nothing_twice(db, restarted, row)


# ── 2. Drop the stream at turn 15 → resume works, timer correct ─────────


@pytest.mark.gate
def test_a_stream_dropped_at_turn_15_resumes_with_the_clock_right(db):
    clock = Clock()
    engine = held_engine(db, clock=clock)
    row = session(engine, minutes=45)
    clock.at(300)
    state = drive_to_turn(engine, row, 15)
    used = state.time_used_s(clock())
    open_turn, asked = state.open_turn_id, state.questions_asked

    presence.presence.attach(row.id)
    presence.presence.detach(row.id, clock())
    clock.at(300 + 10 * 60)
    state = presence.back(db, row.id, clock())  # the stage re-attaches

    assert state.open_turn_id == open_turn and state.questions_asked == asked
    clock.at(300 + 10 * 60 + presence.GRACE_S)
    assert state.time_used_s(clock()) == pytest.approx(used, abs=1.0), "the drop was charged"
    assert "Welcome back" in welcome_line(state)
    state = say(engine, row, HELD)  # and the interview simply carries on
    assert state.status is SessionStatus.live
    nothing_twice(db, engine, row)


# ── 3. Provider 500s for 30 s → the session completes ───────────────────


class OutageLLM(StubLLM):
    """A provider that fails every call for the first `seconds` of the test
    clock, then recovers — 500s, not a slow day."""

    def __init__(self, clock: Clock, seconds: float, **kw):
        super().__init__([verdict(band="below", justification="failed")], **kw)
        self.clock = clock
        self.seconds = seconds

    def _down(self) -> bool:
        return self.clock.offset < self.seconds

    def structured(self, **kw):
        if self._down():
            self.structured_calls.append(kw)
            from backend_M06_Mock_Interview_Engine.llm import LLMResult

            return LLMResult(ok=False, reason="HTTP 500", job=kw["job"], model="stub")
        return super().structured(**kw)

    def stream(self, **kw):
        if self._down():
            from backend_M06_Mock_Interview_Engine.llm import LLMResult

            self.stream_calls.append(kw)
            yield LLMResult(ok=False, reason="HTTP 500", job=kw["job"], model="stub")
            return
        yield from super().stream(**kw)


@pytest.mark.gate
def test_a_provider_down_for_thirty_seconds_does_not_stop_the_session(db):
    """§12: "Provider 500s for 30 s → degradation ladder engages, session
    completes". Thirty seconds at twenty a turn is two failed model turns:
    templates and the rule strategist carry them (§6.2), the ladder reaches
    L3 and wraps up early, and when the provider is back the model is used
    again. (Three running would be panic — `test_degrade` covers that rung
    and its one-minute probe.)

    The answers have substance on purpose: "I don't know" is decided by rule
    and never reaches the model, so it would test nothing here.
    """
    from backend_M06_Mock_Interview_Engine import degrade
    from backend_M06_Mock_Interview_Engine.models import LLMCall

    clock = Clock()
    llm = OutageLLM(clock, seconds=30)
    engine = make(db, plan=rounds_plan(("r1", 8, 28.0)), m05=deep_bank(), clock=clock, llm=llm)
    row = session(engine, minutes=45)
    for step in range(80):
        state = engine.state(row.id)
        if state.is_final:
            break
        clock.at(step * 20.0)  # twenty seconds a turn: the outage spans three
        if state.retry_offer is not None:
            engine.move_on(row.id)
        elif state.open_turn_id is None:
            engine.start(row.id)
        elif state.transcript[-1].question_source == "closing":
            say(engine, row, "No, that's all.")
        else:
            say(engine, row, "Arrays keep elements contiguous, so an index is an offset.")
    state = engine.state(row.id)
    assert state.status is SessionStatus.ended

    health = [e["ok"] for e in events(engine, row, "model.health")]
    assert health[: degrade.WRAP_AFTER] == [False] * degrade.WRAP_AFTER, "no failed model turns"
    triggers = [p["plan"]["replans"][-1]["trigger"] for p in events(engine, row, "plan.changed")]
    assert "degraded" in triggers, "the ladder never engaged"
    assert True in health, "the model was not used again once it was back"
    calls = db.exec(select(LLMCall).where(LLMCall.session_id == row.id)).all()
    assert any(not c.ok for c in calls) and any(c.ok for c in calls)
    built = report.build(state, store.events_for(db, row.id), clock())
    assert built.questions
    nothing_twice(db, engine, row)


# ── 4. Refresh the browser 5 times → 5 clean resumes ────────────────────


@pytest.mark.gate
def test_five_refreshes_are_five_clean_resumes(db):
    clock = Clock()
    engine = held_engine(db, clock=clock)
    row = session(engine, minutes=45)
    state = drive_to_turn(engine, row, 5)
    open_turn = state.open_turn_id
    line = welcome_line(state)

    t = 120.0
    for count in range(1, 6):
        clock.at(t)
        presence.presence.attach(row.id)
        presence.presence.detach(row.id, clock())
        clock.at(t + 20)  # long enough to be a disconnect, not a blip
        state = presence.back(db, row.id, clock())
        t += 60
        assert state.flags.reconnect_count == count
        assert state.open_turn_id == open_turn, "a refresh moved the interview"
        assert welcome_line(state) == line
        assert (presence.suggestion(state) is not None) == (count > presence.SUGGEST_AFTER)

    assert len(events(engine, row, "connection.lost")) == 5
    nothing_twice(db, engine, row)


def test_a_quick_refresh_counts_nothing(db):
    """Under `LOST_AFTER_S` the student never left — no reconnect, no
    "your connection keeps dropping" after three F5s."""
    clock = Clock()
    engine = held_engine(db, clock=clock)
    row = session(engine, minutes=45)
    for i in range(5):
        clock.at(100 + i * 10)
        presence.presence.attach(row.id)
        presence.presence.detach(row.id, clock())
        clock.at(100 + i * 10 + 1.5)
        state = presence.back(db, row.id, clock())
    assert state.flags.reconnect_count == 0


# ── 5. Pause at turn 20, resume 4 minutes later → correct state ─────────


@pytest.mark.gate
def test_a_pause_at_turn_20_resumed_four_minutes_later(db):
    clock = Clock()
    engine = held_engine(db, clock=clock)
    row = session(engine, minutes=60)
    clock.at(600)
    state = drive_to_turn(engine, row, 20)
    used = state.time_used_s(clock())
    open_turn, asked = state.open_turn_id, state.questions_asked

    paused_at = clock()
    store.record(db, row, "session.paused", step="pause", at=paused_at)
    store.record(db, row, "session.resumed", step="resume", at=paused_at + timedelta(minutes=4))
    clock.at(600 + 4 * 60)
    state = engine.continue_session(row.id)

    assert state.status is SessionStatus.live
    assert state.open_turn_id == open_turn and state.questions_asked == asked
    assert state.time_used_s(clock()) == pytest.approx(used, abs=1.0), "the pause was charged"
    state = say(engine, row, HELD)
    assert state.status is SessionStatus.live
    nothing_twice(db, engine, row)


# ── AC-6.16: a retried request ───────────────────────────────────────────


@pytest.mark.gate
def test_a_retried_answer_is_one_answer(db):
    """The browser times out and posts the same answer again: one answer,
    one evaluation, one ledger row, one next question."""
    engine = held_engine(db)
    row = session(engine, minutes=45)
    state = drive_to_turn(engine, row, 4)
    open_turn = state.open_turn_id
    first = engine.answer(row.id, open_turn, HELD)
    again = engine.answer(row.id, open_turn, HELD)
    assert again.open_turn_id == first.open_turn_id
    assert len([e for e in events(engine, row, "answer.received")]) == len(
        {e["turn_id"] for e in events(engine, row, "answer.received")}
    )
    nothing_twice(db, engine, row)
