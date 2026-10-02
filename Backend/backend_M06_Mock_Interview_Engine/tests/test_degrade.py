"""The degradation ladder — spec §10, EC-6.12, §8's badge; and "Everything fails".

What moves a session up the ladder is what it saw: model turns failing in a
row. What must not move is the standard (AC-6.17) — nor the student's ability
to finish: every rung completes the session, and the last one ends it
honestly.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import degrade, outbox, report, store
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox, LLMCall

from .day10 import Clock, deep_bank, events, make, rounds_plan, say, session
from .stubs import StubLLM, verdict

ROUNDS = rounds_plan(("r1", 3, 10.0), ("r2", 2, 7.0), ("r3", 2, 7.0))
ANSWER = "Arrays keep elements contiguous, so an index is an offset."


class DownLLM(StubLLM):
    """A provider failing every call until `up` is set."""

    def __init__(self, **kw):
        super().__init__([verdict()], **kw)
        self.up = False

    def structured(self, **kw):
        if not self.up:
            from backend_M06_Mock_Interview_Engine.llm import LLMResult

            self.structured_calls.append(kw)
            return LLMResult(ok=False, reason="HTTP 500", job=kw["job"], model="stub")
        return super().structured(**kw)

    def stream(self, **kw):
        if not self.up:
            from backend_M06_Mock_Interview_Engine.llm import LLMResult

            self.stream_calls.append(kw)
            yield LLMResult(ok=False, reason="HTTP 500", job=kw["job"], model="stub")
            return
        yield from super().stream(**kw)


def degraded(db, clock=None, plan=ROUNDS):
    clock = clock or Clock()
    llm = DownLLM()
    engine = make(db, plan=plan, m05=deep_bank(), clock=clock, llm=llm)
    row = session(engine, minutes=45)
    return engine, row, clock, llm


def answer(engine, row):
    state = engine.state(row.id)
    if state.retry_offer is not None:
        return engine.move_on(row.id)
    return say(engine, row, ANSWER)


# ── the rungs ─────────────────────────────────────────────────────────────


def test_the_ladder_is_read_off_what_the_session_saw():
    assert degrade.level(model_failures=0, upstream_degraded=False, wrapped=False) == "L0"
    assert degrade.level(model_failures=0, upstream_degraded=True, wrapped=False) == "L1"
    assert degrade.level(model_failures=1, upstream_degraded=False, wrapped=False) == "L2"
    assert (
        degrade.level(model_failures=degrade.WRAP_AFTER, upstream_degraded=False, wrapped=False)
        == "L3"
    )
    assert degrade.level(model_failures=0, upstream_degraded=False, wrapped=True) == "L3"
    assert (
        degrade.level(model_failures=degrade.PANIC_AFTER, upstream_degraded=True, wrapped=True)
        == "panic"
    )


@pytest.mark.gate
def test_failing_turns_climb_the_ladder_and_l3_wraps_up_early(db):
    """L2 after one failed turn (a template carried it); L3 after two — the
    rounds after this one give way, M02 hears `skipped`, and the student sees
    §8's "Wrapping up a little early"."""
    engine, row, clock, llm = degraded(db)
    levels = []
    for _ in range(degrade.WRAP_AFTER):
        state = answer(engine, row)
        levels.append(state.flags.degradation_level)
    assert levels[0] == "L2" and levels[-1] == "L3"

    (change,) = [p["plan"]["replans"][-1] for p in events(engine, row, "plan.changed")]
    assert change["trigger"] == "degraded"
    assert change["live_note"] == f"{degrade.BADGE}."
    dropped = [s for s in change["after"] if s["dropped_reason"]]
    assert dropped and all(s["kind"] != "closing" for s in dropped)


@pytest.mark.gate
def test_panic_stops_asking_the_model_and_the_session_completes(db):
    """EC-6.12: past `PANIC_AFTER` failed turns the model is not called at
    all — stems and rules carry the session to its end."""
    engine, row, clock, llm = degraded(db)
    for _ in range(degrade.PANIC_AFTER):
        answer(engine, row)
    assert engine.state(row.id).flags.degradation_level == "panic"
    calls_before = len(llm.structured_calls) + len(llm.stream_calls)

    for _ in range(40):
        state = engine.state(row.id)
        if state.is_final:
            break
        if state.open_turn_id is None and state.retry_offer is None:
            engine.start(row.id)
        elif state.transcript[-1].question_source == "closing":
            say(engine, row, "No, that's all.")
        else:
            answer(engine, row)
    assert engine.state(row.id).status is SessionStatus.ended
    assert len(llm.structured_calls) + len(llm.stream_calls) == calls_before, (
        "the model was asked while the circuit was open"
    )


def test_a_minute_on_the_model_is_tried_again_and_the_session_climbs_down(db):
    engine, row, clock, llm = degraded(db)
    for _ in range(degrade.PANIC_AFTER):
        answer(engine, row)
    llm.up = True
    clock.at(clock.offset + degrade.PROBE_EVERY_S + 1)
    state = answer(engine, row)
    assert state.flags.model_failures == 0
    # Back down the ladder — but the cut plan stays cut, so the badge stays true.
    assert state.flags.degradation_level == "L3"


def test_the_guard_failing_is_not_the_interview_degrading(db):
    """The guard fails open by design (EC-6.6); its outages are its own."""
    from .stubs import GuardedStubLLM

    engine = make(
        db, plan=ROUNDS, m05=deep_bank(), llm=GuardedStubLLM([verdict()], fail_guard="HTTP 500")
    )
    row = session(engine, minutes=45)
    for _ in range(4):
        state = answer(engine, row)
    assert state.flags.degradation_level in ("L0", "L1")
    assert state.flags.model_failures == 0


