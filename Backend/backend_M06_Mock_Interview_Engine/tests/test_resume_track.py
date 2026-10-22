"""The resume interview (2026-10-22, the user's §1): the student's own resume
is the interview — opened on it, every line with questions behind it, probed
for what they built, why, and how they know it worked — and the notes say
which lines held up."""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import adapters, planner, report, store
from backend_M06_Mock_Interview_Engine.engine import RESUME_OPENER, Engine, ThetaCache

from .conftest import student
from .stubs import BankQuestions, StubLLM, verdict


def resume_interview(db, *verdicts, minutes=15):
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions()),
        llm=StubLLM(list(verdicts) or [verdict(category="correct")]),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        db,
        candidate_id=uuid.uuid4(),
        kind="mock",
        mode="mock",
        minutes=minutes,
        track=planner.RESUME_TRACK,
        include_resume=True,
    )
    return engine, row


def test_it_is_offered_beside_the_banks_tracks(client, candidate_id):
    body = client.get("/v1/interviews/tracks", headers=student(candidate_id)).json()
    first = body["tracks"][0]
    assert first["round_type"] == "resume" and first["title"] == "Your resume"
    assert body["groups"][0] == "Your resume"


def test_the_plan_is_the_resume_between_the_warm_up_and_the_closing(db):
    engine, row = resume_interview(db)
    state = engine.start(row.id)
    kinds = [(s.kind, s.source) for s in state.plan.segments]
    assert kinds == [("warmup", "template"), ("project", "m01_claims"), ("closing", "m05_bank")]
    assert state.plan.segments[1].title == "Your resume"
    assert state.plan.claims, "every line with questions behind it"


def test_it_opens_on_the_resume_not_a_bank_question(db):
    engine, row = resume_interview(db)
    state = engine.start(row.id)
    first = next(t for t in state.transcript if t.role == "interviewer" and t.question_source)
    assert RESUME_OPENER.stem in first.text
    assert not engine.upstreams.m05.requests, "nothing is asked of M05"


def test_the_claims_are_asked_and_followed_up_as_resume_questions(db):
    engine, row = resume_interview(db, verdict(category="correct"))
    engine.start(row.id)
    # The opener, answered; the next is the first claim.
    state = engine.answer(row.id, engine.state(row.id).open_turn_id, "I built a crop classifier.")
    while state.transcript[-1].question_source == "template" and state.open_turn_id:
        state = engine.answer(row.id, state.open_turn_id, "I trained it on leaf photos.")
    asked = [
        t for t in state.transcript if t.role == "interviewer" and t.question_source == "m01_probe"
    ]
    assert asked, "a resume line is asked about"
    assert asked[0].concept_id.startswith("claim:")


def test_an_unsupported_claim_is_pressed_and_the_notes_say_it_stayed_unsupported(db):
    engine, row = resume_interview(db, verdict(category="correct"))
    engine.start(row.id)

    def on_a_claim() -> bool:
        last = next(t for t in reversed(engine.state(row.id).transcript) if t.role == "interviewer")
        return last.question_source == "m01_probe" and last.probe_move is None

    for _ in range(6):  # through the opener and its follow-up, to the first claim
        if on_a_claim():
            break
        engine.answer(row.id, engine.state(row.id).open_turn_id, "I built a crop classifier.")
    assert on_a_claim(), "a resume line is asked about"
    claim = verdict(category="unsupported", unsupported_quote="reaching 94% accuracy")
    engine.llm.verdicts = [claim, claim, claim]
    for _ in range(3):
        engine.answer(
            row.id, engine.state(row.id).open_turn_id, "It was really accurate, trust me."
        )
    state = engine.end(row.id, "ended_by_student")
    moves = [t.probe_move for t in state.transcript if t.role == "interviewer"]
    assert "ask_evidence" in moves
    built = report.build(state, store.events_for(db, row.id), engine.clock())
    claim = next(q for q in built.questions if q.source == "m01_probe")
    assert "reaching 94% accuracy" in claim.unsupported
    assert claim.claim_check and "unsupported" in claim.claim_check


