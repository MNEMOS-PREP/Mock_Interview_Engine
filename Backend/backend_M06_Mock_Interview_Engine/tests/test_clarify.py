"""Asking about a spoken answer before judging it — M11's FR-11.16, EC-11.1.

What is pinned: a word the recogniser was unsure of, near a term that decides
the answer, gets "did you say …?" — once a question, three a session, never
for the same word with an ending, never when what was heard is one of the
question's terms; the reply is judged and scored with the answer it
clarifies, whose unsure words stay unquotable. A question the student spoke
over from its start is put again, once, and what they said then is not
judged against it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace as NS

from backend_M06_Mock_Interview_Engine import outbox, store
from backend_M06_Mock_Interview_Engine.clarify import (
    decisive_terms,
    question_unheard,
    scored,
    unsure_term,
)
from backend_M06_Mock_Interview_Engine.items import Item, KeyPoint, from_dict
from backend_M06_Mock_Interview_Engine.models import ArtifactOutbox
from backend_M06_Mock_Interview_Engine.personas import persona

from .stubs import BankQuestions, StubLLM, close, scored_rows, verdict
from .test_engine import make

ITEM = Item(
    stem="Find the k-th smallest element of an unsorted array.",
    source="m05_bank",
    key_points=(
        KeyPoint(id="kp_1", statement="Quick select partitions around a pivot"),
        KeyPoint(id="kp_2", statement="Average linear time, quadratic in the worst case"),
    ),
    label="Selection",
)
SURE = 0.82
HELD = "It hashes the key to a bucket and reads that bucket."


def at(text: str, words: str) -> list[list[int]]:
    start = text.index(words)
    return [[start, start + len(words)]]


# ── the rule ──────────────────────────────────────────────────────────────


def test_the_specs_own_example_is_asked_about():
    """§6.8: "Sorry — did you say quick sort or quick select?"."""
    answer = "I would use quick sort and then take the k-th element."
    assert unsure_term(answer, at(answer, "quick sort"), ITEM) == ("quick sort", "Quick select")


def test_a_term_of_the_question_heard_as_itself_is_not_asked_about():
    answer = "I would use quick select here."
    assert unsure_term(answer, at(answer, "quick select"), ITEM) is None


def test_the_same_word_with_an_ending_is_not_asked_about():
    answer = "It keeps partitioning around the pivot."
    assert unsure_term(answer, at(answer, "partitioning"), ITEM) is None


def test_short_or_far_words_are_not_asked_about():
    answer = "So it is fast in the end, I believe."
    assert unsure_term(answer, at(answer, "is fast in"), ITEM) is None
    assert unsure_term(answer, at(answer, "I believe"), ITEM) is None


def test_the_decisive_terms_are_the_questions_own():
    terms = decisive_terms(ITEM)
    assert "quick select" in terms and "pivot" in terms
    assert "the" not in terms and "of an" not in terms


def test_a_question_spoken_over_from_its_start_was_not_heard():
    line = NS(
        text="Okay. Dr. Raghavan, over to you. Thanks, Priya. Walk me through your project.",
        parts=[
            NS(text="Okay. Dr. Raghavan, over to you."),
            NS(text="Thanks, Priya. Walk me through your project."),
        ],
        question_text="Walk me through your project.",
        heard_part=0,
        heard=0.3,
    )
    assert question_unheard(line)
    line.heard_part, line.heard = 1, 0.95
    assert not question_unheard(line)
    line.heard = None
    assert not question_unheard(line)


def test_a_clarified_answer_is_scored_with_what_it_clarifies():
    original = NS(
        turn_id=uuid.uuid4(), role="candidate", text="I'd use quick sort.", unsure=[(9, 19)]
    )
    line = NS(turn_id=uuid.uuid4(), role="interviewer", probe_move="clarify_term")
    reply = NS(turn_id=uuid.uuid4(), role="candidate", text="Quick select.", unsure=[(0, 5)])
    opening = NS(turn_id=uuid.uuid4(), role="interviewer", probe_move=None)
    state = NS(transcript=[opening, original, line, reply])
    text, unquotable = scored(state, reply)
    assert text == "I'd use quick sort.\nQuick select."
    assert unquotable == [(9, 19), (20, 25)]


# ── in an interview ───────────────────────────────────────────────────────


def live(db, minutes=10):
    engine = make(db, llm=StubLLM([verdict(band="at")] * 30), m05=BankQuestions())
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=minutes
    )
    engine.start(row.id)
    return engine, row


def asked(state):
    return [t for t in state.transcript if t.role == "interviewer"]


def queued(db, row) -> int:
    return sum(1 for e in store.events_for(db, row.id) if e.kind == "evaluation.queued")


def misheard(state) -> tuple[str, str]:
    """A long term of the open question, and itself with one letter changed
    near its start — the way a recogniser mishears a word it does not know."""
    item = from_dict(state.current_item)
    term = next(t for k, t in decisive_terms(item).items() if " " not in k and len(k) >= 7)
    swap = "x" if term[2].lower() != "x" else "z"
    return term, term[:2] + swap + term[3:]


def test_did_you_say_then_the_reply_is_judged_with_the_answer(db):
    engine, row = live(db)
    state = engine.state(row.id)
    term, heard = misheard(state)
    said = f"I think the {heard} is what matters most here."
    asr = {"mean_confidence": SURE, "unsure": at(said, heard), "model": "w"}
    state = engine.answer(row.id, state.open_turn_id, said, asr=asr)
    line = asked(state)[-1]
    assert line.probe_move == "clarify_term"
    assert heard in line.text and term in line.text
    assert line.text in {
        persona(line.speaker_id).said().clarify_term.format(heard=heard, term=term),
        persona(line.speaker_id).said().clarify_term_one.format(term=term),
    }
    assert queued(db, row) == 0, "the answer asked about owes M13 nothing yet"
    state = engine.answer(row.id, state.open_turn_id, f"{term}, yes.")
    assert asked(state)[-1].probe_move != "clarify_term", "asked once a question"
    # Owed when the question closes (2026-10-22): one evaluation, the answer
    # and the clarification together, the unsure word still unquotable.
    close(engine, row)
    rows = scored_rows(db, row.id)
    assert len(rows) == 1
    request = rows[0].payload
    assert request["answer_text"] == f"{said}{outbox.ANSWER_GAP}{term}, yes."
    assert request["uncitable"] == [list(r) for r in at(said, heard)]
    artifact = db.get(ArtifactOutbox, rows[0].turn_id)
    assert artifact.payload["content"] == request["answer_text"]


def test_never_more_than_three_a_session(db):
    engine, row = live(db, minutes=45)
    clarified = 0
    for _ in range(30):
        state = engine.state(row.id)
        if state.open_turn_id is None or state.current_item is None:
            break
        if asked(state)[-1].probe_move == "clarify_term":
            state = engine.answer(row.id, state.open_turn_id, "Yes, that one.")
            continue
        term, heard = misheard(state)
        said = f"The {heard} matters."
        asr = {"mean_confidence": SURE, "unsure": at(said, heard), "model": "w"}
        state = engine.answer(row.id, state.open_turn_id, said, asr=asr)
        clarified += asked(state)[-1].probe_move == "clarify_term"
    assert clarified == 3


def test_a_question_spoken_over_from_its_start_is_put_again(db):
    engine, row = live(db)
    state = engine.state(row.id)
    line = asked(state)[-1]
    engine.heard(row.id, line.turn_id, 0, 0.05)
    state = engine.answer(row.id, line.turn_id, "Oh, and one more thing about my last project.")
    again = asked(state)[-1]
    assert again.probe_move == "reoffer"
    assert again.text.startswith(persona(again.speaker_id).said().reoffer)
    assert again.text.endswith(line.question_text)
    assert queued(db, row) == 0, "what they said answered something else"
    state = engine.answer(row.id, state.open_turn_id, HELD)
    assert asked(state)[-1].probe_move != "reoffer", "put again once"
    close(engine, row)
    rows = scored_rows(db, row.id)
    assert len(rows) == 1
    assert rows[0].payload["answer_text"] == HELD, "an answer to a question never heard is out"


def test_a_question_heard_before_they_spoke_is_judged_as_ever(db):
    engine, row = live(db)
    state = engine.state(row.id)
    line = asked(state)[-1]
    engine.heard(row.id, line.turn_id, len(line.parts) - 1 if line.parts else 0, 0.95)
    state = engine.answer(row.id, line.turn_id, HELD)
    assert asked(state)[-1].probe_move != "reoffer"
    close(engine, row)
    assert len(scored_rows(db, row.id)) == 1


def test_the_persona_cards_carry_the_aside_for_a_line_spoken_over():
    from backend_M06_Mock_Interview_Engine.router import persona_cards

    for card in persona_cards():
        assert card["go_ahead"] == persona(card["id"]).said().go_ahead
