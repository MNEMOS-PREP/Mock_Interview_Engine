"""The question bank a student has discovered (2026-11-18) — `q_bank_discovered.pdf`.

What is held here, each failing on the code before it:

* a question enters the bank once it was answered and its thread CLOSED —
  never the open one, whose answer key would be on the student's desk while
  it is being asked; never the closing "any questions for me?";
* the follow-ups are the questions the interviewer asked, not the moves that
  only manage the talk, not the stock lines that fit any question, and not
  the acknowledgement in front of one;
* one student's bank holds only their own questions;
* a reviewed answer is printed as written, and the model writes only what
  nobody did — and every follow-up it writes stands for one that was asked;
* the file is drawn again when, and only when, the bank changed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from ai_core.timeutil import utcnow
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, qbank, store
from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import LLMResult
from backend_M06_Mock_Interview_Engine.models import (
    InterviewSession,
    QBankAnswer,
    QBankLookup,
    QBankSeed,
    SessionEvent,
)
from backend_M06_Mock_Interview_Engine.qbank import answers, book, collect, render

from .conftest import student
from .stubs import BankQuestions, NoClaims, StubLLM, verdict

T0 = datetime(2026, 11, 15, 9, 0)

HASH_ITEM = {
    "stem": "Two keys hash to the same bucket. How can a hash map handle that?",
    "source": "m05_bank",
    "question_id": "11111111-1111-4111-8111-111111111111",
    "concept_id": "concept:hashing_internals",
    "rubric_round_type": "dsa_verbal",
    "reference_answer": "Two families. Chaining keeps a list per bucket; open addressing probes.",
    "key_points": [
        {"id": "kp_1", "statement": "Describes chaining.", "required": True},
        {"id": "kp_2", "statement": "Describes open addressing.", "required": False},
    ],
}
OOP_ITEM = {
    "stem": "How would you model a Book as a class?",
    "source": "m05_draft",
    "question_id": "22222222-2222-4222-8222-222222222222",
    "concept_id": "concept:classes_and_objects",
    "rubric_round_type": None,
    "reference_answer": "",
    "key_points": [],
}


class Log:
    """A session's event log, written the way the engine writes it."""

    def __init__(self, session_id: uuid.UUID | None = None):
        self.session_id = session_id or uuid.uuid4()
        self.events: list[SessionEvent] = []

    def add(self, kind: str, **payload) -> Log:
        seq = len(self.events) + 1
        self.events.append(
            SessionEvent(
                session_id=self.session_id,
                seq=seq,
                turn_index=seq,
                step=f"s{seq}",
                kind=kind,
                payload=payload,
                at=T0 + timedelta(minutes=seq),
            )
        )
        return self

    def ask(self, item: dict, **extra) -> Log:
        return self.add(
            "question.asked",
            item=item,
            question_source=item["source"],
            question_text=item["stem"],
            new_question=True,
            probe_move=None,
            **extra,
        )

    def follow(self, text: str, move: str = "rung") -> Log:
        return self.add(
            "question.asked", question_text=text, text=text, new_question=False, probe_move=move
        )

    def answer(self, text: str = "Something I said.") -> Log:
        return self.add("answer.received", text=text, turn_id=str(uuid.uuid4()))

    def end(self) -> Log:
        return self.add("session.ended")


# ── what counts as met ───────────────────────────────────────────────────────


def test_a_question_joins_once_its_thread_closes_and_never_while_open():
    log = Log().ask(HASH_ITEM).answer().ask(OOP_ITEM).answer()
    met = collect.from_events(log.events)
    assert [q.stem for q in met] == [HASH_ITEM["stem"]], "the second is still being asked"
    log.end()
    assert [q.stem for q in collect.from_events(log.events)] == [
        HASH_ITEM["stem"],
        OOP_ITEM["stem"],
    ], "the end closes it"


def test_an_unanswered_question_and_the_closing_are_not_in_the_bank():
    log = (
        Log()
        .ask(HASH_ITEM)  # skipped: no answer
        .ask(OOP_ITEM)
        .answer("A Book has a title and an author.")
        .add("question.asked", question_source="closing", text="Any questions for me?")
        .answer("What does the team work on?")
        .end()
    )
    assert [q.stem for q in collect.from_events(log.events)] == [OOP_ITEM["stem"]]


