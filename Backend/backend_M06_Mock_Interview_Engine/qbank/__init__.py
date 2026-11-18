"""The question bank a student has discovered — `q_bank_discovered.pdf`.

The user's ask (2026-11-18): a PDF that grows as a student answers interview
questions — one styled section per subject (OOP, Machine learning…), every
question they have met with the answer to say, whatever their own answer
was — downloadable from the home page.

    collect.py   the questions a student addressed, from the event log
    book.py      those questions as subjects and topics, with their answers
    answers.py   the answers nobody wrote (follow-ups), by a model, checked
    render.py    the PDF

**It is always current.** A download draws the book from M06's tables and
compares it with the last one drawn (`Book.fingerprint`): the same book is
served from disk, a changed one is drawn again (~0.2 s). So the file is the
student's bank as of their last closed question, not as of a nightly job.

**And it fills in behind the interview.** After every answer (the answer and
end routes), `refresh` runs as a background task: it asks M05 for what an old
event log lacks (an item's track and answer key) and M04 for its concepts'
names, keeps what they said (`QBankLookup`), redraws the file, and has the
follow-ups written (`QBankAnswer`) — off every request path, like the notes.
A module that is down costs a heading or an answer, never the file.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ai_core.timeutil import utcnow
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from ..models import LLMCall, QBankAnswer, QBankLookup
from . import answers as answers_module
from . import render as drawing
from .book import M05_SOURCES, Book, build, prepare
from .collect import Asked

FILE_NAME = drawing.FILE_NAME

log = logging.getLogger("uvicorn.error")

#: A "no such item" or "no such concept" is asked again after this.
RECHECK_MISSING = timedelta(days=7)
#: M05's track names and order.
TRACKS_TTL = timedelta(days=1)
#: Tries per brief before the bank prints the follow-ups unanswered.
MAX_ATTEMPTS = 2
#: A brief claimed for writing this long ago and not finished was lost (a
#: restart mid-call): another refresh may take it.
CLAIM = timedelta(minutes=5)
#: Tokens a minute the writer keeps under on a free tier (Groq's is 8K).
TOKENS_PER_MINUTE = 6000


def storage_dir() -> Path:
    """Where each student's file is kept: `M06_QBANK_DIR`, else beside the
    database the service runs on."""
    return Path(os.getenv("M06_QBANK_DIR") or "qbank_files")


def _paths(candidate_id: uuid.UUID) -> tuple[Path, Path]:
    base = storage_dir() / str(candidate_id)
    return base / FILE_NAME, base / "book.json"


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(candidate_id: uuid.UUID) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(candidate_id), threading.Lock())


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


# ── the name on the cover ────────────────────────────────────────────────────


def name_of(db: Session, candidate_id: uuid.UUID) -> str:
    row = db.get(QBankLookup, f"p:{candidate_id}")
    return str(row.payload.get("name") or "") if row is not None else ""


def remember_name(db: Session, candidate_id: uuid.UUID, name: str) -> None:
    """The name the student's own page asked with, kept so a redraw after an
    answer still says whose bank it is. M06 holds no profile of its own."""
    name = " ".join(name.split())[:60]
    if not name or name == name_of(db, candidate_id):
        return
    row = db.get(QBankLookup, f"p:{candidate_id}") or QBankLookup(key=f"p:{candidate_id}")
    row.payload, row.found, row.fetched_at = {"name": name}, True, utcnow()
    db.add(row)
    db.commit()


# ── the file ─────────────────────────────────────────────────────────────────


@dataclass
class Current:
    book: Book
    pdf: bytes
    updated: datetime
    fingerprint: str

    def summary(self) -> dict[str, Any]:
        return {
            "file_name": FILE_NAME,
            "questions": self.book.questions,
            "follow_ups": self.book.follow_ups,
            "pending": self.book.pending,
            "updated_at": self.updated.isoformat(),
            "subjects": [
                {"title": s.title, "questions": len(s.entries), "accent": s.accent}
                for s in self.book.subjects
            ],
        }


def current(db: Session, candidate_id: uuid.UUID, *, name: str | None = None) -> Current:
    """The student's bank as it stands, drawn again only if it changed."""
    if name:
        remember_name(db, candidate_id, name)
    book = build(db, candidate_id, name=name_of(db, candidate_id))
    fingerprint = book.fingerprint()
    pdf_path, meta_path = _paths(candidate_id)
    with _lock(candidate_id):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            if meta.get("fingerprint") == fingerprint and pdf_path.exists():
                return Current(
                    book,
                    pdf_path.read_bytes(),
                    datetime.fromisoformat(meta["updated"]),
                    fingerprint,
                )
        except (OSError, ValueError, KeyError):
            log.info("M06: question bank of %s unreadable on disk; drawing it again", candidate_id)
        updated = datetime.now().astimezone()
        pdf = drawing.render(book, updated=updated)
        try:
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = pdf_path.with_suffix(".tmp")
            tmp.write_bytes(pdf)
            os.replace(tmp, pdf_path)
            meta_path.write_text(
                json.dumps({"fingerprint": fingerprint, "updated": updated.isoformat()}),
                encoding="utf-8",
            )
        except OSError:
            # Served all the same: the disk copy is a cache of what the
            # tables say, and the next download draws it again.
            log.warning("M06: question bank of %s not kept on disk", candidate_id, exc_info=True)
        return Current(book, pdf, updated, fingerprint)


