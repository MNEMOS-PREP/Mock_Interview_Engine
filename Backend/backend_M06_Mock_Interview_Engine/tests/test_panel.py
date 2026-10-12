"""The panel — FR-6.3, master plan §26: who interviews, chosen from data.

These hold properties, never names. Authoring a persona is supposed to change
the panel; a test that pinned "Dr. Raghavan takes the project" would fail the
day that works.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from backend_M06_Mock_Interview_Engine import panel
from backend_M06_Mock_Interview_Engine.modes import MODES
from backend_M06_Mock_Interview_Engine.personas import personas

from .test_modes import panel_plan

ALL_MODES = tuple(MODES)
#: The cast before 2026-10-07 — a small world some properties are held in.
FIRST_SEVEN = frozenset(
    {
        "bar_raiser",
        "friendly_recruiter",
        "hr_generalist",
        "impatient_senior",
        "methodical_engineer",
        "professor",
        "startup_founder",
    }
)


def seated(plan) -> list[str]:
    return list(dict.fromkeys(s.persona_id for s in plan.segments))


def eligible(mode: str):
    return [p for p in personas().values() if panel.fits(p, MODES[mode].temperament)]


def declares(p, kind: str) -> bool:
    return panel.stem(kind) in panel.words(p.domain_bias)


def part(kind: str, title: str = "") -> SimpleNamespace:
    """The four fields `panel` reads from a segment, and nothing else."""
    return SimpleNamespace(kind=kind, title=title, rubric_round_types=[], concept_ids=[])


# ── shape ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ALL_MODES)
def test_the_lead_opens_and_closes(mode):
    """The person who welcomed the student is the one who says goodbye — and
    is the first the opening introduces."""
    plan = panel_plan(mode)
    lead = plan.panel[0]
    assert plan.segments[0].persona_id == lead == plan.segments[-1].persona_id


@pytest.mark.parametrize("mode", ALL_MODES)
def test_every_mode_seats_a_panel_not_one_person_in_several_hats(mode):
    assert len(seated(panel_plan(mode))) >= 2


@pytest.mark.parametrize("mode", ALL_MODES)
def test_nobody_outside_the_modes_temperament_sits(mode):
    for pid in seated(panel_plan(mode)):
        assert panel.fits(personas()[pid], MODES[mode].temperament), (mode, pid)


@pytest.mark.parametrize("mode", ALL_MODES)
def test_a_part_with_a_declared_expert_goes_to_one(mode):
    """When someone the mode admits declares what a part is about among their
    domains, that part is theirs — the SQL part goes to someone who declares
    SQL, the people questions to someone who declares them, because of what
    the persona files say, not because a table does."""
    plan = panel_plan(mode)
    people = personas()
    seated = {s.persona_id for s in plan.segments}
    for segment in plan.segments[1:-1]:
        topic = panel.segment_words(segment)
        experts = {p.id for p in eligible(mode) if panel.words(p.domain_bias) & topic}
        # 2026-10-11: no two on one panel sound alike (`Persona.sound`), and
        # with eight voices for 39 interviewers an expert may sound like
        # someone already seated. The part is theirs if they could sit.
        others = {people[s].sound for s in seated if s in people}
        could_sit = {e for e in experts if e in seated or people[e].sound not in others}
        if could_sit:
            assert segment.persona_id in could_sit, (mode, segment.title, segment.persona_id)


def test_the_panel_grows_with_the_interview():
    assert panel.panel_size(10) == 2
    assert panel.panel_size(30) == 3
    assert panel.panel_size(60) == 4
    plan = panel_plan("mock")
    short = panel.assign(plan.segments, MODES["mock"].temperament, minutes=10)
    assert len(set(short)) <= 2


def test_the_same_plan_seats_the_same_panel():
    """A re-plan must not reshuffle who the student has met — and the order a
    directory listing returns the persona files in must not matter either."""
    plan = panel_plan("mock")
    people = personas()
    shuffled = list(people.items())
    random.Random(7).shuffle(shuffled)
    first = panel.assign(plan.segments, MODES["mock"].temperament, 45, people)
    again = panel.assign(plan.segments, MODES["mock"].temperament, 45, dict(shuffled))
    assert first == again


def test_bounds_that_exclude_everyone_still_seat_someone():
    """An authoring mistake in a mode is never an interview without anyone."""
    impossible = panel.Temperament(target={"warmth": 0.5}, bounds={"warmth": (2.0, 3.0)})
    out = panel.assign([part("warmup"), part("technical"), part("closing")], impossible, 30)
    assert len(out) == 3 and all(out)


# ── data, not code ────────────────────────────────────────────────────────


def test_a_new_persona_joins_the_panel_without_code():
    """The claim the module makes: author a persona who knows a part better
    than anyone seated, and the panel brings them in for it. Held in the
    first seven's world, where nobody else knows SQL."""
    people = {pid: p for pid, p in personas().items() if pid in FIRST_SEVEN}
    dba = people["methodical_engineer"].model_copy(
        update={
            "id": "database_engineer",
            "name": "Farah",
            "title": "Database Engineer",
            "domain_bias": ["sql", "databases", "query tuning", "technical"],
            "warmth": 0.5,
            "patience": 0.5,
            "follow_up_aggression": 0.8,
        }
    )
    plan = panel_plan("mock")
    with_her = panel.assign(plan.segments, MODES["mock"].temperament, 45, {**people, dba.id: dba})
    by_kind = {s.kind: pid for s, pid in zip(plan.segments, with_her, strict=True)}
    assert by_kind["technical"] == "database_engineer"  # the SQL part
    assert by_kind["warmup"] == by_kind["closing"], "the lead still opens and closes"