def test_follow_ups_are_questions_not_conversation_or_stock_lines():
    log = (
        Log()
        .ask(HASH_ITEM)
        .answer("The second overwrites the first.")
        .follow("Your description suggests overwriting; how does a map keep both?", "challenge")
        .answer()
        .follow("Let me ask that again. Two keys hash to the same bucket…", "reoffer")
        .follow("That's not what I asked.", "redirect_once")
        .follow("Can you say more about why that works?", "rung")  # a stock line
        .follow("Right. Besides chaining, what other technique resolves collisions?", "rung")
        .answer()
        .end()
    )
    (met,) = collect.from_events(log.events)
    assert met.follow_ups == [
        "Your description suggests overwriting; how does a map keep both?",
        "Besides chaining, what other technique resolves collisions?",
    ]


def test_the_same_question_across_interviews_is_one_entry():
    first = Log().ask(HASH_ITEM).answer().follow("How does the load factor affect chains?").answer()
    second = Log().ask(HASH_ITEM).answer().follow("How does the load factor affect chain length?")
    second.answer().follow("What does deleting cost with open addressing?").answer()
    found = collect.merge(
        [*collect.from_events(first.end().events), *collect.from_events(second.end().events)]
    )
    (only,) = found
    assert only.times == 2
    assert only.follow_ups == [
        "How does the load factor affect chains?",
        "What does deleting cost with open addressing?",
    ], "a near-copy of a follow-up is kept once"


def test_a_seeded_question_never_claims_an_interview():
    seeded = collect.Asked.from_payload(
        {**collect.from_events(Log().ask(HASH_ITEM).answer().end().events)[0].payload()}
    )
    seeded.asked, seeded.times = False, 0
    (merged,) = collect.merge([seeded])
    assert merged.asked is False and merged.times == 0
    own = collect.from_events(Log().ask(HASH_ITEM).answer().end().events)
    (both,) = collect.merge([seeded, *own])
    assert both.asked is True and both.times == 1, "asked after all: the student's own count"


# ── the book ─────────────────────────────────────────────────────────────────


def _store(db, candidate: uuid.UUID, log: Log) -> None:
    db.add(InterviewSession(id=log.session_id, candidate_id=candidate, kind="mock", mode="mock"))
    for event in log.events:
        db.add(event)
    db.commit()


def test_subjects_come_from_the_tracks_and_topics_from_m04(db):
    candidate = uuid.uuid4()
    _store(db, candidate, Log().ask(HASH_ITEM).answer().ask(OOP_ITEM).answer().end())
    db.add(
        QBankLookup(
            key="tracks",
            payload={
                "tracks": [
                    {
                        "round_type": "oop_verbal",
                        "title": "OOP and language fundamentals",
                        "blurb": "Classes.",
                    },
                    {
                        "round_type": "dsa_verbal",
                        "title": "Data structures and algorithms",
                        "blurb": "Arrays.",
                    },
                ]
            },
        )
    )
    db.add(
        QBankLookup(
            key=f"q:{OOP_ITEM['question_id']}",
            payload={
                "round_types": ["oop_verbal"],
                "reference_answer": "For a Book class I would declare private fields.",
                "key_points": ["Names the attributes."],
            },
        )
    )
    db.add(QBankLookup(key="c:concept:hashing_internals", payload={"name": "Hash Function Design"}))
    db.commit()

    built = book.build(db, candidate, name="Varun")
    assert [s.title for s in built.subjects] == [
        "OOP and language fundamentals",
        "Data structures and algorithms",
    ], "the setup page's own names, in its order"
    oop, dsa = built.subjects
    assert dsa.topics[0].name == "Hash Function Design"
    assert oop.topics[0].name == "Classes and objects", "no M04 name: the id in words"
    (hashing,) = dsa.entries
    assert hashing.answer == HASH_ITEM["reference_answer"] and hashing.answer_kind == "reviewed"
    (book_q,) = oop.entries
    assert book_q.answer_kind == "practice", "a drafted item's answer says nobody reviewed it"
    assert book_q.key_points == ["Names the attributes."]


def test_a_student_sees_only_their_own_questions(db):
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    _store(db, mine, Log().ask(HASH_ITEM).answer().end())
    _store(db, theirs, Log().ask(OOP_ITEM).answer().end())
    assert [e.question for e in book.build(db, mine).entries] == [HASH_ITEM["stem"]]