# ── filled in behind the interview ───────────────────────────────────────────


def _fresh(row: QBankLookup | None, ttl: timedelta | None = None) -> bool:
    if row is None:
        return False
    age = utcnow() - _aware(row.fetched_at)
    if ttl is not None and age > ttl:
        return False
    return row.found or age < RECHECK_MISSING


def _keep(db: Session, key: str, payload: dict[str, Any], *, found: bool = True) -> None:
    row = db.get(QBankLookup, key) or QBankLookup(key=key)
    row.payload, row.found, row.fetched_at = payload, found, utcnow()
    db.add(row)


def look_up(db: Session, asked: list[Asked], found: dict[str, QBankLookup], upstreams: Any) -> bool:
    """Ask M05 and M04 what the event log lacks, and keep the answers.
    True if anything new was kept."""
    from ..adapters import UpstreamUnavailable  # noqa: PLC0415

    kept = False
    if upstreams.available("M05"):
        kept_tracks = found.get("tracks")
        old_shape = kept_tracks is not None and any(
            "kind" not in t for t in (kept_tracks.payload or {}).get("tracks") or []
        )
        if old_shape or not _fresh(kept_tracks, TRACKS_TTL):
            try:
                body = upstreams.m05.tracks() or {}
                tracks = [
                    {k: t.get(k) for k in ("round_type", "title", "group", "blurb", "kind")}
                    for t in body.get("tracks") or []
                    if t.get("round_type")
                ]
                if tracks:
                    _keep(db, "tracks", {"tracks": tracks})
                    kept = True
            except UpstreamUnavailable as exc:
                log.info("M06: question bank: M05 tracks unavailable: %s", exc)
        for q in asked:
            if not q.question_id or q.source not in M05_SOURCES:
                continue
            if q.reference_answer and q.key_points and q.rubric_round_type:
                continue
            key = f"q:{q.question_id}"
            if _fresh(found.get(key)):
                continue
            try:
                item = upstreams.m05.question(uuid.UUID(q.question_id))
            except (UpstreamUnavailable, KeyError, ValueError) as exc:
                answered = isinstance(exc, KeyError) or getattr(exc, "status", None) in (404, 410)
                if answered:
                    _keep(db, key, {}, found=False)
                    kept = True
                continue
            _keep(
                db,
                key,
                {
                    "round_types": list(item.get("round_types") or []),
                    "reference_answer": str(item.get("reference_answer") or ""),
                    "key_points": [
                        str(kp.get("statement") if isinstance(kp, dict) else kp)
                        for kp in item.get("key_points") or []
                    ],
                    "label": str(item.get("label") or ""),
                },
            )
            kept = True
    if upstreams.available("M04"):
        for concept_id in sorted({q.concept_id for q in asked if q.concept_id and not q.resume}):
            key = f"c:{concept_id}"
            if _fresh(found.get(key)):
                continue
            try:
                concept = upstreams.m04.concept(concept_id)
            except (UpstreamUnavailable, AttributeError) as exc:
                log.info("M06: question bank: M04 concept %s unavailable: %s", concept_id, exc)
                continue
            if concept:
                _keep(db, key, {"name": concept.get("name"), "domain": concept.get("domain")})
            else:
                _keep(db, key, {}, found=False)
            kept = True
    if kept:
        db.commit()
    return kept


def _rate_limited(calls: list) -> bool:
    return bool(calls) and all(
        not c.ok and any(s in (c.reason or "").lower() for s in ("429", "rate limit", "rate_limit"))
        for c in calls
    )


