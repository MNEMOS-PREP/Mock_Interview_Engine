"""The question bank as a book: subjects, topics, questions — from M06's own
tables, with no call to anybody. Pure apart from reading those tables.

Where each part comes from, in order of trust:

  the question     the item's own stem, as the interview asked it
  its answer       the item's reference answer — from the event log, else from
                   M05's item (`QBankLookup` "q:", fetched by `refresh`) — and
                   only where there is none, one the writer wrote (`answers`)
  key points       the item's, the same way; a resume line's `expects`
  follow-ups       the ones asked, merged and answered by the writer; until
                   it has, the asked ones as they were said
  the subject      the item's M05 track (DSA, OOP, Machine learning…) — the
                   setup page's own names and order — else the track of
                   another question on the same concept, else M04's domain
  the topic        M04's name for the concept, else the concept id in words

Every part says which it is (`Entry.answer_kind`), and the page prints it: a
reviewed answer, a practice answer nobody has reviewed yet, or one written
for the bank.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlmodel import Session, select

from ..models import QBankAnswer, QBankLookup
from . import answers as answers_module
from .collect import Asked, discovered

#: Sources whose items live in M05's bank, where `refresh` may look them up.
M05_SOURCES = frozenset({"m05_bank", "m05_draft", "m05_fallback", "revisit"})
RESUME_SUBJECT = "resume"
OTHER_SUBJECT = "other"
#: A subject's colours, by its place in the book: accent (white text on it
#: passes WCAG AA) and the tint its answers sit on.
PALETTE: tuple[tuple[str, str], ...] = (
    ("#176b55", "#eaf4ee"),  # the platform's own green
    ("#2b5c8a", "#e9f0f7"),
    ("#6b4c9a", "#f0ecf6"),
    ("#0e6b75", "#e5f2f3"),
    ("#a14a24", "#f8eee8"),
    ("#55652a", "#eff2e6"),
    ("#9b2f55", "#f7eaef"),
    ("#7a5510", "#f6efe1"),
    ("#40505e", "#edf0f3"),
)


@dataclass
class FollowUp:
    question: str
    #: Empty while it is still to be written.
    answer: str = ""


@dataclass
class Entry:
    key: str
    question: str
    answer: str
    #: `reviewed` · `practice` (an answer nobody has reviewed yet) · `written`
    #: (by the bank's writer) · `guide` (how to answer a line of your resume)
    #: · `pending` (nothing to print yet).
    answer_kind: str
    key_points: list[str] = field(default_factory=list)
    follow_ups: list[FollowUp] = field(default_factory=list)
    #: The follow-ups were asked but are not answered yet.
    follow_ups_pending: bool = False
    times: int = 0
    first_at: str | None = None
    asked: bool = True


@dataclass
class Topic:
    name: str
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Subject:
    key: str
    title: str
    blurb: str = ""
    #: Answered from the student's own life (behavioural, their resume): the
    #: bank's answer is an example to model, never a script to recite.
    personal: bool = False
    accent: str = PALETTE[0][0]
    tint: str = PALETTE[0][1]
    topics: list[Topic] = field(default_factory=list)

    @property
    def entries(self) -> list[Entry]:
        return [e for t in self.topics for e in t.entries]


@dataclass
class Book:
    name: str = ""
    subjects: list[Subject] = field(default_factory=list)

    @property
    def entries(self) -> list[Entry]:
        return [e for s in self.subjects for e in s.entries]

    @property
    def questions(self) -> int:
        return len(self.entries)

    @property
    def follow_ups(self) -> int:
        return sum(len(e.follow_ups) for e in self.entries)

    @property
    def pending(self) -> int:
        """Questions with something still to be written."""
        return sum(1 for e in self.entries if e.answer_kind == "pending" or e.follow_ups_pending)

    def fingerprint(self) -> str:
        """What the page shows, hashed: the same book is not drawn twice."""
        text = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()[:32]


# ── what other modules said, as kept ─────────────────────────────────────────


def lookups(db: Session, keys: set[str]) -> dict[str, QBankLookup]:
    if not keys:
        return {}
    rows = db.exec(select(QBankLookup).where(QBankLookup.key.in_(sorted(keys)))).all()  # type: ignore[attr-defined]
    return {row.key: row for row in rows}


def enrich(question: Asked, found: dict[str, QBankLookup]) -> Asked:
    """Fill what the event log lacks from M05's item, as kept. In place."""
    if question.question_id and question.source in M05_SOURCES:
        row = found.get(f"q:{question.question_id}")
        if row is not None and row.found:
            item = row.payload
            if not question.reference_answer:
                question.reference_answer = str(item.get("reference_answer") or "").strip()
            if not question.key_points:
                question.key_points = [s for s in item.get("key_points") or [] if s]
            if not question.rubric_round_type and item.get("round_types"):
                question.rubric_round_type = str(item["round_types"][0])
            if not question.label and item.get("label"):
                question.label = str(item["label"])
    return question


