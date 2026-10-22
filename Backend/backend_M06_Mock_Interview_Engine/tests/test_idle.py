"""Silence — EC-6.1: "one gentle prompt, then a second, then offer to move on.
Never loop forever." In text, from the persona's patience (§6.7).

The browser says when (it can see typing; the server cannot) and the
interviewer decides what to say. The prompts are lines beside the question,
never turns: the answer box keeps posting to the question it was asked.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import report, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import IDLE_OFFER_AT, speaker
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox, LedgerOutbox
from backend_M06_Mock_Interview_Engine.state import InvalidTransition

from .day10 import Clock, events, make, rounds_plan, say, session

ROUNDS = rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0))


def opened(db, **kw):
    clock = Clock()
    engine = make(db, plan=ROUNDS, clock=clock, **kw)
    row = session(engine, minutes=45)
    say(engine, row, "I don't know")  # the warm-up; the first round's question opens
    return engine, row, clock


def quiet(engine, row, clock, n: int):
    """`n` patiences of silence on the open line, then the browser's ping."""
    state = engine.state(row.id)
    asked = state.turn(state.open_turn_id)
    patience = speaker(state).idle_after_s
    # Event times are wall-clock and the engine's clock is wall-clock plus
    # the test's offset, so moving the offset is what makes the silence.
    elapsed = (clock() - asked.at).total_seconds()
    clock.at(clock.offset + max(patience * n - elapsed, 0.0) + 1)
    return engine.idle(row.id, state.open_turn_id, n)


@pytest.mark.gate
def test_a_prompt_then_a_second_then_the_offer_and_never_a_fourth(db):
    engine, row, clock = opened(db)
    before = engine.state(row.id)
    said = speaker(before).said()

    first = quiet(engine, row, clock, 1)
    second = quiet(engine, row, clock, 2)
    third = quiet(engine, row, clock, 3)

    assert (first.idle_line, second.idle_line, third.idle_line) == (
        said.idle_first,
        said.idle_second,
        said.idle_offer,
    )
    assert third.idle_offer and IDLE_OFFER_AT == 3
    # Lines beside the question, never turns: the answer box has not moved.
    assert third.open_turn_id == before.open_turn_id
    assert len(third.transcript) == len(before.transcript)
    with pytest.raises(InvalidTransition):
        engine.idle(row.id, third.open_turn_id, 4)


def test_a_prompt_before_the_interviewers_patience_is_refused(db):
    """The floor that stops a page talking the interviewer into skipping."""
    engine, row, clock = opened(db)
    state = engine.state(row.id)
    with pytest.raises(InvalidTransition, match="Not yet"):
        engine.idle(row.id, state.open_turn_id, 1)


def test_a_retried_prompt_changes_nothing(db):
    """AC-6.16: the browser retries the same request; one prompt."""
    engine, row, clock = opened(db)
    quiet(engine, row, clock, 1)
    state = engine.state(row.id)
    again = engine.idle(row.id, state.open_turn_id, 1)
    assert len(events(engine, row, "idle.prompted")) == 1
    assert again.idle_prompts == 1


def test_an_answer_clears_the_prompts(db):
    engine, row, clock = opened(db)
    quiet(engine, row, clock, 1)
    state = say(engine, row, "I don't know")
    assert state.idle_prompts == 0 and state.idle_line is None


def test_a_prompt_for_a_question_already_answered_is_refused(db):
    engine, row, clock = opened(db)
    stale = engine.state(row.id).open_turn_id
    say(engine, row, "I don't know")
    with pytest.raises(InvalidTransition, match="already been answered"):
        engine.idle(row.id, stale, 1)


# ── taking the offer ──────────────────────────────────────────────────────


