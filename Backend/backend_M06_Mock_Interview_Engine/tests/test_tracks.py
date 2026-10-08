"""What the student chose on the setup page, and the bank behind it (2026-10-07).

A student asked for a machine-learning interview and was asked DSA and their
resume: the plan probed every round type M13 could score and split the time
among them, the project round opened every session whatever they wanted, and
the bank held twelve approved items, eleven of them DSA. Each test here is
one of those, fixed:

  * the TRACK they pick is the only round type the session asks about;
  * questions from their RESUME come only when they opt in, from the resume
    they pick, spread across it rather than all from one project;
  * a DRAFTED item (M05 FR-5.6) fills a track with nothing approved — asked,
    never scored, never moving θ — and the notes say why;
  * fifteen minutes holds five to seven questions, and a mixed interview is
    a few real rounds, not nine one-question samplers.
"""

from __future__ import annotations

import copy
import uuid

from sqlmodel import select

from backend_M06_Mock_Interview_Engine import planner, store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import (
    FixtureEvaluator,
    FixtureResumes,
    fallback_playlist,
)
from backend_M06_Mock_Interview_Engine.contracts import DRAFT_NOT_SCORED, SessionStatus
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox

from .stubs import BankQuestions, NoClaims, StubLLM, verdict
from .test_engine import make, say

SESSION = uuid.UUID("5e55e55e-0000-4000-8000-000000000001")


def items_for(round_type: str) -> list[dict]:
    """The fallback playlist, re-filed under another round type with new ids
    — the same questions, as a bank that holds `round_type`."""
    out = []
    for item in fallback_playlist()["items"]:
        copied = copy.deepcopy(item)
        copied["id"] = str(uuid.uuid5(uuid.UUID(item["id"]), round_type))
        copied["round_types"] = [round_type]
        copied["rubric_round_type"] = round_type
        out.append(copied)
    return out


def two_track_bank() -> BankQuestions:
    return BankQuestions(items=items_for("dsa_verbal") + items_for("ml_verbal"))


def create(engine, **choices):
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=30, **choices
    )
    return row


def run_to_end(engine, row, answer="It depends on the data.", limit=40):
    for _ in range(limit):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live:
            break
        say(engine, row, answer)
    return engine.state(row.id)


def asked(state):
    return [t for t in state.transcript if t.role == "interviewer" and t.question_id]


# ── the track ─────────────────────────────────────────────────────────────


def test_a_chosen_track_is_the_only_round_type_the_session_asks_about(db):
    bank = two_track_bank()
    engine = make(
        db,
        llm=StubLLM([verdict()] * 80),
        m05=bank,
        m13=FixtureEvaluator(round_types=("dsa_verbal", "ml_verbal")),
        m01=NoClaims(),
    )
    row = create(engine, track="ml_verbal")
    engine.start(row.id)
    state = run_to_end(engine, row)

    assert state.plan.track == "ml_verbal"
    asked_about = {r["round_type"] for r in bank.requests}
    assert asked_about == {"ml_verbal"}, "an ML interview never asks M05 for DSA"
    assert asked(state) and all(t.rubric_round_type == "ml_verbal" for t in asked(state))


def test_with_no_track_the_interview_is_mixed_from_what_can_be_scored(db):
    bank = two_track_bank()
    engine = make(
        db,
        m05=bank,
        m13=FixtureEvaluator(round_types=("dsa_verbal", "ml_verbal")),
        m01=NoClaims(),
    )
    row = create(engine)
    state = engine.plan(row.id)
    assert state.plan.track is None
    assert {r["round_type"] for r in bank.requests} == {"dsa_verbal", "ml_verbal"}


def test_every_request_to_m05_allows_drafts(db):
    """FR-5.6 is M05's to enforce: M06 says drafts may fill the round, and
    M05 says whether the one it chose may be scored."""
    bank = BankQuestions()
    engine = make(db, llm=StubLLM([verdict()] * 20), m05=bank, m01=NoClaims())
    row = create(engine)
    engine.start(row.id)
    say(engine, row, "A hash map reads the bucket its key hashes to.")
    assert bank.requests and all(r.get("allow_drafts") is True for r in bank.requests)


# ── the resume ────────────────────────────────────────────────────────────


def test_the_resume_is_left_out_unless_the_student_asks_for_it(client, as_student):
    """The fixture resume has a risky claim. Not asking for it means no
    project round: "not every interview is meant to ask from resume"."""
    plain = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()
    plan = client.post(f"/v1/interviews/{plain['id']}/plan", headers=as_student).json()["plan"]
    assert "project" not in [s["kind"] for s in plan["segments"]]
    assert plan["resume_included"] is False

    opted = client.post(
        "/v1/interviews", json={"minutes": 30, "include_resume": True}, headers=as_student
    ).json()
    plan = client.post(f"/v1/interviews/{opted['id']}/plan", headers=as_student).json()["plan"]
    assert "project" in [s["kind"] for s in plan["segments"]]
    assert plan["resume_included"] is True


