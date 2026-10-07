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
* **Sitting in** — a plan with one part of its own (no job description, a
  focus session on one topic) would seat one person, and thirty minutes with
  one interviewer reads as one bot. A real technical round is often two at
  the table: one asks, the other sits in and comes in with follow-ups. So a
  panel of one, long enough for a few questions, gets a second person who
  sits in (`sit_in`).

Deterministic: the same plan and mode always seat the same panel, so a re-plan
does not reshuffle who the student has met, and a test can hold it.

**Rotation (2026-10-07).** "Only Priya and Raghavan, every time" — with seven
personas and the lead chosen as whoever sits closest to the mode, every Mock
opened with the same person. There are now three or four interviewers per
track, and among people who fit about equally well the SESSION decides: a
stable number per (session, persona) breaks near-ties (`ROTATION`), and
whoever the student met in their last few interviews stands back
(`MET_RECENTLY`). Still deterministic per session — a re-plan reseats the
same people — but no longer the same panel for every session. Expertise
still wins: rotation only chooses among people who fit.

**Never two alike.** M11 has seven voices for a cast five times that size, so
voices are shared across the cast; one panel never seats two people who sound
the same (`Persona.sound`).
"""

from __future__ import annotations

import hashlib
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


#: How much a session's own draw can move a persona's standing — enough to
#: choose among people who fit about equally well, never enough to seat a
#: stranger to the topic over its expert.
ROTATION = 0.15
#: What having met someone in the last few interviews costs them.
MET_RECENTLY = 0.25


def draw(seed: str | None, persona_id: str) -> float:
    """A number in [0, 1) for this session and persona: the same every time
    this session is planned, different from one session to the next. 0
    without a seed, which is the old, fixed seating."""
    if not seed:
        return 0.0
    digest = hashlib.sha1(f"{seed}:{persona_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def freshness(p: Persona, seed: str | None, recent: frozenset[str]) -> float:
    """What rotation adds to a persona's standing for one session."""
    return ROTATION * draw(seed, p.id) - (MET_RECENTLY if p.id in recent else 0.0)


def lead_for(
    temperament: Temperament,
    people: dict[str, Persona] | None = None,
    *,
    seed: str | None = None,
    recent: frozenset[str] = frozenset(),
    topic: frozenset[str] = frozenset(),
) -> str:
    """The panel's lead: the eligible persona closest to the mode's own
    temperament — and, given the interview's `topic`, one who knows it, so
    an ML interview is led by someone from ML. Opens, closes, and speaks
    when nobody else is named. Rotated by `seed` and `recent`."""
    people = people or personas()
    eligible = [p for p in people.values() if fits(p, temperament)] or list(people.values())
    w = temperament.weight

    def standing(p: Persona) -> float:
        fit = closeness(p, temperament)
        if topic:
            fit = w * fit + (1 - w) * expertise(p, topic)
        return fit + freshness(p, seed, recent)

    return max(eligible, key=lambda p: (standing(p), p.id)).id


def panel_size(minutes: int) -> int:
    if minutes <= 15:
        return 2
    if minutes <= 30:
        return 3
    return 4


def interview_topic(segments: Sequence) -> frozenset[str]:
    """What the interview's own parts are about, together."""
    out: set[str] = set()
    for segment in segments:
        if segment.kind not in ("warmup", "closing"):
            out |= segment_words(segment)
    return frozenset(out)


def assign(
    segments: Sequence,
    temperament: Temperament,
    minutes: int,
    people: dict[str, Persona] | None = None,
    *,
    seed: str | None = None,
    recent: frozenset[str] = frozenset(),
) -> list[str]:
    """A persona id for each segment, in order. Every segment gets one.

    `seed` (the session) and `recent` (who the student met lately) rotate
    the panel among people who fit equally well; without them the seating
    is the fixed one."""
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
    lead = people[
        lead_for(temperament, people, seed=seed, recent=recent, topic=interview_topic(segments))
    ]
    size = panel_size(minutes)
    seated: list[str] = [lead.id]
    runs_kind: dict[str, set[str]] = {}

    def bid(p: Persona, kind: str, topic: frozenset[str], known: float) -> float:
        value = score(p, topic) + freshness(p, seed, recent)
        if p.id in runs_kind.get(kind, set()):
            value += 0.15  # the person already running this kind continues it
        if p.id not in seated:
            if len(seated) >= size:
                return float("-inf")  # the panel is full
            if p.sound in {people[s].sound for s in seated}:
                return float("-inf")  # someone on the panel already sounds like this
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
                - score(p, segment_words(segments[i]))
                - freshness(p, seed, recent),
                i,
                p.id,
            )
            for i in middle
            for p in eligible
            if p.id != lead.id and p.sound != lead.sound
        ]
        if swaps:
            _, i, pid = min(swaps)
            out[i] = pid
    return out


#: A panel of one gets someone sitting in from this long...
SIT_IN_FROM_MINUTES = 15
#: ...when its own parts hold at least this many questions.
SIT_IN_FROM_QUESTIONS = 3


def sit_in(
    segments: Sequence,
    assignment: Sequence[str],
    temperament: Temperament,
    minutes: int,
    people: dict[str, Persona] | None = None,
    *,
    seed: str | None = None,
    recent: frozenset[str] = frozenset(),
) -> str | None:
    """Who sits in on a panel of one — the persona the mode admits that best
    fits this interview's own parts — or None when the panel has two people
    already, or the interview is too short to need a second."""
    people = people or personas()
    if len(set(assignment)) >= 2 or minutes < SIT_IN_FROM_MINUTES:
        return None
    middle = [s for s in segments if s.kind not in ("warmup", "closing")]
    if sum(int(getattr(s, "question_budget", 0) or 0) for s in middle) < SIT_IN_FROM_QUESTIONS:
        return None
    seated = set(assignment)
    sounds = {people[s].sound for s in seated if s in people}
    eligible = [
        p
        for p in people.values()
        if fits(p, temperament) and p.id not in seated and p.sound not in sounds
    ]
    if not eligible:
        return None
    w = temperament.weight
    topics = [segment_words(s) for s in middle]

    def fit(p: Persona) -> float:
        known = sum(expertise(p, topic) for topic in topics) / len(topics)
        return (1 - w) * known + w * closeness(p, temperament) + freshness(p, seed, recent)

    return max(eligible, key=lambda p: (fit(p), p.id)).id


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
    "MET_RECENTLY",
    "ROTATION",
    "TRAITS",
    "Temperament",
    "assign",
    "closeness",
    "draw",
    "expertise",
    "fits",
    "interjector",
    "interview_topic",
    "lead_for",
    "panel_size",
    "persona_words",
    "segment_words",
    "sit_in",
    "words",
]
