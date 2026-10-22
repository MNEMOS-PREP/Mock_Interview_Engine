"""The plan, assembled from M02's — FR-6.1, FR-6.2, spec §6.1.

Every test here is about arithmetic and dropping, because that is all the
assembly does. What it must NOT do — re-price M02's rounds, invent a segment,
call a model — is asserted as hard as what it must.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import planner
from backend_M06_Mock_Interview_Engine.contracts import InterviewPlan

SESSION = uuid.UUID("11111111-1111-4111-8111-111111111111")
JD = uuid.UUID("22222222-2222-4222-8222-222222222222")


def coverage(rounds=None, **overrides) -> dict:
    """M02's `CoveragePlan` in its captured shape."""
    body = {
        "jd_id": str(JD),
        "candidate_id": str(uuid.uuid4()),
        "total_minutes": 39,
        "allocated_minutes": 14.0,
        "allocations": [
            {
                "requirement_id": "R-1",
                "requirement_text": "SQL",
                "question_budget": 4,
                "round_type": "verbal",
                "priority": 0.8,
                "rationale": "the posting asks for it and nothing has measured it",
                "minutes": 14.0,
            }
        ],
        "uncovered": ["Kubernetes"],
        "unmeasurable": ["Go-getter attitude"],
        "rounds": rounds
        if rounds is not None
        else [
            {
                "round_type": "verbal",
                "minutes": 14.0,
                "question_count": 4,
                "requirement_ids": ["R-1"],
                "difficulty": "diagnostic",
            }
        ],
        "difficulty": "diagnostic",
        "plan_version": "greedy-log-v1",
    }
    body.update(overrides)
    return body


REQUIREMENTS = {
    "R-1": {
        "id": "R-1",
        "text": "SQL",
        "measured_by": ["technical"],
        "concept_ids": ["concept:sql_queries", "concept:joins"],
    },
    "R-2": {
        "id": "R-2",
        "text": "Working in a team",
        "measured_by": ["behavioural"],
        "concept_ids": ["concept:thinking_aloud"],
    },
    "R-3": {
        "id": "R-3",
        "text": "Data Structures",
        "measured_by": ["coding"],
        "concept_ids": ["concept:arrays"],
    },
}


def inputs(**overrides) -> planner.PlanInputs:
    base = {
        "session_id": SESSION,
        "mode": "mock",
        "requested_minutes": 45,
        "jd_id": JD,
        "coverage": coverage(),
        "requirements": REQUIREMENTS,
        "available_round_types": ("dsa_verbal",),
    }
    base.update(overrides)
    return planner.PlanInputs(**base)


def kinds(plan: InterviewPlan) -> list[str]:
    return [s.kind for s in plan.segments]


# ── the reserve, taken before M02 is asked ───────────────────────────────


def test_the_warm_up_and_the_closing_come_off_the_top():
    """§6.1. M02 is asked to price what is LEFT, so the plan it returns
    already fits — trimming its allocations afterwards is re-allocating
    them, which is Trap 8."""
    assert planner.reserved_minutes(45) == (4.0, 4.5)  # 10% each, warm-up capped at 4
    assert planner.minutes_for_m02(45) == 36

    # A short session gets a proportionally short warm-up and closing, not
    # four and five minutes of a ten-minute interview — but the closing never
    # drops below the two minutes "any questions for me?" needs.
    assert planner.reserved_minutes(10) == (1.0, 2.0)
    assert planner.minutes_for_m02(10) == 7
    assert planner.reserved_minutes(60) == (4.0, 5.0)  # and never above five

    # And never zero, however short the request.
    assert planner.minutes_for_m02(1) == 1


# ── M02's arithmetic is carried, not redone ──────────────────────────────


@pytest.mark.gate
def test_m02s_minutes_and_question_counts_are_carried_over_untouched():
    """Trap 8. M02 priced each round against the whole ontology and the
    student's coverage debt; a second opinion here is a second planner
    disagreeing with the first one, silently."""
    case = inputs()
    plan = planner.assemble(case)
    technical = [s for s in plan.segments if s.kind == "technical"]
    assert len(technical) == 1
    assert technical[0].minutes == 14.0
    assert technical[0].question_budget == 4
    assert technical[0].requirement_ids == ["R-1"]
    # M02's plan is frozen on the plan, because the endpoint is not persisted
    # and a second call can differ.
    assert plan.coverage_plan == case.coverage
    assert plan.coverage_plan_version == "greedy-log-v1"
    assert plan.uncovered == ["Kubernetes"]


