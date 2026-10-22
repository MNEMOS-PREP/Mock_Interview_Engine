"""One question at a time — the user's spec §5 (2026-10-22).

"Explain how your application uses Redis caching, how you handle cache
invalidation, and what happens when Redis becomes unavailable" is three
questions said as one. A human interviewer asks the first, listens, and only
then asks the next — and skips the next if the answer already covered it.
Bank stems are often written the first way (M05's `hashing_collision_
strategies`: "Walk me through how a hash map can handle that, and what it
costs"), and the student heard all of it at once.

So a stem that asks several independently answerable things is split into a
primary question and follow-up parts, once, and cached:

* **Whether** is decided by rules (`needs_split`): two or more question marks,
  or a clause joined by ", and how / what / why …". A comparison ("what is the
  difference between…", "compare…", "X vs Y") is one question and is never
  split, and neither is anything short.
* **How** is the extraction tier's (`split`), because "and what it costs"
  becomes "What does that cost?" only by reading it. The model also says
  which of the question's key points each part asks for — so a part whose
  points the answer already covered is skipped (`ladder._next_part`), and M13
  scores only what was actually asked (`outbox`).
* **Validated** before it is used (`valid`): every part a question of its own,
  short; nothing the stem asked lost (its content words, mostly kept); no key
  point claimed twice; at most three follow-ups. A split that fails is not
  used — and with no model, only the plain case is split by rule: a stem of
  several questions, each already ending in its own question mark.

Asking parts one at a time does not change the standard: the item, its key
points and its rubric are the same, and the thread of answers is scored
together (`outbox.thread_request`).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import replace
from typing import Any

from sqlmodel import Session

from .items import Item, Part
from .llm import JOB_DECOMPOSE, LLM, LLMResult
from .models import QuestionSplit

log = logging.getLogger("uvicorn.error")

PROMPT_VERSION = "split-1"

#: A stem shorter than this is one question, whatever its punctuation.
MIN_WORDS = 14
#: Follow-ups one question may be split into.
MAX_PARTS = 3
#: A part longer than this is not "one question".
MAX_PART_WORDS = 30
#: The share of the stem's content words the parts must keep between them.
KEEP_AT = 0.7

_COMPARISON = re.compile(
    r"\b(difference|differences|differ|compare|comparing|comparison|versus|vs\.?|contrast)\b",
    re.I,
)
_JOINED = re.compile(
    r"(,|;)\s*(and|also|then)\s+(how|what|why|when|which|where|whether|who|walk|explain|describe)\b"
    r"|\band\s+(what|how)\s+(it|they|this|that)\s+(costs?|means|implies|changes|happens|does)\b"
    r"|\b(also|additionally)\s*,?\s*(how|what|why)\b",
    re.I,
)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the of to in on at for with by is are was were be it its this that these those and or "
    "but if then so than you your how what why when which where whether do does did can could "
    "would should will me us we i".split()
)

SYSTEM = """You split interview questions that ask several independently answerable things into a primary question and follow-up parts, so an interviewer can ask one thing at a time.

