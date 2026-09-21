"""Context that does not grow — FR-6.16, AC-6.10, spec §6.6.

The interviewer sees the last six turns. In a twenty-turn round that means
everything before turn fourteen is gone: it asks about hashing again because
it cannot remember asking. §6.6's answer is a rolling summary regenerated
every four turns, and the word that matters is **replaces** — it stands in
for the dropped turns rather than being added to them. Added, it would be a
context that grows with the session, which is the thing AC-6.10 measures.
"""

from __future__ import annotations

import uuid

import pytest

from backend_M06_Mock_Interview_Engine import adapters, store
from backend_M06_Mock_Interview_Engine.agents import summariser
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.projection import project_for_interviewer

from .stubs import BankQuestions, NoClaims, StubLLM, verdict

NOTE = (
    "Covered hash map lookup and collision handling. The candidate described "
    "bucket indexing and mentioned load factor."
)


def make(db, llm=None) -> Engine:
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=llm or NullLLM(),
        thetas=ThetaCache(),
    )


def talking(db, answers: int):
    """A session with `answers` answers in it — a long round, cheaply."""
    engine = make(db, StubLLM([verdict()], probe="And what decides which bucket?"))
    row, _ = store.create_session(
        db, candidate_id=uuid.uuid4(), kind="mock", mode="mock", minutes=60
    )
    engine.start(row.id)
    for i in range(answers):
        state = engine.state(row.id)
        if state.open_turn_id is None:
            break
        engine.answer(row.id, state.open_turn_id, f"Answer number {i}, about buckets.")
    return engine, row


def force_due(engine: Engine, row, step: str = "due") -> None:
    """Make the next `summarise_if_due` actually run one.

    `at_turn` in the past by more than the interval, because a False from a
    schedule that was not due looks exactly like a False from the guard — and
    the first version of the telegraph gate below passed for that reason.
    """
    state = engine.state(row.id)
    store.record(
        engine.db,
        engine.row(row.id),
        "summary.written",
        step=f"summary:force:{step}",
        payload={"text": "", "at_turn": state.next_turn_index - summariser.EVERY_N_TURNS - 1},
    )


# ── the view stays the same size ─────────────────────────────────────────


@pytest.mark.gate
def test_the_interviewer_sees_a_constant_amount_however_long_the_session(db):
    """AC-6.10 in the form the suite can hold: the view is bounded by
    construction, so token variance has nothing to vary with. The measured
    number is a harness run; this is the thing that makes it true."""
    engine, row = talking(db, answers=12)
    state = engine.state(row.id)
    assert len(state.transcript) > 12, "there is genuinely more history than fits"

    view = project_for_interviewer(
        transcript=state.transcript,
        move="rung",
        ladder_depth=1,
        time_remaining_s=600,
        profile_prefix=state.profile_prefix,
        round_summary="x" * 5000,
    )
    assert len(view.recent_turns) == 6, "§6.6: last six turns, whatever came before"
    assert len(view.round_summary) == summariser.MAX_CHARS, "and a bounded note, not a growing one"

    # The whole of what the model is shown, against a session a fifth the size.
    short_engine, short_row = talking(db, answers=2)
    short = project_for_interviewer(
        transcript=short_engine.state(short_row.id).transcript,
        move="rung",
        ladder_depth=1,
        time_remaining_s=600,
        profile_prefix=state.profile_prefix,
        round_summary=NOTE,
    )
    long_ = project_for_interviewer(
        transcript=state.transcript,
        move="rung",
        ladder_depth=1,
        time_remaining_s=600,
        profile_prefix=state.profile_prefix,
        round_summary=NOTE,
    )
    ceiling = sum(len(t.text) for t in long_.recent_turns) + len(long_.round_summary)
    floor = sum(len(t.text) for t in short.recent_turns) + len(short.round_summary)
    assert ceiling < floor * 6, "a six-times-longer session is not a six-times-larger context"


