"""The closing — FR-6.17's reserved round, and FR-6.21: "record the student's
own closing questions; score them once a rubric exists".

Until day 10 the closing had `question_budget = 0`, so the interviewer said
"Anything you'd like to ask me?" and the session ended in the same breath —
a question put to the student with no way to answer it. These tests are about
the closing actually listening.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import report
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.models import (
    ArtifactOutbox,
    EvaluationOutbox,
    LedgerOutbox,
)

from .day10 import events, last_line, make, rounds_plan, say, session

ONE_ROUND = rounds_plan(("r1", 2, 7.0))


def reach_the_closing(db, **kw):
    engine = make(db, plan=ONE_ROUND, **kw)
    row = session(engine, minutes=30)
    for _ in range(6):
        state = engine.state(row.id)
        if state.transcript[-1].question_source == "closing":
            return engine, row
        say(engine, row, "I don't know")
    raise AssertionError("the plan never reached its closing")


def counts(db) -> tuple[int, int, int]:
    return (
        len(db.exec(select(EvaluationOutbox)).all()),
        len(db.exec(select(ArtifactOutbox)).all()),
        len(db.exec(select(LedgerOutbox)).all()),
    )


@pytest.mark.gate
def test_the_closing_asks_and_waits_for_an_answer(db):
    engine, row = reach_the_closing(db)
    state = engine.state(row.id)
    assert state.status is SessionStatus.live
    assert state.open_turn_id is not None, "a question with no way to answer it"
    assert last_line(state).endswith("Do you have any for me?")


def test_the_closing_is_not_one_of_our_questions(db):
    engine, row = reach_the_closing(db)
    state = engine.state(row.id)
    assert state.questions_asked == 1 + 2, "the closing was counted as a question"
    assert state.closing_asked == 1


@pytest.mark.gate
def test_a_students_questions_are_recorded_in_their_words(db):
    """FR-6.21's half that is buildable: record them. One follow-up chance,
    then the close — and M06 says it cannot speak for the real panel."""
    engine, row = reach_the_closing(db)
    state = say(engine, row, "What does a new graduate work on in the first six months?")
    assert state.status is SessionStatus.live
    assert "real panel" in last_line(state) and last_line(state).endswith("Anything else?")

    state = say(engine, row, "How is the team structured?")
    assert state.status is SessionStatus.ended
    assert state.end_reason == "plan_complete"
    assert state.closing_questions == [
        "What does a new graduate work on in the first six months?",
        "How is the team structured?",
    ]


def test_nothing_to_ask_closes_straight_away(db):
    engine, row = reach_the_closing(db)
    state = say(engine, row, "No, thanks.")
    assert state.status is SessionStatus.ended
    assert last_line(state).startswith("Okay. That's time.")
    assert state.closing_questions == []


@pytest.mark.parametrize(
    "said",
    [
        "No, that's all from me. Thank you.",
        "Nothing from my side, thanks.",
        "No questions from my side.",
        "I think I'm good, thank you so much.",
        "No, that's it for now. Thanks.",
    ],
)
def test_nothing_to_ask_however_it_is_said(said):
    """Two live runs filed "No, that's all from me. Thank you." as the
    student's question for the panel: "from me" was not on a phrase list."""
    from backend_M06_Mock_Interview_Engine.orchestration.graph import says_nothing

    assert says_nothing(said)


@pytest.mark.parametrize(
    "asked",
    [
        "No, I wanted to ask about the team.",
        "What does the team work on?",
        "Yes.",
        "How soon would I hear back",
    ],
)
def test_a_question_is_still_a_question(asked):
    from backend_M06_Mock_Interview_Engine.orchestration.graph import says_nothing

    assert not says_nothing(asked)


def test_i_dont_know_is_not_recorded_as_the_students_question(db):
    """It would appear in their notes as "your question for the interviewer"."""
    engine, row = reach_the_closing(db)
    state = say(engine, row, "I don't know")
    assert state.closing_questions == []
    assert state.status is SessionStatus.ended


def test_a_question_for_the_panel_owes_nobody_anything(db):
    """Not an answer: nothing to score, no evidence to register, no coverage."""
    engine, row = reach_the_closing(db)
    before = counts(db)
    say(engine, row, "What does a new graduate work on?")
    assert counts(db) == before


def test_abuse_at_the_closing_ends_it_politely(db):
    engine, row = reach_the_closing(db)
    state = say(engine, row, "shut up")
    assert state.status is SessionStatus.ended
    assert state.end_reason == "conduct"


def test_the_notes_list_the_students_questions(db):
    engine, row = reach_the_closing(db)
    say(engine, row, "What does a new graduate work on?")
    say(engine, row, "No, that's all.")
    from ai_core.timeutil import utcnow

    built = report.build(engine.state(row.id), [*_events(engine, row)], utcnow())
    assert built.your_questions == ["What does a new graduate work on?"]
    assert all(q.source != "closing" for q in built.questions)
    assert any("not scored" in n for n in built.notes)


def _events(engine, row):
    from backend_M06_Mock_Interview_Engine import store

    return store.events_for(engine.db, row.id)


def test_the_closing_is_recorded_as_such_in_the_log(db):
    engine, row = reach_the_closing(db)
    say(engine, row, "What does a new graduate work on?")
    recorded = events(engine, row, "closing.question")
    assert [r["text"] for r in recorded] == ["What does a new graduate work on?"]


def test_the_closing_is_unscoreable_on_its_own_terms(db):
    """A closing answer is not scored today because it has no bank item —
    but that is an accident of today. If M05 ever mints the closing as an
    item, the student's questions for the panel must still not reach M13:
    there is no rubric for a question, and scoring one under an answer's
    rubric would mark a student down for asking."""
    from backend_M06_Mock_Interview_Engine import outbox

    engine, row = reach_the_closing(db)
    say(engine, row, "What does the first month on the team look like?")
    state = engine.state(row.id)
    asked = next(
        t for t in state.transcript if t.role == "candidate" and t.question_source == "closing"
    )
    as_if_banked = asked.model_copy(
        update={"question_id": "closing-item-1", "rubric_round_type": "verbal"}
    )
    assert outbox.scoreable(state, as_if_banked, None) == (
        "Your questions for the interviewer are recorded, not scored."
    )
