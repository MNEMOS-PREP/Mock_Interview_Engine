"""The notes (2026-10-22, the user's §6): specific to what was said,
different for a right and a wrong answer, kept back until the end, and a
summary that cannot disagree with the questions it summarises."""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import adapters, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache

from .stubs import BankQuestions, NoClaims, StubLLM, verdict

WRONG = verdict(
    category="incorrect",
    severity="material",
    error_quote="it is O(n squared)",
    error_note="One pass of constant work is linear, O(n).",
    misconception="counts nested work in a single loop",
)
RIGHT = verdict(category="correct", correct_points=["one pass, constant work"])


def run(db, *verdicts, answers):
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=StubLLM(list(verdicts)),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15
    )
    engine.start(row.id)
    for text in answers:
        engine.answer(row.id, engine.state(row.id).open_turn_id, text)
    return engine, row


def notes(engine, row):
    return report.build(engine.state(row.id), store.events_for(engine.db, row.id), engine.clock())


def test_a_wrong_answer_corrected_after_a_push_is_written_up_as_exactly_that(db):
    engine, row = run(db, WRONG, RIGHT, answers=["It is O(n squared).", "Linear — one pass."])
    engine.end(row.id, "ended_by_student")
    built = notes(engine, row)
    first = built.questions[0]
    assert [f.said for f in first.went_wrong] == ["it is O(n squared)"]
    assert first.went_wrong[0].why == "One pass of constant work is linear, O(n)."
    assert first.corrected == "prompted"
    assert first.misconception is None, "corrected, so not left standing"
    assert "one pass, constant work" in first.went_well
    assert any("pointed at once" in r for r in first.how_it_went)
    assert any("corrected after the interviewer pushed back" in c for c in built.summary.corrected)


def test_a_right_answer_and_a_wrong_one_are_not_written_up_alike(db):
    good, good_row = run(db, RIGHT, answers=["Linear: one pass, constant work."])
    good.end(good_row.id, "ended_by_student")
    bad, bad_row = run(db, WRONG, WRONG, answers=["O(n squared).", "Still O(n squared)."])
    bad.end(bad_row.id, "ended_by_student")
    right, wrong = notes(good, good_row).questions[0], notes(bad, bad_row).questions[0]
    assert right.went_wrong == [] and wrong.went_wrong
    assert right.study != wrong.study
    assert any("counts nested work" in line for line in wrong.study)
    assert wrong.outcome == "gap:misunderstanding"


def test_nothing_is_shown_while_the_interview_is_live(db):
    engine, row = run(db, WRONG, answers=["It is O(n squared)."])
    live = notes(engine, row).questions[0]
    assert live.went_wrong == [] and live.how_it_went == [] and live.misconception is None
    assert live.one_strong_answer is None and live.study == []


def test_the_summary_is_built_from_the_questions(db):
    engine, row = run(db, WRONG, WRONG, answers=["O(n squared).", "Still O(n squared)."])
    engine.end(row.id, "ended_by_student")
    built = notes(engine, row)
    gaps = [q for q in built.questions if q.outcome == "gap:misunderstanding"]
    assert len(built.summary.gaps) == len(gaps)
    assert all("counts nested work" in g for g in built.summary.gaps)
    assert built.summary.held == []


# ── found by looking at the live notes, 2026-10-23 ───────────────────────


def test_an_answer_to_another_question_says_nothing_about_this_one(db):
    """Live: an off-topic answer to "tell me about a time you thought aloud"
    came back as "the idea to revisit: algorithmic complexity
    misunderstanding", a claim to back up "with the number, the baseline and
    how you measured it", and a gap. It was not judged, so it is none of
    those — in the notes, on the topic, or in the library."""
    from sqlmodel import select

    from backend_M06_Mock_Interview_Engine.models import QuestionAttempt

    off = verdict(
        category="off_question",
        misconception="algorithmic complexity misunderstanding",
        unsupported_quote="it depends on the structure",
        correct_points=["avoids comparing everything"],
    )
    engine, row = run(db, off, off, answers=["It is always O(n squared).", "It depends."])
    engine.end(row.id, "ended_by_student")
    first = notes(engine, row).questions[0]
    assert first.misconception is None and first.unsupported == [] and first.went_well == []
    assert not any("baseline" in line for line in first.study)
    assert not any(t.misconceptions for t in engine.state(row.id).topics.values())
    attempts = db.exec(select(QuestionAttempt).where(QuestionAttempt.session_id == row.id)).all()
    assert attempts and all(a.misconception is None for a in attempts)