def test_the_standard_does_not_move_with_the_ladder(db):
    """AC-6.17: a templated interviewer is not a different exam. The answers
    queued for M13 during an outage carry the mode's own ensemble."""
    engine, row, clock, llm = degraded(db)
    for _ in range(degrade.PANIC_AFTER + 1):
        answer(engine, row)
    rows = db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)).all()
    assert rows and {r.payload["ensemble"] for r in rows} == {outbox.ENSEMBLE_BY_MODE["mock"]}


# ── everything fails (§10) ───────────────────────────────────────────────


@pytest.mark.gate
def test_a_step_that_keeps_crashing_ends_the_session_honestly(db, monkeypatch):
    """The first crash is retried; the second ends the session — aborted,
    with the apology said, nothing still queued sent to be scored, and the
    notes saying plainly that it does not count."""
    import backend_M06_Mock_Interview_Engine.engine as engine_module

    engine, row, clock, llm = degraded(db)
    llm.up = True
    say(engine, row, ANSWER)  # one answer queued for M13 before anything fails
    open_turn = engine.state(row.id).open_turn_id

    def crash(*_a, **_k):
        raise RuntimeError("the graph fell over")

    monkeypatch.setattr(engine_module, "run_step", crash)
    with pytest.raises(RuntimeError):
        engine.answer(row.id, open_turn, ANSWER)
    state = engine.start(row.id)  # the client retries; it crashes again

    assert state.status is SessionStatus.aborted and state.end_reason == "system_failure"
    assert state.transcript[-1].text == degrade.APOLOGY
    queued = db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)).all()
    assert queued and all(r.state == outbox.VOID for r in queued)

    built = report.build(state, store.events_for(db, row.id), clock())
    assert "on us" in built.framing
    assert all(not q.scored for q in built.questions)


def test_one_crash_is_retried_not_ended(db, monkeypatch):
    import backend_M06_Mock_Interview_Engine.engine as engine_module

    engine, row, clock, llm = degraded(db)
    llm.up = True
    open_turn = engine.state(row.id).open_turn_id
    real = engine_module.run_step
    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("a blip")
        return real(*a, **k)

    monkeypatch.setattr(engine_module, "run_step", once)
    with pytest.raises(RuntimeError):
        engine.answer(row.id, open_turn, ANSWER)
    state = engine.start(row.id)
    assert state.status is SessionStatus.live and state.flags.step_failures == 0


# ── M13's words in the notes ─────────────────────────────────────────────


def test_m13s_words_reach_the_notes_and_its_numbers_do_not(db):
    """The display gate: reasoning, missing points and verified quotes — the
    qualitative half M13 lets a student see — and no number, ever."""
    engine = make(db, plan=ROUNDS, m05=deep_bank(), llm=StubLLM([verdict()]))
    m13 = engine.upstreams.m13
    real = m13.evaluate

    def scored(request):
        out = real(request)
        out["aggregated"] = [
            {
                "dimension_key": "correctness",
                "raw_score": 3,
                "calibrated_score": None,
                "reasoning": "Names contiguity as the reason indexing is constant time.",
                "missing_key_points": ["cache locality"],
                "evidence": [
                    {"span": {"quote": "Arrays keep elements contiguous", "verified": True}},
                    {"span": {"quote": "something never said", "verified": False}},
                ],
            }
        ]
        return out

    m13.evaluate = scored
    row = session(engine, minutes=45)
    say(engine, row, ANSWER)
    engine.deliver(row.id)
    engine.end(row.id, "ended_by_student")

    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    noted = [f for q in built.questions for f in q.feedback]
    assert noted and noted[0].reasoning.startswith("Names contiguity")
    assert noted[0].quotes == ["Arrays keep elements contiguous"]
    assert noted[0].missing == ["cache locality"]
    dumped = built.model_dump_json()
    assert '"raw_score"' not in dumped and '"calibrated_score"' not in dumped


def test_mid_session_the_notes_carry_no_verdict(db):
    engine = make(db, plan=ROUNDS, m05=deep_bank(), llm=StubLLM([verdict()]))
    m13 = engine.upstreams.m13
    real = m13.evaluate
    m13.evaluate = lambda request: {
        **real(request),
        "aggregated": [{"dimension_key": "correctness", "reasoning": "Held.", "evidence": []}],
    }
    row = session(engine, minutes=45)
    say(engine, row, ANSWER)
    engine.deliver(row.id)
    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    assert all(not q.feedback for q in built.questions)


# keep the import used for readers: the trace records every failed call
assert LLMCall.__tablename__


# ── AC-6.9's number, from the log ────────────────────────────────────────


def test_the_reliability_numbers_are_counted_off_the_log(client, as_student, engine):
    """Staff only — it counts other students' sessions."""
    import uuid

    from sqlmodel import Session

    from .conftest import admin

    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    with Session(engine) as db:
        row = store.get_session_row(db, uuid.UUID(sid))
        store.record(db, row, "connection.lost", step="away:1")
        store.record(db, row, "connection.resumed", step="back:1", payload={"grace_s": 30.0})
        store.record(db, row, "connection.lost", step="away:2")

    assert client.get("/v1/interviews/reliability", headers=as_student).status_code == 403
    body = client.get("/v1/interviews/reliability", headers=admin()).json()
    assert body["disconnects"] == 2 and body["returns"] == 1
    assert body["reconnect_rate"] == 0.5 and body["reconnect_target"] == 0.95
