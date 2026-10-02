"""Pacing — FR-6.17, spec §6.9, §2.3, EC-6.9, and FR-6.9's hard clock.

"Time budgeting is a scheduling problem … the supervisor must continuously
re-allocate remaining time, and must always reserve the closing round." These
tests move the clock and watch what the session does about it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import pacing
from backend_M06_Mock_Interview_Engine.contracts import DEPTH_CAP, SessionStatus
from backend_M06_Mock_Interview_Engine.engine import ladder_config
from backend_M06_Mock_Interview_Engine.models import LedgerOutbox

from .day10 import Clock, deep_bank, events, last_line, make, rounds_plan, say, session
from .stubs import verdict

THREE_ROUNDS = rounds_plan(("r1", 4, 8.0), ("r2", 2, 4.0), ("r3", 2, 4.0))


# ── 70%: the pace check (§2.3) ────────────────────────────────────────────


@pytest.mark.gate
def test_at_seventy_percent_a_mock_narrows_and_says_so(db):
    """More planned than time: keep what fits by M02's priority, drop the rest,
    and say it out loud with the next question — "we have about N minutes
    left, so I'll focus on…". Real interviewers do this; it turns a rushed
    ending into a managed one."""
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)

    clock.at(0.72 * 30 * 60)
    state = say(engine, row, "I don't know")

    assert 70 in state.time_warnings
    change = events(engine, row, "plan.changed")
    assert change, "the plan was not narrowed"
    assert change[-1]["plan"]["replans"][-1]["trigger"] == "time_overrun"
    dropped = [s for s in state.plan.segments if s.dropped_reason]
    assert dropped and all("70%" in s.dropped_reason for s in dropped)
    assert "so I'll focus on" in last_line(state)


def test_the_dropped_requirements_are_owed_to_m02_as_skipped(db):
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)
    clock.at(0.72 * 30 * 60)
    state = say(engine, row, "I don't know")
    dropped = {r for s in state.plan.segments if s.dropped_reason for r in s.requirement_ids}
    skipped = {
        r.requirement_id
        for r in db.exec(select(LedgerOutbox).where(LedgerOutbox.ledger_state == "skipped")).all()
    }
    assert dropped and dropped <= skipped


def test_practice_offers_and_forces_nothing(db):
    """§6.1's table: in Practice the pace check says how long is left and
    changes nothing."""
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, mode="practice", minutes=30)
    clock.at(0.72 * 30 * 60)
    state = say(engine, row, "I don't know")
    # Practice offers a retry after a break; take the next question instead.
    if state.retry_offer is not None:
        state = engine.move_on(row.id)
    assert not events(engine, row, "plan.changed")
    assert all(s.dropped_reason is None for s in state.plan.segments)
    assert "minutes left" in last_line(state)


def test_each_checkpoint_is_announced_once(db):
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)
    clock.at(0.72 * 30 * 60)
    say(engine, row, "I don't know")
    say(engine, row, "I don't know")
    assert [w["at"] for w in events(engine, row, "time.warning")] == [70]


# ── 90%: the closing is reserved ─────────────────────────────────────────


@pytest.mark.gate
def test_at_ninety_percent_the_closing_takes_over(db):
    """FR-6.17: "must always reserve the closing round". Whatever is left of
    the plan gives way, and the student is asked for their questions."""
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)

    clock.at(0.91 * 30 * 60)
    state = say(engine, row, "I don't know")

    assert state.status is SessionStatus.live
    assert state.transcript[-1].question_source == "closing"
    assert "close to time" in last_line(state).lower()
    # Not the 70% focus line: the closing superseded it.
    assert "focus on" not in last_line(state)
    assert {w["at"] for w in events(engine, row, "time.warning")} == {70, 90}
    # Nor the 70% narrowing behind it. Unsaid, it would still be in the
    # report — "at the 70% mark I left out…" about a session that went
    # straight to its closing — and it would spend one of the two re-plans.
    assert not events(engine, row, "plan.changed")


def test_the_rounds_the_closing_skipped_are_owed_to_m02(db):
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)
    clock.at(0.91 * 30 * 60)
    say(engine, row, "I don't know")
    skipped = {
        r.requirement_id
        for r in db.exec(select(LedgerOutbox).where(LedgerOutbox.ledger_state == "skipped")).all()
    }
    assert {"r1", "r2", "r3"} <= skipped


# ── a round's own clock (EC-6.9, FR-6.9) ─────────────────────────────────


def _two_rounds_then_answer(db, mode: str, seconds_into_round: float):
    clock = Clock()
    engine = make(db, plan=rounds_plan(("r1", 4, 14.0), ("r2", 2, 7.0)), clock=clock)
    row = session(engine, mode=mode, minutes=45)
    say(engine, row, "I don't know")  # the warm-up; the first round opens now
    state = engine.state(row.id)
    first_round = state.current_segment
    started = state.segment_started_used_s
    clock.at(started + seconds_into_round)
    state = say(engine, row, "I don't know")
    if state.retry_offer is not None:
        state = engine.move_on(row.id)
    return state, first_round


@pytest.mark.gate
def test_final_boss_has_a_hard_clock(db):
    """FR-6.9, EC-6.9: 0% overrun. A 14-minute round is over at 14 minutes and
    one second, at the next question boundary — never mid-ladder."""
    state, first_round = _two_rounds_then_answer(db, "final_boss", 14 * 60 + 30)
    assert state.current_segment != first_round


def test_a_mock_round_may_run_a_quarter_over(db):
    """The same moment in a mock is inside its 25% allowance."""
    state, first_round = _two_rounds_then_answer(db, "mock", 14 * 60 + 30)
    assert state.current_segment == first_round


def test_the_round_clock_starts_at_the_crossing(db):
    clock = Clock()
    engine = make(db, plan=rounds_plan(("r1", 4, 14.0)), clock=clock)
    row = session(engine, minutes=45)
    clock.at(100)
    say(engine, row, "I don't know")
    state = engine.state(row.id)
    assert state.segment_started_used_s >= 99


# ── pure arithmetic ───────────────────────────────────────────────────────


def test_the_reading_holds_back_the_closing(db):
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)
    reading = pacing.read(engine.state(row.id), clock())
    closing = next(s for s in engine.state(row.id).plan.segments if s.kind == "closing")
    assert reading.closing_reserve_s == closing.minutes * 60
    assert reading.time_for_questions_s == pytest.approx(
        reading.remaining_s - reading.closing_reserve_s
    )


def test_ahead_of_schedule_goes_one_deeper_from_then_on(db):
    """§6.9: "if ahead_of_schedule: allow one extra depth level" — for the
    rest of the session, not one round: the 70% check runs before the step's
    crossing, so a per-round grant went to the round being left.

    Practice, because its interviewer stops at two follow-ups. The first
    version of this test used a mock's, which is already at the cap of five,
    so "+1, capped" equalled the base and the test could not fail."""
    engine = make(db, plan=THREE_ROUNDS)
    row = session(engine, mode="practice", minutes=30)
    state = engine.state(row.id)
    base = ladder_config(state).max_depth
    assert base < DEPTH_CAP, "a persona at the cap cannot show the extra rung"

    ahead = state.model_copy(update={"extra_depth_segment": state.current_segment})
    assert ladder_config(ahead).max_depth == base + 1
    later = ahead.model_copy(update={"current_segment": state.current_segment + 1})
    assert (
        ladder_config(later).max_depth
        == ladder_config(later.model_copy(update={"extra_depth_segment": None})).max_depth + 1
    )


def test_the_70_percent_check_finds_a_session_ahead(db):
    """The whole path: questions answered faster than the plan priced them,
    then the 70% mark inside a round — and that round has one more rung.

    The clock moves round by round, each inside its own clock (EC-6.9), so
    that what the test sees is the pace check and not a round timing out.
    """
    clock = Clock()
    engine = make(
        db,
        plan=rounds_plan(("r1", 4, 16.0), ("r2", 4, 16.0), ("r3", 4, 16.0)),
        verdicts=[verdict()],
        m05=deep_bank(),
        clock=clock,
    )
    row = session(engine, mode="practice", minutes=60)
    held = "Arrays store it contiguously, so the index is an offset."
    # Seconds into the session at which each round is worked through: every
    # round ends inside 16 minutes x 1.25, and none of it reaches 70%.
    at = {1: 1150.0, 2: 2300.0, 3: 2300.0}

    state = engine.state(row.id)
    for _ in range(80):
        if state.questions_asked >= 12 or state.open_turn_id is None:
            break
        clock.at(at.get(state.current_segment, 0.0))
        state = say(engine, row, held)
    assert state.questions_asked == 12 and state.status is SessionStatus.live
    third_round = state.current_segment
    base = ladder_config(state).max_depth

    clock.at(0.71 * 60 * 60)
    reading = pacing.read(state, clock())
    assert reading.ahead_by >= 1 and not reading.coverage_debt, "the scenario is not ahead"
    for _ in range(10):
        if events(engine, row, "time.warning") or state.open_turn_id is None:
            break
        state = say(engine, row, held)

    assert events(engine, row, "time.warning") == [{"at": 70, "extra_depth": True}]
    assert state.current_segment == third_round, "the round ended instead"
    assert ladder_config(state).max_depth == base + 1


def test_neither_the_warm_up_nor_the_closing_is_over_its_own_clock(db):
    """The warm-up is one question by construction and the closing is the
    student's: an hour late, neither is "over time" — and a round is."""
    clock = Clock()
    engine = make(db, plan=THREE_ROUNDS, clock=clock)
    row = session(engine, minutes=30)
    state = engine.state(row.id)
    late = clock() + timedelta(hours=1)
    by_kind = {s.kind: s for s in state.plan.segments}
    assert not pacing.over_time(state, by_kind["warmup"], late, 0.0)
    assert not pacing.over_time(state, by_kind["closing"], late, 0.0)
    a_round = next(s for s in state.plan.segments if s.requirement_ids)
    assert pacing.over_time(state, a_round, late, 0.0)


# ── §6.1 steps 3–4: the CAT starts from what M04 knows ───────────────────


@pytest.mark.gate
def test_m05_is_seeded_from_m04s_posterior_before_the_plan_probes_it(db):
    """Until 2026-09-30 nothing fetched M04's posterior, so every session's
    CAT started at the prior — adaptive from a standing start, every time."""
    from backend_M06_Mock_Interview_Engine.adapters.fixtures import FixtureMemory

    from .stubs import BankQuestions

    m05 = BankQuestions()
    memory = FixtureMemory(posterior={"concept:stacks": 0.9, "concept:unrelated": -1.0})
    engine = make(db, plan=THREE_ROUNDS, m05=m05, memory=memory)
    session(engine, minutes=30)
    # Only what the posting asks about, as M04 measured it — and before the
    # plan's availability probe, which is the first thing to ask M05 for an item.
    (seeded,) = m05.seeded.values()
    assert seeded == {"concept:stacks": 0.9}
    assert m05.requests, "nothing asked M05 for an item"
    assert m05.requests[0]["theta_provisional"].get("concept:stacks") == 0.9
