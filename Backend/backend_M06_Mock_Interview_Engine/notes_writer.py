"""The written explanation of each answer, after the session (2026-10-24).

The notes said WHAT happened — a status, the student's wrong sentence, the key
points — but not WHY in a way a student can learn from: why a correct answer
was strong, what a partial one should have added, what the right reasoning
is after a wrong one. That is writing, and a model does it here — inside the
same rule as the interview itself: **the verdict is decided by the code; the
model only explains it.** The status (`report._status`) is given to it as
fixed, and every write-up is checked before anyone sees it:

* every quote must be the student's own words, verbatim (an invented quote
  is evidence of something nobody said);
* nothing is praised in an answer judged wrong or missing, and an answer
  with no words has no "strengths";
* a wrong answer must come with the correct reasoning;
* lengths are capped, and generic advice ("practise more") is dropped.

A write-up that fails its checks is not shown — the notes fall back to what
the interview recorded, which is always there. Generation runs once per
session, after it ends, off any request path (`generate`), and the report
reads what is stored (`load`).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from .report import QuestionReport, Writeup, WriteupPoint

log = logging.getLogger("uvicorn.error")

#: Part of every stored write-up's key (`brief_hash`), so moving it rewrites
#: them all. It names the prompt AND the checks a write-up passed: a stored
#: one is only as good as the rules it was checked under. notes-2: a quote
#: is shown once, and never under the gaps of an answer not given.
PROMPT_VERSION = "notes-2"

SYSTEM = """You write the feedback a student reads after a mock technical interview, about ONE question.

The interviewer has already judged the answer. Its verdict is the STATUS, and you must not change, soften or contradict it. Your job is to explain that verdict specifically, from what the student actually said, so they can improve.

Rules:
1. Ground everything in the student's own words. Every "evidence" field is an exact quote — copied character for character, 3 to 25 words — from a STUDENT line. Never quote the interviewer, never invent or paraphrase a quote. Leave "evidence" empty when there is nothing to quote.
2. Write for the status:
   - correct: what made it strong, specifically ("strengths"). "gaps" only for a key point the list marks as not reached — never an invented weakness. "misconception" and "correction" empty.
   - partial: what was right ("strengths"), what was missing and what to add ("gaps", each with a "fix").
   - vague: the terms they used without explaining them ("gaps" quoting those words), and the mechanism they should have explained ("fix").
   - incorrect: the wrong idea in their own words ("misconception", and a "gap" quoting it), why it is wrong, and the correct reasoning ("correction"). Anything they did get right goes in "strengths".
   - unanswered: there is no answer to praise or criticise. "strengths" empty. Say what the question needed ("gaps" with "fix") and how to approach it.
   - unsupported (a line from their resume): what they claimed and what evidence a strong answer gives — the number, the baseline, how it was measured. Never invent facts about their project.