Rules:
- Split ONLY if the question asks two or more things a candidate could answer separately. If it is one question — including a comparison of two related things ("difference between", "compare", "X vs Y") — return split false.
- The primary question is the first and most basic ask. Each part is one later ask, rewritten as a complete, natural question that makes sense on its own after the primary has been answered (e.g. "and what it costs" becomes "What does that cost?").
- Keep every technical ask of the original exactly; add nothing, drop nothing, never answer anything.
- At most 3 parts. Each at most 25 words, ending with a question mark.
- key point ids: for the primary and for each part, the ids of the listed key points that ask is about. Each id at most once. Ids not clearly about any ask go with the primary.
- If split is false, return the original as primary and no parts."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["split", "primary", "primary_key_point_ids", "parts"],
    "properties": {
        "split": {"type": "boolean"},
        "primary": {"type": "string"},
        "primary_key_point_ids": {"type": "array", "items": {"type": "string"}},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "key_point_ids"],
                "properties": {
                    "text": {"type": "string"},
                    "key_point_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def key_for(stem: str) -> str:
    return hashlib.sha1(" ".join(stem.split()).lower().encode()).hexdigest()


def _content(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _questions(stem: str) -> list[str]:
    """The stem's own question sentences, each ending in its mark."""
    pieces = [p.strip() for p in re.split(r"(?<=\?)\s+", stem.strip()) if p.strip()]
    return pieces if len(pieces) >= 2 and all(p.endswith("?") for p in pieces) else []


def needs_split(stem: str) -> bool:
    """Whether a stem asks several independently answerable things."""
    words = stem.split()
    if len(words) < MIN_WORDS or _COMPARISON.search(stem):
        return False
    return stem.count("?") >= 2 or bool(_JOINED.search(stem))


def valid(stem: str, primary: str, parts: list[dict], known: set[str]) -> str | None:
    """None if this split may be used; otherwise why not."""
    if not primary.strip():
        return "no primary question"
    if not parts:
        return "nothing to split off"
    if len(parts) > MAX_PARTS:
        return "too many parts"
    claimed: set[str] = set()
    for part in parts:
        text = str(part.get("text") or "").strip()
        if not text.endswith("?"):
            return "a part is not a question"
        if len(text.split()) > MAX_PART_WORDS:
            return "a part is too long"
        ids = {str(k) for k in part.get("key_point_ids") or []}
        if ids - known:
            return "a part names a key point the question does not have"
        if ids & claimed:
            return "a key point claimed twice"
        claimed |= ids
    asked = _content(stem)
    kept = _content(" ".join([primary, *(str(p.get("text") or "") for p in parts)]))
    if asked and len(asked & kept) / len(asked) < KEEP_AT:
        return "the parts lose what the question asked"
    return None


def split(item: Item, llm: LLM | None) -> QuestionSplit:
    """The split for this item's stem — worked out, not looked up."""
    stem = item.full_stem or item.stem
    row = QuestionSplit(
        key=key_for(stem), question_id=item.question_id, stem=stem, prompt_version=PROMPT_VERSION
    )
    if not needs_split(stem):
        return row
    known = {kp.id for kp in item.key_points}
    if llm is not None and getattr(llm, "available", False):
        points = "\n".join(f"- [{kp.id}] {kp.statement}" for kp in item.key_points) or "- (none)"
        call: LLMResult = llm.structured(
            job=JOB_DECOMPOSE,
            system=SYSTEM,
            user=f"QUESTION:\n{stem}\n\nKEY POINTS:\n{points}",
            schema=SCHEMA,
        )
        data = call.data if call.ok and isinstance(call.data, dict) else None
        if data and data.get("split"):
            primary = str(data.get("primary") or "").strip()
            parts = [p for p in data.get("parts") or [] if isinstance(p, dict)]
            reason = valid(stem, primary, parts, known)
            if reason is None:
                row.method = "model"
                row.primary = primary
                taken = {str(k) for p in parts for k in p.get("key_point_ids") or []}
                row.primary_key_point_ids = [
                    k
                    for k in data.get("primary_key_point_ids") or []
                    if k in known and k not in taken
                ]
                row.parts = [
                    {
                        "index": i + 1,
                        "text": str(p["text"]).strip(),
                        "key_point_ids": [str(k) for k in p.get("key_point_ids") or []],
                    }
                    for i, p in enumerate(parts)
                ]
                return row
            log.info("M06 split refused for %s: %s", item.question_id, reason)
        elif data is not None:
            return row
    pieces = _questions(stem)
    if len(pieces) >= 2 and len(pieces) - 1 <= MAX_PARTS:
        row.method = "rule"
        row.primary = pieces[0]
        row.parts = [
            {"index": i, "text": p, "key_point_ids": []} for i, p in enumerate(pieces[1:], 1)
        ]
    return row


def cached(db: Session, item: Item) -> QuestionSplit | None:
    return db.get(QuestionSplit, key_for(item.full_stem or item.stem))


def apply(item: Item, found: QuestionSplit | None) -> Item:
    """The item as it will be asked: its primary as the stem, the rest as
    parts. Unchanged when the question is asked whole."""
    if found is None or found.method == "whole" or not found.primary or not found.parts:
        return item
    if item.parts:
        return item
    return replace(
        item,
        stem=found.primary,
        full_stem=item.full_stem or item.stem,
        parts=tuple(
            Part(
                index=int(p["index"]),
                text=str(p["text"]),
                key_point_ids=tuple(str(k) for k in p.get("key_point_ids") or []),
            )
            for p in found.parts
        ),
    )


def for_item(db: Session, item: Item, llm: LLM | None) -> Item:
    """The item, split if it should be — from the cache, or worked out now
    and kept. Never raises: a failure asks the question whole."""
    if item.parts or item.source in ("m01_probe", "closing"):
        return item
    try:
        found = cached(db, item)
        if found is None:
            found = split(item, llm)
            db.merge(found)
            db.commit()
        return apply(item, found)
    except Exception:  # noqa: BLE001 — asked whole is always a safe answer
        log.warning("M06 split failed for %s; asked whole", item.question_id, exc_info=True)
        db.rollback()
        return item


__all__ = [
    "PROMPT_VERSION",
    "SCHEMA",
    "apply",
    "cached",
    "for_item",
    "key_for",
    "needs_split",
    "split",
    "valid",
]
