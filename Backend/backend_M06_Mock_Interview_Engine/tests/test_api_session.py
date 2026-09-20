"""Drills, answers, the report and the live stream — over HTTP."""

from __future__ import annotations

import json
import uuid

import pytest

from .stubs import drill_body


def _create(client, headers, **body):
    return client.post("/v1/interviews", json={"minutes": 30, **body}, headers=headers)


def _drill(client, candidate, headers):
    return client.post("/v1/drills", json=drill_body(candidate), headers=headers)


# ── drills (FR-6.23) ─────────────────────────────────────────────────────


def test_m01s_drill_hand_off_returns_a_session_and_a_url(client, candidate_id, as_student):
    made = _drill(client, candidate_id, as_student)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["url"] == f"/mock/{body['session_id']}"
    session = client.get(f"/v1/interviews/{body['session_id']}", headers=as_student).json()
    assert session["kind"] == "drill"
    assert session["status"] == "planned"
    assert session["drill_claim"].startswith("Built a crop-disease classifier")


@pytest.mark.gate
def test_an_anonymous_drill_hand_off_is_refused(client, candidate_id):
    """M01's call today sends no identity headers (M06_REVIEW Part 5)."""
    refused = _drill(client, candidate_id, {"Content-Type": "application/json"})
    assert refused.status_code == 403


def test_a_drill_for_another_student_is_refused(client, as_student):
    assert _drill(client, uuid.uuid4(), as_student).status_code == 403


def test_a_drill_without_probes_is_refused(client, candidate_id, as_student):
    body = {"candidate_id": str(candidate_id), "claim_id": "c", "claim_text": "x", "probes": []}
    assert client.post("/v1/drills", json=body, headers=as_student).status_code == 422


def test_a_whole_drill_over_http(client, candidate_id, as_student):
    sid = _drill(client, candidate_id, as_student).json()["session_id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    assert started["status"] == "live"
    open_turn = started["open_turn_id"]
    assert started["transcript"][-1]["text"].endswith("Walk me through the classifier.")

    answered = client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": open_turn, "text": "A ResNet on leaf images."},
        headers=as_student,
    ).json()
    # No model in tests: the rule fallback deepens once, with the drill's own probe.
    assert answered["transcript"][-1]["text"] == "How did you split the data?"

    done = client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": answered["open_turn_id"], "text": "80/20."},
        headers=as_student,
    ).json()
    assert done["status"] == "ended"
    assert done["end_reason"] == "drill_complete"

    again = client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": answered["open_turn_id"], "text": "a second go"},
        headers=as_student,
    )
    assert again.status_code == 409

    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student).json()
    assert report["kind"] == "drill"
    assert report["questions"][0]["scored"] is False
    assert "not scored" in report["questions"][0]["not_scored_reason"]
    assert report["questions"][0]["strong_answer_covers"]  # shown once it is over


def test_an_answer_longer_than_the_limit_is_refused(client, candidate_id, as_student):
    sid = _drill(client, candidate_id, as_student).json()["session_id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    too_long = client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": started["open_turn_id"], "text": "x" * 9000},
        headers=as_student,
    )
    assert too_long.status_code == 422


# ── the report (FR-6.18, AC-6.1) ─────────────────────────────────────────


def test_every_session_has_a_report_even_one_that_never_started(client, as_student):
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student)
    assert report.status_code == 200
    assert report.json()["status"] == "aborted"
    assert "didn't get going" in report.json()["framing"]


def test_a_short_session_is_framed_as_a_warm_up(client, as_student):
    """EC-6.10."""
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student).json()
    assert "warm-up" in report["framing"]
    assert any("consent" in note for note in report["notes"])


def test_the_answer_key_is_withheld_while_the_session_is_live(client, as_student):
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student).json()
    assert report["questions"]
    assert report["questions"][0]["strong_answer_covers"] == []


# ── the live stream (spec §7) ────────────────────────────────────────────


