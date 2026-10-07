"""Re-planning — FR-6.4, spec §6.4.

Only at a segment boundary, at most two per session, and only from signals
M06 produced on its own hot path. Every change says why in the report, and
says only WHAT, neutrally, while the student is still in the room.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend_M06_Mock_Interview_Engine import replan, report, store
from backend_M06_Mock_Interview_Engine.router import session_out

from .day10 import FAIL, Clock, events, make, rounds_plan, say, session
from .stubs import BankQuestions, verdict

HELD_ABOVE = verdict(band="above", justification="held")


class StretchBank(BankQuestions):
    """M05 choosing every item as the segment's stretch (§6.4's ceiling)."""

    def select(self, request):
        chosen = super().select(request)
        if chosen is not None:
            chosen["reason"] = "stretch"
        return chosen


def run_until(engine, row, predicate, text="I don't know", limit=40):
    for _ in range(limit):
        state = engine.state(row.id)
        if predicate(state) or state.status.value != "live":
            return state
        if state.retry_offer is not None:
            engine.move_on(row.id)
            continue
        if state.open_turn_id is None:
            return state
        say(engine, row, text)
    return engine.state(row.id)


def changed(engine, row) -> list[dict]:
    return [p["plan"]["replans"][-1] for p in events(engine, row, "plan.changed")]


# ── the four triggers ─────────────────────────────────────────────────────


@pytest.mark.gate
def test_struggling_eases_the_rest_of_the_session(db):
    """≥ 3 answers failed at depth ≤ 1 in one round: drop a later round,
    extend the closing, and hand the rest to a gentler interviewer."""
    engine = make(db, plan=rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0)))
    row = session(engine, minutes=45)
    run_until(engine, row, lambda s: bool(changed(engine, row)))

    (change,) = changed(engine, row)
    assert change["trigger"] == "struggling"
    after = {
        s["requirement_ids"][0] if s["requirement_ids"] else s["kind"]: s for s in change["after"]
    }
    assert after["r3"]["dropped_reason"], "a later round was not dropped"
    assert after["r2"]["persona_id"] == replan.RECOVERY_PERSONA
    before_closing = next(s for s in change["before"] if s["kind"] == "closing")
    assert after["closing"]["minutes"] > before_closing["minutes"]


@pytest.mark.gate
def test_a_shared_gap_retargets_the_next_round(db):
    """Two early breaks on ideas that share a prerequisite in M04's graph
    (stacks and hashing both build on arrays): check arrays next."""
    engine = make(db, plan=rounds_plan(("r1", 2, 7.0), ("r2", 2, 7.0), ("r3", 2, 7.0)))
    row = session(engine, minutes=45)
    state = run_until(engine, row, lambda s: bool(changed(engine, row)))

    (change,) = changed(engine, row)
    assert change["trigger"] == "gap_discovered"
    nxt = next(s for s in change["after"] if s["requirement_ids"] == ["r2"])
    assert nxt["concept_ids"][0] == "concept:arrays"
    assert change["live_note"] == "Adjusting — I want to check Arrays first."
    assert state.plan.segments  # and the session carried on


def test_a_round_that_ran_over_compresses_the_next(db):
    clock = Clock()
    engine = make(
        db, plan=rounds_plan(("r1", 2, 7.0), ("r2", 4, 14.0), ("r3", 2, 7.0)), clock=clock
    )
    row = session(engine, minutes=45)
    say(engine, row, "I don't know")  # the warm-up; r1 opens
    started = engine.state(row.id).segment_started_used_s
    clock.at(started + 7 * 60 * 1.5)  # 50% over a 7-minute round
    say(engine, row, "I don't know")

    (change,) = changed(engine, row)
    assert change["trigger"] == "time_overrun"
    before = next(s for s in change["before"] if s["requirement_ids"] == ["r2"])
    after = next(s for s in change["after"] if s["requirement_ids"] == ["r2"])
    assert after["question_budget"] < before["question_budget"]
    closing = [s for s in change["after"] if s["kind"] == "closing"]
    assert closing and closing[0]["dropped_reason"] is None, "the closing was touched"


def test_a_stretch_answered_above_adds_a_question_to_each_part_left(db):
    engine = make(
        db,
        plan=rounds_plan(("r1", 1, 4.0), ("r2", 1, 4.0), ("r3", 1, 4.0)),
        m05=StretchBank(),
        verdicts=[HELD_ABOVE],
    )
    row = session(engine, minutes=45)
    run_until(
        engine, row, lambda s: bool(changed(engine, row)), text="Arrays store it contiguously."
    )

    (change,) = changed(engine, row)
    assert change["trigger"] == "ceiling_hit"
    for rid in ("r2", "r3"):
        before = next(s for s in change["before"] if s["requirement_ids"] == [rid])
        after = next(s for s in change["after"] if s["requirement_ids"] == [rid])
        assert after["question_budget"] == before["question_budget"] + 1


# ── the rules around them ─────────────────────────────────────────────────


def _state_and_events(db):
    """The state as it stood at the first boundary, before the engine's own
    re-plan: the plan it had then, and the round it was leaving."""
    from backend_M06_Mock_Interview_Engine.contracts import PlannedSegment

    engine = make(db, plan=rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0)))
    row = session(engine, minutes=45)
    run_until(engine, row, lambda s: bool(changed(engine, row)))
    first = events(engine, row, "plan.changed")[0]["plan"]["replans"][0]
    state = engine.state(row.id)
    original = [PlannedSegment.model_validate(s) for s in first["before"]]
    leaving = next(s for s in original if s.index == first["at_segment"])
    at_boundary = state.model_copy(
        update={
            "plan": state.plan.model_copy(update={"segments": original, "replans": []}),
            "current_segment": leaving.index,
        }
    )
    return engine, row, at_boundary, leaving


def test_at_most_two_replans_per_session(db):
    """Trap 4: a supervisor that keeps re-planning produces an interview that
    wanders."""
    engine, row, state, leaving = _state_and_events(db)
    found = replan.evaluate(
        state, store.events_for(db, row.id), leaving, engine.clock(), lambda _c: None
    )
    assert found is not None
    full = state.plan.model_copy(update={"replans": [found, found]})
    capped = state.model_copy(update={"plan": full})
    assert (
        replan.evaluate(
            capped, store.events_for(db, row.id), leaving, engine.clock(), lambda _c: None
        )
        is None
    )


@pytest.mark.gate
def test_replanning_reads_no_m13_field(db):
    """§6.4: M13's scores are asynchronous and uncalibrated, so they never
    steer a session. Feed the decision an evaluation saying the opposite of
    what the hot path saw: the decision must not move."""
    engine, row, state, leaving = _state_and_events(db)
    log = store.events_for(db, row.id)
    plain = replan.evaluate(state, log, leaving, engine.clock(), lambda _c: None)
    lying = [
        *log,
        *(
            SimpleNamespace(
                seq=10_000 + i,
                kind="evaluation.completed",
                turn_index=t.turn_index,
                payload={
                    "turn_id": str(t.turn_id),
                    "status": "complete",
                    "composite": 4.0,
                    "band": "above",
                    "justification": "held",
                },
            )
            for i, t in enumerate(state.transcript)
            if t.role == "candidate"
        ),
    ]
    other = replan.evaluate(state, lying, leaving, engine.clock(), lambda _c: None)
    assert plain is not None and other is not None
    assert plain.trigger == other.trigger
    assert plain.signals == other.signals


@pytest.mark.gate
def test_the_reason_waits_for_the_report(db):
    """Mid-session a re-plan shows only a neutral note — "that round was a hard
    one" while the student is still in it is a live score (§2.2). The full
    reason is in the notes afterwards."""
    engine = make(db, plan=rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0)))
    row = session(engine, minutes=45)
    run_until(engine, row, lambda s: bool(changed(engine, row)))
    state = engine.state(row.id)
    live = session_out(state)

    assert live.plan.replans == [], "the reason reached the student mid-session"
    assert live.plan_notes and "hard" not in live.plan_notes[0].lower()

    engine.end(row.id, "ended_by_student")
    from ai_core.timeutil import utcnow

    built = report.build(engine.state(row.id), store.events_for(db, row.id), utcnow())
    assert built.plan_changes and "hard round" in built.plan_changes[0]


def test_a_70_percent_narrowing_takes_the_crossings_one_change(db):
    """The 70% check runs first in a step. When the same step also ends a
    round, the narrowing has already answered the clock — and the clock is
    what a boundary answers first anyway. A second change at that crossing
    is two live notes at once, and the wandering plan Trap 4 is about."""
    clock = Clock()
    # Four questions in each later round: at two minutes a question, the
    # eight they owe cannot fit in what is left at 70%, so there is debt to
    # narrow (with two each, everything still fit and nothing narrowed).
    engine = make(
        db, plan=rounds_plan(("r1", 3, 10.0), ("r2", 4, 7.0), ("r3", 4, 7.0)), clock=clock
    )
    row = session(engine, minutes=45)
    for _ in range(3):  # the warm-up, then two of the first round's three
        state = say(engine, row, "I don't know")
    assert state.questions_in_segment(state.current_segment) == 3

    clock.at(0.72 * 45 * 60)  # its last answer: past 70%, and over its clock
    say(engine, row, "I don't know")

    (only,) = changed(engine, row)
    assert "70% mark" in only["student_sentence"]


def test_what_a_replan_drops_is_owed_to_m02(db):
    from sqlmodel import select

    from backend_M06_Mock_Interview_Engine.models import LedgerOutbox

    engine = make(db, plan=rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0)))
    row = session(engine, minutes=45)
    run_until(engine, row, lambda s: bool(changed(engine, row)))
    skipped = {
        r.requirement_id
        for r in db.exec(select(LedgerOutbox).where(LedgerOutbox.ledger_state == "skipped")).all()
    }
    assert "r3" in skipped


def test_no_m04_means_no_gap_trigger_rather_than_a_guess(db):
    """The gap needs M04's graph to say what two concepts share. Without it
    the trigger does not fire — it never guesses a prerequisite."""
    from .stubs import DownMemory

    engine = make(
        db, plan=rounds_plan(("r1", 2, 7.0), ("r2", 2, 7.0), ("r3", 2, 7.0)), memory=DownMemory()
    )
    row = session(engine, minutes=45)
    run_until(engine, row, lambda s: s.current_segment >= 2)
    assert not changed(engine, row)


# keep FAIL imported for readers of this file: the default verdict is a fail
assert FAIL["justification"] == "failed"
