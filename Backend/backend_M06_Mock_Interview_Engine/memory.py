"""Between interviews: the attempts a student has made, and their library.

The user's spec §9–§10, §14 (2026-10-22). Two tables, both written only by
the module that saw the answers:

* `QuestionAttempt` — one row per question per interview, written when the
  question's thread closes: how it was left (`held`, `gap:…`, `unsupported`,
  skipped…), what each answer was, whether an error was corrected and with
  whose help, the misconception left standing. Idempotent per (session,
  question turn), so a question closed twice is remembered once.
* `SavedQuestion` — the student's library: one entry per student per
  question (`question_key`), however many interviews asked it. Two marks, each
  independent of the other and either one enough to keep the entry: STARRED by
  the student, FLAGGED by the interview when the question was left as a real
  gap. Unstarring a flagged question keeps it; a question that goes well later
  keeps its flag until the student removes it — the flag says it WAS hard.

**Evidence, not reputation.** What is kept is what happened, in the student's
own words and the interview's own outcomes. Nothing here is read back into a
later interview's JUDGEMENT of an answer: a revisited question is judged on
the new answer alone (`thread.py` hands the strategist this interview's
statements, never another's). The comparison is made afterwards, in the
notes and the library (`compare`).

**One student's.** Every read is by `candidate_id`, and the routes are behind
the same identity check as every other (`access.py`).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ai_core.timeutil import utcnow
from sqlmodel import Session, select

from . import outbox
from .items import Item, to_dict
from .models import QuestionAttempt, SavedQuestion
from .state import SessionState

#: How a question was left that makes it worth practising again.
DIFFICULT = frozenset(
    {
        "gap:misunderstanding",
        "gap:complete",
        "gap:surface",
        "gap:advanced",
        "unsupported",
        "avoided",
        "skipped",
    }
)
#: Or: its answers, on average, showed this little.
DIFFICULT_BELOW = 0.35

#: Plain words for an outcome — the library's and the notes'.
OUTCOME_WORDS = {
    "held": "Answered well",
    "ceiling": "Answered well, to the deepest follow-up",
    "gap:minor": "A small slip",
    "gap:detail": "Knew the idea, not the detail",
    "gap:incomplete": "Partly answered",
    "gap:surface": "Stayed at the level of terms",
    "gap:advanced": "The basics held; the deeper part did not",
    "gap:misunderstanding": "A misunderstanding that stood",
    "gap:complete": "Not answered",
    "unsupported": "A claim not backed up",
    "avoided": "Answered a different question",
    "no_answer": "No attempt",
    "skipped": "Skipped",
    "silence": "Moved on after a silence",
    # 2026-10-23: the model that reads answers was down — nothing is said
    # about how it went, either way.
    "unjudged": "Not judged: the answer checker was unavailable",
    "ended": "The interview ended here",
}


def question_key(question_id: uuid.UUID | str | None, stem: str) -> str:
    """One entry per question: the bank's id, or — for a resume probe or a
    backup question, which have none — the words themselves."""
    if question_id:
        return f"q:{question_id}"
    normal = " ".join(stem.split()).lower()
    return "stem:" + hashlib.sha1(normal.encode()).hexdigest()[:16]


def _outcome(decisions: list[dict], how: str | None) -> str | None:
    left = next((d.get("left") for d in reversed(decisions) if d.get("left")), None)
    return left or how


def remember(
    db: Session,
    state: SessionState,
    question: Any,
    decisions: list[dict],
    item: Item | None,
    *,
    how: str | None = None,
) -> QuestionAttempt | None:
    """Write this question's attempt, and flag it in the library when it was
    left as a real gap. Never raises into the interview."""
    if item is None or item.source == "closing" or question.retry:
        return None
    _question, asked, answered = outbox.thread_of(state, question.turn_id)
    if not answered:
        return None
    existing = db.exec(
        select(QuestionAttempt)
        .where(QuestionAttempt.session_id == state.session_id)
        .where(QuestionAttempt.question_turn_id == question.turn_id)
    ).first()
    if existing is not None:
        return existing
    qualities = [float(d["quality"]) for d in decisions if d.get("quality") is not None]
    outcome = _outcome(decisions, how)
    key = question_key(question.question_id, item.full_stem or item.stem)
    attempt = QuestionAttempt(
        candidate_id=state.candidate_id,
        question_key=key,
        session_id=state.session_id,
        question_turn_id=question.turn_id,
        answer_turn_id=answered[0].turn_id,
        stem=item.full_stem or item.stem,
        concept_id=item.concept_id,
        outcome=outcome,
        categories=[d["category"] for d in decisions if d.get("category")],
        quality=round(sum(qualities) / len(qualities), 3) if qualities else None,
        depth=max((t.probe_depth for t in asked), default=0),
        corrected=next((d["corrected"] for d in decisions if d.get("corrected")), None),
        misconception=next(
            (d["misconception"] for d in reversed(decisions) if d.get("misconception")), None
        ),
        answers=[t.text[:1200] for t in answered][:6],
    )
    db.add(attempt)
    hard = outcome in DIFFICULT or (
        attempt.quality is not None and attempt.quality < DIFFICULT_BELOW
    )
    if hard:
        entry = _entry(db, state.candidate_id, key, question, item, state)
        if entry.flagged_at is None:
            entry.flagged_at = utcnow()
        entry.flagged_reason = OUTCOME_WORDS.get(outcome or "", outcome)
        entry.last_session_id = state.session_id
        entry.updated_at = utcnow()
        db.add(entry)
    db.commit()
    return attempt


def _entry(
    db: Session,
    candidate_id: uuid.UUID,
    key: str,
    question: Any,
    item: Item,
    state: SessionState,
) -> SavedQuestion:
    found = db.exec(
        select(SavedQuestion)
        .where(SavedQuestion.candidate_id == candidate_id)
        .where(SavedQuestion.question_key == key)
    ).first()
    if found is not None:
        return found
    from . import thread  # noqa: PLC0415 — thread imports state, like this module

    return SavedQuestion(
        candidate_id=candidate_id,
        question_key=key,
        question_id=question.question_id,
        stem=item.full_stem or item.stem,
        concept_id=item.concept_id,
        topic=item.label or item.concept_id.split(":", 1)[-1].replace("_", " "),
        source=item.source,
        claim_text=thread.claim_text(state, item),
        item=to_dict(item),
        first_session_id=state.session_id,
        last_session_id=state.session_id,
    )


def star(
    db: Session, state: SessionState, question: Any, item: Item | None, *, on: bool
) -> SavedQuestion | None:
    """The student's own mark. Unstarring keeps an entry the interview flagged."""
    if item is None:
        return None
    key = question_key(question.question_id, item.full_stem or item.stem)
    entry = _entry(db, state.candidate_id, key, question, item, state)
    entry.starred_at = utcnow() if on else None
    entry.last_session_id = state.session_id
    entry.updated_at = utcnow()
    if entry.starred_at is None and entry.flagged_at is None:
        if entry.id is not None and db.get(SavedQuestion, entry.id) is not None:
            db.delete(entry)
            db.commit()
        return None
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def attempts_for(db: Session, candidate_id: uuid.UUID, key: str) -> list[QuestionAttempt]:
    return list(
        db.exec(
            select(QuestionAttempt)
            .where(QuestionAttempt.candidate_id == candidate_id)
            .where(QuestionAttempt.question_key == key)
            .order_by(QuestionAttempt.at)
        ).all()
    )


