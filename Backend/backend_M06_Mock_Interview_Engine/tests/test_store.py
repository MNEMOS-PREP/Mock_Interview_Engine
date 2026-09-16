"""`record()` — idempotency, the seq CAS, one occupying session, the cache."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from ai_core.timeutil import utcnow
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.models import Checkpoint, SessionEvent, TurnRecord
from backend_M06_Mock_Interview_Engine.state import InvalidTransition


def _new(db, candidate=None, **kw):
    return store.create_session(
        db,
        candidate_id=candidate or uuid.uuid4(),
        kind=kw.get("kind", "mock"),
        mode=kw.get("mode", "mock"),
        minutes=kw.get("minutes", 30),
    )


def _ask(db, row, turn: int, question_id=None):
    return store.record(
        db,
        row,
        "question.asked",
        step="ask",
        turn_index=turn,
        payload={
            "turn_id": str(uuid.uuid5(row.id, f"t{turn}")),
            "turn_index": turn,
            "text": "What makes lookup constant time?",
            "question_id": str(question_id) if question_id else None,
            "concept_id": "concept:hashing",
        },
    )


def _answer(db, row, turn: int, of: int):
    return store.record(
        db,
        row,
        "answer.received",
        step="answer",
        turn_index=turn,
        payload={
            "turn_id": str(uuid.uuid5(row.id, f"t{turn}")),
            "turn_index": turn,
            "text": "Hashing puts it in a slot.",
            "question_turn_id": str(uuid.uuid5(row.id, f"t{of}")),
            "completion_reason": "submit",
        },
    )


def test_create_writes_the_first_event_and_a_checkpoint(db):
    row, state = _new(db)
    assert state.status is SessionStatus.planned
    events = store.events_for(db, row.id)
    assert [e.kind for e in events] == ["session.created"]
    checkpoint = db.get(Checkpoint, row.id)
    assert checkpoint is not None and checkpoint.last_seq == 1


@pytest.mark.gate
def test_a_retried_step_is_a_no_op(db):
    """AC-6.16: the same (session, turn, step) twice does nothing the second time."""
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    first = _ask(db, row, 0)
    again = _ask(db, row, 0)
    assert first.created is True
    assert again.created is False
    assert again.event.id == first.event.id
    asked = [e for e in store.events_for(db, row.id) if e.kind == "question.asked"]
    assert len(asked) == 1
    assert len(store.load_state(db, row.id).transcript) == 1


def test_an_impossible_transition_never_reaches_the_log(db):
    row, _ = _new(db)
    with pytest.raises(InvalidTransition):
        store.record(db, row, "session.paused", step="pause")
    assert [e.kind for e in store.events_for(db, row.id)] == ["session.created"]


def test_losing_the_seq_race_revalidates_against_the_winner(db, monkeypatch):
    """Two tabs answer the same question. The second must not become a second answer."""
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    _ask(db, row, 0)

    # Tab A reads the state, then tab B's answer lands before A writes.
    real_load = store.load_state
    raced = {"done": False}

    def load_then_race(session, session_id):
        state = real_load(session, session_id)
        if not raced["done"]:
            raced["done"] = True
            store.record(
                db,
                row,
                "answer.received",
                step="answer-tab-b",
                turn_index=1,
                payload={
                    "turn_id": str(uuid.uuid4()),
                    "turn_index": 1,
                    "text": "tab B",
                    "question_turn_id": str(uuid.uuid5(row.id, "t0")),
                },
            )
        return state

    monkeypatch.setattr(store, "load_state", load_then_race)
    with pytest.raises(InvalidTransition, match="already been answered"):
        store.record(
            db,
            row,
            "answer.received",
            step="answer-tab-a",
            turn_index=2,
            payload={
                "turn_id": str(uuid.uuid4()),
                "turn_index": 2,
                "text": "tab A",
                "question_turn_id": str(uuid.uuid5(row.id, "t0")),
            },
        )
    monkeypatch.undo()
    answers = [t for t in store.load_state(db, row.id).transcript if t.role == "candidate"]
    assert [a.text for a in answers] == ["tab B"]


@pytest.mark.gate
def test_one_occupying_session_per_student(db):
    """EC-6.13."""
    candidate = uuid.uuid4()
    first, _ = _new(db, candidate)
    store.record(db, first, "session.started", step="start")
    with pytest.raises(store.LiveSessionExists) as caught:
        _new(db, candidate)
    assert caught.value.session_id == first.id


def test_starting_a_second_planned_session_is_refused_at_the_database(db):
    """The check in create_session is a courtesy; the UNIQUE column is the rule."""
    candidate = uuid.uuid4()
    first, _ = _new(db, candidate)
    store.record(db, first, "session.started", step="start")
    # Bypass create_session's own check by inserting a planned row directly.
    from backend_M06_Mock_Interview_Engine.models import InterviewSession

    sneaky = InterviewSession(candidate_id=candidate)
    db.add(sneaky)
    db.commit()
    db.refresh(sneaky)
    store.record(
        db,
        sneaky,
        "session.created",
        step="created",
        payload={"session_id": str(sneaky.id), "candidate_id": str(candidate)},
    )
    with pytest.raises(store.LiveSessionExists):
        store.record(db, sneaky, "session.started", step="start")
    assert store.load_state(db, sneaky.id).status is SessionStatus.planned


def test_a_planned_session_is_superseded_not_blocking(db):
    candidate = uuid.uuid4()
    first, _ = _new(db, candidate)
    second, _ = _new(db, candidate)
    assert store.load_state(db, first.id).status is SessionStatus.aborted
    assert store.load_state(db, first.id).end_reason == "superseded"
    assert store.load_state(db, second.id).status is SessionStatus.planned


def test_ending_frees_the_slot(db):
    candidate = uuid.uuid4()
    first, _ = _new(db, candidate)
    store.record(db, first, "session.started", step="start")
    store.record(db, first, "session.ended", step="end", payload={"reason": "completed"})
    assert store.occupying_session(db, candidate) is None
    _new(db, candidate)


def test_a_stale_checkpoint_is_brought_forward_from_the_log(db):
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    checkpoint = db.get(Checkpoint, row.id)
    stale_seq = checkpoint.last_seq
    # Append an event whose checkpoint write "fails".
    event = SessionEvent(
        session_id=row.id, seq=stale_seq + 1, step="pause", kind="session.paused", at=utcnow()
    )
    db.add(event)
    db.commit()
    state = store.load_state(db, row.id)
    assert state.status is SessionStatus.paused
    assert state.last_seq == stale_seq + 1


def test_an_unreadable_checkpoint_is_a_cache_miss(db):
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    checkpoint = db.get(Checkpoint, row.id)
    checkpoint.state_json = {"session_id": "not-a-uuid"}
    db.add(checkpoint)
    db.commit()
    assert store.load_state(db, row.id).status is SessionStatus.live


def test_the_checkpoint_never_moves_backwards(db):
    row, _ = _new(db)
    live = store.record(db, row, "session.started", step="start").state
    older = live.model_copy(update={"last_seq": 1})
    assert store.write_checkpoint(db, older) is False
    assert db.get(Checkpoint, row.id).last_seq == live.last_seq


def test_a_failed_checkpoint_write_loses_no_event(db, monkeypatch):
    """§10: checkpoint failure → continue; the log is intact."""
    row, _ = _new(db)

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "write_checkpoint", boom)
    recorded = store.record(db, row, "session.started", step="start")
    monkeypatch.undo()
    assert recorded.created is True
    # The event committed before the checkpoint was attempted, and the stale
    # checkpoint is brought forward from the log on the next read.
    assert db.get(Checkpoint, row.id).last_seq == 1
    assert store.load_state(db, row.id).status is SessionStatus.live


def test_replay_matches_the_checkpointed_state(db):
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    _ask(db, row, 0, uuid.uuid4())
    _answer(db, row, 1, of=0)
    assert store.replay(db, row.id).model_dump(mode="json") == store.load_state(
        db, row.id
    ).model_dump(mode="json")


def test_turns_are_projected_with_the_bytes_that_were_stored(db):
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    _ask(db, row, 0, uuid.uuid4())
    _answer(db, row, 1, of=0)
    turns = db.exec(
        select(TurnRecord).where(TurnRecord.session_id == row.id).order_by(TurnRecord.turn_index)
    ).all()
    assert [t.role for t in turns] == ["interviewer", "candidate"]
    assert turns[1].text_sha256 == store.sha256("Hashing puts it in a slot.")
    assert turns[1].completion_reason == "submit"


def test_seen_items_come_from_what_was_actually_asked(db):
    candidate = uuid.uuid4()
    row, _ = _new(db, candidate)
    store.record(db, row, "session.started", step="start")
    qid = uuid.uuid4()
    _ask(db, row, 0, qid)
    assert store.seen_item_ids(db, candidate) == {qid}
    assert store.seen_item_ids(db, candidate, now=utcnow() + timedelta(days=91)) == set()
    assert store.seen_item_ids(db, uuid.uuid4()) == set()


@pytest.mark.gate
def test_no_theta_in_a_persisted_checkpoint(db):
    """AC-6.13, on real bytes: a checkpoint after a scripted session has no θ key."""
    row, _ = _new(db)
    store.record(db, row, "session.started", step="start")
    for i in range(0, 30, 2):
        _ask(db, row, i, uuid.uuid4())
        _answer(db, row, i + 1, of=i)
        store.record(
            db,
            row,
            "probe.decided",
            step="decide",
            turn_index=i + 1,
            payload={"move": {"kind": "move_on"}, "success": True},
        )
    raw = json.dumps(db.get(Checkpoint, row.id).state_json).lower()

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    assert not [k for k in keys(json.loads(raw)) if "theta" in k]
