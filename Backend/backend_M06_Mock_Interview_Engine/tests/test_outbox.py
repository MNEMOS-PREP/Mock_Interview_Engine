"""What M06 owes M13 and M02 — FR-6.14, FR-6.24, AC-6.2, AC-6.16."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, outbox, report, store, sweeper
from backend_M06_Mock_Interview_Engine.contracts import (
    InterviewPlan,
    PlannedSegment,
    SessionStatus,
)
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox, LedgerOutbox

from .stubs import BankQuestions, DownMemory, StubLLM, drill_body, verdict

JD_ID = uuid.UUID("0d0d0d0d-0000-4000-8000-00000000000d")


def make(db, llm=None, **upstreams) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(**upstreams),
        llm=llm or NullLLM(),
        thetas=ThetaCache(),
    )


def mock_with_plan(engine: Engine, *, jd: bool = True, requirements=("r1", "r2")):
    """A session with M02's plan behind it — day 5 builds this for real."""
    row, _ = store.create_session(
        engine.db,
        candidate_id=uuid.uuid4(),
        kind="mock",
        mode="mock",
        minutes=10,
        jd_id=JD_ID if jd else None,
    )
    plan = InterviewPlan(
        id=uuid.uuid4(),
        session_id=row.id,
        mode="mock",
        total_minutes=10,
        segments=[
            PlannedSegment(
                index=0,
                kind="technical",
                title="Data structures",
                persona_id="methodical_engineer",
                minutes=9.0,
                question_budget=2,
                requirement_ids=list(requirements),
                concept_ids=["concept:time_complexity"],
                rubric_round_types=["dsa_verbal"],
            )
        ],
        jd_id=JD_ID if jd else None,
    )
    store.record(
        engine.db, row, "plan.set", step="plan", payload={"plan": plan.model_dump(mode="json")}
    )
    return row


def say(engine: Engine, row, text: str):
    state = engine.state(row.id)
    return engine.answer(row.id, state.open_turn_id, text)


def queued(db, session_id) -> list[EvaluationOutbox]:
    return list(
        db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == session_id)).all()
    )


def ledger(db, session_id) -> list[LedgerOutbox]:
    return list(db.exec(select(LedgerOutbox).where(LedgerOutbox.session_id == session_id)).all())


# ── what reaches M13 (AC-6.2) ────────────────────────────────────────────


@pytest.mark.gate
def test_the_request_m13_receives_carries_the_answer_and_nothing_else(db):
    """AC-6.2. What is absent is the blind-scoring property."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear: constant work, n times.")

    rows = queued(db, row.id)
    assert len(rows) == 1
    payload = rows[0].payload
    assert set(payload) == set(outbox.EVALUATION_KEYS)
    assert payload["answer_text"] == "Linear: constant work, n times."
    assert payload["ensemble"] == "n3_het_v1"
    assert payload["round_type"] == "dsa_verbal"

    raw = json.dumps(payload).lower()
    for leaked in ("interviewer", "probe", "verdict", "band", "justification", "steelman", "move"):
        assert leaked not in raw, leaked
    # One question's answer, never the conversation around it.
    assert "first question" not in raw


def test_practice_mode_asks_for_the_single_evaluator(db):
    """M13's `n1_practice` drops the COUNT, never the tier (its ensemble.py)."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row, _ = store.create_session(
        db, candidate_id=uuid.uuid4(), kind="mock", mode="practice", minutes=10
    )
    engine.start(row.id)
    say(engine, row, "Linear.")
    assert queued(db, row.id)[0].payload["ensemble"] == "n1_practice"


# ── what is not queued, and why ──────────────────────────────────────────


def test_a_drill_turn_is_never_queued(db):
    engine = make(db, llm=StubLLM([verdict()] * 4))
    body = drill_body(uuid.uuid4())
    row, _ = engine.create_drill(
        candidate_id=uuid.UUID(body["candidate_id"]),
        claim_id=body["claim_id"],
        claim_text=body["claim_text"],
        probes=body["probes"],
        source_module="M01",
    )
    engine.start(row.id)
    say(engine, row, "A ResNet-50 on PlantVillage.")
    assert queued(db, row.id) == []


def test_a_backup_question_is_not_queued_and_the_report_says_why(db):
    """M13 resolves a package from M05; M06's own fallback items are not there."""
    from .stubs import DownQuestions

    engine = make(db, llm=StubLLM([verdict()] * 4), m05=DownQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "A hash map.")
    assert queued(db, row.id) == []

    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    question = built.questions[0]
    assert question.scored is False
    assert question.scoring_status == "not_scored"
    assert "backup set" in question.not_scored_reason