def test_the_requirements_become_the_concepts_m05_selects_on():
    plan = planner.assemble(inputs())
    technical = next(s for s in plan.segments if s.kind == "technical")
    assert technical.concept_ids == ["concept:sql_queries", "concept:joins"]
    assert technical.rubric_round_types == ["dsa_verbal"]


def test_a_segment_is_named_in_the_postings_own_words():
    """Not "Technical Round 1". The student is about to be asked about SQL."""
    plan = planner.assemble(inputs())
    assert [s.title for s in plan.segments] == ["Warm-up", "SQL", "Your questions"]
    technical = next(s for s in plan.segments if s.kind == "technical")
    assert technical.rationale.startswith("the posting asks for it")


def test_a_round_measured_only_behaviourally_is_a_behavioural_segment():
    plan = planner.assemble(
        inputs(
            coverage=coverage(
                rounds=[
                    {
                        "round_type": "verbal",
                        "minutes": 7.0,
                        "question_count": 2,
                        "requirement_ids": ["R-2"],
                    }
                ]
            )
        )
    )
    assert "behavioural" in kinds(plan)

    # One behavioural requirement among technical ones is still a technical
    # round — it would otherwise change which persona runs it.
    mixed = planner.assemble(
        inputs(
            coverage=coverage(
                rounds=[
                    {
                        "round_type": "verbal",
                        "minutes": 7.0,
                        "question_count": 2,
                        "requirement_ids": ["R-1", "R-2"],
                    }
                ]
            )
        )
    )
    assert "technical" in kinds(mixed) and "behavioural" not in kinds(mixed)


# ── what this session cannot serve ───────────────────────────────────────


@pytest.mark.gate
def test_a_coding_round_is_dropped_and_owed_to_m02_as_skipped():
    """M07 does not exist. Serving a coding round as conversation would tell
    a student they had one; dropping it silently would leave M02's ledger
    believing those requirements are still coming."""
    plan = planner.assemble(
        inputs(
            coverage=coverage(
                rounds=[
                    {
                        "round_type": "coding",
                        "minutes": 24.0,
                        "question_count": 2,
                        "requirement_ids": ["R-3"],
                    },
                    {
                        "round_type": "verbal",
                        "minutes": 14.0,
                        "question_count": 4,
                        "requirement_ids": ["R-1"],
                    },
                ]
            )
        )
    )
    dropped = [s for s in plan.segments if s.dropped_reason is not None]
    assert len(dropped) == 1
    assert "coding round isn't built yet" in dropped[0].dropped_reason

    # It keeps its place in the plan, with its reason — the preview shows the
    # before as well as the after.
    assert dropped[0] in plan.segments
    assert dropped[0] not in planner.live_segments(plan)
    assert planner.skipped_requirements(plan) == ["R-3"]

    # And the verbal round beside it is untouched.
    live = [s for s in planner.live_segments(plan) if s.kind == "technical"]
    assert [s.requirement_ids for s in live] == [["R-1"]]


def test_with_no_round_type_available_the_segment_says_so():
    """M05 answered 409 for everything, or could not be asked. Rule 2: the
    session narrows, and the reason is not an empty list nobody reads."""
    plan = planner.assemble(inputs(available_round_types=()))
    technical = next(s for s in plan.segments if s.kind == "technical")
    assert technical.dropped_reason == (
        "The question bank had nothing for this topic, so it was left out."
    )
    assert planner.skipped_requirements(plan) == ["R-1"]


# ── the shape of every plan ──────────────────────────────────────────────


@pytest.mark.gate
def test_every_plan_opens_with_a_warm_up_and_closes_with_the_students_questions():
    """§6.1's order, and the closing is reserved: never dropped by a re-plan
    or by the clock (FR-6.17)."""
    for case in (inputs(), inputs(coverage=None, jd_id=None), inputs(available_round_types=())):
        plan = planner.assemble(case)
        assert kinds(plan)[0] == "warmup"
        assert kinds(plan)[-1] == "closing"
        assert plan.segments[-1].is_reserved is True
        assert plan.segments[-1].dropped_reason is None
        assert [s.index for s in plan.segments] == list(range(len(plan.segments)))


