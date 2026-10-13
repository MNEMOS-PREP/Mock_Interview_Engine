"""The session lifecycle over HTTP, and who may touch it (FR-6.26)."""

from __future__ import annotations

import uuid

import pytest

from .conftest import admin, student


def _create(client, headers, **body):
    return client.post("/v1/interviews", json={"minutes": 30, **body}, headers=headers)


# ── meta ─────────────────────────────────────────────────────────────────


def test_health_and_status(client):
    assert client.get("/health").json()["module"] == "M06"
    status = client.get("/status").json()
    assert status["id"] == "M06"
    assert status["reserved_port"] == 8106


def test_deps_names_every_upstream_and_requires_none(client, monkeypatch):
    from backend_M06_Mock_Interview_Engine import dependencies

    registry = dependencies.deps()
    monkeypatch.setattr(registry, "_probe", lambda dep: (False, "unreachable (test)"))
    registry.clear_cache()
    rows = client.get("/v1/deps").json()
    assert {r["module_id"] for r in rows} == {"M01", "M02", "M04", "M05", "M13"}
    assert not any(r["required"] for r in rows)
    assert all(r["on_missing"] for r in rows)
    registry.clear_cache()


# ── lifecycle ────────────────────────────────────────────────────────────


def test_create_start_pause_resume_end(client, as_student):
    created = _create(client, as_student)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["status"] == "planned"

    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    assert started.json()["status"] == "live"

    paused = client.post(f"/v1/interviews/{sid}/pause", headers=as_student)
    assert paused.json()["status"] == "paused"
    # 30 minutes planned: two pauses (FR-6.12, revised), one spent.
    assert paused.json()["flags"]["pauses_used"] == 1
    assert paused.json()["flags"]["pauses_allowed"] == 2
    assert paused.json()["flags"]["pause_used"] is False

    resumed = client.post(f"/v1/interviews/{sid}/resume", headers=as_student)
    assert resumed.json()["status"] == "live"

    ended = client.post(f"/v1/interviews/{sid}/end", json={"reason": "done"}, headers=as_student)
    assert ended.json()["status"] == "ended"
    assert ended.json()["end_reason"] == "done"


def _pause_twice(client, headers, minutes):
    sid = _create(client, headers, minutes=minutes).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=headers)
    client.post(f"/v1/interviews/{sid}/pause", headers=headers)
    client.post(f"/v1/interviews/{sid}/resume", headers=headers)
    return client.post(f"/v1/interviews/{sid}/pause", headers=headers)


def test_a_short_interview_gets_one_pause(client, as_student):
    """FR-6.12, revised 2026-10-04: one pause per 15 planned minutes."""
    again = _pause_twice(client, as_student, 15)
    assert again.status_code == 409
    assert "one per 15 minutes" in again.json()["detail"]


def test_a_longer_interview_gets_more_pauses(client, as_student):
    """'Once' was strict for 45 minutes: water at minute 10 left nothing for 35."""
    again = _pause_twice(client, as_student, 30)
    assert again.status_code == 200
    assert again.json()["flags"]["pauses_used"] == 2
    assert again.json()["flags"]["pause_used"] is True


def test_a_repeated_start_is_idempotent(client, as_student):
    sid = _create(client, as_student).json()["id"]
    first = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    second = client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    assert second.status_code == 200
    assert second.json()["started_at"] == first["started_at"]


def test_ending_a_planned_session_aborts_it(client, as_student):
    sid = _create(client, as_student).json()["id"]
    ended = client.post(f"/v1/interviews/{sid}/end", headers=as_student).json()
    assert ended["status"] == "aborted"


@pytest.mark.gate
def test_a_second_live_session_is_refused_with_the_way_back(client, as_student):
    """EC-6.13 — blocked with an explanation, and the id of the one to resume."""
    first = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{first}/start", headers=as_student)
    refused = _create(client, as_student)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["session_id"] == first
    assert "in progress" in detail["message"]


def test_nothing_answers_for_an_unknown_session(client, as_student):
    assert client.get(f"/v1/interviews/{uuid.uuid4()}", headers=as_student).status_code == 404


def test_trace_replays_to_the_same_state(client, as_student):
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    client.post(f"/v1/interviews/{sid}/pause", headers=as_student)
    trace = client.get(f"/v1/interviews/{sid}/trace", headers=admin()).json()
    kinds = [e["kind"] for e in trace["events"]]
    # The plan is assembled during the bootstrap, before the greeting: a
    # session that started without one would be asking questions off a plan
    # the student never saw.
    assert kinds[:4] == [
        "session.created",
        "consent.resolved",
        "plan.set",
        "session.started",
    ]
    assert kinds[-1] == "session.paused"
    assert trace["replay_matches"] is True