# ── delivery (FR-6.14) ───────────────────────────────────────────────────


def test_delivery_sends_to_m13_and_records_what_came_back(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    assert engine.state(row.id).flags.evaluation_pending == 1

    drained = engine.deliver(row.id)
    assert drained.evaluations_sent == 1
    assert engine.upstreams.m13.requests[0]["answer_text"] == "Linear."
    assert queued(db, row.id)[0].state == outbox.SENT

    state = engine.state(row.id)
    assert state.flags.evaluation_pending == 0
    turn_id = next(t.turn_id for t in state.transcript if t.role == "candidate")
    assert state.evaluation_status[str(turn_id)] == "complete"

    built = report.build(state, store.events_for(db, row.id), engine.clock())
    assert built.questions[0].scoring_status == "complete"
    # A status, never a number: the report has nowhere to put one, and M13's
    # display gate is what decides whether anybody may see it at all.
    score_fields = {
        name
        for model in (report.SessionReport, report.QuestionReport)
        for name in model.model_fields
        if "scor" in name  # "scoring_status" does not contain "score"
    }
    # Three, and every one of them a word: can it be scored, why not, and
    # where it is. Nothing numeric.
    assert score_fields == {"scored", "not_scored_reason", "scoring_status"}
    assert "composite" not in json.dumps(built.model_dump(mode="json"))


def test_m13_being_down_keeps_the_row_and_the_student_is_told(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    engine.upstreams.m13.fail = True
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")

    drained = engine.deliver(row.id)
    assert drained.evaluations_sent == 0 and drained.failed == 1
    waiting = queued(db, row.id)[0]
    assert waiting.state == outbox.PENDING
    assert waiting.attempts == 1
    assert "fixture set to fail" in waiting.last_error

    built = report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())
    assert built.questions[0].scoring_status == "queued"
    assert any("still with the evaluator" in note for note in built.notes)

    # And it goes when M13 comes back.
    engine.upstreams.m13.fail = False
    assert engine.deliver(row.id).evaluations_sent == 1


def test_a_row_nobody_can_deliver_is_held_rather_than_retried_for_ever(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    engine.upstreams.m13.fail = True
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    for _ in range(outbox.MAX_ATTEMPTS):
        engine.deliver(row.id)
    held = queued(db, row.id)[0]
    assert held.state == outbox.HELD
    assert outbox.status(db, row.id)["evaluations"]["held"] == 1


@pytest.mark.gate
def test_delivering_twice_sends_once(db):
    """AC-6.16, on the outbox: at-least-once delivery, never twice from here."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    engine.deliver(row.id)
    engine.deliver(row.id)
    assert len(engine.upstreams.m13.requests) == 1


@pytest.mark.gate
def test_two_senders_over_the_same_row_post_it_once(db):
    """The first live run's bug: a background task and an explicit drain both
    took the same row, so M13 scored one answer three times concurrently and
    the third call timed out at 60 s. A row is claimed before it is sent."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")

    second: list[outbox.Drained] = []

    def while_m13_is_working(_request):
        # Somebody else drains this session while the first request is open.
        second.append(outbox.drain(db, engine.upstreams, session_id=row.id))

    engine.upstreams.m13.on_request = while_m13_is_working
    first = engine.deliver(row.id)

    assert len(engine.upstreams.m13.requests) == 1
    assert first.evaluations_sent == 1
    assert second[0].evaluations_sent == 0
    assert second[0].in_flight == 1
    assert queued(db, row.id)[0].state == outbox.SENT


def test_a_row_abandoned_mid_send_is_picked_up_again(db):
    """A process that dies between the claim and the reply must not strand the
    row. One that is merely slow must keep it."""
    from datetime import timedelta

    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")

    claimed = queued(db, row.id)[0]
    claimed.state, claimed.claimed_at = outbox.SENDING, engine.clock()
    db.commit()
    assert engine.deliver(row.id).evaluations_sent == 0  # still in flight
    assert engine.state(row.id).flags.evaluation_pending == 1  # and still owed

    claimed.claimed_at = engine.clock() - timedelta(seconds=outbox.STALE_CLAIM_S + 1)
    db.commit()
    assert engine.deliver(row.id).evaluations_sent == 1
    assert queued(db, row.id)[0].state == outbox.SENT


def test_a_retried_answer_queues_one_evaluation(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    open_turn = engine.state(row.id).open_turn_id
    engine.answer(row.id, open_turn, "Linear.")
    engine.answer(row.id, open_turn, "Linear.")
    assert len(queued(db, row.id)) == 1


# ── the coverage ledger (FR-6.24) ────────────────────────────────────────


def test_asking_and_answering_write_m02s_ledger(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    asked = ledger(db, row.id)
    assert {(r.requirement_id, r.ledger_state) for r in asked} == {
        ("r1", "asked"),
        ("r2", "asked"),
    }

    say(engine, row, "Linear.")
    states = {(r.requirement_id, r.ledger_state) for r in ledger(db, row.id)}
    assert ("r1", "answered") in states and ("r2", "answered") in states

    engine.deliver(row.id)
    sent = engine.upstreams.m02.ledger
    assert {(r["requirement_id"], r["state"]) for r in sent} >= {
        ("r1", "asked"),
        ("r1", "answered"),
    }
    assert all(r["jd_id"] == str(JD_ID) for r in sent)
    assert all(r["turn_id"] for r in sent), "a row about no turn cannot be disputed later"


def test_without_a_job_description_there_is_no_ledger_to_write(db):
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine, jd=False)
    engine.start(row.id)
    say(engine, row, "Linear.")
    assert ledger(db, row.id) == []
    engine.deliver(row.id)
    assert engine.upstreams.m02.ledger == []


def test_m02_being_down_does_not_hold_up_the_evaluation(db):
    """Two obligations, two rows: one upstream's outage is not the other's."""
    from .stubs import DownPlanner

    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions(), m02=DownPlanner())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    drained = engine.deliver(row.id)
    assert drained.evaluations_sent == 1
    assert drained.ledger_sent == 0
    assert outbox.status(db, row.id)["coverage"]["pending"] >= 1


def test_a_drain_that_moves_nothing_says_whether_anything_is_owed(db):
    """`evaluations_sent: 0` has two meanings and a student-facing route has to
    tell them apart: nothing to send, or somebody else is sending it."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")

    claimed = queued(db, row.id)[0]
    claimed.state, claimed.claimed_at = outbox.SENDING, engine.clock()
    db.commit()

    drained = engine.deliver(row.id)
    assert (drained.evaluations_sent, drained.failed, drained.in_flight) == (0, 0, 1)


def test_the_outbox_is_visible_over_http(client, candidate_id, as_student):
    created = client.post("/v1/interviews", json={"minutes": 10}, headers=as_student).json()
    sid = created["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=as_student)
    body = client.get(f"/v1/interviews/{sid}/outbox", headers=as_student).json()
    assert set(body) == {"artifacts", "evaluations", "coverage"}
    drained = client.post(f"/v1/interviews/{sid}/outbox/drain", headers=as_student).json()
    assert drained["evaluations_sent"] == 0
    assert (
        client.get(f"/v1/interviews/{uuid.uuid4()}/outbox", headers=as_student).status_code == 404
    )


def test_the_session_still_ends_with_everything_queued(db):
    """FR-6.18 with AC-6.1: a report exists whatever the upstreams are doing."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    engine.upstreams.m13.fail = True
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    state = engine.end(row.id, "ended_by_student")
    assert state.status is SessionStatus.ended
    built = report.build(state, store.events_for(db, row.id), engine.clock())
    assert built.questions and built.questions[0].scoring_status == "queued"


def test_a_student_is_told_a_consequence_once(db):
    """M04 owns consent, so when M04 is absent its own sentence is the whole
    story. The first live run printed both, which reads as two problems."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    state = engine.state(row.id)
    assert state.flags.consent_id is None  # the fixture M04 grants none here

    notes = report.build(state, store.events_for(db, row.id), engine.clock()).notes
    said = [n for n in notes if "skill graph" in n]
    # M04 answered and granted no consent, so M06 says why in its own words.
    assert "M04" not in state.flags.degraded
    assert said == ["This session didn't update your skill graph — consent isn't recorded yet."]

    # M04 absent: its own sentence already says the session will not count, and
    # M06 does not repeat the consequence underneath it.
    down = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions(), m04=DownMemory())
    row = mock_with_plan(down)
    down.start(row.id)
    state = down.state(row.id)
    notes = report.build(state, store.events_for(db, row.id), down.clock()).notes
    said = [n for n in notes if "skill graph" in n]
    assert said == [state.flags.degraded["M04"]], notes


# ── the answer text M13's evidence resolves against (M04 §5.1) ───────────


@pytest.mark.gate
def test_the_answer_reaches_m04_before_the_evaluation_reaches_m13(db):
    """The seam that made a fully scored interview move nothing.

    M13 quotes character spans of the answer and cites `artifact_id =
    turn_id`; M04 refuses any observation whose evidence does not resolve. Run
    live, every one of nine observations came back "evidence does not
    resolve", so the score existed and the skill graph did not move.
    """
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Keys are hashed to a bucket index, so you do not scan.")

    engine.upstreams.m04.register_artifact = lambda payload: (_ for _ in ()).throw(
        adapters.UpstreamUnavailable("M04", "connection refused")
    )
    held = engine.deliver(row.id)
    assert held.artifacts_sent == 0
    # And the evaluation waits with it, rather than being scored into a
    # rejection two modules downstream.
    assert held.evaluations_sent == 0
    assert held.waiting_on_artifact == 1
    assert engine.upstreams.m13.requests == []

    del engine.upstreams.m04.register_artifact
    moved = engine.deliver(row.id)
    assert (moved.artifacts_sent, moved.evaluations_sent) == (1, 1)

    turn_id = next(t.turn_id for t in engine.state(row.id).transcript if t.role == "candidate")
    # The artifact IS the turn, because that is the id M13 cites.
    assert engine.upstreams.m04.artifacts[turn_id] == (
        "Keys are hashed to a bucket index, so you do not scan."
    )
    assert engine.upstreams.m13.requests[0]["turn_id"] == str(turn_id)


def test_the_registered_text_is_exactly_what_was_scored(db):
    """M13 quotes character offsets into this string. Trimming, joining or
    re-punctuating it here moves every span that points at it."""
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    row = mock_with_plan(engine)
    engine.start(row.id)
    answer = "   Buckets, and a load factor — kept bounded by resizing.   "
    say(engine, row, answer)
    engine.deliver(row.id)

    turn_id = next(t.turn_id for t in engine.state(row.id).transcript if t.role == "candidate")
    registered = engine.upstreams.m04.artifacts[turn_id]
    assert registered == engine.upstreams.m13.requests[0]["answer_text"]


# ── the worker that retries (sweeper.py) ─────────────────────────────────


@pytest.mark.gate
def test_the_sweeper_retries_what_nobody_is_left_to_retry(engine_db):
    """The first live run's second bug: a send that timed out went back to
    `pending`, the student had stopped answering, and no code path asked M13
    again. A score must not depend on somebody being in the room."""
    db, session_factory = engine_db
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    engine.upstreams.m13.fail = True
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    engine.deliver(row.id)
    assert queued(db, row.id)[0].state == outbox.PENDING  # tried once, still owed

    engine.upstreams.m13.fail = False
    swept = sweeper.sweep_once(session_factory, engine.upstreams, NullLLM())
    assert swept.evaluations_sent == 1
    db.expire_all()
    assert queued(db, row.id)[0].state == outbox.SENT

    # And what M13 said reaches the report, exactly as it would on a turn.
    state = engine.state(row.id)
    built = report.build(state, store.events_for(db, row.id), engine.clock())
    assert built.questions[0].scoring_status == "complete"

    # Nothing owed, nothing swept.
    assert sweeper.sweep_once(session_factory, engine.upstreams, NullLLM()).moved == 0


def test_the_sweeper_leaves_a_held_row_alone(engine_db):
    """A row past MAX_ATTEMPTS is a row for a person to look at. Sweeping it
    for ever would hide the problem and keep M13 busy with it."""
    db, session_factory = engine_db
    engine = make(db, llm=StubLLM([verdict()] * 4), m05=BankQuestions())
    engine.upstreams.m13.fail = True
    row = mock_with_plan(engine)
    engine.start(row.id)
    say(engine, row, "Linear.")
    for _ in range(outbox.MAX_ATTEMPTS):
        sweeper.sweep_once(session_factory, engine.upstreams, NullLLM())
    db.expire_all()
    assert queued(db, row.id)[0].state == outbox.HELD

    engine.upstreams.m13.fail = False
    assert sweeper.sweep_once(session_factory, engine.upstreams, NullLLM()).moved == 0
    assert outbox.sessions_owing(db, limit=5) == []
