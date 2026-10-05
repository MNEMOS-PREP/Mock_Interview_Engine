"""The panel — who interviews, for which part, chosen from the personas' own data.

The project's claim (master plan §26, §32): the orchestrator does what a panel
lead and a few interviewers would — and a student should come out of a mock
feeling they met a PANEL, not one bot wearing hats. Until 2026-10-06 the panel
was a table per mode ("Mock: engineer, professor for projects, HR for people
questions"). A table is one posting behind the day it is written, and it could
not bring in an expert the plan needed but the table had not foreseen.

So the panel is now assembled from data, the same way every time:

* **Temperament** — each mode says what kind of panel it is as numbers: a
  target `warmth` / `patience` / `follow_up_aggression`, with hard bounds
  (Practice: warm and patient, never pushy; Final Boss: never warm). A persona
  outside the bounds never sits on that panel.
* **Expertise** — each persona says what it is good at (`domain_bias`, its
  `title` and `style`); each part of the interview says what it is about (its
  kind, its title in the posting's words, its rubric, its concepts). Overlap
  is expertise. Authoring a persona changes the panel; no code does.
* **Shape** — the lead (best for the warm-up) opens AND closes: the person who
  welcomed the student is the one who says goodbye. The panel grows with the
  interview (two people for 15 minutes, up to four for an hour) and a person
  who already runs a part is preferred for the next part of the same kind.

Deterministic: the same plan and mode always seat the same panel, so a re-plan
does not reshuffle who the student has met, and a test can hold it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .personas import Persona, personas

TRAITS = ("warmth", "patience", "follow_up_aggression")
_WORD = re.compile(r"[a-z0-9]+")
#: Words that say nothing about a domain.
_STOP = frozenset(
    "a an and or the of to for in on at with by is are be your you who what how why "
    "it its this that as from up out into about part round".split()
)


@dataclass(frozen=True)
class Temperament:
    """What kind of panel a mode is, as numbers — never as names."""

    target: dict[str, float]
    #: trait -> (lowest, highest) a panelist may have. Outside is never seated.
    bounds: dict[str, tuple[float, float]]
    #: How much temperament counts against expertise when choosing (0–1).
    weight: float = 0.5


def stem(word: str) -> str:
    """Crude, on purpose: 'algorithms' and 'algorithm', 'projects' and 'project'."""
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def words(*texts: str | Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for text in texts:
        items = [text] if isinstance(text, str) else list(text)
        for item in items:
            for word in _WORD.findall(item.lower().replace("_", " ").replace(".", " ")):
                if word not in _STOP and len(word) > 1:
                    out.add(stem(word))
    return frozenset(out)


def persona_words(p: Persona) -> frozenset[str]:
    """What a persona is good at: its domains count most, its title and style too."""
    return words(p.domain_bias, p.title, p.style)


def segment_words(segment) -> frozenset[str]:
    return words(
        segment.kind,
        segment.title or "",
        segment.rubric_round_types,
        segment.concept_ids,
    )


def expertise(p: Persona, topic: frozenset[str]) -> float:
    """Share of the topic's words this persona claims, its declared domains
    counting double. 0 when nothing overlaps."""
    if not topic:
        return 0.0
    declared = words(p.domain_bias)
    described = persona_words(p)
    hits = sum(2.0 if w in declared else 1.0 for w in topic if w in described)
    return min(1.0, hits / (2.0 * len(topic)) * 2.0)


def fits(p: Persona, temperament: Temperament) -> bool:
    return all(lo <= getattr(p, t) <= hi for t, (lo, hi) in temperament.bounds.items())


def closeness(p: Persona, temperament: Temperament) -> float:
    """1 for a persona exactly on the mode's target, falling with distance."""
    gaps = [abs(getattr(p, t) - v) for t, v in temperament.target.items()]
    return 1.0 - sum(gaps) / max(1, len(gaps))


