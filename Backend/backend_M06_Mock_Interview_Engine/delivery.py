"""How an answer was said — the user's spec §7 (2026-10-22). Pure.

Repeated "basically", "like", "you know" can bury a strong answer. This reads
the answer's own words for the habits that are measurable in text, and says
so once, briefly, when one crosses a line — without interrupting the answer,
and never more than one note per answer, with a cooldown between notes.

**What it can measure, and what it cannot.**

* Lexical fillers ("basically", "actually", "literally", "you know", "I mean",
  "kind of", "sort of", and "like" where it is a filler, not a verb): yes,
  from the transcript.
* Vocal fillers ("um", "uh", "er"): counted when they are in the text — but
  Whisper, which writes down spoken answers (M11), usually leaves them out,
  so they are UNDER-counted for speech and never claimed as measured.
* Repeated words ("the the") and restarts ("sorry", "let me rephrase", "no
  wait"): from the text, outside the stretches the recogniser was unsure of —
  a doubled word inside a garbled stretch is the recogniser's, not theirs.
* Pace: words per minute, only when the room says how long they spoke.
* Confidence, tone, emotion, pronunciation: NOT measured. Nothing here
  claims them.

A small number of fillers is how people talk: nothing is said below
`MIN_WORDS` words, or below both the count and the rate. The thresholds are
environment settings (`M06_FILLER_RATE`, `M06_FILLER_MIN`), tested against
realistic answers in `test_delivery.py`.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field

#: Below this many words an answer is too short for a habit to show.
MIN_WORDS = 25
#: Fillers per 100 words at which a note is worth giving…
FILLER_RATE = float(os.getenv("M06_FILLER_RATE", "6"))
#: …and the least number of them, whatever the rate.
FILLER_MIN = int(os.getenv("M06_FILLER_MIN", "4"))
#: One filler said this often is named.
NAME_AT = 3
#: Repeats and restarts together at which a note is worth giving.
RESTARTS_AT = 4
#: Words per minute above which "slow down a little" is said.
FAST_WPM = 190
#: Answers between two notes — a second note in a row is a distraction.
COOLDOWN = 2
#: Modes that give the note live; the others keep it for the report, as a
#: real panel would never say it mid-interview.
LIVE_MODES = frozenset({"practice", "mock"})

_WORD = re.compile(r"[a-z']+")
_VOCAL = frozenset({"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm"})
_LEXICAL = ("basically", "actually", "literally", "honestly")
_PHRASES = ("you know", "i mean", "kind of", "sort of")
#: "like" is a filler when commas fence it, when it opens a clause, or after
#: a vocal filler — and not after the verbs and nouns it belongs to.
_LIKE_FILLER = re.compile(
    r"(?:(?:^|[.!?]\s+|,\s*)like\s*,)|(?:,\s*like\s+(?!this|that|a|an|the)\b)"
    r"|(?:\b(?:um|uh|er)\s*,?\s*like\b)|(?:^\s*like\b)"
    # "and like, um" — a clause opened on it, or a vocal filler after it.
    r"|(?:\b(?:and|so|but)\s+like\s*,)|(?:(?<!,\s)(?<!,)\blike\s*,?\s*(?:um|uh|er)\b)",
    re.I,
)
_RESTART = re.compile(
    r"\b(sorry|let me rephrase|let me start again|what i (?:mean|meant|wanted to say) is"
    r"|no,? wait|wait,? no|scratch that|i'?ll rephrase)\b",
    re.I,
)


@dataclass(frozen=True)
class Delivery:
    words: int
    fillers: dict[str, int] = field(default_factory=dict)
    repeats: int = 0
    restarts: int = 0
    wpm: float | None = None
    spoken: bool = False

    @property
    def filler_count(self) -> int:
        return sum(self.fillers.values())

    @property
    def filler_rate(self) -> float:
        return 100.0 * self.filler_count / self.words if self.words else 0.0

    @property
    def top(self) -> tuple[str, int] | None:
        return Counter(self.fillers).most_common(1)[0] if self.fillers else None

    def as_payload(self) -> dict:
        return {
            "words": self.words,
            "fillers": dict(self.fillers),
            "repeats": self.repeats,
            "restarts": self.restarts,
            "wpm": self.wpm,
            "spoken": self.spoken,
        }


def _outside(text: str, unsure: list[tuple[int, int]]) -> str:
    """The text with the recogniser's unsure stretches blanked out."""
    if not unsure:
        return text
    chars = list(text)
    for a, b in unsure:
        for i in range(max(a, 0), min(b, len(chars))):
            chars[i] = " "
    return "".join(chars)