def test_a_written_follow_up_set_replaces_the_raw_one_and_counts_as_done(db):
    candidate = uuid.uuid4()
    log = Log().ask(HASH_ITEM).answer().follow("Why does that stay O(1)?", "probe_missing")
    _store(db, candidate, log.answer().end())
    before = book.build(db, candidate)
    (entry,) = before.entries
    assert (
        entry.follow_ups[0].question == "Why does that stay O(1)?"
        and not entry.follow_ups[0].answer
    )
    assert entry.follow_ups_pending and before.pending == 1

    asked, _ = book.prepare(db, candidate)
    db.add(
        QBankAnswer(
            brief_hash=answers.brief_hash(asked[0]),
            question_key=asked[0].key,
            payload={
                "answer": "",
                "follow_ups": [
                    {
                        "asked": [1],
                        "question": "Why does hash map lookup stay O(1) on average?",
                        "answer": "The load factor is kept bounded, so each chain stays short.",
                    }
                ],
            },
        )
    )
    db.commit()
    after = book.build(db, candidate)
    (entry,) = after.entries
    assert entry.follow_ups[0].question.startswith("Why does hash map lookup")
    assert after.pending == 0
    assert before.fingerprint() != after.fingerprint()


# ── what the writer may write ────────────────────────────────────────────────


def _asked(**changes) -> collect.Asked:
    one = collect.from_events(
        Log()
        .ask(HASH_ITEM)
        .answer()
        .follow("How does the load factor matter?")
        .answer()
        .follow("Why is deleting harder with probing?")
        .answer()
        .end()
        .events
    )[0]
    for name, value in changes.items():
        setattr(one, name, value)
    return one


def test_a_follow_up_the_model_invents_is_dropped():
    question = _asked()
    written, problems = answers.check(
        {
            "answer": "",
            "follow_ups": [
                {
                    "asked": [1],
                    "question": "How does the load factor affect chain length?",
                    "answer": "A bounded load factor keeps chains short, so lookups stay constant.",
                },
                {
                    "asked": [],
                    "question": "What is a bloom filter?",
                    "answer": "A probabilistic set.",
                },
                {
                    "asked": [9],
                    "question": "What is consistent hashing?",
                    "answer": "A ring of nodes.",
                },
            ],
        },
        question,
    )
    assert [f["question"] for f in written.follow_ups] == [
        "How does the load factor affect chain length?"
    ]
    assert len(problems) == 2


def test_a_reviewed_answer_is_never_replaced_and_a_missing_one_is_required():
    written, _ = answers.check(
        {"answer": "A different answer the model preferred.", "follow_ups": []}, _asked()
    )
    assert written.answer == "", "the item's own answer stands"
    refused, problems = answers.check({"answer": "", "follow_ups": []}, _asked(reference_answer=""))
    assert refused is None and problems


def test_marks_are_stripped_and_a_list_is_refused():
    question = _asked(reference_answer="")
    ok, _ = answers.check(
        {
            "answer": "I would use a `HashMap` with **chaining**, keeping a list per bucket and "
            "resizing when the load factor passes three quarters.",
            "follow_ups": [],
        },
        question,
    )
    assert "`" not in ok.answer and "**" not in ok.answer
    refused, _ = answers.check(
        {"answer": "- chaining\n- probing\n- resizing", "follow_ups": []}, question
    )
    assert refused is None


# ── the file ─────────────────────────────────────────────────────────────────


def test_the_pdf_draws_any_text_and_an_empty_bank():
    empty = render.render(book.Book(name=""), updated=datetime(2026, 11, 18, 10, 0))
    assert empty.startswith(b"%PDF")
    assert render.markup("x ∈ S, ∑ a<b & c").count("QB-Fallback") >= 1
    assert "&lt;" in render.markup("a<b") and "&amp;" in render.markup("a & b")
    # Neither Inter nor DejaVu Sans draws Han; a box would be worse than nothing.
    assert render.markup("漢 smile") == " smile", "a glyph no font has is left out"


def test_the_file_is_drawn_again_only_when_the_bank_changed(db):
    candidate = uuid.uuid4()
    log = Log().ask(HASH_ITEM).answer()
    _store(db, candidate, log)
    first = qbank.current(db, candidate, name="Varun")
    assert first.book.questions == 0, "the only question is still open"
    again = qbank.current(db, candidate)
    assert again.updated == first.updated and again.pdf == first.pdf, "unchanged: served from disk"
    db.add(
        SessionEvent(
            session_id=log.session_id,
            seq=99,
            turn_index=99,
            step="end",
            kind="session.ended",
            payload={},
        )
    )
    db.commit()
    later = qbank.current(db, candidate)
    assert later.book.questions == 1 and later.fingerprint != first.fingerprint
    assert later.book.name == "Varun", "the name the page asked with is kept"
    pdf, _ = qbank._paths(candidate)
    assert pdf.read_bytes() == later.pdf


# ── filled in behind the interview ───────────────────────────────────────────


