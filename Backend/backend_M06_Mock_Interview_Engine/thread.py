"""The open question's thread, read off the session — 2026-10-22. Pure.

A real interviewer listens to a question as a conversation: what they asked,
what the student said, what they asked next. One answer at a time, three
things a student does are invisible — correcting an earlier mistake,
contradicting an earlier statement, and giving the same answer to a new
follow-up. So the strategist and the ladder are handed the thread, assembled
here from the transcript and nothing else.

Every function is a function of the `SessionState`; nothing here calls a
model or the database.
"""

from __future__ import annotations

import re

from .contracts import TurnView
from .items import Item, Part
from .ladder import Context
from .state import SessionState

#: Two answers are "the same answer again" at this word overlap, when both
#: are long enough to mean it.
REPEAT_AT = 0.8
REPEAT_MIN_WORDS = 8

#: An answer that ends on one of these, with no full stop, was cut off — when
#: the room did not already say so.
_DANGLING = frozenset(
    "and or but because so the a an of to with which that then if when where "
    "into by for like is are was were".split()
)
_WORD = re.compile(r"[a-z0-9']+")


def question_turn(state: SessionState) -> TurnView | None:
    """The new question the current thread belongs to."""
    return state.open_question_turn()


def thread_turns(state: SessionState) -> list[TurnView]:
    """Every turn of the current question, from the question itself up to and
    including the latest one."""
    opened = question_turn(state)
    if opened is None:
        return []
    start = next((i for i, t in enumerate(state.transcript) if t.turn_id == opened.turn_id), None)
    if start is None:
        return []
    return [t for t in state.transcript[start:] if t.role in ("interviewer", "candidate")]


def thread_before_answer(state: SessionState) -> tuple[tuple[str, str], ...]:
    """The thread as (role, words), without the answer being judged now."""
    turns = thread_turns(state)
    if turns and turns[-1].role == "candidate":
        turns = turns[:-1]
    return tuple(
        (t.role, (t.question_text or t.text) if t.role == "interviewer" else t.text) for t in turns
    )


def earlier_answers_here(state: SessionState) -> list[str]:
    turns = thread_turns(state)
    answers = [t.text for t in turns if t.role == "candidate"]
    return answers[:-1] if answers else []


def earlier_statements(state: SessionState, limit: int = 3) -> tuple[str, ...]:
    """The student's answers to OTHER questions, newest last — for spotting a
    direct contradiction, never for judging this answer by them."""
    here = {t.turn_id for t in thread_turns(state)}
    said = [
        t.text
        for t in state.transcript
        if t.role == "candidate" and t.turn_id not in here and len(t.text.split()) >= 5
    ]
    return tuple(said[-limit:])


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def is_repeat(answer: str, earlier: list[str]) -> bool:
    """The same answer again: most of its words are an earlier answer's."""
    now = _words(answer)
    if len(now) < REPEAT_MIN_WORDS:
        return False
    for before in earlier:
        then = _words(before)
        if len(then) < REPEAT_MIN_WORDS:
            continue
        if len(now & then) / len(now | then) >= REPEAT_AT:
            return True
    return False


def cut_off(turn: TurnView | None) -> bool:
    """The answer was cut off: the room said so, or it stops mid-sentence."""
    if turn is None or turn.role != "candidate":
        return False
    if turn.completion_reason == "interrupted":
        return True
    text = turn.text.strip()
    if not text or text[-1] in ".?!)\"'":
        return False
    words = _WORD.findall(text.lower())
    return len(words) >= 4 and words[-1] in _DANGLING


def parts_left(item: Item, asked: list[int]) -> tuple[Part, ...]:
    return tuple(p for p in item.parts if p.index not in asked)


def not_asked_yet(state: SessionState, item: Item) -> frozenset[str]:
    """Key points of the parts of this question not asked yet — reported if
    an answer already covers them, never counted against it."""
    asked = state.ladder.parts_asked if state.ladder is not None else []
    return frozenset(k for p in parts_left(item, asked) for k in p.key_point_ids)


def in_scope(item: Item, asked: list[int]) -> list[str]:
    """The key point ids of what this question actually asked — all of them
    for a question asked whole; the primary's and the asked parts' otherwise."""
    later = {k for p in parts_left(item, asked) for k in p.key_point_ids}
    return [kp.id for kp in item.key_points if kp.id not in later]


def claim_text(state: SessionState, item: Item) -> str | None:
    """The resume line a claim question is about, in full."""
    if item.source != "m01_probe":
        return None
    claim_id = item.concept_id.split(":", 1)[-1]
    if state.drill and str(state.drill.get("claim_id")) == claim_id:
        return str(state.drill.get("claim_text") or "") or None
    for claim in state.plan.claims if state.plan is not None else []:
        if str(claim.get("id")) == claim_id:
            return str(claim.get("text") or "") or None
    return item.label or None


def context(state: SessionState, item: Item, answer: str) -> Context:
    """What the ladder knows besides the answer."""
    ladder = state.ladder
    topic = state.topics.get(item.concept_id) if item.concept_id else None
    last = state.transcript[-1] if state.transcript else None
    return Context(
        parts_left=parts_left(item, ladder.parts_asked if ladder else []),
        topic_level=topic.level if topic is not None else 0,
        repeated_answer=is_repeat(answer, earlier_answers_here(state)),
        cut_off=cut_off(last),
        seen_misconceptions=tuple(topic.misconceptions) if topic is not None else (),
        key_points={kp.id: kp.statement for kp in item.key_points},
        required=frozenset(kp.id for kp in item.key_points if kp.required),
    )


def recent_openers(state: SessionState, persona_id: str, n: int = 4) -> list[str]:
    """How this interviewer opened their last few lines — never the same way
    twice running."""
    from .agents.interviewer import opener  # noqa: PLC0415 — agents import this module's peers

    said: list[str] = []
    for turn in state.transcript:
        if turn.role != "interviewer":
            continue
        if turn.parts:
            said.extend(p.text for p in turn.parts if p.speaker_id == persona_id)
        elif turn.speaker_id == persona_id:
            said.append(turn.text)
    return [o for o in (opener(s) for s in said[-n:]) if o]


__all__ = [
    "claim_text",
    "context",
    "cut_off",
    "earlier_statements",
    "is_repeat",
    "parts_left",
    "recent_openers",
    "thread_before_answer",
    "thread_turns",
]