def test_follow_ups_on_a_claim_are_about_the_work(db):
    from backend_M06_Mock_Interview_Engine.engine import ladder_config

    engine, row = resume_interview(db)
    engine.start(row.id)
    state = engine.state(row.id).model_copy(update={"current_item": {"source": "m01_probe"}})
    assert ladder_config(state).resume is True


def test_a_question_that_does_not_say_which_line_reads_the_line_out():
    """Live: "Walk me through this project" was asked about two different
    lines with nothing to say which. A question that names its line is left
    as M01 wrote it."""
    from backend_M06_Mock_Interview_Engine.items import from_drill

    def opening(claim: str, question: str) -> str:
        return from_drill(
            {"claim_id": "c1", "claim_text": claim, "probes": [{"depth": 0, "question": question}]}
        ).stem

    team = "Led a team of 4 to build ordering for 3 campus canteens."
    generic = "What was the situation when you took this on, and what did you own?"
    assert opening(team, generic) == f"On your resume: “{team.rstrip('.')}”. {generic}"
    latency = "Cut API p95 latency from 800 ms to 200 ms by adding Redis caching."
    named = "Walk me through API p95 latency — what did you actually build, in your own words?"
    assert opening(latency, named) == named
    project = "Walk me through this project — what did you actually build, in your own words?"
    assert opening(team, project).startswith("On your resume: “Led a team of 4")


def test_a_resume_lines_topic_is_named_by_its_line_never_its_id(db):
    """Live: the summary read "0ac8493e-1d89-…: a real gap", and a line's
    label was cut mid-word ("…reduced average order w")."""
    import re

    from backend_M06_Mock_Interview_Engine.items import shorten

    line = "Led a team of 4 to build ordering for 3 campus canteens; reduced average wait by 40%."
    assert shorten(line, 60) == "Led a team of 4 to build ordering for 3 campus canteens…"
    assert shorten("Short line.", 60) == "Short line."

    engine, row = resume_interview(db, verdict(category="correct"))
    engine.start(row.id)
    for _ in range(6):  # through the opener, to the first claim
        last = next(t for t in reversed(engine.state(row.id).transcript) if t.role == "interviewer")
        if last.question_source == "m01_probe" and last.probe_move is None:
            break
        engine.answer(row.id, engine.state(row.id).open_turn_id, "I built a crop classifier.")
    wrong = verdict(category="incorrect", severity="material", error_quote="it was magic")
    engine.llm.verdicts = [wrong, wrong, wrong]
    for _ in range(3):
        if engine.state(row.id).open_turn_id is None:
            break
        engine.answer(row.id, engine.state(row.id).open_turn_id, "It was magic, honestly.")
    state = engine.end(row.id, "ended_by_student")
    built = report.build(state, store.events_for(db, row.id), engine.clock())
    claim = next(q for q in built.questions if q.source == "m01_probe")
    assert built.summary.topics, "the line's topic moved"
    uuid_like = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")
    assert not any(uuid_like.search(t) or "claim:" in t for t in built.summary.topics)
    assert any(t.startswith(shorten(claim.topic, 60)) for t in built.summary.topics)
    assert not any(".:" in line for line in [*built.summary.gaps, *built.summary.topics])


def test_the_last_answer_of_a_part_reaches_its_topic(db):
    """The step that ends a part records the new part before its own
    decision, and the fold folded that decision into no question: the last
    answer of every part never reached its topic (2026-10-23)."""
    engine, row = resume_interview(db, verdict(category="correct"))
    engine.start(row.id)
    for text in ["I built a crop classifier.", "I trained it on leaf photos."]:
        engine.answer(row.id, engine.state(row.id).open_turn_id, text)
    state = engine.state(row.id)
    opener = state.topics["resume:overview"]
    assert opener.recent == [1.0, 1.0] and opener.level == 1
    assert store.replay(db, row.id).model_dump(mode="json") == state.model_dump(mode="json")
