"""Practice's retry — spec §6.1's mode table, §15.4.

"Real interviews don't [let you retry]. But a 'let me try that again' in
Practice mode is genuinely valuable for learning. Allow in Practice only, mark
the retry in the data, score the first attempt."

So: offered after a graceful exit, in Practice only, once per question; the
second attempt is recorded and never scored, never sent to M05 as a θ
observation, and never counted as coverage — the first attempt is the
measurement, and the notes say which is which.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox
from backend_M06_Mock_Interview_Engine.state import InvalidTransition

from .conftest import student
from .stubs import BankQuestions, NoClaims, StubLLM, answer, verdict

FAIL = verdict(band="below", justification="failed")


def make(db, verdicts, m05=None) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=m05 or BankQuestions(), m01=NoClaims()),
        llm=StubLLM(verdicts),
        thetas=ThetaCache(),
    )


def live(engine: Engine, mode="practice"):
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=30
    )
    engine.start(row.id)
    return row


def say(engine: Engine, row, text: str):
    return answer(engine, row, text)


def evaluations(db) -> int:
    return len(db.exec(select(EvaluationOutbox)).all())


@pytest.mark.gate
def test_practice_offers_another_go_after_a_break_and_waits(db):
    engine = make(db, [FAIL])
    row = live(engine)
    asked = engine.state(row.id).questions_asked

    state = say(engine, row, "It overwrites the old value, I think.")

    assert state.retry_offer is not None
    assert state.open_turn_id is None, "nothing is asked until the student chooses"
    assert state.questions_asked == asked
    said = state.transcript[-1].text
    # The exit first, then the offer — so it reads as an option, not a verdict.
    assert said.startswith("That's fair — it's a detail people usually look up.")
    assert said.endswith("Want another go at that one, or shall we move on?")


def test_mock_moves_on_without_an_offer(db):
    engine = make(db, [FAIL])
    row = live(engine, mode="mock")
    state = say(engine, row, "It overwrites the old value, I think.")
    assert state.retry_offer is None
    assert state.open_turn_id is not None, "the next question is already asked"


@pytest.mark.gate
def test_the_retry_is_recorded_and_never_scored(db):
    """§15.4: score the first attempt. The retry owes M13 nothing, M05 nothing,
    and M02's ledger nothing — the requirement was already asked once."""
    m05 = BankQuestions()
    engine = make(db, [FAIL, verdict()], m05)
    row = live(engine)
    first_stem = engine.state(row.id).current_item["stem"]
    say(engine, row, "It overwrites the old value, I think.")
    queued = evaluations(db)
    observed = len(m05.observed)

    state = engine.retry(row.id)
    retry_turn = state.transcript[-1]
    assert retry_turn.retry is True
    assert retry_turn.text == f"Sure — take it from the top: {first_stem}"
    assert state.questions_asked == 1, "a retry is not a new question"

    say(engine, row, "It chains the entries in a list at that slot.")
    assert evaluations(db) == queued, "the retry was sent to be scored"
    assert len(m05.observed) == observed, "the retry moved θ"


def test_a_question_is_retried_once(db):
    engine = make(db, [FAIL])
    row = live(engine)
    say(engine, row, "no idea")
    engine.retry(row.id)
    state = say(engine, row, "still no idea")
    assert state.retry_offer is None, "the second attempt is the last one"
    assert state.open_turn_id is not None


def test_moving_on_asks_the_next_question_without_repeating_the_exit(db):
    engine = make(db, [FAIL, verdict()])
    row = live(engine)
    say(engine, row, "no idea")
    state = engine.move_on(row.id)
    assert state.retry_offer is None
    assert state.open_turn_id is not None
    line = state.transcript[-1].text
    assert "detail people usually look up" not in line, "the exit was said twice"
    assert state.questions_asked == 2


def test_there_is_nothing_to_retry_unless_it_was_offered(db):
    engine = make(db, [verdict()])
    row = live(engine)
    with pytest.raises(InvalidTransition):
        engine.retry(row.id)
    with pytest.raises(InvalidTransition):
        engine.move_on(row.id)


def test_the_notes_show_both_attempts_and_say_which_counted(db):
    engine = make(db, [FAIL, verdict()])
    row = live(engine)
    say(engine, row, "no idea")
    engine.retry(row.id)
    say(engine, row, "It chains the entries in a list.")
    engine.end(row.id, "ended_by_student")

    from ai_core.timeutil import utcnow

    built = report.build(engine.state(row.id), store.events_for(db, row.id), utcnow())
    first = built.questions[0]
    assert first.retried is True
    # The first attempt is "no idea", twice since 2026-10-22 (the simpler
    # question in between); the retry is the last answer, marked as one.
    retries = [e.retry for e in first.exchanges if e.role == "candidate"]
    assert retries[-1] is True and not any(retries[:-1])
    assert any("first attempt is the one that was scored" in n for n in built.notes)


def test_the_stage_is_told_a_retry_is_on_offer(client, candidate_id, upstreams):
    """Over HTTP: the session says so, and the two choices are routes."""
    from backend_M06_Mock_Interview_Engine import llm

    llm.set_llm(StubLLM([FAIL]))
    upstreams.m05 = BankQuestions()
    upstreams.m01 = NoClaims()
    headers = student(candidate_id)
    created = client.post(
        "/v1/interviews", json={"mode": "practice", "minutes": 30}, headers=headers
    ).json()
    session = client.post(f"/v1/interviews/{created['id']}/start", headers=headers).json()
    after = client.post(
        f"/v1/interviews/{created['id']}/answer",
        json={"question_turn_id": session["open_turn_id"], "text": "no idea"},
        headers=headers,
    ).json()
    # 2026-10-22: a give-up first gets one simpler question; giving up on that
    # too is the break the retry is offered after.
    assert after["retry_offered"] is False and after["open_turn_id"]
    after = client.post(
        f"/v1/interviews/{created['id']}/answer",
        json={"question_turn_id": after["open_turn_id"], "text": "no idea"},
        headers=headers,
    ).json()
    assert after["retry_offered"] is True
    moved = client.post(f"/v1/interviews/{created['id']}/move-on", headers=headers)
    assert moved.status_code == 200 and moved.json()["retry_offered"] is False
    again = client.post(f"/v1/interviews/{created['id']}/retry", headers=headers)
    assert again.status_code == 409
