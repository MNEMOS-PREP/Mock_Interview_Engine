"""`SafetyGuard` — the rule half (master plan §26.6).

Every line the interviewer says passes through `screen`. This is the rule
filter that §10 falls back to when the guard model is slow or down — which is
why it is written first and why it is enough on its own for templated copy.

Two things it refuses:

* **A telegraphed verdict** (Trap 6). "Exactly", "that's wrong", "good job" —
  any of them tells the student how they are doing, and the measurement dies
  the moment students optimise for the tell.
* **A question a real interviewer must not ask** (§26.6): religion, caste,
  marital status, pregnancy, and the rest of the list below. Real interviews
  in India do ask these. This one never will.

A refused MODEL line is replaced by its template; the template itself is
screened in the test suite, so the fallback cannot fail the same check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..phrasebook import TELEGRAPHS

#: §26.6's list. Phrases rather than bare words where a bare word is also
#: ordinary technical vocabulary — a tree node has "children".
PERSONAL = (
    "religion",
    "religious",
    "caste",
    "married",
    "marital",
    "husband",
    "wife",
    "boyfriend",
    "girlfriend",
    "pregnan",
    "have children",
    "have kids",
    "family plan",
    "your age",
    "how old are you",
    "native place",
    "which community",
)

_TELEGRAPH_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in TELEGRAPHS) + r")\b", re.I)
_PERSONAL_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in PERSONAL) + r")", re.I)


@dataclass(frozen=True)
class Screened:
    ok: bool
    reason: str = ""


def screen(text: str) -> Screened:
    if not text or not text.strip():
        return Screened(False, "empty")
    if match := _TELEGRAPH_RE.search(text):
        return Screened(False, f"telegraphs a verdict: {match.group(0)!r}")
    if match := _PERSONAL_RE.search(text):
        return Screened(False, f"personal question: {match.group(0)!r}")
    return Screened(True)


__all__ = ["PERSONAL", "Screened", "screen"]