# ── naming ───────────────────────────────────────────────────────────────────


def _words(identifier: str) -> str:
    """`concept:hashing_internals` → "Hashing internals"; short ids, which are
    acronyms in this platform's vocabulary (`dbms_verbal` → "DBMS"), upper."""
    base = identifier.split(":", 1)[-1].removesuffix("_verbal")
    parts = [p for p in re.split(r"[_\-\s]+", base) if p]
    if len(parts) == 1 and len(parts[0]) <= 4:
        return parts[0].upper()
    text = " ".join(parts)
    return text[:1].upper() + text[1:]


def topic_name(question: Asked, found: dict[str, QBankLookup]) -> str:
    if question.about_you and not question.resume:
        return "Opening questions"
    if question.resume:
        line = " ".join((question.label or "").split())
        return line if len(line) <= 70 else line[:67].rsplit(" ", 1)[0] + "…"
    row = found.get(f"c:{question.concept_id}")
    if row is not None and row.found and row.payload.get("name"):
        return str(row.payload["name"])
    if question.label:
        return question.label
    return _words(question.concept_id) if question.concept_id else "General"


def _tracks(found: dict[str, QBankLookup]) -> list[dict[str, Any]]:
    row = found.get("tracks")
    return list((row.payload or {}).get("tracks") or []) if row is not None else []


# ── the book ─────────────────────────────────────────────────────────────────


def _answer(question: Asked, written: QBankAnswer | None) -> tuple[str, str]:
    if question.reference_answer:
        kind = "reviewed" if question.source == "m05_bank" else "practice"
        return question.reference_answer, kind
    if written is not None and written.status == "ready" and written.payload.get("answer"):
        return str(written.payload["answer"]), "guide" if question.about_you else "written"
    return "", "pending"


def _follow_ups(question: Asked, written: QBankAnswer | None) -> tuple[list[FollowUp], bool]:
    if written is not None and written.status == "ready":
        return [
            FollowUp(question=str(f["question"]), answer=str(f["answer"]))
            for f in written.payload.get("follow_ups") or []
        ], False
    asked = [
        FollowUp(question=text) for text in question.follow_ups[: answers_module.MAX_FOLLOW_UPS]
    ]
    failed = written is not None and written.status == "failed"
    return asked, bool(asked) and not failed


def prepare(db: Session, candidate_id: Any) -> tuple[list[Asked], dict[str, QBankLookup]]:
    """The student's questions, filled from what other modules said, and
    what they said. The writer (`refresh`) and the book both start here, so
    a question's brief — and the key of what was written for it — is the
    same for both."""
    found_qs = discovered(db, candidate_id)
    keys = {"tracks"}
    for q in found_qs:
        if q.question_id:
            keys.add(f"q:{q.question_id}")
        if q.concept_id:
            keys.add(f"c:{q.concept_id}")
    found = lookups(db, keys)
    for q in found_qs:
        enrich(q, found)
    return found_qs, found