def test_the_resume_the_student_picks_is_the_one_read(client, as_student):
    """Several resumes: the picked one, not M01's current one. The fixture's
    older resume has nothing shaky on it, so picking it means no project
    round — and naming a resume is itself opting in."""
    older = uuid.uuid5(FixtureResumes().resume_id, "older")
    created = client.post(
        "/v1/interviews", json={"minutes": 30, "resume_id": str(older)}, headers=as_student
    ).json()
    plan = client.post(f"/v1/interviews/{created['id']}/plan", headers=as_student).json()["plan"]
    assert plan["resume_included"] is True and plan["resume_id"] == str(older)
    assert "project" not in [s["kind"] for s in plan["segments"]]

    current = FixtureResumes().resume_id
    created = client.post(
        "/v1/interviews", json={"minutes": 30, "resume_id": str(current)}, headers=as_student
    ).json()
    plan = client.post(f"/v1/interviews/{created['id']}/plan", headers=as_student).json()["plan"]
    assert "project" in [s["kind"] for s in plan["segments"]]


def test_a_track_that_is_not_a_round_type_is_refused(client, as_student):
    response = client.post(
        "/v1/interviews", json={"minutes": 30, "track": "DROP TABLE"}, headers=as_student
    )
    assert response.status_code == 422


def claim(cid: str, section: str, risk: float, subjects: list[str]) -> dict:
    return {
        "id": cid,
        "text": f"claim {cid}",
        "risk_band": "risky",
        "risk_score": risk,
        "section_id": section,
        "subject_concepts": subjects,
        "probes": [{"depth": 0, "question": "q", "expects": ["x"]}],
    }


def test_resume_questions_are_spread_across_the_resume():
    """Three shaky lines on the first project and one on the second: the
    second project is asked about second, not fourth, and a line on a new
    subject comes before another on the same one."""
    claims = [
        claim("a1", "projectA", 0.9, ["concept:cnn"]),
        claim("a2", "projectA", 0.85, ["concept:cnn"]),
        claim("a3", "projectA", 0.8, ["concept:sql"]),
        claim("b1", "projectB", 0.5, ["concept:react"]),
    ]
    assert [c["id"] for c in planner.defendable(claims)] == ["a1", "b1", "a3", "a2"]


# ── drafts ────────────────────────────────────────────────────────────────


class DraftBank(BankQuestions):
    """M05 when nothing approved fits: every pick is a draft (FR-5.6)."""

    def select(self, request):
        chosen = super().select(request)
        if chosen is not None:
            chosen["scored_use"] = False
        return chosen


def test_a_drafted_question_is_asked_and_never_scored(db):
    bank = DraftBank()
    engine = make(db, llm=StubLLM([verdict()] * 40), m05=bank, m01=NoClaims())
    row = create(engine)
    engine.start(row.id)
    say(engine, row, "A hash map reads the bucket its key hashes to.")
    state = engine.state(row.id)

    drafted = asked(state)
    assert drafted and all(t.question_source == "m05_draft" for t in drafted)
    assert all(t.rubric_round_type is None for t in drafted), "nothing for M13 to score against"
    owed = db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == row.id)).all()
    assert owed == [], "a draft's answer is not sent to be scored"
    assert bank.observed == [], "and it moves no θ"


def test_the_notes_say_why_a_drafted_question_has_no_score(client, as_student):
    from backend_M06_Mock_Interview_Engine import adapters

    adapters.set_upstreams(adapters.fixture_upstreams(m05=DraftBank(), m01=NoClaims()))
    sid = client.post("/v1/interviews", json={"minutes": 30}, headers=as_student).json()["id"]
    started = client.post(f"/v1/interviews/{sid}/start", headers=as_student).json()
    client.post(
        f"/v1/interviews/{sid}/answers",
        json={"question_turn_id": started["open_turn_id"], "text": "I'd hash the key."},
        headers=as_student,
    )
    client.post(f"/v1/interviews/{sid}/end", headers=as_student)
    report = client.get(f"/v1/interviews/{sid}/report", headers=as_student).json()
    first = report["questions"][0]
    assert first["scored"] is False
    assert first["not_scored_reason"] == DRAFT_NOT_SCORED
    assert first["strong_answer_covers"], "what a strong answer covers, in its place"


# ── how much fits ─────────────────────────────────────────────────────────


def no_jd(**overrides) -> planner.PlanInputs:
    base = {
        "session_id": SESSION,
        "mode": "mock",
        "requested_minutes": 15,
        "available_round_types": ("dsa_verbal",),
    }
    base.update(overrides)
    return planner.PlanInputs(**base)


def questions_in(plan) -> int:
    return sum(s.question_budget for s in plan.segments if s.dropped_reason is None)


