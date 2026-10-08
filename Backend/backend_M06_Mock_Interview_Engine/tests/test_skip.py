"""Skipping a question (2026-10-07).

The student's rule: "if a candidate skips a question another question should
come as replacement — 2 skips of same question number means points go down".
So a skip at a question's opening is free the first time at that number, and
the replacement is asked AS that number; skipping the replacement too leaves
it, counted as not answered, and the session's estimate for its concept goes
down. A skip after answering, with a follow-up open, is moving on.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.phrasebook import LINES as REGISTERS
from backend_M06_Mock_Interview_Engine.report import SKIPPED_LEFT, SKIPPED_REPLACED
from backend_M06_Mock_Interview_Engine.state import InvalidTransition

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make, say


def live(db, *, mode="mock", minutes=30):
    bank = BankQuestions()
    engine = make(db, llm=StubLLM([verdict()] * 60), m05=bank, m01=NoClaims())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=minutes
    )
    engine.start(row.id)
    return engine, row, bank


def questions(state):
    return [t for t in state.transcript if t.role == "interviewer" and t.question_id]


def skip(engine, row):
    state = engine.state(row.id)
    return engine.skip(row.id, state.open_turn_id)


def test_the_first_skip_brings_a_different_question_at_the_same_number(db):
    engine, row, bank = live(db)
    first = engine.state(row.id)
    assert first.questions_asked == 1
    skipped = questions(first)[-1]

    state = skip(engine, row)
    replacement = questions(state)[-1]
    assert replacement.question_id != skipped.question_id, "a different question"
    assert state.questions_asked == 1, "asked as the same number"
    assert state.questions_in_segment(skipped.segment_index) == 1, "the skip costs nothing"
    assert state.turn(skipped.turn_id).replaced is True
    assert bank.observed == [], "and nothing about the student moved"


def test_the_replacement_is_introduced_as_a_different_one_not_the_next(db):
    engine, row, _ = live(db)
    state = skip(engine, row)
    line = questions(state)[-1].text
    leads = {lines.skip_lead for lines in REGISTERS.values()}
    assert any(lead in line for lead in leads), line
    nexts = {lines.next_question_lead for lines in REGISTERS.values()}
    assert not any(n in line for n in nexts), "'next' would say the skipped one was used up"


def test_a_second_skip_at_the_same_number_counts_and_lowers_the_estimate(db):
    engine, row, bank = live(db)
    skip(engine, row)  # the first: replaced
    replacement = questions(engine.state(row.id))[-1]

    state = skip(engine, row)  # the second, at the same number: left
    assert state.turn(replacement.turn_id).skipped is True
    assert state.turn(replacement.turn_id).replaced is False
    assert state.questions_asked == 2, "the next question is the next number"
    assert state.skips_left == 1
    (observed,) = bank.observed
    assert observed[1] == replacement.concept_id
    assert observed[2]["band"] == "below", "points go down"


def test_the_second_skip_says_the_question_is_left_before_the_next(db):
    engine, row, _ = live(db)
    skip(engine, row)
    state = skip(engine, row)
    line = questions(state)[-1].text
    assert any(lines.skip_leave in line for lines in REGISTERS.values()), line


def test_each_number_gets_its_own_free_skip(db):
    """A skip at question 2 is a first skip there, whatever happened at 1."""
    engine, row, bank = live(db)
    skip(engine, row)
    skip(engine, row)  # question 1 left
    state = skip(engine, row)  # question 2's first skip
    assert state.questions_asked == 2
    assert len(bank.observed) == 1, "only the question skipped twice counted"


def test_skipping_a_follow_up_moves_on_with_nothing_against_it(db):
    engine, row, bank = live(db)
    state = say(engine, row, "It hashes the key to a bucket and reads that bucket.")
    assert state.ladder is not None and state.ladder.depth > 0, "a follow-up is open"
    asked_before = state.questions_asked
    observed_before = len(bank.observed)

    state = skip(engine, row)
    assert state.questions_asked == asked_before + 1, "the answered question counts"
    assert len(bank.observed) == observed_before, "no penalty for a follow-up"


def test_a_stale_skip_is_refused_rather_than_skipping_the_replacement(db):
    engine, row, _ = live(db)
    stale = engine.state(row.id).open_turn_id
    engine.skip(row.id, stale)
    with pytest.raises(InvalidTransition, match="moved on"):
        engine.skip(row.id, stale)


def test_the_closing_cannot_be_skipped(db):
    engine, row, _ = live(db, minutes=8)
    for _ in range(20):
        state = engine.state(row.id)
        open_turn = state.turn(state.open_turn_id) if state.open_turn_id else None
        if open_turn is not None and open_turn.question_source == "closing":
            break
        say(engine, row, "I don't know")
    with pytest.raises(InvalidTransition, match="your questions"):
        skip(engine, row)


def test_the_notes_say_what_each_skip_did(client, as_student):
    from backend_M06_Mock_Interview_Engine import adapters

    adapters.set_upstreams(adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()))
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    state = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    for _ in range(2):
        state = client.post(
            f"/v1/interviews/{sid}/skip",
            json={"question_turn_id": state["open_turn_id"]},
            headers=as_student,
        ).json()
    stale = client.post(
        f"/v1/interviews/{sid}/skip",
        json={"question_turn_id": str(uuid.uuid4())},
        headers=as_student,
    )
    assert stale.status_code == 409
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student).json()

    first, second = report["questions"][:2]
    assert (first["skipped"], first["not_scored_reason"]) == ("replaced", SKIPPED_REPLACED)
    assert (second["skipped"], second["not_scored_reason"]) == ("left", SKIPPED_LEFT)
    assert any("You skipped 2 questions" in note for note in report["notes"])


def test_a_question_skipped_once_is_not_offered_in_the_next_interview(db):
    """2026-10-08: "if the same question is asked in every interview the
    candidate gets irritated". A skipped question is a hard exclusion for
    months, not freshness M05 may relax when the bank runs thin."""
    engine, row, bank = live(db)
    skipped = questions(engine.state(row.id))[-1].question_id
    skip(engine, row)
    engine.end(row.id, "ended_by_student")

    later, _ = store.create_session(
        engine.db, candidate_id=row.candidate_id, kind="mock", mode="mock", minutes=30
    )
    bank.requests.clear()
    engine.start(later.id)
    selections = [r for r in bank.requests if "seen_item_ids" in r]  # not the plan's probe
    assert selections, "the next interview asked M05 for a question"
    assert all(str(skipped) in r["seen_item_ids"] for r in selections)
    assert skipped not in {t.question_id for t in questions(engine.state(later.id))}