class WriterLLM:
    """The bank's writer, answering every brief the same way."""

    available = True

    def __init__(self, *, fail: str | None = None):
        self.fail, self.calls = fail, []

    def structured(self, *, job, system, user, schema):
        self.calls.append(job)
        if self.fail:
            return LLMResult(ok=False, reason=self.fail, job=job, tier="generation")
        return LLMResult(
            ok=True,
            job=job,
            tier="writing",
            model="stub-writer",
            data={
                "answer": "I would keep a list per bucket and resize as the table fills up.",
                "follow_ups": [
                    {
                        "asked": [1, 2],
                        "question": "Why does the load factor matter?",
                        "answer": "It sets the expected chain length, so lookups stay short.",
                    }
                ],
            },
        )


class Ontology:
    def concept(self, concept_id):
        return (
            {"name": "Hash Function Design", "domain": "cs_core"}
            if "hashing" in concept_id
            else None
        )


class Bank:
    def __init__(self, *, down: bool = False):
        self.down, self.asked = down, []

    def tracks(self):
        if self.down:
            raise UpstreamUnavailable("M05", "connection refused")
        return {"tracks": [{"round_type": "oop_verbal", "title": "OOP", "blurb": "Classes."}]}

    def question(self, question_id):
        self.asked.append(str(question_id))
        if self.down:
            raise UpstreamUnavailable("M05", "connection refused")
        if str(question_id) != OOP_ITEM["question_id"]:
            raise UpstreamUnavailable("M05", "no such question", status=404)
        return {
            "round_types": ["oop_verbal"],
            "reference_answer": "I would declare fields.",
            "key_points": [{"statement": "Names the attributes."}],
        }


def _ups(m05=None):
    ups = adapters.fixture_upstreams()
    ups.m05, ups.m04 = m05 or Bank(), Ontology()
    return ups


@pytest.mark.qbank
def test_refresh_looks_up_what_the_log_lacks_and_writes_the_rest(engine_db):
    db, factory = engine_db
    candidate = uuid.uuid4()
    log = Log().ask(OOP_ITEM).answer().follow("What goes in the constructor?").answer()
    _store(db, candidate, log.ask(HASH_ITEM).answer().end())
    writer = WriterLLM()
    qbank.refresh(candidate, factory=factory, upstreams=_ups(), llm=writer, sleep=lambda s: None)

    db.expire_all()
    found = {row.key: row for row in db.exec(select(QBankLookup)).all()}
    assert found[f"q:{OOP_ITEM['question_id']}"].payload["reference_answer"]
    assert found["c:concept:hashing_internals"].payload["name"] == "Hash Function Design"
    assert found["c:concept:classes_and_objects"].found is False
    built = qbank.current(db, candidate).book
    assert [s.title for s in built.subjects] == ["OOP", "DSA"]
    (oop,) = built.subjects[0].entries
    assert oop.answer == "I would declare fields." and oop.answer_kind == "practice"
    assert oop.follow_ups[0].answer.startswith("It sets the expected"), "written, not pending"
    assert writer.calls, "one call for the one question with follow-ups"
    assert built.pending == 0


@pytest.mark.qbank
def test_a_module_that_is_down_is_asked_again_and_a_rate_limit_spends_no_attempt(engine_db):
    db, factory = engine_db
    candidate = uuid.uuid4()
    _store(
        db,
        candidate,
        Log().ask(OOP_ITEM).answer().follow("What goes in the constructor?").answer().end(),
    )
    limited = WriterLLM(fail="429 Too Many Requests: rate limit reached")
    qbank.refresh(
        candidate,
        factory=factory,
        upstreams=_ups(Bank(down=True)),
        llm=limited,
        sleep=lambda s: None,
    )
    db.expire_all()
    assert db.get(QBankLookup, f"q:{OOP_ITEM['question_id']}") is None, "not kept: ask again"
    assert db.exec(select(QBankAnswer)).all() == [], "out of quota is not the question's fault"
    assert len(limited.calls) == 2, "the writing tier, then the fallback — then it stops"


# ── the routes ───────────────────────────────────────────────────────────────


def test_the_routes_serve_the_signed_in_students_bank(client, db):
    candidate = uuid.uuid4()
    _store(db, candidate, Log().ask(HASH_ITEM).answer().end())
    assert client.get("/v1/interviews/question-bank").status_code in (401, 403)

    summary = client.get("/v1/interviews/question-bank", headers=student(candidate)).json()
    assert summary["questions"] == 1 and summary["file_name"] == "q_bank_discovered.pdf"
    assert summary["subjects"][0]["questions"] == 1

    response = client.get("/v1/interviews/question-bank.pdf?name=Varun", headers=student(candidate))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="q_bank_discovered.pdf"' in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    stranger = client.get("/v1/interviews/question-bank", headers=student(uuid.uuid4())).json()
    assert stranger["questions"] == 0, "another student's questions never reach this one"