def build(db: Session, candidate_id: Any, *, name: str = "") -> Book:
    """The book for one student, as it stands in M06's tables right now."""
    found_qs, found = prepare(db, candidate_id)

    hashes = {
        q.key: answers_module.brief_hash(q) for q in found_qs if answers_module.needs_writing(q)
    }
    rows = (
        {
            row.brief_hash: row
            for row in db.exec(
                select(QBankAnswer).where(QBankAnswer.brief_hash.in_(sorted(set(hashes.values()))))  # type: ignore[attr-defined]
            ).all()
        }
        if hashes
        else {}
    )

    # The subject: the item's track, else a track another question on the
    # same concept has, else M04's domain for the concept.
    concept_track = {
        q.concept_id: q.rubric_round_type for q in found_qs if q.concept_id and q.rubric_round_type
    }
    tracks = _tracks(found)
    titles = {str(t.get("round_type")): t for t in tracks if t.get("round_type")}
    order = {str(t.get("round_type")): n for n, t in enumerate(tracks)}

    subjects: dict[str, Subject] = {}
    topics: dict[tuple[str, str], Topic] = {}
    for q in found_qs:
        personal = False
        if q.about_you:
            key, title, blurb = (
                RESUME_SUBJECT,
                "You, your resume and projects",
                (
                    "The questions only you can answer: how to open, and the lines of "
                    "your resume the interviewers asked you to defend — what to say, in "
                    "which order."
                ),
            )
        else:
            track = q.rubric_round_type or concept_track.get(q.concept_id)
            domain_row = found.get(f"c:{q.concept_id}")
            domain = (
                str(domain_row.payload.get("domain") or "")
                if domain_row is not None and domain_row.found
                else ""
            )
            if track:
                meta = titles.get(track, {})
                key, title, blurb = (
                    track,
                    str(meta.get("title") or _words(track)),
                    str(meta.get("blurb") or ""),
                )
                personal = meta.get("kind") == "behavioural"
            elif domain:
                key, title, blurb = f"domain:{domain}", _words(domain), ""
            else:
                key, title, blurb = OTHER_SUBJECT, "More questions", ""
        subject = subjects.get(key)
        if subject is None:
            subject = subjects[key] = Subject(
                key=key, title=title, blurb=blurb, personal=personal or q.about_you
            )
        topic_title = topic_name(q, found)
        topic = topics.get((key, topic_title))
        if topic is None:
            topic = topics[(key, topic_title)] = Topic(name=topic_title)
            subject.topics.append(topic)
        written = rows.get(hashes.get(q.key, ""))
        answer, kind = _answer(q, written)
        follow_ups, pending = _follow_ups(q, written)
        topic.entries.append(
            Entry(
                key=q.key,
                question=q.stem,
                answer=answer,
                answer_kind=kind,
                key_points=list(q.key_points or q.expects),
                follow_ups=follow_ups,
                follow_ups_pending=pending,
                times=q.times,
                first_at=q.first_at.date().isoformat() if q.first_at and q.asked else None,
                asked=q.asked,
            )
        )

    def place(subject: Subject) -> tuple[int, int, str]:
        if subject.key == RESUME_SUBJECT:
            return (2, 0, "")
        if subject.key == OTHER_SUBJECT:
            return (3, 0, "")
        if subject.key in order:
            return (0, order[subject.key], subject.title)
        return (1, 0, subject.title)

    ordered = sorted(subjects.values(), key=place)
    for n, subject in enumerate(ordered):
        subject.accent, subject.tint = PALETTE[n % len(PALETTE)]
    return Book(name=name, subjects=ordered)


__all__ = [
    "Book",
    "Entry",
    "FollowUp",
    "M05_SOURCES",
    "PALETTE",
    "Subject",
    "Topic",
    "build",
    "enrich",
    "prepare",
]