def test_every_part_has_an_interviewer_and_the_lead_opens_and_closes():
    """FR-6.3. Who sits on the panel is `panel.assign`'s (test_panel.py); the
    planner's part is that every segment names someone, and that the person
    the student meets first is the one who says goodbye."""
    from backend_M06_Mock_Interview_Engine.personas import persona

    leads = {}
    for mode in ("practice", "final_boss"):
        plan = planner.assemble(inputs(mode=mode))
        segments = plan.segments
        assert all(s.persona_id for s in segments)
        assert segments[0].persona_id == plan.panel[0] == segments[-1].persona_id
        leads[mode] = persona(segments[0].persona_id)
    # The lead is the mode's kind of person, whoever it is this time.
    assert leads["practice"].speech == "friendly"
    assert leads["final_boss"].warmth <= 0.5


# ── no job description (§10) ─────────────────────────────────────────────


def test_without_a_job_description_the_plan_says_it_is_not_tailored():
    """A student must not think a generic session was built for a posting."""
    plan = planner.assemble(inputs(coverage=None, jd_id=None))
    middle = [s for s in plan.segments if s.kind == "technical"]
    assert middle, "there is still an interview to run"
    assert all("Not tailored to a job description" in s.rationale for s in middle)
    assert plan.jd_id is None
    assert plan.coverage_plan is None
    assert all(s.requirement_ids == [] for s in plan.segments)
    # The budget is what is left after the reserve, split over what M05 can
    # fill — 45 − 4 − 4.5 = 36.5 minutes, one round type.
    assert middle[0].minutes == 36.5
    assert middle[0].question_budget == 18  # 36.5 // 2


def test_with_no_job_description_and_no_bank_there_is_still_a_report():
    """AC-6.1 — every session produces a report, so every session has a plan,
    even one that can ask nothing."""
    plan = planner.assemble(inputs(coverage=None, jd_id=None, available_round_types=()))
    assert kinds(plan) == ["warmup", "closing"]


# ── the project segment (§6.1) ───────────────────────────────────────────


def claim(id="c1", band="risky", probes=1) -> dict:
    return {
        "id": id,
        "text": "Built a crop-disease classifier reaching 94% accuracy",
        "risk_band": band,
        "probes": [{"depth": d, "question": f"q{d}", "expects": "x"} for d in range(probes)],
    }


@pytest.mark.gate
def test_the_project_segment_is_paid_for_by_the_largest_round_not_the_closing():
    """§6.1. The closing is reserved (FR-6.17), so the minutes come from the
    largest verbal segment — and not all of them: a session that was 14
    minutes of SQL should not become 4 because the resume had a shaky line."""
    plan = planner.assemble(inputs(claims=(claim(), claim("c2")), resume_included=True))
    kinds_in_order = kinds(plan)
    assert kinds_in_order == ["warmup", "project", "technical", "closing"]

    project = plan.segments[1]
    technical = plan.segments[2]
    closing = plan.segments[3]
    assert project.minutes == 4.0  # two claims at 2, and under half of 14
    assert technical.minutes == 10.0  # 14 − 4, paid by the largest round
    assert technical.question_budget == 4, "M02's count, carried (Trap 8)"
    assert closing.minutes == planner.reserved_minutes(45)[1]  # untouched
    assert project.question_budget == 2
    assert project.source == "m01_claims"


def test_a_resume_with_nothing_shaky_gets_no_project_segment():
    """Not a degraded session — a student with nothing to defend is not
    missing a feature."""
    opted_in = {"resume_included": True}
    assert "project" not in kinds(planner.assemble(inputs(**opted_in)))
    assert "project" not in kinds(
        planner.assemble(inputs(claims=(claim(band="safe"),), **opted_in))
    )
    # A claim M01 could not write probes for is one M06 has no question for,
    # and inventing one would be M06 deciding what to ask about a resume.
    assert "project" not in kinds(
        planner.assemble(inputs(claims=(claim(probes=0),), **opted_in))
    )


