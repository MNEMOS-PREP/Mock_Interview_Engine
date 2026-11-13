"""A mixed mock interview and the student's career goal (2026-11-13).

Once M22's goal tracks reached the bank, every mixed interview drew from all
of them: measured live, a student whose goal was Backend Developer got four
of 32 parts on backend, databases or system design, and the rest on mobile,
embedded, cybersecurity and product. Now a student with a goal is asked from
the goal's own tracks, weighted by each track's share of its interview and
varied between sessions; a student with nothing to go on is asked the core
tracks M05 marks `mixed`, as before the goal tracks existed.
"""

from __future__ import annotations

import collections
import uuid

from backend_M06_Mock_Interview_Engine import planner, store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import FixtureEvaluator, FixtureGoals

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make
from .test_tracks import items_for

CORE = ("dsa_verbal", "os_verbal", "dbms_verbal", "cn_verbal", "behavioural")
GOAL_ONLY = ("backend_verbal", "system_design_verbal", "devops_verbal")
NICHE = ("embedded_verbal", "product_verbal", "mobile_verbal")
ALL = CORE + GOAL_ONLY + NICHE
#: M05's `/v1/bank/tracks` metadata: the core tracks carry `mixed: true`.
TRACKS = {rt: {"title": rt.replace("_verbal", "").title(), "mixed": rt in CORE} for rt in ALL}
#: M22's Goal Context for a backend goal, field for field (engine.context).
BACKEND_MIX = (
    ("backend_verbal", 30.0, ("concept:api_design", "concept:authentication")),
    ("dbms_verbal", 15.0, ("concept:indexing",)),
    ("dsa_verbal", 15.0, ()),
    ("system_design_verbal", 12.0, ()),
    ("behavioural", 12.0, ()),
    ("devops_verbal", 6.0, ()),
    ("os_verbal", 5.0, ()),
    ("cn_verbal", 5.0, ()),
)


def mixed(**overrides) -> planner.PlanInputs:
    base = {
        "session_id": uuid.uuid4(),
        "mode": "mock",
        "requested_minutes": 30,
        "available_round_types": ALL,
        "tracks": TRACKS,
    }
    base.update(overrides)
    return planner.PlanInputs(**base)


def parts(plan) -> list[str]:
    return [s.rubric_round_types[0] for s in plan.segments if s.kind not in ("warmup", "closing")]


def test_a_mixed_interview_asks_the_goals_own_tracks_weighted_and_varied():
    goal_tracks = {t for t, _, _ in BACKEND_MIX}
    seen: collections.Counter = collections.Counter()
    plans = set()
    for _ in range(200):
        picked = parts(
            planner.assemble(mixed(goal_mix=BACKEND_MIX, goal_title="Backend Developer"))
        )
        assert picked and set(picked) <= goal_tracks, "nothing outside the goal"
        seen.update(picked)
        plans.add(tuple(sorted(picked)))
    assert len(plans) > 3, "a different mix from session to session"
    assert seen["backend_verbal"] > seen["dbms_verbal"] > seen["os_verbal"], "by share"
    assert not set(seen) & set(NICHE)


def test_a_goal_part_leans_on_the_goals_open_competencies_and_says_why():
    plan = planner.assemble(mixed(goal_mix=BACKEND_MIX[:1], goal_title="Backend Developer"))
    (part,) = [s for s in plan.segments if s.rubric_round_types == ["backend_verbal"]]
    assert part.concept_ids == ["concept:api_design", "concept:authentication"]
    assert "Backend Developer" in part.rationale and "30%" in part.rationale


def test_without_a_goal_or_courses_only_the_core_tracks_are_drawn():
    seen = set()
    for _ in range(100):
        seen.update(parts(planner.assemble(mixed())))
    assert seen <= set(CORE) and seen


def test_a_goal_whose_tracks_the_bank_cannot_serve_falls_back_to_the_core():
    plan = planner.assemble(mixed(goal_mix=(("ai_apps_verbal", 100.0, ()),), goal_title="AI"))
    assert set(parts(plan)) <= set(CORE)


def test_a_picked_track_is_still_the_track_even_with_a_goal():
    # The engine probes only the picked track, so it is all that is available.
    plan = planner.assemble(
        mixed(
            goal_mix=BACKEND_MIX,
            track="embedded_verbal",
            available_round_types=("embedded_verbal",),
        )
    )
    assert parts(plan) == ["embedded_verbal"]


def context(candidate: uuid.UUID) -> dict:
    """M22's `GET /v1/goals/context/{id}` body, trimmed to what M06 reads."""
    return {
        "candidate_id": str(candidate),
        "primary_goal_id": "g1",
        "goals": [
            {
                "goal_id": "g1",
                "title": "Backend Developer",
                "track_shares": {t: s for t, s, _ in BACKEND_MIX},
                "track_concepts": {t: list(c) for t, _, c in BACKEND_MIX if c},
            }
        ],
    }


def engine_with(db, goals: FixtureGoals):
    return make(
        db,
        llm=StubLLM([verdict()] * 40),
        m05=BankQuestions(
            items=[
                i
                for rt in ("backend_verbal", "dbms_verbal", "embedded_verbal")
                for i in items_for(rt)
            ]
        ),
        m13=FixtureEvaluator(round_types=("backend_verbal", "dbms_verbal", "embedded_verbal")),
        m01=NoClaims(),
        m22=goals,
    )


def test_the_engine_reads_the_goal_context_for_a_mixed_interview_only(db):
    candidate = uuid.uuid4()
    engine = engine_with(db, FixtureGoals(contexts={str(candidate): context(candidate)}))
    row, _ = store.create_session(
        engine.db, candidate_id=candidate, kind="mock", mode="mock", minutes=30
    )
    plan = engine.plan(row.id).plan
    asked = {s.rubric_round_types[0] for s in plan.segments if s.kind not in ("warmup", "closing")}
    assert asked and asked <= {"backend_verbal", "dbms_verbal"}, "the goal's tracks the bank serves"
    assert all("Backend Developer" in s.rationale for s in plan.segments if s.kind == "technical")

    other = uuid.uuid4()  # no goal: the mixed interview as it was
    row, _ = store.create_session(
        engine.db, candidate_id=other, kind="mock", mode="mock", minutes=30
    )
    plan = engine.plan(row.id).plan
    assert not any("Backend Developer" in s.rationale for s in plan.segments)
    assert not any(s.dropped_reason for s in plan.segments), "no goal is not a degraded interview"
