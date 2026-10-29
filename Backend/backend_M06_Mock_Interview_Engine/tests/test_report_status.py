"""One status per question (2026-10-24, the user's notes brief).

A correct, a vague and a wrong answer looked alike in the notes: how the
question ended was a grey phrase, and the only coloured badge came from M13
on scored questions. Each question now carries one status, derived from the
interview's own judgement of the whole thread — tested here answer type by
answer type, through the engine, so what is judged, stored and shown agree.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import adapters, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache

from .stubs import BankQuestions, NoClaims, StubLLM, verdict

RIGHT = verdict(category="correct", correct_points=["linear in n"])
WRONG = verdict(
    category="incorrect",
    severity="material",
    error_quote="it is O(n squared)",
    error_note="One pass of constant work is linear.",
    misconception="counts a single loop as nested",
)
VAGUE = verdict(category="vague", key_points_missing=["kp1", "kp2"])
PARTIAL = verdict(category="partial", severity="minor", key_points_missing=["kp2"])


def notes(db, *verdicts, answers, end=True):
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
        if engine.state(row.id).open_turn_id is None:
            break
        engine.answer(row.id, engine.state(row.id).open_turn_id, text)
    if end:
        engine.end(row.id, "ended_by_student")
    return report.build(engine.state(row.id), store.events_for(db, row.id), engine.clock())


def first(db, *verdicts, answers):
    return notes(db, *verdicts, answers=answers).questions[0]


def test_a_correct_answer_is_correct_and_its_points_are_marked_covered(db):
    q = first(db, RIGHT, RIGHT, RIGHT, answers=["Linear.", "One pass.", "Constant work each step."])
    assert (q.status, q.status_label) == ("correct", "Correct")
    assert q.key_points and all(point.covered for point in q.key_points)
    assert q.status_qualifier is None


def test_a_vague_answer_is_vague_not_correct(db):
    q = first(db, VAGUE, VAGUE, VAGUE, answers=["It is efficient.", "It is fast.", "Optimised."])
    assert q.status == "vague"
    assert "terms" in q.status_detail
    assert [p.covered for p in q.key_points] == [False, False]


def test_a_wrong_answer_is_incorrect_with_the_misconception_named(db):
    q = first(db, WRONG, WRONG, answers=["O(n squared).", "Still O(n squared)."])
    assert (q.status, q.status_label) == ("incorrect", "Incorrect")
    assert "counts a single loop as nested" in q.status_detail


def test_a_wrong_answer_then_i_dont_know_is_still_incorrect_not_unanswered(db):
    """They did answer — wrongly. "Not answered" would hide the mistake."""
    q = first(db, WRONG, answers=["O(n squared).", "I don't know.", "I don't know."])
    assert q.status == "incorrect"


def test_i_dont_know_is_not_answered_not_incorrect(db):
    q = first(db, RIGHT, answers=["I don't know.", "I don't know."])
    assert (q.status, q.status_label) == ("unanswered", "Not answered")
    assert "did not know" in q.status_detail
    assert all(point.covered is False for point in q.key_points)
    assert q.study, "what to learn is everything a strong answer covers"


def test_a_partial_answer_is_partly_correct(db):
    q = first(db, PARTIAL, PARTIAL, PARTIAL, answers=["Linear.", "Linear, I said.", "Yes."])
    assert q.status == "partial"
    assert [p.covered for p in q.key_points] == [True, False]


def test_a_point_reached_once_stays_reached_when_a_follow_up_misses_it(db):
    """Live, session C (2026-10-24): the first answer reached the problem and
    the outcome; a follow-up on something narrower was judged wrong with every
    key point "missing", and the rubric then marked ✕ the very points the
    write-up quoted the student making. Missed means missed by every answer."""
    first_answer = verdict(category="partial", severity="minor", key_points_missing=["kp2"])
    # As the live verdict had it: the follow-up, judged alone, reached nothing.
    wrong_alone = {**WRONG, "key_points_missing": ["kp1", "kp2"]}
    q = first(
        db,
        first_answer,
        wrong_alone,
        wrong_alone,
        answers=["Linear, one pass.", "O(n squared) now.", "Still O(n squared)."],
    )
    assert q.status == "incorrect", "the wrong idea stood, whatever the first answer reached"
    assert [p.covered for p in q.key_points] == [True, False]
    # Nor is a point the student reached put on their study list.
    reached = q.key_points[0].statement
    assert not any(reached in line for line in q.study), q.study


def test_a_wrong_idea_in_a_follow_up_says_where_it_came(db):
    """Session C, Q1 (the user's call, 2026-10-24): an opening that held, a
    follow-up whose wrong idea stood. Still incorrect — the colour, counts and
    focus are the status's — but labelled for where the error came."""
    held = verdict(category="partial", severity="minor", key_points_missing=["kp2"])
    q = first(db, held, WRONG, WRONG, answers=["Linear.", "O(n squared) now.", "Still."])
    assert q.status == "incorrect"
    assert q.status_label == "Incorrect in a follow-up"
    assert q.status_detail.startswith("Your first answer held up, but a follow-up did not.")
    assert "counts a single loop as nested" in q.status_detail


def test_a_wrong_opening_is_plainly_incorrect(db):
    q = first(db, WRONG, WRONG, answers=["O(n squared).", "Still O(n squared)."])
    assert (q.status, q.status_label) == ("incorrect", "Incorrect")


def test_a_correction_after_a_push_says_so(db):
    q = first(db, WRONG, RIGHT, RIGHT, answers=["O(n squared).", "Linear, sorry.", "One pass."])
    assert q.status in ("correct", "partial")
    assert q.status_qualifier == "after a push"


def test_an_answer_to_another_question_is_not_answered_and_says_why(db):
    off = verdict(category="off_question")
    q = first(db, off, off, answers=["Hash maps are fast.", "They use buckets."])
    assert q.status == "unanswered"
    assert "different question" in q.status_detail


def test_a_question_the_interview_ended_on_is_not_reached(db):
    built = notes(db, RIGHT, answers=[])
    q = built.questions[0]
    assert (q.status, q.status_label) == ("not_reached", "Not reached")
    assert all(point.covered is None for point in q.key_points)


def test_nothing_is_judged_while_the_interview_is_live(db):
    built = notes(db, WRONG, answers=["O(n squared)."], end=False)
    q = built.questions[0]
    assert q.status is None and q.key_points == []


def test_the_summary_counts_the_statuses_and_puts_the_worst_first(db):
    built = notes(
        db,
        WRONG,
        WRONG,
        RIGHT,
        RIGHT,
        RIGHT,
        answers=["O(n squared).", "Still O(n squared).", "Push, pop.", "LIFO.", "FIFO."],
    )
    statuses = [q.status for q in built.questions]
    assert statuses[0] == "incorrect"
    assert built.summary.status_counts.get("incorrect") == 1
    assert sum(built.summary.status_counts.values()) == len(statuses)
    assert built.summary.focus and built.summary.focus[0].endswith("— incorrect")


def test_held_up_is_only_what_the_status_calls_correct():
    """An answer that held but left part of a strong answer out is "Mostly
    correct": it is something to work on, so it is not listed as held too."""
    from types import SimpleNamespace

    def q(topic, status, label):
        return report.QuestionReport(
            question=f"About {topic}?", source="m05_bank", scored=True, topic=topic,
            outcome="held", status=status, status_label=label,
        )  # fmt: skip

    mostly, right = q("Stacks", "partial", "Mostly correct"), q("Queues", "correct", "Correct")
    summary = report._summary(SimpleNamespace(topics={}), [mostly, right])
    assert summary.held == ["Queues"]
    assert summary.focus == ["Stacks — mostly correct"]


def test_every_status_has_a_label_and_a_place_in_the_order():
    assert set(report.FOCUS_ORDER) <= set(report.STATUSES)
    assert len(set(report.STATUSES)) == len(report.STATUSES)


def test_a_vague_attempt_then_i_dont_know_is_vague_not_unanswered(db):
    """Live: "It uses hashing, which makes it fast", the same again, then "I'm
    not sure" — they tried, and the notes say how the attempt went."""
    q = first(
        db, VAGUE, VAGUE, answers=["It is efficient.", "Fast.", "I don't know.", "I don't know."]
    )
    assert q.status == "vague"


def test_a_vague_follow_up_does_not_mark_missed_points_covered(db):
    """Live walkthrough, 2026-10-29, the hash-map question: a partial first
    answer, then "Honestly I'm not sure... a good hash function?" — judged
    vague with nothing listed missing — then "I don't know". The intersection
    of misses came out empty and the checklist marked ✓ the very points the
    write-up said were omitted. A vague reply reaches nothing."""
    vague_empty = verdict(category="vague", key_points_missing=[])
    q = first(
        db,
        PARTIAL,
        vague_empty,
        vague_empty,
        answers=["Linear, one pass.", "Not sure, it is just efficient?", "I don't know."],
    )
    assert [p.covered for p in q.key_points] == [True, False]
    missed = q.key_points[1].statement
    assert any(missed in line for line in q.study) or q.study, q.study


def test_incomplete_with_nothing_named_missing_marks_no_point_either_way(db):
    """Live, 2026-10-29: correct_incomplete came back with an empty list of
    misses, twice. Crediting every point would tick what the write-up says
    was left out; ✕ on every point would cross out what it quotes as right.
    Until M13 judges, the checklist does not guess."""
    unnamed = verdict(category="correct_incomplete", key_points_missing=[])
    q = first(db, unnamed, unnamed, answers=["Linear, one pass.", "Yes, linear."])
    assert q.status == "partial"
    assert [p.covered for p in q.key_points] == [None, None]
    # A later answer that reaches everything settles it.
    q = first(db, unnamed, RIGHT, answers=["Linear.", "One pass, constant work."])
    assert [p.covered for p in q.key_points] == [True, True]


def test_m13s_judgement_decides_the_checklist_when_it_has_scored():
    """One judgement for the write-up and the checklist: they cannot disagree."""
    feedback = [
        report.Feedback(dimension="correctness", missing=["kp2", "kp3"]),
        report.Feedback(dimension="communication", missing=[]),
    ]
    assert report._checklist_missed(feedback, ["kp1", "kp2", "kp3"], {"kp1", "kp2", "kp3"}) == [
        "kp2",
        "kp3",
    ]
    # Before M13 answers: what no content-bearing answer reached.
    assert report._checklist_missed([], ["kp1", "kp2"], {"kp1"}) == ["kp2"]
    # Nothing judged the content: unknown, not a guess either way.
    assert report._checklist_missed([], ["kp1", "kp2"], None) is None