def test_the_summary_replaces_the_dropped_turns_rather_than_joining_them(db):
    """Added instead of substituted, this would be the growth it prevents."""
    engine, row = talking(db, answers=10)
    state = engine.state(row.id)
    view = project_for_interviewer(
        transcript=state.transcript,
        move="rung",
        ladder_depth=1,
        time_remaining_s=600,
        round_summary=NOTE,
    )
    shown = [t.text for t in view.recent_turns]
    assert shown == [t.text for t in state.transcript[-6:]]
    assert "Answer number 0" not in " ".join(shown), "the early turns are gone from the window"
    assert view.round_summary == NOTE, "and the note is what stands in for them"


# ── when it is written ───────────────────────────────────────────────────


def test_the_note_is_due_every_four_turns(db):
    assert summariser.is_due(3) is False
    assert summariser.is_due(4) is True

    engine, row = talking(db, answers=1)
    engine.llm = StubLLM([verdict()], probe=NOTE)
    assert engine.summarise_if_due(row.id) is False, "two turns in, there is little to note"


def test_a_note_is_written_once_four_turns_have_passed_in_this_round(db):
    """Counted from the start of the ROUND, not of the session: a segment
    transition resets it, because the note is a round summary."""
    engine, row = talking(db, answers=1)
    engine.llm = StubLLM([verdict()], probe=NOTE)

    for _ in range(12):
        state = engine.state(row.id)
        if state.next_turn_index - state.summary_at_turn >= summariser.EVERY_N_TURNS:
            break
        if state.open_turn_id is None:
            break
        engine.answer(row.id, state.open_turn_id, "More about buckets and load factor.")

    assert engine.summarise_if_due(row.id) is True
    assert engine.state(row.id).round_summary == NOTE

    # Written, so it is not due again on the very next turn.
    assert engine.summarise_if_due(row.id) is False


def test_a_new_round_starts_its_note_afresh(db):
    """Carrying the last round's note across would have the interviewer open
    by referring to a topic it has just left."""
    engine, row = talking(db, answers=1)
    store.record(
        engine.db,
        engine.row(row.id),
        "summary.written",
        step="summary:test",
        payload={"text": NOTE, "at_turn": 2},
    )
    assert engine.state(row.id).round_summary == NOTE

    store.record(
        engine.db,
        engine.row(row.id),
        "segment.transition",
        step="segment:99",
        payload={"from": 0, "to": 1, "from_title": "A", "to_title": "B", "line": "Next."},
    )
    state = engine.state(row.id)
    assert state.round_summary == ""
    assert state.summary_at_turn == state.next_turn_index, "and the four-turn count restarts"


def test_with_no_model_there_is_no_note_rather_than_an_invented_one(db):
    """An interviewer told "the student discussed hashing" by a template that
    does not know what was discussed is worse than one told nothing."""
    engine, row = talking(db, answers=6)
    engine.llm = NullLLM()
    force_due(engine, row)
    assert engine.summarise_if_due(row.id) is False
    assert engine.state(row.id).round_summary == ""


@pytest.mark.gate
def test_a_note_that_telegraphs_a_verdict_is_dropped(db):
    """It feeds the interviewer, which may not know how an answer scored
    (FR-6.15, AC-6.3) — and anything the note says, the interviewer can read
    back out. The prompt forbids judgement; the guard is what enforces it,
    and it is the SAME guard every interviewer line goes through, so there is
    one definition of a word that gives the game away.
    """
    engine, row = talking(db, answers=1)
    engine.llm = StubLLM([verdict()], probe="The candidate's answer was incorrect on collisions.")
    force_due(engine, row)
    # It IS due, so a False here is the guard and not the schedule.
    assert summariser.is_due(
        engine.state(row.id).next_turn_index - engine.state(row.id).summary_at_turn
    )
    assert engine.summarise_if_due(row.id) is False
    assert engine.state(row.id).round_summary == "", "a telegraphing note is no note"

    # And a note that says the same thing without the verdict is kept, so the
    # gate is about the telegraph rather than about refusing every note.
    engine.llm = StubLLM([verdict()], probe=NOTE)
    force_due(engine, row)
    assert engine.summarise_if_due(row.id) is True
    assert engine.state(row.id).round_summary == NOTE
