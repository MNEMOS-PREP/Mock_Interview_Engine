"""Between interviews (2026-10-22): the library, revisiting a question, and
whether memory is actually used — validated, not assumed (the user's §10).

Scenario A→B, as the spec writes it: a student struggles in interview A; the
question and how it went are saved; interview B offers it back; the new
answer is judged on its own; the two attempts are compared afterwards. And
the failure modes: one student's memory reaching another, a question
remembered twice, an old attempt treated as today's ability.
"""

from __future__ import annotations

import uuid

from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, memory, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.models import QuestionAttempt, SavedQuestion

from .conftest import student
from .stubs import BankQuestions, NoClaims, StubLLM, verdict

WRONG = verdict(
    category="incorrect",
    severity="material",
    error_quote="it is O(n squared)",
    misconception="counts nested work in a single loop",
)
RIGHT = verdict(category="correct", correct_points=["one pass, constant work"])


def engine_for(db, *verdicts) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=StubLLM(list(verdicts)),
        thetas=ThetaCache(),
    )


def interview_a(db, candidate):
    """Interview A: the first question answered wrong twice, then ended."""
    engine = engine_for(db, WRONG, WRONG, RIGHT)
    row, _ = store.create_session(db, candidate_id=candidate, kind="mock", mode="mock", minutes=15)
    engine.start(row.id)
    for text in ("It is O(n squared).", "Still O(n squared), I think."):
        engine.answer(row.id, engine.state(row.id).open_turn_id, text)
    engine.end(row.id, "ended_by_student")
    return engine, row


def test_a_question_left_as_a_gap_is_saved_and_flagged_once(db):
    candidate = uuid.uuid4()
    interview_a(db, candidate)
    attempts = db.exec(
        select(QuestionAttempt).where(QuestionAttempt.candidate_id == candidate)
    ).all()
    assert [a.outcome for a in attempts if a.outcome] == ["gap:misunderstanding"]
    (saved,) = db.exec(select(SavedQuestion).where(SavedQuestion.candidate_id == candidate)).all()
    assert saved.flagged_at is not None and saved.starred_at is None
    assert saved.item["stem"], "kept as asked, so it can be practised again"


def test_star_and_unstar_keep_the_interviews_flag(db):
    candidate = uuid.uuid4()
    engine, row = interview_a(db, candidate)
    state = engine.state(row.id)
    question = state.open_question_turn() or next(
        t for t in state.transcript if t.role == "interviewer" and t.question_source
    )
    first = next(t for t in state.transcript if t.role == "interviewer" and t.question_source)
    from backend_M06_Mock_Interview_Engine.items import from_dict

    raw = next(
        e.payload["item"]
        for e in store.events_for(db, row.id)
        if e.kind == "question.asked" and e.payload.get("turn_id") == str(first.turn_id)
    )
    entry = memory.star(db, state, first, from_dict(raw), on=True)
    assert entry.starred_at is not None and entry.flagged_at is not None
    entry = memory.star(db, state, first, from_dict(raw), on=False)
    assert entry is not None and entry.starred_at is None, "still flagged, still saved"
    del question