def test_the_project_segment_never_eats_more_than_half_a_round():
    """Five shaky claims is a resume problem, not a reason to cancel the
    interview the posting asked for."""
    many = tuple(claim(f"c{i}") for i in range(5))
    plan = planner.assemble(inputs(claims=many, resume_included=True))
    project = next(s for s in plan.segments if s.kind == "project")
    technical = next(s for s in plan.segments if s.kind == "technical")
    assert project.minutes == 7.0 == technical.minutes
    assert project.question_budget == 3  # what 7 minutes actually holds
    assert len(plan.claims) == 5, "the plan still records every claim it saw"


def test_with_no_round_to_take_from_the_project_segment_is_the_interview():
    """No JD and no bank — but a resume with something worth defending is
    still an interview worth having."""
    plan = planner.assemble(
        inputs(
            coverage=None,
            jd_id=None,
            available_round_types=(),
            claims=(claim(),),
            resume_included=True,
        )
    )
    assert kinds(plan) == ["warmup", "project", "closing"]
    assert next(s for s in plan.segments if s.kind == "project").minutes == 2.0


# ── a focused session ("Practise Recursion" on Today) ────────────────────


def test_a_chosen_focus_is_the_whole_interview():
    """Practise Recursion means recursion: one segment, every usable minute,
    and the concepts handed to M05 as the coverage it selects on."""
    plan = planner.assemble(
        inputs(
            coverage=None,
            jd_id=None,
            focus_concepts=("concept:recursion",),
            focus_label="Recursion",
        )
    )
    middle = [s for s in plan.segments if s.kind == "technical"]
    assert len(middle) == 1
    assert middle[0].title == "Focus: Recursion"
    assert middle[0].concept_ids == ["concept:recursion"]
    assert middle[0].minutes == 36.5
    assert "You chose to practise Recursion" in middle[0].rationale


def test_a_focus_without_a_label_is_named_from_its_concept():
    plan = planner.assemble(
        inputs(coverage=None, jd_id=None, focus_concepts=("concept:dynamic_programming",))
    )
    assert [s.title for s in plan.segments if s.kind == "technical"] == [
        "Focus: dynamic programming"
    ]


FOCUS_TRACKS = {
    "behavioural": {
        "round_type": "behavioural",
        "kind": "behavioural",
        "concept_ids": ["concept:thinking_aloud", "concept:explaining_tradeoffs"],
    },
    "dbms_verbal": {
        "round_type": "dbms_verbal",
        "concept_ids": ["concept:indexing", "concept:hashing"],
    },
    "dsa_verbal": {
        "round_type": "dsa_verbal",
        "concept_ids": ["concept:hashing", "concept:hashing_internals"],
    },
}


def focused(*concepts: str, **overrides) -> InterviewPlan:
    return planner.assemble(
        inputs(
            coverage=None,
            jd_id=None,
            available_round_types=tuple(FOCUS_TRACKS),
            tracks=FOCUS_TRACKS,
            focus_concepts=concepts,
            **overrides,
        )
    )


def test_a_focus_is_asked_under_the_tracks_that_hold_it_most_first():
    """A live "Focus: Hashing" was planned under every available track and
    asked under the first alphabetically — behavioural — so it heard "tell me
    about a time…" (2026-10-22). And M05 is told to keep to it."""
    plan = focused("concept:hashing", "concept:hashing_internals", focus_label="Hashing")
    part = next(s for s in plan.segments if s.title == "Focus: Hashing")
    assert part.rubric_round_types == ["dsa_verbal", "dbms_verbal"]
    assert part.concepts_only and part.kind == "technical"


def test_a_behavioural_focus_is_run_by_that_side_of_the_panel():
    plan = focused("concept:thinking_aloud", focus_label="Thinking aloud")
    part = next(s for s in plan.segments if s.title == "Focus: Thinking aloud")
    assert (part.kind, part.rubric_round_types) == ("behavioural", ["behavioural"])


def test_a_focus_m05_says_nothing_about_keeps_every_track():
    """No track contents from M05: every available track, as before."""
    plan = planner.assemble(
        inputs(
            coverage=None,
            jd_id=None,
            available_round_types=("behavioural", "dsa_verbal"),
            focus_concepts=("concept:hashing",),
        )
    )
    part = next(s for s in plan.segments if s.title.startswith("Focus:"))
    assert part.rubric_round_types == ["behavioural", "dsa_verbal"]
    assert part.concepts_only


