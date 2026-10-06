"""A question is asked once per interview — M05 §6.6, found live 2026-10-06.

A panel run for a student whose history covered the bank heard the same
question ("You have a single loop over an array of n elements…") at the
warm-up, at the next round and again after that. M06 had sent the student's
whole history as M05's hard "never" filter, so relaxing freshness could not
help; M05 fell to its playlist, and the playlist ignored what this interview
had asked. What is pinned here: the two filters carry what they mean, a
repeat is refused whoever offers it, and a deliberate re-ask is announced.
"""

from __future__ import annotations

import uuid

from backend_M06_Mock_Interview_Engine import store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import LocalQuestions
from backend_M06_Mock_Interview_Engine.contracts import SessionStatus

from .stubs import BankQuestions, StubLLM, verdict
from .test_engine import make, say

HELD = "It hashes the key to a bucket and reads that bucket."


class RepeatingQuestions(BankQuestions):
    """M05's playlist before 2026-10-06: the same item, whatever was asked."""

    def select(self, request):
        self.requests.append(dict(request))
        chosen = LocalQuestions.select(
            self, {**request, "seen_item_ids": [], "recent_item_ids": []}
        )
        if chosen is not None:
            chosen["reason"] = "fallback"
        return chosen


class Rechecking(BankQuestions):
    """M05 relaxing freshness, as §6.8 step 1 does — and saying so."""

    DISCLOSURE = "You've seen this one before — I'm asking again deliberately to see if it stuck."

    def select(self, request):
        chosen = super().select(request)
        if chosen is not None:
            chosen["reason"] = "fallback"
            chosen["disclosure"] = self.DISCLOSURE
        return chosen


def run(engine, row, limit):
    for _ in range(limit):
        state = engine.state(row.id)
        if state.status is not SessionStatus.live:
            return state
        say(engine, row, HELD)
    return engine.state(row.id)


def new_questions(state):
    return [
        t
        for t in state.transcript
        if t.role == "interviewer" and t.probe_move is None and t.question_id is not None
    ]


def start(db, m05, candidate=None, minutes=30):
    engine = make(db, llm=StubLLM([verdict(band="at", justification="held")] * 90), m05=m05)
    row, _ = store.create_session(
        engine.db, candidate_id=candidate or uuid.uuid4(), kind="mock", mode="mock", minutes=minutes
    )
    engine.start(row.id)
    return engine, row


def test_a_question_offered_again_is_never_asked_again(db):
    engine, row = start(db, RepeatingQuestions())
    state = run(engine, row, limit=14)
    ids = [t.question_id for t in new_questions(state)]
    assert len(ids) >= 2, "the run asked more than one question"
    assert len(ids) == len(set(ids)), ids


def test_this_interview_is_the_hard_filter_and_history_is_freshness(db):
    """`seen_item_ids` is what this interview asked; `recent_item_ids` adds
    what the student was asked before — which M05 may relax, and announce."""
    candidate = uuid.uuid4()
    first_bank = BankQuestions()
    engine, row = start(db, first_bank, candidate=candidate)
    run(engine, row, limit=3)
    before = {str(t.question_id) for t in new_questions(engine.state(row.id))}
    engine.end(row.id, "ended_by_student")
    assert before

    bank = BankQuestions()
    engine, row = start(db, bank, candidate=candidate)
    # The first request is the plan's availability probe, which asks nothing
    # of any history; the first selection is the one after it.
    opening = next(r for r in bank.requests if "seen_item_ids" in r)
    assert opening["seen_item_ids"] == [], "nothing asked in this interview yet"
    assert before <= set(opening["recent_item_ids"]), "the history is freshness"
    # Long enough for a second question: a held answer climbs the ladder first.
    run(engine, row, limit=12)
    asked_here = {str(t.question_id) for t in new_questions(engine.state(row.id))}
    assert len(asked_here) >= 2
    last = bank.requests[-1]
    assert last["seen_item_ids"], "what this interview asked is never asked again"
    assert set(last["seen_item_ids"]) <= asked_here, "only this interview's questions"
    assert before <= set(last["recent_item_ids"])


def test_a_deliberate_re_ask_is_announced(db):
    engine, row = start(db, Rechecking())
    asked = new_questions(engine.state(row.id))[0]
    assert Rechecking.DISCLOSURE in asked.text
