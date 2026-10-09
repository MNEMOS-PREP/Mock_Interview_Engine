"""The lines the room may say next, made ahead (2026-10-09).

The user, after a mock: gaps in speech and awkward pauses, worst when a line
was long. On this laptop M11 makes speech barely faster than it is spoken, so
a line made when it is needed keeps the student waiting. `Engine.upcoming`
names what is likely to be said next — the questions M05 would choose now,
after the lead-in they will follow, and the panel's stock phrases — so the
room can have M11 make them while the student answers.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import FixtureEvaluator
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.engine import seated
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import BankQuestions, DownQuestions, NoClaims, StubLLM, verdict
from .test_engine import make, say
from .test_tracks import items_for


def create(engine, **choices):
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15, **choices
    )
    return row


def a_track_engine(db, **kw):
    return make(
        db,
        llm=StubLLM([verdict()] * 40),
        m05=BankQuestions(items=items_for("dsa_verbal")),
        m13=FixtureEvaluator(round_types=("dsa_verbal",)),
        m01=NoClaims(),
        **kw,
    )


def questions(lines):
    return [line for line in lines if line["kind"] == "question"]


def test_the_next_questions_are_named_after_the_lead_in_they_follow(db):
    engine = a_track_engine(db)
    row = create(engine, track="dsa_verbal")
    state = engine.plan(row.id)
    lines = engine.upcoming(row.id)

    asked = questions(lines)
    assert 1 <= len(asked) <= 3, "M05's choice and its alternatives"
    asker = persona(state.plan.segments[0].persona_id)
    bank = {item["stem"] for item in items_for("dsa_verbal")}
    for line in asked:
        lead, stem = line["parts"]
        assert lead == {"speaker_id": asker.id, "text": asker.said().next_question_lead}
        assert stem["speaker_id"] == asker.id and stem["text"] in bank


def test_the_question_asked_is_one_of_those_named(db):
    """Made ahead only helps if it is what is said: the real selection asks
    M05 the same thing `upcoming` asked."""
    engine = a_track_engine(db)
    row = create(engine, track="dsa_verbal")
    engine.plan(row.id)
    named = {line["parts"][1]["text"] for line in questions(engine.upcoming(row.id))}
    state = engine.start(row.id)
    first = next(t for t in state.transcript if t.role == "interviewer" and t.question_id)
    assert first.question_text in named
    named = {line["parts"][1]["text"] for line in questions(engine.upcoming(row.id))}
    state = say(engine, row, "A hash map hashes the key to a bucket and compares keys there.")
    second = [t for t in state.transcript if t.role == "interviewer" and t.question_id][-1]
    if second.question_id != first.question_id:  # not a follow-up rung
        assert second.question_text in named


def test_the_panel_stock_phrases_come_with_names_and_topics_in_place(db):
    engine = a_track_engine(db)
    row = create(engine)
    state = engine.plan(row.id)
    lines = [line for line in engine.upcoming(row.id) if line["kind"] == "phrase"]
    panel = seated(state)
    for who in panel:
        theirs = [
            line["parts"][0]["text"] for line in lines if line["parts"][0]["speaker_id"] == who.id
        ]
        assert who.said().next_question_lead in theirs
        for other in panel:
            if other.id != who.id:
                assert who.said().hand_over.format(name=other.name) in theirs
    assert all("{" not in line["parts"][0]["text"] for line in lines)
    texts = [(line["parts"][0]["speaker_id"], line["parts"][0]["text"]) for line in lines]
    assert len(texts) == len(set(texts)), "each phrase once"


def test_without_m05_the_phrases_are_still_made(db):
    engine = make(db, m05=DownQuestions(), m01=NoClaims())
    row = create(engine)
    engine.plan(row.id)
    lines = engine.upcoming(row.id)
    assert lines and not questions(lines)


def test_a_finished_interview_has_nothing_to_make(db):
    engine = a_track_engine(db)
    row = create(engine, track="dsa_verbal")
    engine.plan(row.id)
    engine.end(row.id, "ended_by_student")
    assert engine.state(row.id).status is not SessionStatus.live
    assert engine.upcoming(row.id) == []


def test_the_route_answers_for_the_session(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 15}, headers=as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/plan", headers=as_student)
    body = client.get(f"/v1/interviews/{sid}/upcoming", headers=as_student).json()
    assert isinstance(body["lines"], list) and body["lines"]
    assert (
        client.get(f"/v1/interviews/{uuid.uuid4()}/upcoming", headers=as_student).status_code == 404
    )


def test_every_interviewers_stock_phrases_are_listed_for_making_ahead(client, as_student):
    body = client.get("/v1/interviews/phrases", headers=as_student).json()["personas"]
    assert len(body) >= 39
    professor = persona("professor").said()
    assert professor.next_question_lead in body["professor"]
    assert all("{" not in text for texts in body.values() for text in texts)
