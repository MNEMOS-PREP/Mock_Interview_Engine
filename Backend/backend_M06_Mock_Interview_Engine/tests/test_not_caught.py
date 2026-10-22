"""A spoken answer the recogniser could not make out — M11's FR-11.15/11.16.

What is pinned: an answer M11's recogniser was unsure of (mean confidence
under 0.4) is not judged — the interviewer asks to hear it again, in the
register's words, once a question; it owes M13 nothing and takes the ladder
no deeper; the one said again is judged as usual. A confident or typed answer
is untouched. The answer keeps how sure the recogniser was and which words
it was not, so they are never quoted back.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import BankQuestions, StubLLM, close, scored_rows, verdict
from .test_engine import make

UNSURE = {"mean_confidence": 0.22, "unsure": [[0, 9]], "model": "whisper-large-v3-turbo"}
SURE = {"mean_confidence": 0.81, "unsure": [], "model": "whisper-large-v3-turbo"}


def live(db):
    engine = make(db, llm=StubLLM([verdict(band="at")] * 20), m05=BankQuestions())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=10
    )
    engine.start(row.id)
    return engine, row


def answer(engine, row, text, asr=None):
    state = engine.state(row.id)
    return engine.answer(row.id, state.open_turn_id, text, asr=asr)


def queued(db, row) -> int:
    return sum(1 for e in store.events_for(db, row.id) if e.kind == "evaluation.queued")


def test_an_answer_nobody_could_make_out_is_asked_for_again_and_not_judged(db):
    engine, row = live(db)
    before = engine.state(row.id)
    depth = before.ladder.depth if before.ladder else 0
    state = answer(engine, row, "mumble hash mumble", asr=UNSURE)
    line = state.transcript[-1]
    asker = persona(line.speaker_id)
    assert line.probe_move == "didnt_catch"
    assert line.text == asker.said().didnt_catch
    assert queued(db, row) == 0, "words nobody could make out owe M13 nothing"
    assert (state.ladder.depth if state.ladder else 0) == depth, "no follow-up spent"
    said = state.transcript[-2]
    assert said.role == "candidate" and said.asr_confidence == 0.22
    assert said.unsure == [(0, 9)]


def test_it_asks_once_a_question_then_judges_what_it_heard(db):
    engine, row = live(db)
    answer(engine, row, "mumble hash mumble", asr=UNSURE)
    state = answer(engine, row, "mumble again", asr=UNSURE)
    assert state.transcript[-1].probe_move != "didnt_catch"
    close(engine, row)
    rows = scored_rows(db, row.id)
    assert len(rows) == 1, "the second is judged"
    assert rows[0].payload["answer_text"] == "mumble again", "the first, never made out, is not"


def test_a_confident_or_typed_answer_is_judged_as_ever(db):
    for asr in (SURE, None):
        engine, row = live(db)
        state = answer(engine, row, "It hashes the key to a bucket.", asr=asr)
        assert state.transcript[-1].probe_move != "didnt_catch"
        close(engine, row)
        assert len(scored_rows(db, row.id)) == 1


def test_the_route_takes_the_recognisers_note(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 10}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    r = client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": started["open_turn_id"], "text": "mumble", "asr": UNSURE},
        headers=as_student,
    )
    assert r.status_code == 200, r.text
    turns = r.json()["transcript"]
    assert turns[-1]["probe_move"] == "didnt_catch"
    assert turns[-2]["asr_confidence"] == 0.22
    bad = client.post(
        f"/v1/interviews/{sid}/answer",
        json={
            "question_turn_id": r.json()["open_turn_id"],
            "text": "x",
            "asr": {"mean_confidence": 3},
        },
        headers=as_student,
    )
    assert bad.status_code == 422


def test_m13_is_told_which_words_not_to_quote(db):
    """FR-11.15: the second, judged answer goes to M13 with its unsure words
    marked, so they are scored but never quoted back as the student's."""
    from backend_M06_Mock_Interview_Engine import outbox

    engine, row = live(db)
    answer(engine, row, "mumble hash mumble", asr=UNSURE)
    state = answer(engine, row, "it hashes the key", asr={**SURE, "unsure": [[3, 9]]})
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    request = outbox.evaluation_request(state, said, "n1")
    assert request["uncitable"] == [[3, 9]]
    typed = outbox.evaluation_request(
        state, [t for t in state.transcript if t.role == "interviewer"][0], "n1"
    )
    assert "uncitable" not in typed


def test_an_answer_in_hindi_is_kept_as_said_and_noted_never_penalised(db):
    """M11's FR-11.22 and EC-11.10: the recogniser names the language it heard;
    the turn keeps it, M13's own rule scores content never language, and the
    notes say so once."""
    from datetime import UTC, datetime

    from backend_M06_Mock_Interview_Engine import report as report_module

    engine, row = live(db)
    hindi = {**SURE, "language": "hindi"}
    state = answer(engine, row, "हैश मैप की को एक बकेट में रखता है", asr=hindi)
    said = [t for t in state.transcript if t.role == "candidate"][-1]
    assert said.language == "hindi"
    report = report_module.build(
        engine.state(row.id), store.events_for(db, row.id), datetime.now(UTC)
    )
    assert any("partly in Hindi" in note for note in report.notes)
    assert all("penal" not in note or "never" in note for note in report.notes)