def _frames(client, sid, headers):
    with client.stream("GET", f"/v1/interviews/{sid}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    frames = []
    for block in text.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if line.startswith(":") or ": " not in line:
                continue
            key, value = line.split(": ", 1)
            fields[key] = value
        if "event" in fields:
            frames.append(fields)
    return frames


@pytest.mark.gate
def test_the_stream_never_carries_the_verdict_or_the_answer_key(client, candidate_id, as_student):
    """§2.2: no live score. The log has both; the browser gets neither."""
    sid = _drill(client, candidate_id, as_student).json()["session_id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    client.post(
        f"/v1/interviews/{sid}/answer",
        json={"question_turn_id": started["open_turn_id"], "text": "I don't know"},
        headers=as_student,
    )
    frames = _frames(client, sid, as_student)
    kinds = [f["event"] for f in frames]
    assert "question.asked" in kinds and "probe.decided" in kinds
    assert kinds[-1] == "stream.closed"
    payloads = [json.loads(f["data"]) for f in frames if f["event"] != "stream.closed"]
    for payload in payloads:
        for secret in ("verdict", "band", "item", "key_points", "expects"):
            assert secret not in payload["data"], (payload["kind"], secret)
    decided = next(p for p in payloads if p["kind"] == "probe.decided")
    assert decided["data"] == {"move": "move_on"}


def test_the_stream_resumes_after_the_last_event_id(client, candidate_id, as_student):
    sid = _drill(client, candidate_id, as_student).json()["session_id"]
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    everything = _frames(client, sid, as_student)
    ids = [int(f["id"]) for f in everything if "id" in f]
    assert len(ids) >= 2
    tail = _frames(client, sid, {**as_student, "Last-Event-ID": str(ids[0])})
    assert [int(f["id"]) for f in tail if "id" in f] == ids[1:]


def test_the_stream_refuses_a_stranger(client, candidate_id, as_student):
    sid = _drill(client, candidate_id, as_student).json()["session_id"]
    stranger = {"X-Role": "student", "X-Candidate-Id": str(uuid.uuid4())}
    assert client.get(f"/v1/interviews/{sid}/events", headers=stranger).status_code == 403


def test_the_agent_registry_is_published(client):
    body = client.get("/v1/agents").json()
    names = {a["name"] for a in body["agents"]}
    assert {"ProbeStrategist", "TechnicalInterviewer", "SafetyGuard"} <= names
    assert body["model_on"] is False
    assert "strategist" in body["step_graph"]


# ── the plan preview (FR-6.2) ────────────────────────────────────────────


def test_the_plan_can_be_seen_before_the_interview_starts(client, as_student):
    """A student should know what they are about to be asked."""
    sid = client.post(
        "/v1/interviews", json={"minutes": 45, "jd_id": str(uuid.uuid4())}, headers=as_student
    ).json()["id"]

    previewed = client.post(f"/v1/interviews/{sid}/plan", headers=as_student).json()
    assert previewed["status"] == "planned", "previewing is not starting"
    # The fixture resume has one risky claim, so the plan opens with the
    # student's own work before the posting's requirements (§6.1's order).
    assert [s["kind"] for s in previewed["plan"]["segments"]] == [
        "warmup",
        "project",
        "technical",
        "closing",
    ]
    assert previewed["transcript"] == [], "nobody has been greeted yet"

    # Idempotent: refreshing the preview does not ask M02 to price it twice.
    again = client.post(f"/v1/interviews/{sid}/plan", headers=as_student).json()
    assert again["plan"]["id"] == previewed["plan"]["id"]


def test_dropping_a_segment_keeps_it_visible_with_its_reason(client, as_student):
    """The report has to say what was planned as well as what happened."""
    sid = client.post(
        "/v1/interviews", json={"minutes": 45, "jd_id": str(uuid.uuid4())}, headers=as_student
    ).json()["id"]
    client.post(f"/v1/interviews/{sid}/plan", headers=as_student)

    before = client.get(f"/v1/interviews/{sid}", headers=as_student).json()["plan"]["segments"]
    technical = next(s for s in before if s["kind"] == "technical")

    edited = client.delete(
        f"/v1/interviews/{sid}/plan/segments/{technical['index']}", headers=as_student
    ).json()
    dropped = edited["plan"]["segments"][technical["index"]]
    assert dropped["dropped_reason"] == "You removed this part of the plan."
    assert len(edited["plan"]["segments"]) == len(before), "dropped, not deleted"

    # And the interview that follows does not ask it.
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    assert started["plan"]["segments"][technical["index"]]["dropped_reason"] is not None
    assert started["transcript"], "there is still a warm-up to run"


def test_the_closing_cannot_be_dropped(client, as_student):
    """FR-6.17 — it is reserved, and it is where the student asks."""
    sid = client.post("/v1/interviews", json={"minutes": 45}, headers=as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/plan", headers=as_student)
    last = (
        len(client.get(f"/v1/interviews/{sid}", headers=as_student).json()["plan"]["segments"]) - 1
    )

    refused = client.delete(f"/v1/interviews/{sid}/plan/segments/{last}", headers=as_student)
    assert refused.status_code == 409
    assert "where you ask your questions" in refused.json()["detail"]


def test_the_plan_cannot_be_edited_once_the_interview_has_started(client, as_student):
    """Changing it mid-session is a re-plan (FR-6.4), and M06 owns when those
    happen — a student who could drop the segment they are in could drop the
    question they are being asked."""
    sid = client.post(
        "/v1/interviews", json={"minutes": 45, "jd_id": str(uuid.uuid4())}, headers=as_student
    ).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)

    refused = client.delete(f"/v1/interviews/{sid}/plan/segments/1", headers=as_student)
    assert refused.status_code == 409
    assert "before the interview starts" in refused.json()["detail"]