def lead_for(temperament: Temperament, people: dict[str, Persona] | None = None) -> str:
    """The panel's lead: the eligible persona closest to the mode's own
    temperament. Opens, closes, and speaks when nobody else is named."""
    people = people or personas()
    eligible = [p for p in people.values() if fits(p, temperament)] or list(people.values())
    return max(eligible, key=lambda p: (closeness(p, temperament), p.id)).id


def panel_size(minutes: int) -> int:
    if minutes <= 15:
        return 2
    if minutes <= 30:
        return 3
    return 4


def assign(
    segments: Sequence,
    temperament: Temperament,
    minutes: int,
    people: dict[str, Persona] | None = None,
) -> list[str]:
    """A persona id for each segment, in order. Every segment gets one."""
    people = people or personas()
    eligible = sorted((p for p in people.values() if fits(p, temperament)), key=lambda p: p.id)
    if not eligible:
        # Bounds that exclude everyone are an authoring mistake; never an
        # interview without an interviewer.
        eligible = sorted(people.values(), key=lambda p: p.id)
    w = temperament.weight

    def score(p: Persona, topic: frozenset[str]) -> float:
        return (1 - w) * expertise(p, topic) + w * closeness(p, temperament)

    if not segments:
        return []
    # The lead is chosen for temperament first: the panel's manner is the
    # mode's, and the lead is who the student meets first and last.
    lead = people[lead_for(temperament, people)]
    size = panel_size(minutes)
    seated: list[str] = [lead.id]
    runs_kind: dict[str, set[str]] = {}

    def bid(p: Persona, kind: str, topic: frozenset[str], known: float) -> float:
        value = score(p, topic)
        if p.id in runs_kind.get(kind, set()):
            value += 0.15  # the person already running this kind continues it
        if p.id not in seated:
            if len(seated) >= size:
                return float("-inf")  # the panel is full
            if expertise(p, topic) > known:
                value += 0.12  # an expert the panel lacks joins it
        return value

    out: list[str] = []
    for segment in segments:
        if segment.kind in ("warmup", "closing"):
            out.append(lead.id)
            continue
        topic = segment_words(segment)
        # What the panel already knows about this part: a newcomer is brought
        # in for knowing it better, never just for being new.
        known = max(expertise(people[s], topic) for s in seated)
        _, chosen = max((bid(p, segment.kind, topic, known), p.id) for p in eligible)
        if chosen not in seated:
            seated.append(chosen)
        runs_kind.setdefault(segment.kind, set()).add(chosen)
        out.append(chosen)

    # A panel, not one person in several hats: an interview with two or more
    # parts of its own seats at least two people. The second takes the part
    # where swapping costs the least fit — so the choice is still the data's.
    middle = [i for i, s in enumerate(segments) if s.kind not in ("warmup", "closing")]
    if len(set(out)) < 2 and len(middle) >= 2:
        swaps = [
            (
                score(people[out[i]], segment_words(segments[i]))
                - score(p, segment_words(segments[i])),
                i,
                p.id,
            )
            for i in middle
            for p in eligible
            if p.id != lead.id
        ]
        if swaps:
            _, i, pid = min(swaps)
            out[i] = pid
    return out


def interjector(
    panel: Sequence[str],
    owner: str,
    topic: frozenset[str],
    people: dict[str, Persona] | None = None,
    *,
    margin: float = 0.2,
) -> str | None:
    """A panelist who knows this topic clearly better than the one asking, or
    None. Used for one follow-up — then the owner takes the question back."""
    people = people or personas()
    if owner not in people or not topic:
        return None
    own = expertise(people[owner], topic)
    best = max(
        (people[p] for p in dict.fromkeys(panel) if p in people and p != owner),
        key=lambda p: (expertise(p, topic), p.id),
        default=None,
    )
    if best is None:
        return None
    theirs = expertise(best, topic)
    return best.id if theirs >= 0.25 and theirs >= own + margin else None


__all__ = [
    "TRAITS",
    "Temperament",
    "assign",
    "closeness",
    "expertise",
    "fits",
    "interjector",
    "lead_for",
    "panel_size",
    "persona_words",
    "segment_words",
    "words",
]