def test_the_notes_of_an_older_session_read_past_what_an_unjudged_answer_carried(db):
    """Recorded before 2026-10-23, a decision kept the model's fields on any
    answer. The notes still leave them out."""
    engine, row = run(db, verdict(category="off_question"), answers=["Something else."])
    engine.end(row.id, "ended_by_student")
    event = next(e for e in store.events_for(db, row.id) if e.kind == "probe.decided")
    event.payload = {
        **event.payload,
        "misconception": "complexity",
        "unsupported_quote": "it depends",
        "correct_points": ["one pass"],
    }
    db.add(event)
    db.commit()
    first = notes(engine, row).questions[0]
    assert first.misconception is None and first.unsupported == [] and first.went_well == []


def test_a_statement_without_its_reason_is_not_asked_for_a_baseline(db):
    """ "The number, the baseline and how you measured it" is for a resume
    line. A bank question's unsupported statement needs its reason."""
    said = verdict(category="unsupported", unsupported_quote="hash maps are always O(1)")
    engine, row = run(db, said, said, answers=["Hash maps are always O(1).", "They just are."])
    engine.end(row.id, "ended_by_student")
    first = notes(engine, row).questions[0]
    assert first.unsupported == ["hash maps are always O(1)"]
    assert any("why each statement holds" in line for line in first.study)
    assert not any("baseline" in line for line in first.study)


def test_a_correction_after_a_push_is_still_one_after_a_later_right_answer(db):
    """Live: the answer after the correction relabelled it "corrected
    yourself" — in the notes, the summary and the library."""
    engine, row = run(
        db,
        WRONG,
        RIGHT,
        RIGHT,
        answers=["It is O(n squared).", "Linear — one pass.", "Each element is visited once."],
    )
    engine.end(row.id, "ended_by_student")
    built = notes(engine, row)
    assert built.questions[0].corrected == "prompted"
    assert any("after the interviewer pushed back" in c for c in built.summary.corrected)


def test_a_vague_answer_shows_a_gap_not_a_misconception(db):
    """Live: "revisit the idea behind this: no mechanism" — a vague answer
    said nothing wrong, so there is nothing to unlearn."""
    vague = verdict(category="vague", misconception="no mechanism")
    engine, row = run(db, vague, vague, answers=["It is efficient.", "It is fast."])
    engine.end(row.id, "ended_by_student")
    first = notes(engine, row).questions[0]
    assert first.misconception is None
    assert not any("no mechanism" in line for line in first.study)


def test_the_notes_of_an_older_session_keep_a_helped_correction_helped(db):
    """Recorded before 2026-10-23, the answer after a correction could carry
    `corrected="self"`; the notes keep "after the interviewer pushed back"."""
    engine, row = run(
        db,
        WRONG,
        RIGHT,
        RIGHT,
        answers=["O(n squared).", "Linear — one pass.", "Each element once."],
    )
    engine.end(row.id, "ended_by_student")
    last = [e for e in store.events_for(db, row.id) if e.kind == "probe.decided"][-1]
    last.payload = {**last.payload, "corrected": "self"}
    db.add(last)
    db.commit()
    assert notes(engine, row).questions[0].corrected == "prompted"


def test_a_point_two_decisions_worded_differently_is_listed_once(db):
    """Live: "What held" read "Uses chaining", "Uses open addressing",
    "mentions chaining", "mentions open addressing"."""
    first = verdict(category="correct", correct_points=["Uses chaining", "Uses open addressing"])
    second = verdict(
        category="correct", correct_points=["mentions chaining", "names a load factor"]
    )
    engine, row = run(db, first, second, answers=["Chaining or probing.", "Chains; load factor."])
    engine.end(row.id, "ended_by_student")
    well = notes(engine, row).questions[0].went_well
    assert well == ["Uses chaining", "Uses open addressing", "names a load factor"]


def test_a_lines_own_full_stop_is_not_followed_by_a_colon():
    """Live summary: "Wrote integration tests … in pytest.: the basics held"."""
    line = report.QuestionReport(
        question="Tell me about the tests.",
        source="m01_probe",
        scored=False,
        topic="Wrote integration tests for the payments service in pytest.",
    )
    assert report._label(line) == "Wrote integration tests for the payments service in pytest"