def analyse(
    text: str,
    *,
    spoken: bool = False,
    unsure: list[tuple[int, int]] | None = None,
    duration_s: float | None = None,
) -> Delivery:
    lowered = text.lower()
    words = _WORD.findall(lowered)
    fillers: Counter[str] = Counter()
    for word in words:
        if word in _VOCAL:
            fillers["um/uh"] += 1
        elif word in _LEXICAL:
            fillers[word] += 1
    for phrase in _PHRASES:
        fillers[phrase] += len(re.findall(rf"\b{phrase}\b", lowered))
    fillers["like"] += len(_LIKE_FILLER.findall(text))
    clean = _words_of(_outside(lowered, unsure or []))
    repeats = sum(
        1 for a, b in zip(clean, clean[1:], strict=False) if a == b and a not in ("that", "had")
    )
    wpm = round(len(words) / (duration_s / 60.0), 1) if duration_s and duration_s > 3 else None
    return Delivery(
        words=len(words),
        fillers={k: v for k, v in fillers.items() if v},
        repeats=repeats,
        restarts=len(_RESTART.findall(text)),
        wpm=wpm,
        spoken=spoken,
    )


def _words_of(text: str) -> list[str]:
    return _WORD.findall(text)


def note(delivery: Delivery) -> str | None:
    """The one line to say about this answer, or None. Never more than one."""
    if delivery.words < MIN_WORDS:
        return None
    if delivery.filler_count >= FILLER_MIN and delivery.filler_rate >= FILLER_RATE:
        top = delivery.top
        if top is not None and top[1] >= NAME_AT and top[0] != "um/uh":
            return (
                f"Quick note: you said “{top[0]}” {top[1]} times in that answer. "
                "Try a short pause instead."
            )
        return "Quick note: quite a few fillers in that one. Try leading with your main point."
    if delivery.repeats + delivery.restarts >= RESTARTS_AT:
        return "Quick note: a few restarts there. Take a breath and lead with your main point."
    if delivery.wpm is not None and delivery.wpm > FAST_WPM:
        return "Quick note: that was fast. Slowing down a little will make it easier to follow."
    return None


def live_note(delivery: Delivery, *, mode: str, answers_since_last: int | None) -> str | None:
    """The note, if it should be said NOW — the mode gives notes live, and
    the last one was long enough ago."""
    if mode not in LIVE_MODES:
        return None
    if answers_since_last is not None and answers_since_last < COOLDOWN:
        return None
    return note(delivery)


def summarise(deliveries: list[Delivery]) -> list[str]:
    """The report's lines about how the answers were said, across them all."""
    counted = [d for d in deliveries if d.words >= MIN_WORDS]
    if not counted:
        return []
    out: list[str] = []
    totals: Counter[str] = Counter()
    for d in counted:
        totals.update(d.fillers)
    words = sum(d.words for d in counted)
    rate = 100.0 * sum(totals.values()) / words if words else 0.0
    habitual = [(w, n) for w, n in totals.most_common(3) if n >= NAME_AT and w != "um/uh"]
    piled = [d for d in counted if note(d) and d.filler_count >= FILLER_MIN]
    if rate >= FILLER_RATE and habitual:
        named = ", ".join(f"“{w}” ×{n}" for w, n in habitual)
        out.append(f"Fillers came up often ({named}). A short pause does the same job.")
    elif rate >= FILLER_RATE:
        out.append("Fillers came up often across your answers.")
    elif piled:
        # Fine on average, but an answer where they piled up is still worth
        # knowing about — an average is how one bad answer disappears.
        named = ", ".join(f"“{w}” ×{n}" for w, n in habitual) or "fillers"
        count = len(piled)
        out.append(
            f"Fillers were fine overall, but in {count} answer{'s' if count != 1 else ''} they "
            f"piled up ({named})."
        )
    else:
        out.append("Fillers were not a problem: a few, as in any natural answer.")
    restarts = sum(d.repeats + d.restarts for d in counted)
    if restarts >= RESTARTS_AT:
        out.append(f"{restarts} restarts or repeated words — leading with the main point helps.")
    paces = [d.wpm for d in counted if d.wpm is not None]
    if paces and max(paces) > FAST_WPM:
        out.append("Some answers were fast; slowing a little makes them easier to follow.")
    if any(d.spoken for d in counted):
        out.append(
            "Measured from what the recogniser wrote down, which usually leaves out “um” and "
            "“uh” — so those are under-counted, and tone or confidence are not measured at all."
        )
    return out


__all__ = [
    "COOLDOWN",
    "FILLER_MIN",
    "FILLER_RATE",
    "MIN_WORDS",
    "Delivery",
    "analyse",
    "live_note",
    "note",
    "summarise",
]