def test_fifteen_minutes_holds_five_to_seven_questions():
    """The student's own number (2026-10-07). §6.5's 3.5 minutes a question
    and a five-minute closing made it three."""
    assert 5 <= questions_in(planner.assemble(no_jd())) <= 7
    with_resume = no_jd(
        resume_included=True, claims=(claim("a1", "projectA", 0.9, ["concept:cnn"]),)
    )
    assert 5 <= questions_in(planner.assemble(with_resume)) <= 7


NINE = (
    "dsa_verbal",
    "os_verbal",
    "dbms_verbal",
    "cn_verbal",
    "oop_verbal",
    "systems_verbal",
    "ml_verbal",
    "dl_verbal",
    "behavioural",
)


def test_a_mixed_interview_is_a_few_real_rounds_not_nine_samplers():
    short = planner.assemble(no_jd(available_round_types=NINE))
    parts = [s for s in short.segments if s.kind in ("technical", "behavioural")]
    assert len(parts) == 1, "fifteen minutes is one round"

    long = planner.assemble(no_jd(available_round_types=NINE, requested_minutes=45))
    parts = [s for s in long.segments if s.kind in ("technical", "behavioural")]
    assert 2 <= len(parts) < len(NINE)
    assert all(s.question_budget >= planner.MIN_QUESTIONS_PER_PART for s in parts)


def test_which_rounds_a_mixed_interview_gets_changes_from_session_to_session():
    picks = {
        tuple(
            s.rubric_round_types[0]
            for s in planner.assemble(
                no_jd(available_round_types=NINE, session_id=uuid.uuid4())
            ).segments
            if s.rubric_round_types and s.kind != "warmup"
        )
        for _ in range(20)
    }
    assert len(picks) > 1, "the same round every time is the boredom the student reported"


def test_a_track_is_named_by_m05_and_run_by_the_interviewer_it_calls_for():
    tracks = {"behavioural": {"title": "HR and behavioural", "kind": "behavioural"}}
    plan = planner.assemble(
        no_jd(available_round_types=("behavioural",), track="behavioural", tracks=tracks)
    )
    (part,) = [s for s in plan.segments if s.rubric_round_types == ["behavioural"] and s.index]
    assert part.title == "HR and behavioural"
    assert part.kind == "behavioural", "the HR side of the panel runs it"
    assert "The track you picked" in part.rationale


# ── what the setup page is offered ────────────────────────────────────────


def test_the_setup_page_is_offered_every_track_and_whether_it_is_scored(client):
    body = client.get("/v1/interviews/tracks").json()
    offered = {t["round_type"]: t for t in body["tracks"]}
    # The fixture bank holds DSA, which M13's fixture can score.
    assert offered["dsa_verbal"]["scored"] is True
    assert offered["dsa_verbal"]["title"], "a name, not an id"


def test_a_drafts_only_track_is_offered_and_says_it_is_not_scored(client):
    from backend_M06_Mock_Interview_Engine import adapters

    class Tracks(BankQuestions):
        def tracks(self):
            return {
                "groups": ["AI and ML"],
                "tracks": [
                    {
                        "round_type": "ml_verbal",
                        "title": "Machine learning",
                        "group": "AI and ML",
                        "kind": "technical",
                        "approved": 0,
                        "drafts": 50,
                    }
                ],
            }

    adapters.set_upstreams(
        adapters.fixture_upstreams(
            m05=Tracks(), m13=FixtureEvaluator(round_types=("dsa_verbal", "ml_verbal"))
        )
    )
    (ml,) = client.get("/v1/interviews/tracks").json()["tracks"]
    assert (ml["title"], ml["scored"], ml["drafts"]) == ("Machine learning", False, 50)


def test_the_resume_picker_lists_the_students_resumes(client, as_student):
    body = client.get("/v1/interviews/resumes", headers=as_student).json()
    listed = {r["filename"]: r for r in body["resumes"]}
    assert listed["resume_final.pdf"]["is_active"] is True
    assert listed["resume_final.pdf"]["defendable"] == 1
    assert listed["resume_second_year.pdf"]["defendable"] == 0, "nothing to push on"
    assert "redacted_text" not in str(body), "only what the picker shows"


def test_the_resume_picker_needs_a_signed_in_student(client):
    assert client.get("/v1/interviews/resumes").status_code in (401, 403)


def test_m05_is_told_what_this_interview_asked_in_order(db):
    """So the next question is not the same topic again, or the same question
    in other words (2026-10-08)."""
    bank = BankQuestions()
    # A failed opening: the interviewer moves on, so a next question is chosen.
    failed = verdict(justification="failed", band="below")
    engine = make(db, llm=StubLLM([failed] * 20), m05=bank, m01=NoClaims())
    row = create(engine)
    engine.start(row.id)
    say(engine, row, "I don't know.")
    state = engine.state(row.id)
    asked_ids = list(dict.fromkeys(str(t.question_id) for t in asked(state)))
    last = [r for r in bank.requests if "asked_this_session" in r][-1]
    assert last["asked_this_session"] == asked_ids[: len(last["asked_this_session"])]
    assert last["asked_this_session"], "the warm-up was asked before the next selection"