def test_expertise_counts_declared_domains_over_a_title():
    people = personas()
    topic = panel.words("behavioural", "conflict in a team")
    assert panel.expertise(people["hr_generalist"], topic) > 0
    assert panel.expertise(people["hr_generalist"], topic) > panel.expertise(
        people["methodical_engineer"], topic
    )
    assert panel.expertise(people["methodical_engineer"], frozenset()) == 0.0


# ── interjections ─────────────────────────────────────────────────────────


def test_an_expert_on_the_panel_cuts_in_when_they_clearly_know_more():
    topic = panel.words("behavioural", "conflict", "teamwork")
    seated_ = ["methodical_engineer", "hr_generalist"]
    assert panel.interjector(seated_, "methodical_engineer", topic) == "hr_generalist"


def test_nobody_cuts_in_on_someone_who_knows_as_much():
    topic = panel.words("behavioural", "conflict", "teamwork")
    seated_ = ["methodical_engineer", "hr_generalist"]
    assert panel.interjector(seated_, "hr_generalist", topic) is None


def test_only_someone_on_the_panel_cuts_in():
    topic = panel.words("behavioural", "conflict", "teamwork")
    assert panel.interjector(["methodical_engineer"], "methodical_engineer", topic) is None
    assert (
        panel.interjector(["methodical_engineer", "bar_raiser"], "methodical_engineer", topic)
        is None
    )


# ── sitting in ────────────────────────────────────────────────────────────


def test_a_panel_of_one_gets_someone_sitting_in():
    """One part of its own (a focus session, no job description) would seat
    one interviewer for half an hour; a real round has a second at the table."""
    one_part = [part("warmup"), part("technical", "Recursion"), part("closing")]
    for p in one_part:
        p.question_budget = 0 if p.kind != "technical" else 5
    temperament = MODES["mock"].temperament
    assignment = panel.assign(one_part, temperament, 30)
    assert len(set(assignment)) == 1
    sitter = panel.sit_in(one_part, assignment, temperament, 30)
    assert sitter is not None and sitter not in assignment
    assert panel.fits(personas()[sitter], temperament)
    # Not for a short interview, nor for a panel that already has two.
    assert panel.sit_in(one_part, assignment, temperament, 10) is None
    assert panel.sit_in(one_part, [*assignment[:-1], "hr_generalist"], temperament, 30) is None


def test_the_plan_records_everyone_the_opening_introduces():
    plan = panel_plan("mock")
    assert plan.panel[0] == plan.segments[0].persona_id, "the lead first"
    assert set(plan.panel) >= {s.persona_id for s in plan.segments}


# ── the recovery posture stays on the panel ───────────────────────────────


def test_a_struggling_student_is_handed_to_someone_gentler_they_have_met():
    """§6.4's recovery posture, on a panel: the warmest person already on it,
    not a stranger arriving mid-interview."""
    from backend_M06_Mock_Interview_Engine import replan

    plan = panel_plan("mock")
    lead = plan.panel[0]
    plan = plan.model_copy(update={"panel": [lead, "friendly_recruiter", *plan.panel[1:]]})
    gentler = replan.recovery_persona(plan)
    assert gentler in plan.panel
    people = personas()
    assert people[gentler].speech == "friendly"
    assert people[gentler].warmth > people[lead].warmth


def test_a_panel_with_nobody_gentle_borrows_the_gentlest_the_mode_admits():
    """Found live (2026-10-07): a mock's panel of Priya and the professor,
    and a struggling student. The professor is warmer than Priya but not
    gentle — handing him the rest of the interview changed nothing but the
    panel's shape. The gentlest friendly persona the mode admits joins."""
    from backend_M06_Mock_Interview_Engine import replan

    plan = panel_plan("mock").model_copy(update={"panel": ["methodical_engineer", "professor"]})
    gentler = replan.recovery_persona(plan)
    people = personas()
    assert gentler not in plan.panel
    assert people[gentler].speech == "friendly"
    assert panel.fits(people[gentler], MODES["mock"].temperament)


def test_final_boss_stays_final_boss_when_a_student_struggles():
    """Nobody gentle is admitted to a Final Boss panel: the pace eases by
    mechanics, and the student is not promised a gentler interviewer."""
    from backend_M06_Mock_Interview_Engine import replan

    assert replan.recovery_persona(panel_plan("final_boss")) is None