# ── a mixed interview from the student's courses (2026-10-13) ──────────────

COURSE_TRACKS = {
    "dsa_verbal": {
        "round_type": "dsa_verbal",
        "concept_ids": ["concept:arrays", "concept:recursion"],
    },
    "os_verbal": {
        "round_type": "os_verbal",
        "concept_ids": ["concept:deadlocks", "concept:virtual_memory"],
    },
    "ml_verbal": {"round_type": "ml_verbal", "concept_ids": ["concept:decision_trees"]},
}


def mixed(**overrides) -> planner.PlanInputs:
    base = {
        "coverage": None,
        "jd_id": None,
        "requested_minutes": 30,
        "available_round_types": ("dsa_verbal", "os_verbal", "ml_verbal"),
        "tracks": COURSE_TRACKS,
    }
    base.update(overrides)
    return inputs(**base)


def parts(plan: InterviewPlan) -> dict[str, list[str]]:
    return {s.rubric_round_types[0]: s.concept_ids for s in plan.segments if s.kind == "technical"}


def test_a_mixed_interview_is_drawn_from_what_the_courses_taught():
    """A third-semester student who has sat OS and DSA is not asked machine
    learning they have not reached; each part leans on what they studied."""
    plan = planner.assemble(mixed(studied_concepts=("concept:deadlocks", "concept:arrays")))
    assert parts(plan) == {"dsa_verbal": ["concept:arrays"], "os_verbal": ["concept:deadlocks"]}
    middle = [s for s in plan.segments if s.kind == "technical"]
    assert all("what your courses have covered" in s.rationale for s in middle)


def test_a_track_the_courses_barely_touch_waits_for_one_they_can_fill():
    """Two shared concepts cannot fill a three-question part: first-year
    maths' linear algebra does not make a machine-learning round."""
    tracks = {
        rt: {"round_type": rt, "concept_ids": [f"concept:{c}" for c in letters]}
        for rt, letters in (("os_verbal", "abc"), ("ml_verbal", "xyz"))
    }
    studied = ("concept:a", "concept:b", "concept:c", "concept:x", "concept:y")
    plan = planner.assemble(
        mixed(
            available_round_types=("os_verbal", "ml_verbal"),
            tracks=tracks,
            studied_concepts=studied,
        )
    )
    assert list(parts(plan)) == ["os_verbal"]


def test_without_coursework_the_mix_is_what_it_was():
    plan = planner.assemble(mixed())
    assert parts(plan) == {"dsa_verbal": [], "os_verbal": [], "ml_verbal": []}
    assert not any("courses" in s.rationale for s in plan.segments)


def test_courses_no_track_asks_about_leave_the_mix_as_it_was():
    plan = planner.assemble(mixed(studied_concepts=("concept:sql_queries",)))
    assert parts(plan) == {"dsa_verbal": [], "os_verbal": [], "ml_verbal": []}


def test_a_picked_track_is_asked_as_picked():
    """The student chose machine learning; their courses do not narrow it."""
    plan = planner.assemble(
        mixed(
            track="ml_verbal",
            available_round_types=("ml_verbal",),
            studied_concepts=("concept:arrays", "concept:decision_trees"),
        )
    )
    assert parts(plan) == {"ml_verbal": []}


def test_each_part_is_steered_to_at_most_eight_studied_concepts():
    many = tuple(f"concept:c{i}" for i in range(12))
    tracks = {"dsa_verbal": {"round_type": "dsa_verbal", "concept_ids": list(many)}}
    plan = planner.assemble(
        mixed(available_round_types=("dsa_verbal",), tracks=tracks, studied_concepts=many)
    )
    assert parts(plan)["dsa_verbal"] == list(many[:8])  # freshest first


def test_a_focus_no_track_asks_about_is_left_out_and_says_why():
    """A resume line's id reached the focus from the notes' "practise again"
    (2026-10-23). Held to the focus, M05 has nothing: the part is on the plan,
    left out, with the reason — not a warm-up and a goodbye."""
    plan = focused("claim:0ac8493e", focus_label="Led a team of 4")
    part = next(s for s in plan.segments if s.title == "Focus: Led a team of 4")
    assert part.dropped_reason == planner.FOCUS_UNSERVED
    assert part.question_budget == 0