def test_the_routes_are_one_students_own(client, candidate_id):
    """Another student's library is not theirs to read, star or delete."""
    me, stranger = student(candidate_id), student(uuid.uuid4())
    created = client.post("/v1/interviews", json={"mode": "mock", "minutes": 15}, headers=me).json()
    session = client.post(f"/v1/interviews/{created['id']}/start", headers=me).json()
    turn = session["open_turn_id"]
    starred = client.post(
        f"/v1/interviews/{created['id']}/questions/{turn}/star", json={"on": True}, headers=me
    )
    assert starred.status_code == 200 and starred.json()["starred"] is True
    mine = client.get("/v1/interviews/library", headers=me).json()
    assert len(mine) == 1 and mine[0]["starred"] is True
    assert client.get("/v1/interviews/library", headers=stranger).json() == []
    assert (
        client.post(
            f"/v1/interviews/{created['id']}/questions/{turn}/star",
            json={"on": True},
            headers=stranger,
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/v1/interviews/library/{mine[0]['id']}", headers=stranger).status_code
        == 404
    )
    assert client.delete(f"/v1/interviews/library/{mine[0]['id']}", headers=me).status_code == 204
    assert client.get("/v1/interviews/library", headers=me).json() == []


def test_the_library_filters_by_mark(client, candidate_id):
    me = student(candidate_id)
    created = client.post("/v1/interviews", json={"mode": "mock", "minutes": 15}, headers=me).json()
    session = client.post(f"/v1/interviews/{created['id']}/start", headers=me).json()
    client.post(
        f"/v1/interviews/{created['id']}/questions/{session['open_turn_id']}/star",
        json={"on": True},
        headers=me,
    )
    assert len(client.get("/v1/interviews/library?mark=starred", headers=me).json()) == 1
    assert client.get("/v1/interviews/library?mark=flagged", headers=me).json() == []


def test_scenario_a_to_b_revisit_judge_alone_compare_after(db):
    """§10's scenario, end to end."""
    candidate = uuid.uuid4()
    interview_a(db, candidate)
    (saved,) = db.exec(select(SavedQuestion).where(SavedQuestion.candidate_id == candidate)).all()

    # B: the student chooses to practise it again.
    engine = engine_for(db, RIGHT, RIGHT, RIGHT)
    row, _ = store.create_session(
        db,
        candidate_id=candidate,
        kind="mock",
        mode="mock",
        minutes=10,
        revisit=[
            {"entry_id": str(saved.id), "question_key": saved.question_key, "item": saved.item}
        ],
    )
    state = engine.start(row.id)
    assert [s.source for s in state.plan.segments] == ["revisit", "m05_bank"]
    asked = next(t for t in state.transcript if t.role == "interviewer" and t.question_source)
    assert saved.item["stem"] in asked.text
    assert "chose to practise again" in asked.text, "a repeat is announced, never silent"

    # Judged on the new answer alone: the strategist sees this interview only.
    engine.answer(row.id, state.open_turn_id, "One pass with constant work: linear.")
    judged = engine.llm.structured_calls[-1]["user"]
    assert "O(n squared)" not in judged, "the old answer never prejudges the new one"
    engine.end(row.id, "ended_by_student")

    # Compared afterwards, in the notes.
    attempts = memory.attempts_for(db, candidate, saved.question_key)
    assert len(attempts) == 2
    built = report.build(
        engine.state(row.id),
        store.events_for(db, row.id),
        engine.clock(),
        history={saved.question_key: attempts},
        marks=memory.marks(db, candidate, {saved.question_key}),
    )
    revisited = next(q for q in built.questions if q.question_key == saved.question_key)
    assert revisited.last_time is not None
    assert "held" in revisited.last_time.lower() or "better" in revisited.last_time.lower()
    assert revisited.flagged is True


def test_one_students_memory_never_reaches_another(db):
    a, b = uuid.uuid4(), uuid.uuid4()
    interview_a(db, a)
    assert memory.library(db, b) == []
    key = memory.library(db, a)[0].question_key
    assert memory.attempts_for(db, b, key) == []


def test_closing_a_question_twice_remembers_it_once(db):
    candidate = uuid.uuid4()
    engine, row = interview_a(db, candidate)
    engine.end(row.id, "left")  # a second end: a no-op, and no second memory
    attempts = db.exec(
        select(QuestionAttempt).where(QuestionAttempt.candidate_id == candidate)
    ).all()
    keys = [(a.session_id, a.question_turn_id) for a in attempts]
    assert len(keys) == len(set(keys))


def test_a_stranger_cannot_revisit_someone_elses_question(client, candidate_id, db):
    other = uuid.uuid4()
    interview_a(db, other)
    (theirs,) = db.exec(select(SavedQuestion).where(SavedQuestion.candidate_id == other)).all()
    res = client.post(
        "/v1/interviews",
        json={"mode": "mock", "minutes": 10, "revisit": [str(theirs.id)]},
        headers=student(candidate_id),
    )
    assert res.status_code == 404