@pytest.mark.gate
def test_a_student_sees_the_raw_trace_only_after_the_interview(client, as_student):
    """The log holds verdict bands and the open question's key points."""
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    live = client.get(f"/v1/interviews/{sid}/trace", headers=as_student)
    assert live.status_code == 403
    assert "once the interview is over" in live.json()["detail"]
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    assert client.get(f"/v1/interviews/{sid}/trace", headers=as_student).status_code == 200


def test_history_and_recent_sessions(client, candidate_id, as_student):
    first = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{first}/start", headers=as_student)
    client.post(f"/v1/interviews/{first}/end", headers=as_student)
    _create(client, as_student)

    history = client.get(f"/v1/interviews/by-candidate/{candidate_id}", headers=as_student).json()
    assert len(history) == 2
    recent = client.get(
        f"/v1/interviews/by-candidate/{candidate_id}/recent", headers=as_student
    ).json()
    assert [r["id"] for r in recent] == [first]


# ── identity (FR-6.26) ───────────────────────────────────────────────────


@pytest.mark.gate
def test_anonymous_callers_are_refused_everywhere_a_student_is_named(
    client, candidate_id, as_student
):
    sid = _create(client, as_student).json()["id"]
    for method, path in [
        ("get", f"/v1/interviews/{sid}"),
        ("post", f"/v1/interviews/{sid}/start"),
        ("get", f"/v1/interviews/{sid}/transcript"),
        ("get", f"/v1/interviews/{sid}/trace"),
        ("get", f"/v1/interviews/by-candidate/{candidate_id}"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 403, f"{method} {path} answered anonymously"
        assert response.json()["detail"] == "Not signed in."
    assert _create(client, {}).status_code == 403


@pytest.mark.gate
def test_one_student_cannot_reach_another_students_session(client, as_student):
    sid = _create(client, as_student).json()["id"]
    stranger = student(uuid.uuid4())
    assert client.get(f"/v1/interviews/{sid}", headers=stranger).status_code == 403
    assert client.post(f"/v1/interviews/{sid}/end", headers=stranger).status_code == 403
    assert client.get(f"/v1/interviews/{sid}", headers=as_student).status_code == 200


def test_a_student_cannot_create_a_session_for_someone_else(client, as_student):
    other = uuid.uuid4()
    assert _create(client, as_student, candidate_id=str(other)).status_code == 403


def test_an_admin_may_create_on_behalf_of_a_student(client):
    other = uuid.uuid4()
    created = _create(client, admin(), candidate_id=str(other))
    assert created.status_code == 201
    assert created.json()["candidate_id"] == str(other)


def test_meta_routes_are_not_gated(client, monkeypatch):
    from backend_M06_Mock_Interview_Engine import dependencies

    registry = dependencies.deps()
    monkeypatch.setattr(registry, "_probe", lambda dep: (False, "unreachable (test)"))
    registry.clear_cache()
    assert client.get("/v1/deps").status_code == 200
    registry.clear_cache()


def test_a_focus_is_planned_as_one_segment(client, as_student):
    """Today's "Practise Recursion" reaches the plan, not just the URL."""
    created = _create(
        client,
        as_student,
        focus_concepts=["concept:recursion"],
        focus_label="Recursion",
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    titles = [s["title"] for s in started["plan"]["segments"]]
    assert "Focus: Recursion" in titles


def test_a_course_focus_of_eight_is_planned_and_nine_refused(client, as_student):
    """A course sends its syllabus's concepts; eight is the ontology's most
    for one session (M04 §3.2.1), and more is a request to sample, not focus."""
    eight = [f"concept:c{i}" for i in range(8)]
    assert _create(client, as_student, focus_concepts=eight, focus_label="OS").status_code == 201
    nine = [f"concept:c{i}" for i in range(9)]
    assert _create(client, as_student, focus_concepts=nine).status_code == 422


def test_the_cohort_figure_counts_this_weeks_interviews_and_names_no_one(client, as_student):
    before = client.get("/v1/interviews/stats", headers=as_student).json()
    sid = _create(client, as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    after = client.get("/v1/interviews/stats", headers=as_student).json()
    assert after["interviews_this_week"] == before["interviews_this_week"] + 1
    assert after["students_this_week"] >= 1
    assert set(after) == {"interviews_this_week", "students_this_week", "since"}


def test_a_mixed_interview_follows_the_students_courses(client, as_student, upstreams):
    """2026-10-13: M04's coursework reaches the plan, and M05 is seeded with
    the student's own estimate on those concepts before the first question."""
    upstreams.m04.studied = ["concept:recursion", "concept:sql_queries"]
    sid = _create(client, as_student).json()["id"]
    plan = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()["plan"]
    technical = [s for s in plan["segments"] if s["kind"] == "technical"]
    assert technical and technical[0]["concept_ids"] == ["concept:recursion"]
    assert "what your courses have covered" in technical[0]["rationale"]
