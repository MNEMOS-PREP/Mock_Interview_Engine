"""What a student has met in their interviews — read from the event log. Pure.

A question enters the bank once it was ADDRESSED: asked, answered at least
once, and its thread closed — the interviewer moved to another question, or
the session ended. An open thread is left out until it closes, so the bank
never holds the answer key to a question still being asked (§2.2: the notes
wait for the end for the same reason, and the bank waits only for the
question).

What is kept is the question, never the student's answer to it: the item's
stem, its reference answer and key points (the answer key M05 wrote), and the
follow-ups the interviewer actually asked. How the student did is the notes'
business; the bank is what to revise, whatever happened.

Follow-ups are the moves that ask something new — a deeper rung, a missing
point, a challenge, a simpler question, a request for specifics or evidence.
Moves that only manage the conversation (put the question again, clarify,
redirect, hint) are not questions of their own, and a next PART of the stem is
already in the stem.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from ..memory import question_key
from ..models import InterviewSession, QBankSeed, SessionEvent

#: Interviewer moves that ask a question of their own (`ladder.decide`).
CONTENT_MOVES = frozenset(
    {
        "rung",
        "probe_missing",
        "probe_specifics",
        "challenge",
        "simplify",
        "confront",
        "ask_evidence",
    }
)
#: The events the bank is built from — and nothing else is read.
KINDS = ("question.asked", "answer.received", "session.ended", "session.aborted")
#: Sources whose questions are about one student's own resume: theirs alone,
#: never seeded into anybody else's bank.
RESUME_SOURCES = frozenset({"m01_probe"})
#: …and the opening line every interview may start with, which any student can
#: be asked (so it may be seeded) but only they can answer.
ABOUT_YOU_SOURCES = frozenset({"template"})
#: Two follow-ups are the same question at this content-word overlap. Words
#: catch only the near-copies: "why is it O(1)?" and "why is lookup
#: constant-time?" share few, and the writer merges those (`answers.py`).
SAME_AT = 0.5

_WORD = re.compile(r"[a-z0-9]+")
_FILLER = frozenset(
    "the a an and or of to in on for with that this what how why when which is are be "
    "you your would could can does do it its as at by from if then than so there they "
    "we i me my about into explain describe tell walk through".split()
)


@dataclass
class Asked:
    """One question as the student met it, across every interview that asked it."""

    key: str
    stem: str
    source: str = ""
    question_id: str | None = None
    concept_id: str = ""
    label: str = ""
    rubric_round_type: str | None = None
    reference_answer: str = ""
    key_points: list[str] = field(default_factory=list)
    #: A resume probe's "what a strong answer shows", by depth, flattened.
    expects: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    first_at: datetime | None = None
    last_at: datetime | None = None
    times: int = 1
    #: False for a question seeded into the bank, not asked of this student.
    asked: bool = True

    @property
    def resume(self) -> bool:
        return self.source in RESUME_SOURCES

    @property
    def about_you(self) -> bool:
        """A question only the student can answer: a line of their resume, or
        the opening "walk me through your resume" (a `template` line)."""
        return self.resume or self.source in ABOUT_YOU_SOURCES

    def payload(self) -> dict[str, Any]:
        out = asdict(self)
        for name in ("first_at", "last_at"):
            out[name] = out[name].isoformat() if out[name] else None
        return out

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> Asked:
        known = set(cls.__dataclass_fields__)
        values = {k: v for k, v in data.items() if k in known}
        for name in ("first_at", "last_at"):
            if isinstance(values.get(name), str):
                values[name] = datetime.fromisoformat(values[name])
        return cls(**values)


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in _FILLER and len(w) > 1)


def same_question(a: str, b: str) -> bool:
    left, right = words(a), words(b)
    if not left or not right:
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return len(left & right) / len(left | right) >= SAME_AT


def _normal(stem: str) -> str:
    return " ".join(stem.lower().split())


def _points(item: dict[str, Any]) -> list[str]:
    return [str(kp.get("statement") or "").strip() for kp in item.get("key_points") or []]


def _expects(item: dict[str, Any]) -> list[str]:
    raw = item.get("expects") or {}
    out: list[str] = []
    for depth in sorted(raw, key=lambda d: int(d) if str(d).isdigit() else 0):
        for point in raw[depth] or []:
            text = str(point.get("statement") if isinstance(point, dict) else point).strip()
            if text and text not in out:
                out.append(text)
    return out


def _generic() -> tuple[str, ...]:
    """The stock follow-ups that fit any question ("Can you say more about
    why that works?") — read from the phrasebook that says them, so a new
    stock line is recognised the day it is added."""
    from ..phrasebook import ANGLE_RUNGS, GENERIC_RUNGS  # noqa: PLC0415

    return (*GENERIC_RUNGS.values(), *ANGLE_RUNGS.values())


def generic(text: str) -> bool:
    """A follow-up with nothing of its question in it: out of the interview,
    it asks nothing a student could revise."""
    return any(same_question(text, stock) for stock in _generic())


#: "Right. Besides chaining, what…" — a short sentence that is not a question,
#: before the one that is: the interviewer acknowledging, not asking.
_LEAD_IN = re.compile(r"^(?:[^.?!]{1,24}[.!])\s+(?=\S[^?]*\?)")


def strip_lead_in(text: str) -> str:
    text = " ".join(text.split())
    rest = _LEAD_IN.sub("", text, count=1)
    return rest if len(words(text) - words(rest)) <= 3 else text


def _add_follow_up(entry: Asked, text: str) -> None:
    text = strip_lead_in(text)
    if not text or same_question(text, entry.stem) or generic(text):
        return
    if any(same_question(text, seen) for seen in entry.follow_ups):
        return
    entry.follow_ups.append(text)


def from_events(events: Iterable[SessionEvent]) -> list[Asked]:
    """The questions one interview addressed, in the order it asked them."""
    out: list[Asked] = []
    current: Asked | None = None
    answered = False

    def close() -> None:
        nonlocal current, answered
        if current is not None and answered:
            out.append(current)
        current, answered = None, False

    for event in sorted(events, key=lambda e: e.seq):
        p = event.payload or {}
        if event.kind in ("session.ended", "session.aborted"):
            close()
            continue
        if event.kind == "answer.received":
            if current is not None and str(p.get("text") or "").strip():
                answered = True
            continue
        if event.kind != "question.asked":
            continue
        if p.get("question_source") == "closing":
            # FR-6.21: "any questions for me?" is not one of ours.
            close()
            continue
        if p.get("retry"):
            continue
        is_new = p.get("new_question", p.get("probe_move") is None)
        if is_new or current is None:
            close()
            item = p.get("item") or {}
            stem = str(item.get("full_stem") or item.get("stem") or p.get("question_text") or "")
            stem = " ".join(stem.split())
            if not stem:
                continue
            qid = item.get("question_id") or p.get("question_id")
            current = Asked(
                key=question_key(qid, stem),
                stem=stem,
                source=str(item.get("source") or p.get("question_source") or ""),
                question_id=str(qid) if qid else None,
                concept_id=str(item.get("concept_id") or p.get("concept_id") or ""),
                label=str(item.get("label") or ""),
                rubric_round_type=item.get("rubric_round_type") or p.get("rubric_round_type"),
                reference_answer=str(item.get("reference_answer") or "").strip(),
                key_points=[s for s in _points(item) if s],
                expects=_expects(item),
                first_at=event.at,
                last_at=event.at,
            )
            continue
        if p.get("probe_move") in CONTENT_MOVES:
            _add_follow_up(current, str(p.get("question_text") or p.get("text") or ""))
    # A session still running leaves its open question out: it is not closed.
    return out


def merge(found: Iterable[Asked]) -> list[Asked]:
    """One entry per question, however many interviews asked it — by its key,
    or by its words when two items carry the same stem (a fallback copy)."""
    by_key: dict[str, Asked] = {}
    by_stem: dict[str, Asked] = {}
    order: list[Asked] = []
    for one in found:
        target = by_key.get(one.key) or by_stem.get(_normal(one.stem))
        if target is None:
            fresh = Asked(**{**one.__dict__, "follow_ups": list(one.follow_ups)})
            by_key[one.key] = by_stem[_normal(one.stem)] = fresh
            order.append(fresh)
            continue
        by_key.setdefault(one.key, target)
        if one.asked and not target.asked:
            # Asked of this student after all: their own dates, not the seed's.
            target.asked, target.times = True, one.times
            target.first_at, target.last_at = one.first_at, one.last_at
        elif one.asked:
            target.times += one.times
            starts = [t for t in (target.first_at, one.first_at) if t]
            ends = [t for t in (target.last_at, one.last_at) if t]
            target.first_at = min(starts) if starts else None
            target.last_at = max(ends) if ends else None
        for name in ("reference_answer", "rubric_round_type", "concept_id", "label", "question_id"):
            if not getattr(target, name) and getattr(one, name):
                setattr(target, name, getattr(one, name))
        if not target.key_points and one.key_points:
            target.key_points = list(one.key_points)
        if not target.expects and one.expects:
            target.expects = list(one.expects)
        for text in one.follow_ups:
            _add_follow_up(target, text)
    return order


def candidate_sessions(db: Session, candidate_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.exec(
            select(InterviewSession.id)
            .where(InterviewSession.candidate_id == candidate_id)
            .order_by(InterviewSession.created_at)
        ).all()
    )


def events_of(db: Session, session_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[SessionEvent]]:
    """The events the bank reads, for many sessions in one query."""
    out: dict[uuid.UUID, list[SessionEvent]] = {sid: [] for sid in session_ids}
    if not session_ids:
        return out
    rows = db.exec(
        select(SessionEvent)
        .where(SessionEvent.session_id.in_(session_ids))  # type: ignore[attr-defined]
        .where(SessionEvent.kind.in_(KINDS))  # type: ignore[attr-defined]
        .order_by(SessionEvent.session_id, SessionEvent.seq)
    ).all()
    for row in rows:
        out[row.session_id].append(row)
    return out


def asked_of(db: Session, candidate_id: uuid.UUID) -> list[Asked]:
    """Every question this student's interviews addressed, oldest first."""
    sessions = candidate_sessions(db, candidate_id)
    by_session = events_of(db, sessions)
    found: list[Asked] = []
    for session_id in sessions:
        found.extend(from_events(by_session[session_id]))
    return found


def seeded_of(db: Session, candidate_id: uuid.UUID) -> list[Asked]:
    rows = db.exec(
        select(QBankSeed).where(QBankSeed.candidate_id == candidate_id).order_by(QBankSeed.added_at)
    ).all()
    out = []
    for row in rows:
        try:
            one = Asked.from_payload(row.payload)
        except (TypeError, ValueError):
            continue
        one.asked = False
        one.times = 0
        out.append(one)
    return out


def discovered(db: Session, candidate_id: uuid.UUID) -> list[Asked]:
    """The student's own questions, then any seeded ones they were not asked."""
    return merge([*asked_of(db, candidate_id), *seeded_of(db, candidate_id)])


__all__ = [
    "CONTENT_MOVES",
    "RESUME_SOURCES",
    "Asked",
    "asked_of",
    "discovered",
    "from_events",
    "merge",
    "same_question",
    "seeded_of",
]
