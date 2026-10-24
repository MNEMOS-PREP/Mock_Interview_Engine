"""Each answer explained after the session (2026-10-24, `notes_writer.py`).

The verdict is the code's; the model only explains it — and nothing it
writes is shown until it passes the checks here: the student's own words,
no praise for a wrong answer, the correct reasoning after one, nothing to
praise in an answer never given. Failure at every step leaves the notes as
the interview recorded them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from backend_M06_Mock_Interview_Engine import adapters, notes_writer, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.models import LLMCall, QuestionWriteup
from backend_M06_Mock_Interview_Engine.report import Exchange, QuestionReport

from .conftest import student
from .stubs import BankQuestions, NoClaims, StubLLM, answer, verdict

WRONG = verdict(
    category="incorrect",
    severity="material",
    error_quote="it is O(n squared)",
    error_note="One pass of constant work is linear.",
    misconception="counts a single loop as nested",
)
SAID = "I think it is O(n squared), because the loop looks at every element."
EXPLAINED = {
    "headline": "You counted a single loop as nested work, so the complexity came out quadratic.",
    "strengths": [{"point": "You looked at what the loop does", "evidence": "", "fix": ""}],
    "gaps": [
        {
            "point": "A single pass over n elements is linear, not quadratic.",
            "evidence": "it is O(n squared)",
            "fix": "Count the passes: one loop doing constant work per element is O(n).",
        }
    ],
    "misconception": "A single loop over the array was treated as nested work.",
    "correction": "Each element is visited once with constant work, so the time is O(n).",
    "model_answer": "It is O(n): one pass over n elements, constant work each step.",
    "next_steps": [
        "Trace one loop over a five-element array and count the operations per element.",
        "practise more",
    ],
}


def question(status: str, answer: str = SAID, **extra) -> QuestionReport:
    q = QuestionReport(
        question="What is the time complexity of a single loop doing constant work?",
        source="m05_bank",
        scored=True,
        exchanges=[Exchange(role="interviewer", text="What is the complexity?")]
        + ([Exchange(role="candidate", text=answer)] if answer else []),
        status=status,
        status_label=status,
        status_detail="detail",
        question_key="qk",
    )
    for name, value in extra.items():
        setattr(q, name, value)
    return q


# ── the checks ────────────────────────────────────────────────────────────


def test_a_quote_must_be_the_students_own_words():
    raw = {
        **EXPLAINED,
        "strengths": [
            {"point": "Named the loop", "evidence": "every single element twice", "fix": ""}
        ],
        "gaps": [{"point": "Linear", "evidence": "a made-up phrase they never said", "fix": "x"}],
    }
    writeup, problems = notes_writer.check(raw, question("incorrect"))
    assert writeup is not None
    assert writeup.strengths == [], "a strength resting on an invented quote is dropped"
    assert writeup.gaps[0].evidence == "", "an invented quote is removed from a gap"
    assert any("not in the answer" in p for p in problems)


def test_a_real_quote_survives_punctuation_and_case():
    raw = {**EXPLAINED, "gaps": [{"point": "x", "evidence": "It is O(N squared)", "fix": "y"}]}
    writeup, _ = notes_writer.check(raw, question("incorrect"))
    assert writeup.gaps[0].evidence == "It is O(N squared)"


def test_a_wrong_answer_is_never_praised():
    raw = {**EXPLAINED, "headline": "Great answer, just a small slip on the complexity."}
    writeup, problems = notes_writer.check(raw, question("incorrect"))
    assert writeup is None and "praise" in problems[0]


def test_a_wrong_answer_comes_with_the_correct_reasoning():
    writeup, problems = notes_writer.check({**EXPLAINED, "correction": ""}, question("incorrect"))
    assert writeup is None and "correct reasoning" in problems[0]


def test_an_answer_never_given_has_no_strengths():
    writeup, _ = notes_writer.check(EXPLAINED, question("unanswered", answer=""))
    assert writeup is not None and writeup.strengths == []


def test_a_give_up_is_not_quoted_under_every_gap():
    """Measured on minimax-m3.1-flash: "I'm not sure, I don't know this one."
    quoted as the evidence of each of three gaps. True, and noise."""
    gave_up = "I'm not sure, I don't know this one."
    raw = {
        **EXPLAINED,
        "gaps": [
            {"point": "Name the loop's cost.", "evidence": gave_up, "fix": "Count the iterations."},
            {
                "point": "Say why it is linear.",
                "evidence": gave_up,
                "fix": "Constant work per pass.",
            },
        ],
    }
    writeup, problems = notes_writer.check(raw, question("unanswered", answer=gave_up))
    assert writeup is not None
    assert [g.evidence for g in writeup.gaps] == ["", ""]
    assert [g.fix for g in writeup.gaps] == ["Count the iterations.", "Constant work per pass."]
    assert not any("gap quote" in p for p in problems)


def test_one_sentence_is_quoted_once_however_many_gaps_it_shows():
    """Live, session C: a one-line vague answer quoted whole under each of
    its three gaps. The first gap keeps the quote; the rest keep their fix."""
    raw = {
        **EXPLAINED,
        "gaps": [
            {
                "point": "No mechanism.",
                "evidence": SAID,
                "fix": "Say how the key reaches a bucket.",
            },
            {"point": "No conditions.", "evidence": SAID.upper(), "fix": "Name the load factor."},
        ],
    }
    writeup, _ = notes_writer.check(raw, question("vague"))
    assert [bool(g.evidence) for g in writeup.gaps] == [True, False]
    assert writeup.gaps[1].fix == "Name the load factor."


def test_a_correct_answer_carries_no_invented_misconception():
    writeup, _ = notes_writer.check(EXPLAINED, question("correct"))
    assert writeup.misconception == "" and writeup.correction == ""


def test_generic_advice_is_dropped_and_lengths_are_capped():
    raw = {**EXPLAINED, "model_answer": "word " * 1000}
    writeup, _ = notes_writer.check(raw, question("incorrect"))
    assert writeup.next_steps == [EXPLAINED["next_steps"][0]]
    assert len(writeup.model_answer) <= notes_writer.MAX_ANSWER


def test_malformed_output_is_refused_not_shown():
    for raw in ({"headline": 3, "strengths": "none"}, "not json at all", {"strengths": []}):
        writeup, problems = notes_writer.check(raw, question("incorrect"))
        assert writeup is None and problems


def test_only_a_judged_answer_is_sent_to_the_writer():
    """The writer explains a verdict; it never supplies one. The prompt has
    no rule for `not_judged`, and asked about one it would judge it itself."""
    for status in ("correct", "partial", "vague", "incorrect", "unanswered", "unsupported"):
        assert notes_writer.wanted(question(status)), status
    for status in ("not_judged", "not_reached", None):
        assert not notes_writer.wanted(question(status)), status
    assert not notes_writer.wanted(question("correct", question_key=None))


def test_the_brief_fixes_the_status_and_quotes_only_the_student():
    text = notes_writer.brief(question("incorrect"))
    assert "STATUS (fixed, do not change it): incorrect" in text
    assert "STUDENT: " + SAID in text and "INTERVIEWER: What is the complexity?" in text


# ── written once, after the session ────────────────────────────────────────


def ended(engine, *, notes):
    llm = StubLLM([WRONG])
    llm.notes = notes
    with Session(engine) as db:
        interview = Engine(
            db=db,
            upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
            llm=llm,
            thetas=ThetaCache(),
        )
        row, _ = store.create_session(
            db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15
        )
        interview.start(row.id)
        for text in [SAID, "Still O(n squared)."]:
            interview.answer(row.id, interview.state(row.id).open_turn_id, text)
        interview.end(row.id, "ended_by_student")
        return row.id, llm


def shown(engine, session_id) -> tuple[str, QuestionReport]:
    with Session(engine) as db:
        built = report.build(
            store.load_state(db, session_id), store.events_for(db, session_id), datetime.now(UTC)
        )
        status = notes_writer.attach(
            built.questions, notes_writer.load(db, session_id), datetime.now(UTC)
        )
        return status, built.questions[0]


def test_it_is_written_once_and_the_notes_show_it(engine):
    session_id, llm = ended(engine, notes={"notes_writeup": EXPLAINED})
    assert shown(engine, session_id)[0] == "pending"
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    status, q = shown(engine, session_id)
    assert status == "ready"
    assert q.status == "incorrect" and q.writeup is not None
    assert q.writeup.correction.startswith("Each element is visited once")
    assert q.writeup.model == "stub-notes_writeup"
    calls_before = len(llm.notes_calls)
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    assert len(llm.notes_calls) == calls_before, "written once"
    with Session(engine) as db:
        logged = len(db.exec(select(LLMCall).where(LLMCall.job == "notes_writeup")).all())
    assert logged >= 1, "every call is in the trace"


def test_the_second_model_writes_when_the_first_fails(engine):
    session_id, llm = ended(engine, notes={"notes_writeup_fallback": EXPLAINED})
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    status, q = shown(engine, session_id)
    assert status == "ready" and q.writeup.model == "stub-notes_writeup_fallback"


def test_a_writing_tier_that_does_not_answer_is_tried_once_per_run(engine):
    """NIM can hang until its 90 s timeout on some networks. Asked again for
    every question, eight questions are twelve minutes of "Writing…"; after
    one failure the run goes straight to the fallback."""
    llm = StubLLM([verdict(category="dont_know")])
    llm.notes = {"notes_writeup_fallback": EXPLAINED}  # the writing tier fails
    with Session(engine) as db:
        interview = Engine(
            db=db,
            upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
            llm=llm,
            thetas=ThetaCache(),
        )
        row, _ = store.create_session(
            db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15
        )
        interview.start(row.id)
        for _ in range(3):
            if interview.state(row.id).open_turn_id is None:
                break
            answer(interview, row, "I don't know.")
        interview.end(row.id, "ended_by_student")
        session_id = row.id
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))

    jobs = [call["job"] for call in llm.notes_calls]
    assert jobs.count("notes_writeup_fallback") >= 2, "several questions were written"
    assert jobs.count("notes_writeup") == 1, jobs
    with Session(engine) as db:
        rows = db.exec(select(QuestionWriteup)).all()
    assert rows and all(r.status == "ready" for r in rows)


def test_a_writeup_that_fails_its_checks_falls_back_then_stays_as_recorded(engine):
    praising = {**EXPLAINED, "headline": "Excellent work overall!"}
    session_id, llm = ended(
        engine, notes={"notes_writeup": praising, "notes_writeup_fallback": praising}
    )
    for _ in range(notes_writer.MAX_ATTEMPTS + 1):
        notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    status, q = shown(engine, session_id)
    assert status == "partial" and q.writeup is None
    assert len(llm.notes_calls) == 2 * notes_writer.MAX_ATTEMPTS, "no endless retrying"
    with Session(engine) as db:
        row = db.exec(select(QuestionWriteup)).one()
    assert row.status == "failed" and "praise" in row.reason


def test_a_writeup_from_an_older_brief_is_not_shown(engine):
    session_id, llm = ended(engine, notes={"notes_writeup": EXPLAINED})
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    with Session(engine) as db:
        row = db.exec(select(QuestionWriteup)).one()
        row.brief_hash = "written-for-another-judgement"
        db.add(row)
        db.commit()
    status, q = shown(engine, session_id)
    assert q.writeup is None and status == "pending"


def test_nothing_is_written_while_the_interview_is_live(engine):
    llm = StubLLM([WRONG])
    llm.notes = {"notes_writeup": EXPLAINED}
    with Session(engine) as db:
        interview = Engine(
            db=db,
            upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
            llm=llm,
            thetas=ThetaCache(),
        )
        row, _ = store.create_session(
            db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=15
        )
        interview.start(row.id)
        interview.answer(row.id, interview.state(row.id).open_turn_id, SAID)
        session_id = row.id
    notes_writer.generate(session_id, llm=llm, factory=lambda: Session(engine))
    assert not getattr(llm, "notes_calls", [])


def test_the_report_says_pending_and_never_waits_for_the_writer(client, candidate_id):
    """The route answers at once; the writing happens after the response
    (here the model is off, so nothing is written and nothing breaks)."""
    headers = student(candidate_id)
    sid = client.post("/v1/interviews", json={"minutes": 15}, headers=headers).json()["id"]
    client.post(f"/v1/interviews/{sid}/start", headers=headers)
    client.post(f"/v1/interviews/{sid}/end", json={"reason": "ended_by_student"}, headers=headers)
    got = client.get(f"/v1/interviews/{sid}/report", headers=headers)
    assert got.status_code == 200
    assert got.json()["writeups"] in ("none", "pending")
