"""A different panel each interview (2026-10-07).

"Every interview it's only Priya and Raghavan … if it's Meera and Raghavan
it becomes boring, add multiple." Seven personas, and a lead chosen as
whoever sits closest to the mode, meant every Mock opened with the same
person. Now the cast is three or four per track, and the session decides
among people who fit about equally well — with whoever the student met
lately standing back, and never two people who sound the same at one table.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import panel, planner, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.modes import MODES
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make, say

pytestmark = pytest.mark.rotation

TRACKS = {"ml_verbal": {"title": "Machine learning", "kind": "technical"}}


def ml_plan(session_id: uuid.UUID, mode: str = "mock", recent=frozenset(), minutes: int = 30):
    return planner.assemble(
        planner.PlanInputs(
            session_id=session_id,
            mode=mode,
            requested_minutes=minutes,
            available_round_types=("ml_verbal",),
            track="ml_verbal",
            tracks=TRACKS,
            recent_personas=frozenset(recent),
        )
    )


#: Session ids fixed, so the draw is the same on every run: a test of a
#: spread over random ids is a test that fails one run in five.
SESSIONS = [
    uuid.uuid5(uuid.UUID("0c0ffee0-0000-4000-8000-000000000000"), str(i)) for i in range(24)
]


def test_different_interviews_meet_different_people():
    """In one mode and one track the people who fit are few — two or three
    ML interviewers suit a Mock — so the panel varies more than its lead."""
    plans = [ml_plan(session) for session in SESSIONS]
    leads = {plan.panel[0] for plan in plans}
    panels = {tuple(plan.panel) for plan in plans}
    assert len(leads) >= 2, f"24 interviews, {len(leads)} lead(s): {sorted(leads)}"
    assert len(panels) >= 4, f"24 interviews, {len(panels)} panels: {sorted(panels)}"


def test_one_interview_always_seats_the_same_panel():
    """A re-plan of the same session must not reshuffle who the student met."""
    session = uuid.uuid4()
    assert ml_plan(session).panel == ml_plan(session).panel


def test_an_ml_interview_is_run_by_people_who_know_ml():
    for session in SESSIONS[:12]:
        plan = ml_plan(session)
        part = next(s for s in plan.segments if s.rubric_round_types == ["ml_verbal"] and s.index)
        knows = panel.words(persona(part.persona_id).domain_bias)
        assert {"machine", "ml"} & knows, (part.persona_id, sorted(knows))


def test_whoever_the_student_met_lately_stands_back():
    for session in SESSIONS[:12]:
        before = ml_plan(session).panel
        after = ml_plan(session, recent=before).panel
        assert after[0] not in before, "last time's lead does not open again"


@pytest.mark.parametrize("mode", tuple(MODES))
def test_nobody_on_a_panel_sounds_like_anyone_else(mode):
    """M11 has seven voices for a cast of thirty-nine: two of them at one
    table would be two names in one voice."""
    for session in SESSIONS[:16]:
        plan = ml_plan(session, mode=mode, minutes=45)
        sounds = [persona(p).sound for p in plan.panel]
        assert len(sounds) == len(set(sounds)), (mode, plan.panel)


def test_the_next_interview_opens_with_someone_new(db):
    """End to end: the panel a student met is what the next plan avoids."""
    engine = make(db, llm=StubLLM([verdict()] * 40), m05=BankQuestions(), m01=NoClaims())
    student = uuid.uuid4()
    leads = []
    for _ in range(3):
        row, _ = store.create_session(
            engine.db, candidate_id=student, kind="mock", mode="mock", minutes=30
        )
        engine.start(row.id)
        state = engine.state(row.id)
        assert state.status is SessionStatus.live
        leads.append(state.plan.panel[0])
        say(engine, row, "A hash map reads the bucket its key hashes to.")
        engine.end(row.id, "ended_by_student")
    assert len(set(leads)) == 3, leads
