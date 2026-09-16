"""The fold — spec §6.8. Pure, deterministic, strict."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from backend_M06_Mock_Interview_Engine.contracts import SessionFlags, SessionStatus
from backend_M06_Mock_Interview_Engine.state import (
    EVENT_KINDS,
    InvalidTransition,
    SessionState,
    UnknownEvent,
    apply,
    fold,
)

T0 = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


@dataclass
class Ev:
    kind: str
    payload: dict
    at: datetime
    seq: int


def _log(*steps: tuple[str, dict, int]) -> list[Ev]:
    """(kind, payload, seconds after T0) → events with seq in order."""
    return [
        Ev(kind, payload, T0 + timedelta(seconds=s), i + 1)
        for i, (kind, payload, s) in enumerate(steps)
    ]


SID = uuid.uuid4()
CID = uuid.uuid4()
CREATED = (
    "session.created",
    {"session_id": str(SID), "candidate_id": str(CID), "requested_minutes": 30},
    0,
)


def _asked(turn: int, qid: uuid.UUID | None = None, **extra) -> dict:
    return {
        "turn_id": str(uuid.uuid5(SID, f"q{turn}")),
        "turn_index": turn,
        "text": f"question {turn}",
        "question_id": str(qid) if qid else None,
        "concept_id": "concept:hashing",
        **extra,
    }


def _answered(turn: int, question_turn: int) -> dict:
    return {
        "turn_id": str(uuid.uuid5(SID, f"a{turn}")),
        "turn_index": turn,
        "text": f"answer {turn}",
        "question_turn_id": str(uuid.uuid5(SID, f"q{question_turn}")),
    }


def test_fold_is_deterministic():
    events = _log(
        CREATED,
        ("session.started", {}, 5),
        ("question.asked", _asked(0, uuid.uuid4()), 6),
        ("answer.received", _answered(1, 0), 40),
        ("probe.decided", {"move": {"kind": "rung", "depth": 1}, "success": True}, 41),
    )
    first = fold(events).model_dump(mode="json")
    second = fold(list(reversed(events))).model_dump(mode="json")
    assert first == second


def test_every_event_kind_is_handled():
    assert "session.created" in EVENT_KINDS
    with pytest.raises(UnknownEvent):
        fold(_log(CREATED, ("session.teleported", {}, 1)))


def test_created_must_come_first_and_only_once():
    with pytest.raises(InvalidTransition):
        fold(_log(("session.started", {}, 0)))
    with pytest.raises(InvalidTransition):
        fold(_log(CREATED, CREATED))


def test_apply_never_mutates_its_input():
    base = fold(_log(CREATED))
    before = base.model_dump(mode="json")
    apply(base, "session.started", {}, T0, 2)
    assert base.model_dump(mode="json") == before


def test_nothing_happens_after_the_end():
    events = _log(CREATED, ("session.started", {}, 1), ("session.ended", {"reason": "x"}, 2))
    state = fold(events)
    assert state.status is SessionStatus.ended
    with pytest.raises(InvalidTransition):
        apply(state, "question.asked", _asked(0), T0, 4)
    with pytest.raises(InvalidTransition):
        apply(state, "session.ended", {}, T0, 4)


def test_pause_stops_the_clock():
    events = _log(
        CREATED,
        ("session.started", {}, 0),
        ("session.paused", {}, 60),
        ("session.resumed", {}, 60 + 240),
    )
    state = fold(events)
    now = T0 + timedelta(seconds=60 + 240 + 30)
    assert state.time_used_s(now) == pytest.approx(90)
    assert state.flags.pause_used is True
    assert state.time_remaining_s(now) == pytest.approx(30 * 60 - 90)


def test_an_answer_cannot_arrive_while_paused():
    state = fold(_log(CREATED, ("session.started", {}, 0), ("session.paused", {}, 5)))
    with pytest.raises(InvalidTransition):
        apply(state, "answer.received", _answered(1, 0), T0, 4)


def test_a_new_question_opens_a_new_ladder_and_a_rung_does_not():
    events = _log(
        CREATED,
        ("session.started", {}, 0),
        ("question.asked", _asked(0, uuid.uuid4()), 1),
        ("answer.received", _answered(1, 0), 2),
        ("probe.decided", {"move": {"kind": "rung", "depth": 1}, "success": True}, 3),
        ("question.asked", _asked(2, probe_move="rung", probe_depth=1), 4),
    )
    state = fold(events)
    assert state.ladder is not None
    assert state.ladder.depth == 1
    assert state.ladder.moves == ["rung"]


def test_break_depth_keeps_the_shallowest_break_per_concept():
    events = _log(
        CREATED,
        ("session.started", {}, 0),
        ("question.asked", _asked(0, uuid.uuid4()), 1),
        ("probe.decided", {"move": {"kind": "move_on", "graceful": True}, "break_depth": 3}, 2),
        ("question.asked", _asked(1, uuid.uuid4()), 3),
        ("probe.decided", {"move": {"kind": "move_on", "graceful": True}, "break_depth": 1}, 4),
        ("question.asked", _asked(2, uuid.uuid4()), 5),
        ("probe.decided", {"move": {"kind": "move_on", "graceful": True}, "break_depth": 2}, 6),
    )
    assert fold(events).break_depths == {"concept:hashing": 1}


def test_the_answer_inherits_the_question_it_answers():
    qid = uuid.uuid4()
    events = _log(
        CREATED,
        ("session.started", {}, 0),
        (
            "question.asked",
            _asked(0, qid, rubric_round_type="dsa_verbal", question_source="m05_bank"),
            1,
        ),
        ("hint.given", {"level": 1}, 2),
        ("answer.received", _answered(1, 0), 3),
    )
    answer = fold(events).transcript[-1]
    assert answer.role == "candidate"
    assert answer.question_id == qid
    assert answer.rubric_round_type == "dsa_verbal"
    assert answer.hint_level_used == 1


def test_naive_timestamps_from_sqlite_fold_cleanly():
    naive = [
        Ev(e.kind, e.payload, e.at.replace(tzinfo=None), e.seq)
        for e in _log(CREATED, ("session.started", {}, 0))
    ]
    state = fold(naive)
    assert state.time_used_s(T0 + timedelta(seconds=10)) == pytest.approx(10)


@pytest.mark.gate
def test_no_ability_estimate_can_live_in_session_state():
    """AC-6.13, at the schema: nothing that is checkpointed has a θ field (FR-6.25)."""

    def fields(model) -> set[str]:
        return {name.lower() for name in model.model_fields}

    for model in (SessionState, SessionFlags):
        leaked = {f for f in fields(model) if "theta" in f or "ability" in f}
        assert not leaked, f"{model.__name__} can hold an ability estimate: {leaked}"