def write_answers(
    db: Session,
    candidate_id: uuid.UUID,
    asked: list[Asked],
    llm: Any,
    *,
    budget: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    redraw_every: int = 5,
) -> int:
    """Write what is missing, one question at a time. How many were tried."""
    from ..llm import JOB_QBANK, JOB_QBANK_FALLBACK  # noqa: PLC0415

    jobs: tuple[str, ...] = (JOB_QBANK, JOB_QBANK_FALLBACK)
    tried = 0
    for q in asked:
        if budget is not None and tried >= budget:
            break
        if not answers_module.needs_writing(q):
            continue
        digest = answers_module.brief_hash(q)
        row = db.get(QBankAnswer, digest)
        if row is not None and (row.status == "ready" or row.attempts >= MAX_ATTEMPTS):
            continue
        if (
            row is not None
            and row.status == "writing"
            and utcnow() - _aware(row.updated_at) < CLAIM
        ):
            continue  # another worker is writing it
        # Claimed before the call: a refresh behind an answer and one behind a
        # download (or a second worker) must not write the same brief twice.
        before = (row.status, row.attempts) if row is not None else None
        try:
            row = row or QBankAnswer(brief_hash=digest, question_key=q.key)
            row.status, row.updated_at = "writing", utcnow()
            db.add(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        written, model, problems, calls = answers_module.write_one(llm, q, jobs)
        if calls and calls[0].job == JOB_QBANK and not calls[0].ok:
            # The writing tier did not answer at all (a 429, a hang): the
            # rest of this run goes straight to the fallback, as the notes do.
            jobs = (JOB_QBANK_FALLBACK,)
        for call in calls:
            db.add(
                LLMCall(
                    session_id=None,
                    job=call.job,
                    tier=call.tier,
                    model_id=call.model,
                    prompt_version=answers_module.PROMPT_VERSION,
                    ok=call.ok,
                    error=None if call.ok else (call.reason or "")[:500],
                    tokens_in=call.tokens_in,
                    tokens_out=call.tokens_out,
                    latency_ms=call.latency_ms,
                )
            )
        if written is None and _rate_limited(calls):
            # Out of quota is not this question's fault: no attempt is spent,
            # the claim is let go, and the next refresh carries on from here.
            if before is None:
                db.delete(row)
            else:
                row.status, row.attempts = before
                db.add(row)
            db.commit()
            log.info("M06: question bank answers paused: the model is rate-limited")
            break
        row.attempts += 1
        row.prompt_version = answers_module.PROMPT_VERSION
        row.problems = problems[:20]
        row.updated_at = utcnow()
        if written is not None:
            row.status, row.model, row.reason = "ready", model, None
            row.payload = written.payload()
        else:
            row.status, row.reason = "failed", ("; ".join(problems)[:500] or "no model answered")
        db.add(row)
        db.commit()
        tried += 1
        if redraw_every and tried % redraw_every == 0:
            current(db, candidate_id)
        used = sum(
            (c.tokens_in or 0) + (c.tokens_out or 0) for c in calls if c.tier == "generation"
        )
        if used:
            sleep(min(30.0, used / TOKENS_PER_MINUTE * 60))
    return tried


_running: set[str] = set()
_running_lock = threading.Lock()


def refresh(
    candidate_id: uuid.UUID,
    *,
    factory: Callable[[], Session],
    upstreams: Any,
    llm: Any = None,
    budget: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Bring one student's bank up to date: look up, redraw, write, redraw.
    A background task; never raises, and one run per student at a time."""
    key = str(candidate_id)
    with _running_lock:
        if key in _running:
            return
        _running.add(key)
    try:
        from ..llm import get_llm  # noqa: PLC0415

        with factory() as db:
            asked, found = prepare(db, candidate_id)
            if look_up(db, asked, found, upstreams):
                asked, found = prepare(db, candidate_id)
            current(db, candidate_id)
            model = llm or get_llm()
            if model.available:
                if write_answers(db, candidate_id, asked, model, budget=budget, sleep=sleep):
                    current(db, candidate_id)
    except Exception:  # noqa: BLE001 — a background task; the bank stands without it
        log.exception("M06: question bank refresh failed for %s", candidate_id)
    finally:
        with _running_lock:
            _running.discard(key)


__all__ = [
    "FILE_NAME",
    "Current",
    "current",
    "look_up",
    "refresh",
    "remember_name",
    "storage_dir",
    "write_answers",
]