@pytest.mark.gate
def test_taking_the_offer_moves_on_and_nothing_is_scored(db):
    """The question was asked and never answered: M02 hears `asked` and no
    `answered`, M13 is sent nothing, and the notes say what happened without
    calling it a failure."""
    engine, row, clock = opened(db)
    for n in (1, 2, 3):
        quiet(engine, row, clock, n)
    left = engine.state(row.id).open_turn_id
    asked_before = engine.state(row.id).questions_asked

    state = engine.move_on(row.id)

    assert state.status is SessionStatus.live
    assert state.open_turn_id not in (None, left)
    assert state.questions_asked == asked_before + 1
    (moved,) = events(engine, row, "idle.moved_on")
    assert moved["for"] == str(left)
    assert not any(
        str(r.turn_id) == str(left)
        for r in db.exec(select(EvaluationOutbox)).all()
        if getattr(r, "turn_id", None) is not None
    )
    answered = [r for r in db.exec(select(LedgerOutbox)).all() if r.ledger_state == "answered"]
    # Nothing is `answered`: the question left after a silence had no answer,
    # and the warm-up asks for no requirement. Until 2026-10-22 this was one
    # row — the warm-up's answer, credited to the NEXT round's requirement,
    # because it was written after the step had already crossed into it.
    assert answered == []

    engine.end(row.id, "ended_by_student")
    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    entry = next(q for q in built.questions if q.moved_on)
    assert entry.scored is False and "after a pause" in entry.not_scored_reason


def test_two_silences_in_a_round_ease_the_rest_of_the_session(db):
    """§6.4's `struggling` has counted silences since day 10, and nothing
    wrote one until today — that leg of the trigger could not fire."""
    from backend_M06_Mock_Interview_Engine import replan

    engine, row, clock = opened(db)
    for _ in range(replan.STRUGGLING_SILENCES):
        for n in (1, 2, 3):
            quiet(engine, row, clock, n)
        engine.move_on(row.id)
    # Finish the round however it goes; the boundary decides.
    for _ in range(10):
        state = engine.state(row.id)
        if events(engine, row, "plan.changed") or state.open_turn_id is None:
            break
        if state.current_segment != 1:
            break
        say(engine, row, "A stack is last in, first out.")
    changes = [p["plan"]["replans"][-1] for p in events(engine, row, "plan.changed")]
    assert changes and changes[0]["trigger"] == "struggling"
    assert changes[0]["signals"]["silences"] >= replan.STRUGGLING_SILENCES


def test_at_the_closing_the_offer_wraps_up(db):
    engine = make(db, plan=rounds_plan(("r1", 1, 4.0)), clock=Clock())
    clock = engine.clock
    row = session(engine, minutes=30)
    for _ in range(6):
        state = engine.state(row.id)
        if state.transcript[-1].question_source == "closing":
            break
        say(engine, row, "I don't know")
    for n in (1, 2, 3):
        quiet(engine, row, clock, n)
    state = engine.state(row.id)
    assert state.idle_line == speaker(state).said().idle_offer_closing

    state = engine.move_on(row.id)
    assert state.status is SessionStatus.ended
    assert state.closing_questions == []


def test_nothing_to_move_on_from_is_refused(db):
    engine, row, clock = opened(db)
    with pytest.raises(InvalidTransition, match="nothing to move on from"):
        engine.move_on(row.id)


# ── over HTTP ────────────────────────────────────────────────────────────


def test_the_idle_route_takes_the_prompt_number(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    early = client.post(
        f"/v1/interviews/{sid}/idle",
        json={"question_turn_id": started["open_turn_id"], "n": 1},
        headers=as_student,
    )
    assert early.status_code == 409  # the interviewer's patience has not run out
    bad = client.post(
        f"/v1/interviews/{sid}/idle",
        json={"question_turn_id": started["open_turn_id"], "n": 4},
        headers=as_student,
    )
    assert bad.status_code == 422
    out = client.get(f"/v1/interviews/{sid}", headers=as_student).json()
    assert out["idle_prompts"] == 0 and out["idle_offered"] is False
