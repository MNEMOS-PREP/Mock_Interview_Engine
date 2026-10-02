"""§7's last three routes — repeat, flag, switch-modality.

Each one is small, and each one had the same history: named in the spec's API
surface, absent from the product. The contract gate (`test_client_contract`)
is what keeps the next one from going the same way.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.state import InvalidTransition

from .day10 import deep_bank, events, make, rounds_plan, say, session
from .stubs import DownQuestions

ROUNDS = rounds_plan(("r1", 3, 10.0))


def opened(db, **kw):
    engine = make(db, plan=ROUNDS, m05=kw.pop("m05", None) or deep_bank(), **kw)
    row = session(engine, minutes=30)
    say(engine, row, "I don't know")  # past the warm-up, onto a bank question
    return engine, row


# ── repeat ────────────────────────────────────────────────────────────────


@pytest.mark.gate
def test_repeat_is_the_question_verbatim_and_never_a_turn(db):
    """A rephrasing could change what is being asked; a turn would move the
    answer box. Neither happens."""
    engine, row = opened(db)
    before = engine.state(row.id)
    asked = before.open_question_turn()

    again = engine.repeat(row.id)
    engine.repeat(row.id)

    assert again.turn_id == asked.turn_id and again.text == asked.text
    after = engine.state(row.id)
    assert after.open_turn_id == before.open_turn_id
    assert len(after.transcript) == len(before.transcript)
    assert len(events(engine, row, "question.repeated")) == 1, "recorded once per question"


def test_nothing_open_nothing_to_repeat(db):
    engine, row = opened(db)
    engine.end(row.id, "ended_by_student")
    with pytest.raises(InvalidTransition):
        engine.repeat(row.id)


# ── flag ──────────────────────────────────────────────────────────────────


@pytest.mark.gate
def test_a_flag_reaches_m05_and_is_on_the_log(db):
    engine, row = opened(db)
    asked = engine.state(row.id).open_question_turn()
    calls = []
    engine.upstreams.m05.flag = lambda qid, reason, note, cid: (
        calls.append((qid, reason, cid)) or {}
    )

    out = engine.flag(row.id, asked.turn_id, "unclear", "")

    assert out["forwarded"] is True
    assert calls == [(asked.question_id, "unclear", row.candidate_id)]
    (flagged,) = events(engine, row, "question.flagged")
    assert flagged["question_id"] == str(asked.question_id) and flagged["forwarded"] is True


def test_with_m05_down_the_flag_is_kept_and_says_so(db):
    """Recorded here either way, and `forwarded: false` tells the student the
    item has not been excluded yet — rather than "thanks, done"."""
    engine, row = opened(db)
    asked = engine.state(row.id).open_question_turn()

    def down(*_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M05", "connection refused")

    engine.upstreams.m05.flag = down
    out = engine.flag(row.id, asked.turn_id, "wrong", "the expected answer is off")
    assert out["forwarded"] is False
    assert events(engine, row, "question.flagged")[0]["forwarded"] is False


def test_only_a_bank_question_can_be_flagged(db):
    """M05 can only exclude an item it owns; the backup set is M06's."""
    engine, row = opened(db, m05=DownQuestions())
    asked = engine.state(row.id).open_question_turn()
    with pytest.raises(InvalidTransition, match="bank"):
        engine.flag(row.id, asked.turn_id, "unclear", "")
    with pytest.raises(InvalidTransition):
        engine.flag(row.id, uuid.uuid4(), "unclear", "")


# ── switch-modality ──────────────────────────────────────────────────────


def test_switching_to_text_is_a_no_op_and_anything_else_names_its_module(db):
    engine, row = opened(db)
    before = engine.state(row.id)
    assert engine.switch_modality(row.id, "verbal").last_seq == before.last_seq
    with pytest.raises(InvalidTransition, match="M07"):
        engine.switch_modality(row.id, "coding")
    with pytest.raises(InvalidTransition, match="M08"):
        engine.switch_modality(row.id, "design")


def test_the_three_over_http(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    repeated = client.post(f"/v1/interviews/{sid}/repeat", headers=as_student)
    assert repeated.status_code == 200
    assert repeated.json()["turn_id"] == started["open_turn_id"]

    switched = client.post(
        f"/v1/interviews/{sid}/switch-modality", json={"to": "coding"}, headers=as_student
    )
    assert switched.status_code == 409 and "M07" in switched.json()["detail"]

    flagged = client.post(
        f"/v1/interviews/{sid}/flag",
        json={"question_turn_id": started["open_turn_id"], "reason": "unclear"},
        headers=as_student,
    )
    # The fixture warm-up is the backup set's, which M05 does not own.
    assert flagged.status_code in (200, 409)


# keep store imported for readers: the events above are its rows
assert store.record
