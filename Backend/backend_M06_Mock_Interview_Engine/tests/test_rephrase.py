"""When the student asks for the question again, and when a wrong answer is
still an answer (2026-10-07).

The user, live:

- "I didn't understand the question. Can you come again?" was answered
  "That's a different question. Here's mine again." — the strategist had no
  way to say "asks to rephrase", so it said off_question.
- A wrong but on-topic answer about binary search tree lookup ("O of log n is
  true always, but not when the one we search for is the root") got the same
  line.
- At the closing, "Can you explain the dynamic array question you asked me?"
  was told to ask the real panel.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from backend_M06_Mock_Interview_Engine.agents.strategist import ProbeStrategist, rule_verdict
from backend_M06_Mock_Interview_Engine.clarify import on_topic
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus
from backend_M06_Mock_Interview_Engine.phrasebook import LINES

from .day10 import last_line, make, rounds_plan, say, session
from .stubs import StubLLM, verdict
from .test_closing import reach_the_closing

ONE_ROUND = rounds_plan(("r1", 2, 7.0))


def moves(engine, row) -> list[str | None]:
    return [t.probe_move for t in engine.state(row.id).transcript if t.role == "interviewer"]


# ── asking for the question again ────────────────────────────────────────


def test_not_understanding_the_question_is_seen_without_a_model():
    for said in (
        "I didn't understand the question. Can you come again?",
        "Sorry, can you rephrase that?",
        "what do you mean",
        "Could you explain the question?",
        "I don't get it, can you say that again?",
    ):
        assert rule_verdict(said).asks_to_rephrase, said
    # A long answer with doubt in it is an answer: the model judges it.
    long_answer = (
        "I don't understand why people say it is always logarithmic, because when the tree "
        "is a chain of inserts in sorted order every lookup walks the whole height of it"
    )
    assert not rule_verdict(long_answer).asks_to_rephrase
    assert not rule_verdict("A stable sort keeps equal keys in their order.").asks_to_rephrase


def test_a_request_to_rephrase_needs_no_model_call():
    llm = StubLLM()
    item = NS(stem="Why is lookup O(1)?", key_points=[], expected_at=lambda d: [])
    decision = ProbeStrategist(llm).decide(item, 0, "Why is lookup O(1)?", "Can you come again?")
    assert decision.verdict.asks_to_rephrase
    assert llm.structured_calls == [], "a second of silence for what a rule can see"


def test_the_question_is_put_another_way_and_nothing_is_judged(db):
    llm = StubLLM([verdict()], rephrased="In other words, what makes the lookup fast?")
    engine = make(db, plan=ONE_ROUND, llm=llm)
    row = session(engine, minutes=30)
    asked = engine.state(row.id).transcript[-1].question_text
    state = say(engine, row, "I didn't understand the question. Can you come again?")
    line = last_line(state)
    assert any(line.startswith(lines.rephrase_lead) for lines in LINES.values()), line
    assert "different question" not in line
    assert "In other words, what makes the lookup fast?" in line
    assert moves(engine, row)[-1] == "rephrase"
    # Still the same question: an answer now is judged against it.
    assert engine.state(row.id).transcript[-1].question_id is not None
    assert asked


def test_twice_in_other_words_then_a_kinder_way_out(db):
    llm = StubLLM([verdict()])
    engine = make(db, plan=ONE_ROUND, llm=llm)
    row = session(engine, minutes=30)
    for _ in range(2):
        say(engine, row, "Sorry, can you rephrase that?")
        assert moves(engine, row)[-1] == "rephrase"
    say(engine, row, "Sorry, can you rephrase that?")
    assert moves(engine, row)[-1] != "rephrase"


def test_with_no_model_the_question_is_said_again_after_the_lead(db):
    llm = StubLLM([verdict()], fail_stream="the model is down")
    engine = make(db, plan=ONE_ROUND, llm=llm)
    row = session(engine, minutes=30)
    asked = engine.state(row.id).transcript[-1].question_text
    state = say(engine, row, "Can you repeat the question?")
    assert asked in last_line(state)
    assert "different question" not in last_line(state)


# ── a wrong answer is still an answer ────────────────────────────────────


BST = NS(
    stem=(
        "A binary search tree gives O(log n) lookup. When does that stop being true, "
        "and what is done about it?"
    ),
    label="binary search trees",
    key_points=[NS(statement="States that an unbalanced tree degrades lookup to O(n).")],
)


def test_a_confused_attempt_using_the_questions_words_is_on_topic():
    said = (
        "Big O complexity always talks about the upper limit of the time complexity possible. "
        "So O of log n is true always, but we can consider it as not true when the element "
        "we are searching for is at the top, is the root."
    )
    assert on_topic(said, BST, BST.stem)
    assert not on_topic("I like cricket and I play it on weekends.", BST, BST.stem)
    assert not on_topic("", BST, BST.stem)


def test_the_strategists_off_question_is_overruled_for_an_on_topic_answer(db):
    llm = StubLLM([verdict(off_question=True, band="below", justification="partial")])
    engine = make(db, plan=ONE_ROUND, llm=llm)
    row = session(engine, minutes=30)
    asked = engine.state(row.id).transcript[-1].question_text or ""
    # Words from the question itself, said back wrongly.
    words = [w for w in asked.replace("?", "").split() if len(w) >= 5][:3]
    state = say(engine, row, f"I think {' '.join(words)} is always true, nothing else matters.")
    assert "different question" not in last_line(state)
    assert moves(engine, row)[-1] != "redirect_once"


def test_a_truly_different_answer_is_still_redirected(db):
    llm = StubLLM([verdict(off_question=True)])
    engine = make(db, plan=ONE_ROUND, llm=llm)
    row = session(engine, minutes=30)
    say(engine, row, "My favourite food is biryani and I cook it on Sundays.")
    assert moves(engine, row)[-1] == "redirect_once"


# ── the closing explains what was asked ──────────────────────────────────


def test_a_question_about_the_interview_is_explained_at_the_closing(db):
    explanation = (
        "A dynamic array grows by allocating a bigger block, usually double, and copying; "
        "that copy is rare, so appends are O(1) amortised."
    )
    engine, row = reach_the_closing(
        db, llm=StubLLM([verdict(band="below", justification="failed")], closing=explanation)
    )
    state = say(engine, row, "Can you explain the dynamic array question you asked me?")
    assert state.status is SessionStatus.live
    line = last_line(state)
    assert explanation in line and line.endswith("Anything else?")
    assert "real panel" not in line


def test_how_did_i_do_goes_to_the_report(db):
    engine, row = reach_the_closing(
        db, llm=StubLLM([verdict(band="below", justification="failed")], closing="REPORT")
    )
    state = say(engine, row, "How did I do?")
    assert "report" in last_line(state).lower()
    assert "real panel" not in last_line(state)
