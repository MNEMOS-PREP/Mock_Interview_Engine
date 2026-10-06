"""What the student heard of a line they cut in on — M11's FR-11.9.

What is pinned: the line of record stays whole and the turn carries the cut;
the part being heard and how far through it come from the room, once per
line; the heard portion snaps back to a whole word; the interviewer model
reads the line as far as it was heard, marked as cut off; only an
interviewer's line can be cut, and only the session's own student says so.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import heard, store
from backend_M06_Mock_Interview_Engine.contracts import SpokenPart, TurnView
from backend_M06_Mock_Interview_Engine.projection import project_for_interviewer

from .stubs import BankQuestions, StubLLM, verdict
from .test_engine import make


def turn(**fields) -> TurnView:
    base = dict(
        turn_id=uuid.uuid4(),
        turn_index=3,
        segment_index=1,
        role="interviewer",
        text=(
            "Okay. Dr. Raghavan, over to you. Thanks, Priya. "
            "Walk me through the classifier you built."
        ),
        at="2026-10-06T10:00:00Z",
    )
    return TurnView(**{**base, **fields})


def test_a_line_heard_to_the_end_is_not_cut():
    assert heard.heard_text(turn()) is None
    assert heard.for_interviewer(turn()) == turn().text


def test_the_heard_part_snaps_back_to_a_whole_word():
    line = turn(heard_part=0, heard=0.5, text="What is the time complexity, and why?")
    assert heard.heard_text(line) == "What is the time"
    assert heard.for_interviewer(line) == "What is the time" + heard.CUT_MARK


def test_a_panel_line_is_heard_up_to_the_part_being_spoken():
    parts = [
        SpokenPart(speaker_id="methodical_engineer", text="Okay. Dr. Raghavan, over to you."),
        SpokenPart(
            speaker_id="professor", text="Thanks, Priya. Walk me through the classifier you built."
        ),
    ]
    line = turn(parts=parts, heard_part=1, heard=0.3)
    assert heard.heard_text(line) == "Okay. Dr. Raghavan, over to you. Thanks, Priya."
    nothing_yet = turn(parts=parts, heard_part=0, heard=0.0)
    assert heard.heard_text(nothing_yet) == ""


def test_the_interviewer_model_reads_the_line_as_far_as_it_was_heard():
    cut = turn(heard_part=0, heard=0.5, text="What is the time complexity, and why?")
    answer = TurnView(
        turn_id=uuid.uuid4(),
        turn_index=4,
        segment_index=1,
        role="candidate",
        text="O of n.",
        at="2026-10-06T10:00:05Z",
    )
    view = project_for_interviewer(
        transcript=[cut, answer], move="rung", ladder_depth=1, time_remaining_s=600
    )
    assert view.recent_turns[0].text.endswith(heard.CUT_MARK)
    assert view.recent_turns[1].text == "O of n."


def test_the_room_records_the_cut_once_and_the_line_stays_whole(db):
    engine = make(db, llm=StubLLM([verdict()] * 10), m05=BankQuestions())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=10
    )
    state = engine.start(row.id)
    opening = next(t for t in state.transcript if t.role == "interviewer")
    engine.heard(row.id, opening.turn_id, 2, 0.4)
    engine.heard(row.id, opening.turn_id, 0, 0.1)  # a second report is not the cut
    after = engine.state(row.id).turn(opening.turn_id)
    assert (after.heard_part, after.heard) == (2, 0.4)
    assert after.text == opening.text, "the line of record stays whole"


def test_the_route_takes_a_cut_from_the_sessions_student(client, as_student):
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    line = started["transcript"][0]
    r = client.post(
        f"/v1/interviews/{sid}/heard",
        json={"turn_id": line["turn_id"], "part_index": 0, "heard": 0.25},
        headers=as_student,
    )
    assert r.status_code == 204
    after = client.get(f"/v1/interviews/{sid}", headers=as_student).json()["transcript"][0]
    assert (after["heard_part"], after["heard"]) == (0, 0.25)
    # Not a number between 0 and 1, and not a stranger.
    bad = client.post(
        f"/v1/interviews/{sid}/heard",
        json={"turn_id": line["turn_id"], "heard": 1.5},
        headers=as_student,
    )
    assert bad.status_code == 422
    stranger = {"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())}
    refused = client.post(
        f"/v1/interviews/{sid}/heard",
        json={"turn_id": line["turn_id"], "heard": 0.5},
        headers=stranger,
    )
    assert refused.status_code == 403
