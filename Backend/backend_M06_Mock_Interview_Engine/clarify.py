"""Asking about a spoken answer before judging it — M11's FR-11.16 and EC-11.1.

Two cases where the honest thing is to ask, not to judge:

- **A word nobody is sure of, next to a word that decides the answer** (spec
  §6.8): "if the final transcript has a low-confidence span overlapping a
  decisive term, the interviewer asks a natural clarifier: 'Sorry — did you
  say quick sort or quick select?' (max once per turn, max 3 per session —
  beyond that it's annoying)". The decisive terms are the question's own — its
  key points, what a good answer at each rung contains, its label and its
  stem — so there is no list here to fall behind the bank. A heard span is
  close to a term when they share most of their letters (difflib), and not
  when one is the other with an ending added ("sort" and "sorted" are one
  word, said one way or another — asking would only annoy).
- **A question the student never heard** (EC-11.1): they started speaking
  before most of it was said — M11's FR-11.9 records where — so what they
  said answers something else. The question is put again, and what they said
  is not judged against it.

The reply to "did you say …?" is the answer, clarified: it is judged and
scored together with the answer it clarifies (`clarified`), the original
first so its unsure words keep their places and stay unquotable.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

#: How alike a heard span and a term must be to ask which was meant.
CLOSE = 0.72

#: Words that never decide an answer on their own.
_STOP = frozenset(
    "a an and are as at be by can could do does each for from has have how i if in into is "
    "it its may might more most of on or other over same should so some such than that the "
    "their them then there these they this through to under very was we were what when "
    "where which while who why will with would you your about after before between both".split()
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#'\-]*")


def _key(words: list[str]) -> str:
    return " ".join(word.lower().strip("'-") for word in words)


def decisive_terms(item: Any) -> dict[str, str]:
    """The question's own terms of one to three words: key → as written."""
    sources: list[str] = [kp.statement for kp in getattr(item, "key_points", ())]
    for points in (getattr(item, "expects", None) or {}).values():
        sources.extend(points)
    sources += [getattr(item, "label", "") or "", getattr(item, "stem", "") or ""]
    terms: dict[str, str] = {}
    for source in sources:
        tokens = _TOKEN.findall(source or "")
        for n in (1, 2, 3):
            for i in range(len(tokens) - n + 1):
                window = tokens[i : i + n]
                lowered = [w.lower() for w in window]
                if lowered[0] in _STOP or lowered[-1] in _STOP:
                    continue
                if max(len(w) for w in lowered) < 4:
                    continue
                terms.setdefault(_key(window), " ".join(window))
    return terms


def _same_stem(a: str, b: str) -> bool:
    """One word with an ending added or changed: "sort"/"sorted",
    "partitions"/"partitioning". A shared stem of four letters at least, so
    "sort" and "select" — the spec's own example — stay two words."""
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    shared = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        shared += 1
    return shared >= max(4, min(len(a), len(b)) - 3)


def _one_word(a: str, b: str) -> bool:
    """The same words, said one way or another: spacing, or endings."""
    if a.replace(" ", "").replace("-", "") == b.replace(" ", "").replace("-", ""):
        return True  # "hash map" and "hashmap"
    aw, bw = a.split(), b.split()
    return len(aw) == len(bw) and all(_same_stem(x, y) for x, y in zip(aw, bw, strict=True))


def unsure_term(
    answer: str, unsure: list[tuple[int, int]] | list[list[int]], item: Any
) -> tuple[str, str] | None:
    """(what was heard, the term it may have been), or None.

    Only a span the recogniser was unsure of, only near a term of this
    question, and never when what was heard IS one of its terms."""
    terms = decisive_terms(item)
    if not terms:
        return None
    keys = list(terms)
    best: tuple[float, str, str] | None = None
    for start, end in unsure:
        heard = _TOKEN.findall(answer[int(start) : int(end)])
        for key in keys:
            n = len(key.split())
            for i in range(len(heard) - n + 1):
                window = heard[i : i + n]
                wkey = _key(window)
                if max(len(w) for w in wkey.split()) < 4:
                    continue
                if any(_one_word(wkey, k) for k in keys if len(k.split()) == n):
                    continue  # heard as a term of the question: likely right
                ratio = difflib.SequenceMatcher(None, wkey, key).ratio()
                if ratio >= CLOSE and (best is None or ratio > best[0]):
                    best = (ratio, " ".join(window), terms[key])
    return (best[1], best[2]) if best else None


def question_unheard(line: Any) -> bool:
    """EC-11.1: the student came in before most of the question was said.

    `line` is the interviewer turn they answered; FR-11.9 records the part
    being heard when they came in and how far through it (0–1)."""
    if line is None or getattr(line, "heard", None) is None:
        return False
    text = line.text
    parts = [p.text for p in line.parts] if getattr(line, "parts", None) else [text]
    index = min(int(line.heard_part or 0), len(parts) - 1)
    heard_upto = sum(len(p) + 1 for p in parts[:index]) + round(len(parts[index]) * line.heard)
    question = getattr(line, "question_text", None) or text
    start = text.rfind(question)
    if start < 0:
        start = max(0, len(text) - len(question))
    return heard_upto < start + 0.4 * len(question)


def clarified(state: Any, turn: Any) -> Any | None:
    """The answer `turn` clarifies, when it replies to a "did you say …?"."""
    transcript = state.transcript
    at = next((i for i, t in enumerate(transcript) if t.turn_id == turn.turn_id), None)
    if at is None or at < 2:
        return None
    line = transcript[at - 1]
    if line.role != "interviewer" or line.probe_move != "clarify_term":
        return None
    return next((t for t in reversed(transcript[: at - 1]) if t.role == "candidate"), None)


def scored(state: Any, turn: Any) -> tuple[str, list[tuple[int, int]]]:
    """The text an answer is scored on, and the ranges in it nobody may quote.

    A reply to "did you say …?" is scored with the answer it clarifies, that
    answer first — so its unsure ranges keep their places — then the reply."""
    unsure = [(int(a), int(b)) for a, b in (getattr(turn, "unsure", None) or [])]
    original = clarified(state, turn)
    if original is None:
        return turn.text, unsure
    offset = len(original.text) + 1
    before = [(int(a), int(b)) for a, b in (original.unsure or [])]
    return f"{original.text}\n{turn.text}", [
        *before,
        *[(a + offset, b + offset) for a, b in unsure],
    ]


__all__ = [
    "CLOSE",
    "clarified",
    "decisive_terms",
    "question_unheard",
    "scored",
    "unsure_term",
]