3. Never praise a wrong or missing answer. Never criticise a point the list marks as reached. No generic advice ("practise more", "be confident", "revise the basics"): every next step names the concept or the exact thing to do.
4. "model_answer": a correct answer to the question as asked, in 2 to 5 sentences, consistent with the key points (a different correct approach is fine). For a resume line you do not know their project: say what a strong answer would contain instead.
5. "headline": one sentence, specific to this answer, that matches the status.
6. Plain, direct English, second person ("you"). No markdown."""

_POINT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["point", "evidence", "fix"],
    "properties": {
        "point": {"type": "string"},
        "evidence": {"type": "string"},
        "fix": {"type": "string"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "headline",
        "strengths",
        "gaps",
        "misconception",
        "correction",
        "model_answer",
        "next_steps",
    ],
    "properties": {
        "headline": {"type": "string"},
        "strengths": {"type": "array", "items": _POINT},
        "gaps": {"type": "array", "items": _POINT},
        "misconception": {"type": "string"},
        "correction": {"type": "string"},
        "model_answer": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
}

#: What a write-up may hold — enough to explain, never a wall of text.
MAX_STRENGTHS, MAX_GAPS, MAX_STEPS = 4, 5, 3
MAX_TEXT, MAX_ANSWER = 400, 1500
#: Statuses whose answers have nothing to praise.
_NO_PRAISE = frozenset({"incorrect", "unanswered", "vague", "unsupported", "not_reached"})
_PRAISE = re.compile(
    r"\b(great|excellent|well done|good job|nice work|impressive|strong answer|perfect|"
    r"spot on|nailed)\b",
    re.I,
)
_GENERIC = re.compile(
    r"^\W*(practi[cs]e (more|regularly|this topic)|keep practi[cs]ing|be (more )?confident|"
    r"revise the basics|review the basics|study (more|harder)|read more)\W*$",
    re.I,
)
_KIND = {
    "m05_bank": "a question from the reviewed question bank",
    "m05_draft": "a practice question (its reference answer is not yet reviewed)",
    "m05_fallback": "a question from the bank",
    "local_fallback": "a question from the backup set",
    "m01_probe": "a question about a line on the student's own resume",
    "revisit": "a question the student chose to practise again",
    "template": "an opening question",
}


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(re.sub(r"[^\w'\s]", " ", text).split())


def said(question: QuestionReport) -> str:
    """Everything the student said on this question, in order."""
    return "\n".join(e.text for e in question.exchanges if e.role == "candidate")


def quoted(evidence: str, spoken: str) -> bool:
    """Whether `evidence` is the student's own words (punctuation and case
    aside) — the test an invented quote fails."""
    needle = _norm(evidence)
    return bool(needle) and needle in _norm(spoken)


def brief(question: QuestionReport) -> str:
    """What the writer is told about one question — all of it the interview's
    own record, the status first and fixed."""
    lines = [f"QUESTION: {question.question}"]
    kind = _KIND.get(question.source, "an interview question")
    if question.source == "m01_probe" and question.topic:
        kind += f' — the line: "{question.topic}"'
    lines.append(f"KIND: {kind}")
    status = f"{question.status} — {question.status_label}: {question.status_detail}"
    if question.status_qualifier:
        status += f" ({question.status_qualifier})"
    lines.append(f"STATUS (fixed, do not change it): {status}")
    if question.key_points:
        lines.append("KEY POINTS a strong answer covers (reached / NOT reached / unknown):")
        for point in question.key_points:
            mark = {True: "reached", False: "NOT reached", None: "unknown"}[point.covered]
            lines.append(f"  - [{mark}] {point.statement}")
    lines.append("THE CONVERSATION (only STUDENT lines may be quoted):")
    for exchange in question.exchanges:
        who = "STUDENT" if exchange.role == "candidate" else "INTERVIEWER"
        lines.append(f"  {who}: {exchange.text}")
    noted = [f'  - wrong: "{f.said}" — {f.why}' for f in question.went_wrong]
    noted += [f"  - right: {point}" for point in question.went_well]
    noted += [f'  - claimed without support: "{claim}"' for claim in question.unsupported]
    noted += [
        f'  - did not fit together: "{f.why}" then "{f.said}"' for f in question.contradictions
    ]
    if question.misconception:
        noted.append(f"  - the misconception: {question.misconception}")
    if noted:
        lines.append("WHAT THE INTERVIEWER NOTED:")
        lines.extend(noted)
    if question.one_strong_answer:
        reviewed = "reviewed by a person" if question.strong_answer_reviewed else "not yet reviewed"
        lines.append(f"REFERENCE ANSWER ({reviewed}): {question.one_strong_answer}")
    return "\n".join(lines)


class _RawPoint(BaseModel):
    point: str = ""
    evidence: str = ""
    fix: str = ""


class _Raw(BaseModel):
    headline: str = ""
    strengths: list[_RawPoint] = Field(default_factory=list)
    gaps: list[_RawPoint] = Field(default_factory=list)
    misconception: str = ""
    correction: str = ""
    model_answer: str = ""
    next_steps: list[str] = Field(default_factory=list)


def _cap(text: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def check(raw: Any, question: QuestionReport) -> tuple[Writeup | None, list[str]]:
    """The write-up, if it can be shown, and what was wrong with it. Fixable
    problems are fixed (an unquotable quote is dropped); a write-up that
    contradicts the status is refused."""
    problems: list[str] = []
    try:
        parsed = _Raw.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema: {exc.errors()[0]['msg']}"]
    status = question.status or ""
    spoken = said(question)
    headline = _cap(parsed.headline, 240)
    if not headline:
        return None, ["no headline"]
    if status in _NO_PRAISE and _PRAISE.search(headline):
        return None, [f"praise in the headline of a {status} answer"]

    strengths: list[WriteupPoint] = []
    for item in parsed.strengths[:MAX_STRENGTHS]:
        if not item.point.strip():
            continue
        if item.evidence and not quoted(item.evidence, spoken):
            problems.append(f"strength quote not in the answer: {item.evidence[:60]!r}")
            continue
        strengths.append(WriteupPoint(point=_cap(item.point), evidence=_cap(item.evidence)))
    if not spoken.strip() or status in ("unanswered", "not_reached"):
        if strengths:
            problems.append("strengths for an answer that was not given")
        strengths = []

    gaps: list[WriteupPoint] = []
    quoted_already: set[str] = set()
    for item in parsed.gaps[:MAX_GAPS]:
        if not item.point.strip():
            continue
        evidence = item.evidence
        if evidence and not quoted(evidence, spoken):
            problems.append(f"gap quote not in the answer: {evidence[:60]!r}")
            evidence = ""
        if status in ("unanswered", "not_reached"):
            # Measured: minimax quoted "I don't know this one" under every
            # gap of a blank answer — true, and noise three times over.
            evidence = ""
        if evidence and _norm(evidence) in quoted_already:
            # And a one-sentence vague answer quoted whole under all three of
            # its gaps (live, session C): the student reads it once.
            evidence = ""
        if evidence:
            quoted_already.add(_norm(evidence))
        gaps.append(
            WriteupPoint(point=_cap(item.point), evidence=_cap(evidence), fix=_cap(item.fix))
        )

    misconception, correction = _cap(parsed.misconception), _cap(parsed.correction, 700)
    if status == "correct" and not question.went_wrong:
        misconception = correction = ""
    if status == "incorrect" and not correction:
        return None, ["a wrong answer without the correct reasoning"]

    steps = [
        _cap(step, 240)
        for step in parsed.next_steps
        if step.strip() and len(step.strip()) >= 25 and not _GENERIC.match(step.strip())
    ][:MAX_STEPS]
    return (
        Writeup(
            headline=headline,
            strengths=strengths,
            gaps=gaps,
            misconception=misconception,
            correction=correction,
            model_answer=_cap(parsed.model_answer, MAX_ANSWER),
            next_steps=steps,
        ),
        problems,
    )


# ── written once, after the session, off every request path ───────────────

#: A write-up claimed this long ago and still pending was lost (a restart).
STALE = timedelta(minutes=5)
#: Tries per question before the notes stay as the interview recorded them.
MAX_ATTEMPTS = 2

_running: set[uuid.UUID] = set()
_running_lock = threading.Lock()


def wanted(question: QuestionReport) -> bool:
    """A question there is something to explain about: it was judged. Not a
    `not_judged` one — the writer explains a verdict and never makes one, and
    there the interview made none for it to explain."""
    return bool(question.question_key) and question.status not in (
        None,
        "not_reached",
        "not_judged",
    )


def brief_hash(question: QuestionReport) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(f"{PROMPT_VERSION}\n{brief(question)}".encode()).hexdigest()[:32]


def load(db: Session, session_id: uuid.UUID) -> dict[str, Any]:
    from .models import QuestionWriteup  # noqa: PLC0415

    rows = db.exec(select(QuestionWriteup).where(QuestionWriteup.session_id == session_id)).all()
    return {row.question_key: row for row in rows}


def _fresh(row: Any, now: datetime) -> bool:
    at = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=UTC)
    return now - at < STALE


def attach(questions: list[QuestionReport], rows: dict[str, Any], now: datetime) -> str:
    """Put each ready write-up on its question — only one written from the
    question as it stands — and say where the writing is: `none` (nothing to
    explain), `pending`, `ready`, or `partial` (some could not be written)."""
    states = []
    for question in questions:
        if not wanted(question):
            continue
        row = rows.get(question.question_key or "")
        current = row is not None and row.brief_hash == brief_hash(question)
        if current and row.status == "ready":
            question.writeup = Writeup.model_validate({**row.payload, "model": row.model})
            states.append("ready")
        elif current and row.status == "failed" and row.attempts >= MAX_ATTEMPTS:
            states.append("failed")
        elif current and row.status == "pending" and not _fresh(row, now):
            states.append("failed" if row.attempts >= MAX_ATTEMPTS else "missing")
        else:
            states.append("pending" if current and row.status == "pending" else "missing")
    if not states:
        return "none"
    if any(s in ("pending", "missing") for s in states):
        return "pending"
    return "ready" if all(s == "ready" for s in states) else "partial"


def write_one(
    llm: Any, question: QuestionReport, jobs: tuple[str, ...] | None = None
) -> tuple[Writeup | None, str, list[str], list]:
    """The write-up from the writing tier, else the generation tier, else
    none. (write-up, model, problems, calls)."""
    from .llm import JOB_NOTES, JOB_NOTES_FALLBACK  # noqa: PLC0415

    calls, problems = [], []
    for job in jobs or (JOB_NOTES, JOB_NOTES_FALLBACK):
        result = llm.structured(job=job, system=SYSTEM, user=brief(question), schema=SCHEMA)
        result.prompt_version = PROMPT_VERSION
        calls.append(result)
        if not result.ok:
            problems.append(f"{result.model}: {result.reason}")
            continue
        writeup, found = check(result.data, question)
        problems.extend(f"{result.model}: {p}" for p in found)
        if writeup is not None:
            writeup.model = result.model
            return writeup, result.model, problems, calls
    return None, "", problems, calls


def generate(session_id: uuid.UUID, *, llm: Any = None, factory: Any = None) -> None:
    """Write what is missing for one ended session. Safe to call twice: a
    session already being written is left to the call writing it, and a
    question already written is not written again."""
    with _running_lock:
        if session_id in _running:
            return
        _running.add(session_id)
    try:
        _generate(session_id, llm=llm, factory=factory)
    except Exception:  # noqa: BLE001 — a background task; the notes stand without it
        log.exception("M06: notes write-up failed for %s", session_id)
    finally:
        with _running_lock:
            _running.discard(session_id)


def _generate(session_id: uuid.UUID, *, llm: Any, factory: Any) -> None:
    from ai_core.db import engine  # noqa: PLC0415

    from . import report as report_module  # noqa: PLC0415
    from . import store  # noqa: PLC0415
    from .llm import JOB_NOTES, JOB_NOTES_FALLBACK, get_llm  # noqa: PLC0415
    from .models import LLMCall, QuestionWriteup  # noqa: PLC0415

    llm = llm or get_llm()
    if not llm.available:
        return
    # Once the writing tier fails to answer at all (a timeout, a 429, a key it
    # refuses), the rest of this run goes straight to the fallback. NIM can
    # hang until the 90 s timeout on some networks: eight questions would be
    # twelve minutes of "Writing…" before a fallback that takes two seconds.
    # A write-up that came back and failed its checks does not count.
    jobs: tuple[str, ...] = (JOB_NOTES, JOB_NOTES_FALLBACK)
    open_session = factory or (lambda: Session(engine))
    with open_session() as db:
        state = store.load_state(db, session_id)
        if not state.is_final:
            return
        now = datetime.now(UTC)
        built = report_module.build(state, store.events_for(db, session_id), now)
        rows = load(db, session_id)
        for question in built.questions:
            if not wanted(question):
                continue
            digest = brief_hash(question)
            row = rows.get(question.question_key or "")
            if row is not None and row.brief_hash == digest:
                if row.status == "ready" or row.attempts >= MAX_ATTEMPTS:
                    continue
                if row.status == "pending" and _fresh(row, now):
                    continue
            if row is None:
                row = QuestionWriteup(session_id=session_id, question_key=question.question_key)
            if row.brief_hash != digest:
                row.attempts = 0
            row.status, row.brief_hash, row.prompt_version = "pending", digest, PROMPT_VERSION
            row.attempts += 1
            row.updated_at = now
            db.add(row)
            db.commit()
            started = time.perf_counter()
            writeup, model, problems, calls = write_one(llm, question, jobs)
            if calls and calls[0].job == JOB_NOTES and not calls[0].ok:
                jobs = (JOB_NOTES_FALLBACK,)
            for call in calls:
                db.add(
                    LLMCall(
                        session_id=session_id,
                        job=call.job,
                        tier=call.tier,
                        model_id=call.model,
                        prompt_version=PROMPT_VERSION,
                        ok=call.ok,
                        error=None if call.ok else (call.reason or "")[:500],
                        tokens_in=call.tokens_in,
                        tokens_out=call.tokens_out,
                        latency_ms=call.latency_ms,
                    )
                )
            row.latency_ms = int((time.perf_counter() - started) * 1000)
            row.problems = problems[:20]
            row.updated_at = datetime.now(UTC)
            if writeup is not None:
                row.status, row.model, row.reason = "ready", model, None
                row.payload = json.loads(writeup.model_dump_json(exclude={"model"}))
            else:
                row.status, row.reason = "failed", "; ".join(problems)[:500] or "no model answered"
            db.add(row)
            db.commit()
