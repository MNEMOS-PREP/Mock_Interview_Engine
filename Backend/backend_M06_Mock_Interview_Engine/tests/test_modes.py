"""Modes as configs of one engine — FR-6.8, FR-6.9, FR-6.3.

Before day 9 the mode table lived in three places, each knowing one column.
These tests hold it to one place, and hold each mode to the mechanics its
summary promises — the summary is what a student reads when choosing.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import adapters, outbox, planner, store
from backend_M06_Mock_Interview_Engine.contracts import Mode
from backend_M06_Mock_Interview_Engine.engine import (
    Engine,
    ThetaCache,
    hint_offer,
    ladder_config,
    speaker,
)
from backend_M06_Mock_Interview_Engine.modes import ENSEMBLE_BY_MODE, MODES, mode_config
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_planner import JD, REQUIREMENTS, SESSION, coverage

ALL_MODES = tuple(Mode.__args__)


def make(db, llm=None, **upstreams) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(**upstreams),
        llm=llm or StubLLM([verdict()]),
        thetas=ThetaCache(),
    )


def live(engine: Engine, mode: str):
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=30
    )
    engine.start(row.id)
    return row


def panel_plan(mode: str):
    """A posting with a technical and a behavioural round, and a shaky claim."""
    rounds = [
        {"round_type": "verbal", "minutes": 14.0, "question_count": 4, "requirement_ids": ["R-1"]},
        {"round_type": "verbal", "minutes": 7.0, "question_count": 2, "requirement_ids": ["R-2"]},
    ]
    claim = {"id": "c-1", "text": "Built a thing", "risk_band": "risky", "probes": [{"q": 1}]}
    return planner.assemble(
        planner.PlanInputs(
            session_id=SESSION,
            mode=mode,
            requested_minutes=45,
            jd_id=JD,
            coverage=coverage(rounds=rounds),
            requirements=REQUIREMENTS,
            available_round_types=("dsa_verbal",),
            claims=(claim,),
        )
    )


def who(plan) -> dict[str, str]:
    return {s.kind: s.persona_id for s in plan.segments}


# ── one table ─────────────────────────────────────────────────────────────


def test_every_mode_the_contract_names_has_a_config():
    assert set(MODES) == set(ALL_MODES)


def test_the_ensemble_table_is_derived_not_copied():
    """The fairness gate and the contract tests read `outbox.ENSEMBLE_BY_MODE`;
    it has to be the same table, not a second one that can disagree."""
    assert outbox.ENSEMBLE_BY_MODE is ENSEMBLE_BY_MODE
    assert ENSEMBLE_BY_MODE == {m: c.ensemble for m, c in MODES.items()}


def test_an_unknown_mode_runs_as_mock():
    assert mode_config("nonsense").id == "mock"


def test_no_mode_promises_a_mechanic_that_does_not_exist():
    """Voice needs M11, camera M12, and there is no interruption in text. A
    summary that offers them is a promise the session breaks."""
    for config in MODES.values():
        lowered = config.summary.lower()
        for absent in ("voice", "camera", "interrupt", "speak"):
            assert absent not in lowered, f"{config.id} promises {absent!r}"


# ── FR-6.3: a panel, one persona per segment ─────────────────────────────


def test_a_mock_is_a_panel():
    """The lead engineer opens and closes, a professor takes the project, HR
    takes the people questions."""
    assert who(panel_plan("mock")) == {
        "warmup": "methodical_engineer",
        "project": "professor",
        "technical": "methodical_engineer",
        "behavioural": "hr_generalist",
        "closing": "methodical_engineer",
    }


def test_final_boss_is_bar_raisers_and_never_a_friendly_voice():
    personas = who(panel_plan("final_boss"))
    assert personas["technical"] == "bar_raiser"
    assert personas["warmup"] == "bar_raiser"
    assert "friendly_recruiter" not in personas.values()


def test_practice_is_gentle_throughout():
    registers = {persona(p).speech for p in who(panel_plan("practice")).values()}
    assert registers == {"friendly"}


def test_the_new_voice_in_a_panel_introduces_itself(db):
    """A hand-over in a real panel is a person saying who they are. The first
    line of a round run by someone new is their greeting."""
    from backend_M06_Mock_Interview_Engine.engine import bridge_line, introduced

    plan = panel_plan("mock")
    project = next(s for s in plan.segments if s.kind == "project")
    technical = next(s for s in plan.segments if s.kind == "technical")
    met = frozenset({"methodical_engineer"})
    assert "Dr. Raghavan" in bridge_line(project, met)
    # Priya has spoken already, so her round gets a bridge, not a second hello.
    assert "Hello" not in bridge_line(technical, met)
    assert introduced is not None


# ── the mechanics each mode claims ────────────────────────────────────────


@pytest.mark.gate
def test_final_boss_offers_no_hints_from_the_table(db):
    """FR-6.9: pressure via mechanics. The reason comes from the config, not
    from a string compared somewhere else."""
    engine = make(db, m05=BankQuestions(), m01=NoClaims())
    row = live(engine, "final_boss")
    offer = hint_offer(engine.state(row.id))
    assert offer.available is False
    assert offer.unavailable_reason == MODES["final_boss"].no_hints_reason


def test_every_other_mode_offers_hints(db):
    for mode in ("practice", "mock", "real_drive"):
        engine = make(db, m05=BankQuestions(), m01=NoClaims())
        row = live(engine, mode)
        assert hint_offer(engine.state(row.id)).available is True, mode


def test_the_ladder_goes_as_deep_as_the_persona(db):
    """Final Boss goes to the cap; Practice stops at two follow-ups."""
    depths = {}
    for mode in ALL_MODES:
        engine = make(db, m05=BankQuestions(), m01=NoClaims())
        row = live(engine, mode)
        config = ladder_config(engine.state(row.id))
        depths[mode] = config.max_depth
        assert config.steelman_enabled is False, "FR-6.20 is blocked in every mode"
    assert depths["final_boss"] == 5
    assert depths["practice"] == 2


def test_practice_stops_after_two_follow_ups_and_final_boss_does_not(db):
    """The same answer, held at every rung, in two modes."""
    reached = {}
    for mode in ("practice", "final_boss"):
        engine = make(db, llm=StubLLM([verdict(band="at")]), m05=BankQuestions(), m01=NoClaims())
        row = live(engine, mode)
        start = engine.state(row.id).questions_asked
        for _ in range(8):
            state = engine.state(row.id)
            if state.open_turn_id is None or state.questions_asked != start:
                break
            engine.answer(row.id, state.open_turn_id, "It hashes to a bucket and reads it.")
        events = store.events_for(db, row.id)
        reached[mode] = max(
            (int(e.payload.get("probe_depth") or 0) for e in events if e.kind == "question.asked"),
            default=0,
        )
    assert reached["practice"] == 2
    assert reached["final_boss"] > reached["practice"]


def test_the_speaker_is_the_segments_persona(db):
    engine = make(db, m05=BankQuestions(), m01=NoClaims())
    row = live(engine, "final_boss")
    assert speaker(engine.state(row.id)).id == "bar_raiser"
