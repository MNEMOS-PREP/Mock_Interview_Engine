"""A goal interview (2026-11-12): planned from M22's blueprint.

M22 (Follow Your Goal) keeps fixed interview configurations per career goal —
say 25% backend, 20% frontend, 15% databases — and publishes, for each
attempt, a blueprint: the parts, each a track with a question budget and the
concepts to ask about. M06 plans the interview from it, so every attempt
under one configuration has the same distribution and the results compare.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import planner, store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import FixtureEvaluator, FixtureGoals

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make
from .test_tracks import asked, items_for, run_to_end

CONFIG = "a1b2c3d4-0000-4000-8000-000000000022"


def blueprint(budgets: dict[str, int]) -> dict:
    """M22's `Blueprint`, field for field (schemas.Blueprint)."""
    return {
        "config_id": CONFIG, "series": "s1", "version": 2, "name": "Backend, fixed", "mode": "role",
        "m06_mode": "mock", "minutes": 30, "questions": sum(budgets.values()),
        "segments": [
            {"area": track.split("_")[0], "title": f"Part on {track}", "track": track,
             "kind": "technical", "concept_ids": ["concept:hashing", "concept:arrays"],
             "concepts_only": True, "question_budget": n, "share": 0.5, "rationale": "Half of it."}
            for track, n in budgets.items()
        ],
    }


def goal_engine(db, budgets: dict[str, int], **extra):
    goals = FixtureGoals({CONFIG: blueprint(budgets)})
    engine = make(
        db,
        llm=StubLLM([verdict()] * 80),
        m05=BankQuestions(items=items_for("dsa_verbal") + items_for("ml_verbal")),
        m13=FixtureEvaluator(round_types=("dsa_verbal", "ml_verbal")),
        m01=NoClaims(),
        m22=goals,
        **extra,
    )
    return engine, goals


def test_the_plan_is_the_blueprints_parts(db):
    engine, goals = goal_engine(db, {"dsa_verbal": 3, "ml_verbal": 2})
    row, _ = store.create_session(engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock",
                                  minutes=30, goal_config_id=CONFIG)
    plan = engine.plan(row.id).plan
    middle = [s for s in plan.segments if s.kind not in ("warmup", "closing")]
    assert [(s.rubric_round_types, s.question_budget) for s in middle] == [
        (["dsa_verbal"], 3), (["ml_verbal"], 2),
    ]
    assert all(s.source == "m22_goal" and s.concepts_only for s in middle)
    assert middle[0].concept_ids == ["concept:hashing", "concept:arrays"]
    assert goals.asked == [(CONFIG, 30)], "asked once, with the session's length"


def test_a_part_the_bank_cannot_serve_is_left_out_with_the_reason(db):
    engine, _ = goal_engine(db, {"dsa_verbal": 3, "security_verbal": 2})
    row, _ = store.create_session(engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock",
                                  minutes=30, goal_config_id=CONFIG)
    middle = [s for s in engine.plan(row.id).plan.segments if s.kind not in ("warmup", "closing")]
    security = next(s for s in middle if s.rubric_round_types == ["security_verbal"])
    assert security.dropped_reason == planner.GOAL_UNSERVED


def test_a_goal_interview_asks_only_in_its_tracks(db):
    engine, _ = goal_engine(db, {"ml_verbal": 3})
    row, _ = store.create_session(engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock",
                                  minutes=30, goal_config_id=CONFIG)
    engine.start(row.id)
    state = run_to_end(engine, row)
    assert state.goal_config_id == CONFIG
    questions = asked(state)
    assert len(questions) >= 2
    assert all(t.rubric_round_type == "ml_verbal" for t in questions), "the warm-up too"


def test_without_m22_it_is_an_ordinary_interview_and_says_why(db):
    engine, goals = goal_engine(db, {"dsa_verbal": 3})
    goals.blueprints.clear()  # M22 knows no such configuration
    row, _ = store.create_session(engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock",
                                  minutes=30, goal_config_id=CONFIG)
    plan = engine.plan(row.id).plan
    assert not any(s.source == "m22_goal" for s in plan.segments)
    assert [s for s in plan.segments if s.kind not in ("warmup", "closing")], "still an interview"