@pytest.mark.qbank
def test_answering_in_an_interview_brings_the_file_up_to_date(client, db, monkeypatch):
    """The route wiring, end to end: the file on disk after an interview is
    the bank with that interview's questions in it."""
    monkeypatch.setattr(qbank, "write_answers", lambda *a, **k: 0)
    candidate = uuid.uuid4()
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=StubLLM([verdict(category="correct", correct_points=["one pass"])]),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(db, candidate_id=candidate, kind="mock", mode="mock", minutes=15)
    engine.start(row.id)
    first = engine.state(row.id).open_turn_id
    engine.answer(row.id, first, "One pass, so it is O(n).")
    response = client.post(
        f"/v1/interviews/{row.id}/end",
        json={"reason": "ended_by_student"},
        headers=student(candidate),
    )
    assert response.status_code == 200
    pdf, meta = qbank._paths(candidate)
    assert pdf.exists() and meta.exists(), "redrawn behind the end of the interview"
    built = qbank.current(db, candidate)
    assert built.book.questions >= 1
    assert built.pdf == pdf.read_bytes(), "and nothing has changed since"


def test_a_seed_row_reads_like_an_asked_question(db):
    candidate = uuid.uuid4()
    (one,) = collect.from_events(Log().ask(HASH_ITEM).answer().end().events)
    db.add(QBankSeed(candidate_id=candidate, question_key=one.key, payload=one.payload()))
    db.commit()
    (entry,) = book.build(db, candidate).entries
    assert entry.question == HASH_ITEM["stem"] and entry.asked is False and entry.first_at is None


def test_a_brief_another_worker_is_writing_is_left_to_it(db):
    """A refresh behind an answer and one behind a download, or two workers:
    one brief is written once. A claim left by a worker that died is taken."""
    candidate = uuid.uuid4()
    _store(
        db,
        candidate,
        Log().ask(HASH_ITEM).answer().follow("Why does chaining work?").answer().end(),
    )
    asked, _ = book.prepare(db, candidate)
    digest = answers.brief_hash(asked[0])
    db.add(QBankAnswer(brief_hash=digest, question_key=asked[0].key, status="writing"))
    db.commit()
    writer = WriterLLM()
    assert qbank.write_answers(db, candidate, asked, writer, sleep=lambda s: None) == 0
    assert writer.calls == []

    row = db.get(QBankAnswer, digest)
    row.updated_at = utcnow() - timedelta(minutes=30)  # stored in UTC, as M06 writes it
    db.add(row)
    db.commit()
    assert qbank.write_answers(db, candidate, asked, writer, sleep=lambda s: None) == 1
    db.refresh(row)
    assert row.status == "ready" and row.attempts == 1


OPENING = {
    "stem": "To start, walk me through your resume.",
    "source": "template",
    "question_id": None,
    "concept_id": "",
    "reference_answer": "",
    "key_points": [],
}


def test_a_frame_for_the_students_own_story_leaves_their_facts_blank():
    (opening,) = collect.from_events(Log().ask(OPENING).answer().end().events)
    assert opening.about_you and "FRAME" in answers.brief(opening)
    invented = (
        "I built an end-to-end pipeline on AWS, led a team of two interns, and the product "
        "team adopted it after launch."
    )
    refused, problems = answers.check({"answer": invented, "follow_ups": []}, opening)
    assert refused is None and problems
    frame = (
        "I would open with [your degree and year], then pick [the project you are proudest "
        "of]: what it does, [your part in it], and [one result you can measure]."
    )
    kept, _ = answers.check({"answer": frame, "follow_ups": []}, opening)
    assert kept.answer == frame


def test_a_behavioural_answer_is_an_example_not_a_script(db):
    candidate = uuid.uuid4()
    story = {
        **OOP_ITEM,
        "question_id": "33333333-3333-4333-8333-333333333333",
        "stem": "Tell me about a tight deadline.",
        "rubric_round_type": "behavioural",
        "reference_answer": "In my capstone we had three weeks…",
    }
    _store(db, candidate, Log().ask(story).answer().ask(OPENING).answer().end())
    db.add(
        QBankLookup(
            key="tracks",
            payload={
                "tracks": [
                    {
                        "round_type": "behavioural",
                        "title": "HR and behavioural",
                        "kind": "behavioural",
                    },
                ]
            },
        )
    )
    db.commit()
    hr, you = book.build(db, candidate).subjects
    assert hr.personal and you.personal
    assert you.entries[0].answer_kind == "pending", "nothing written yet: never invented"