def compare(attempts: list[QuestionAttempt]) -> str | None:
    """The latest attempt against the one before it, in plain words — or
    None when there is nothing to compare. Outcomes and the answers' own
    quality only: never a score from M13 (its numbers are behind its gate)."""
    if len(attempts) < 2:
        return None
    before, now = attempts[-2], attempts[-1]
    if now.quality is None or before.quality is None:
        return None
    delta = now.quality - before.quality
    then_words = OUTCOME_WORDS.get(before.outcome or "", "answered")
    now_words = OUTCOME_WORDS.get(now.outcome or "", "answered")
    if before.misconception and not now.misconception and delta > 0:
        return f"Last time: {then_words.lower()} ({before.misconception}). This time it held."
    if delta >= 0.25:
        return f"Better than last time: {then_words.lower()} then, {now_words.lower()} now."
    if delta <= -0.25:
        return f"Harder than last time: {then_words.lower()} then, {now_words.lower()} now."
    return f"About the same as last time: {now_words.lower()}."


def library(db: Session, candidate_id: uuid.UUID) -> list[SavedQuestion]:
    return list(
        db.exec(
            select(SavedQuestion)
            .where(SavedQuestion.candidate_id == candidate_id)
            .order_by(SavedQuestion.updated_at.desc())  # type: ignore[union-attr]
        ).all()
    )


def marks(db: Session, candidate_id: uuid.UUID, keys: set[str]) -> dict[str, tuple[bool, bool]]:
    """(starred, flagged) for each of these questions the student has saved."""
    found = db.exec(
        select(SavedQuestion)
        .where(SavedQuestion.candidate_id == candidate_id)
        .where(SavedQuestion.question_key.in_(sorted(keys)))  # type: ignore[attr-defined]
    ).all()
    return {e.question_key: (e.starred_at is not None, e.flagged_at is not None) for e in found}


def remove(db: Session, candidate_id: uuid.UUID, entry_id: uuid.UUID) -> bool:
    entry = db.get(SavedQuestion, entry_id)
    if entry is None or entry.candidate_id != candidate_id:
        return False
    db.delete(entry)
    db.commit()
    return True


__all__ = [
    "DIFFICULT",
    "OUTCOME_WORDS",
    "attempts_for",
    "compare",
    "library",
    "question_key",
    "remember",
    "remove",
    "star",
]
