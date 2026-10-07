"""Personas as data — spec §6.7, Trap 7, FR-6.3.

**Trap 7 is "personas that are just adjectives in a prompt".** "Be a strict
interviewer" produces a rude one on some turns and a friendly one on others.
So a persona here is a parameter vector, and every parameter drives a concrete
mechanic that a test can see — never a mood the model is asked to have:

    register              which authored line table is said (phrasebook)
    lines                 this persona's own greeting, exits and bridges, if any
    follow_up_aggression  how deep the ladder may go (`max_depth`) and how
                          many generic rungs it may spend
    patience              seconds of silence before an idle prompt (EC-6.1)
    interruption_threshold  words of typed answer before "let's keep it moving"
    verbosity_target      the most words a model-phrased probe may use
    note_taking_cadence   how often "let me note that down" is said
    hints_available       whether this interviewer gives hints at all
    style                 one authored sentence the interviewer model reads

`warmth` and `formality` are carried in the register choice and the authored
lines rather than being handed to a model as numbers it would interpret
differently on every call. `domain_bias` is Phase 3 (company matching with
M15), carried and validated now so a persona file never has to change shape.
`voice_id` is read since 2026-10-05: until M11 exists, the browser speaks each
line in the voice it names (`locale-voice-manner`, e.g. `en-IN-female-warm`),
so it is on the card and its shape is checked at load like every other field.

**Personas are data, validated at load.** A file missing a parameter, naming
an unknown register, or carrying a line the guard refuses fails the BOOT —
`app.py` loads every persona before serving — rather than failing a session
at minute twenty. `id` must equal the file name, so two files cannot claim one
persona.

**The persona never changes the standard** (AC-6.17, `test_fairness.py`). What
varies here is the experience: the words, the register, how deep the ladder
goes, whether hints exist. Nothing here reaches M13's payload or the
strategist's prompt.
"""

from __future__ import annotations

import dataclasses
import functools
import math
import string
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .agents.guard import screen
from .contracts import DEPTH_CAP
from .phrasebook import BACKCHANNELS, LINES, Lines, Register

PERSONA_DIR = Path(__file__).resolve().parent / "personas"

#: The persona a session falls back to if its plan names one that no longer
#: exists — a live interview must not crash because a file was renamed.
FALLBACK_PERSONA = "methodical_engineer"

#: Every line a persona may override. Anything else in `lines:` is a typo, and
#: a typo'd override is a line that silently never ships.
LINE_NAMES = frozenset(f.name for f in dataclasses.fields(Lines))


def placeholders(text: str) -> frozenset[str]:
    """The `{names}` a line is formatted with."""
    return frozenset(name for _, name, _, _ in string.Formatter().parse(text) if name)


#: What each line must name, read off the neutral register's own template —
#: so a new templated line needs no rule here. An override missing one says
#: less than the line promises ("Next up: ." for a bridge with no {topic});
#: one naming a field nobody fills raises KeyError mid-session.
LINE_FIELDS: dict[str, frozenset[str]] = {
    name: placeholders(getattr(LINES["neutral"], name)) for name in LINE_NAMES
}


class PersonaError(ValueError):
    """A persona file that must not be served. Raised at boot."""


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=60)
    #: `register:` in the file. Renamed in Python only because pydantic's
    #: BaseModel already has a `register` attribute.
    speech: Register = Field(alias="register")
    style: str = Field(min_length=10, max_length=240)

    # §6.7's vector. No defaults, on purpose: a missing parameter is a boot
    # failure, not a silent 0.5.
    warmth: float = Field(ge=0.0, le=1.0)
    patience: float = Field(ge=0.0, le=1.0)
    formality: float = Field(ge=0.0, le=1.0)
    interruption_threshold: float = Field(ge=0.0, le=1.0)
    follow_up_aggression: float = Field(ge=0.0, le=1.0)
    verbosity_target: int = Field(ge=10, le=45)
    domain_bias: list[str]
    #: `locale-voice-manner`: `en-IN-female-warm`, `en-IN-male-brisk`. The
    #: browser picks a voice for the locale and kind and paces it by the
    #: manner; M11 will map the same id to its own voices.
    voice_id: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}-[a-z]+-[a-z]+$")
    #: The M11 voice this persona speaks in — a key of Voice_Engine's
    #: `voices/cast.json`, where the same persona is cast (2026-10-07). M11
    #: has seven voices and the cast is five times that, so voices are shared
    #: across the cast; this is how a panel avoids seating two people who
    #: sound the same (`panel.py`). Optional: without it, M11 matches the
    #: `voice_id`, and the panel treats the persona as a voice of its own.
    voice: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    note_taking_cadence: int = Field(ge=0, le=12)
    hints_available: bool

    lines: dict[str, str] = Field(default_factory=dict)

    @field_validator("lines")
    @classmethod
    def _lines_are_known_and_safe(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - LINE_NAMES)
        if unknown:
            raise ValueError(
                f"unknown line(s) {unknown}; a persona may override {sorted(LINE_NAMES)}"
            )
        for name, text in value.items():
            verdict = screen(text)
            if not verdict.ok:
                raise ValueError(f"line {name!r} is refused by the guard: {verdict.reason}")
        for name, text in value.items():
            have, need = placeholders(text), LINE_FIELDS[name]
            if have != need:
                said = " and ".join(f"{{{f}}}" for f in sorted(need)) or "no {placeholders}"
                raise ValueError(f"line {name!r} must say {said}, as the register's does")
        return value

    # ── the mechanics the parameters drive ───────────────────────────────

    def said(self) -> Lines:
        """This persona's line table: its register's, with its own on top."""
        return dataclasses.replace(LINES[self.speech], **self.lines)

    @property
    def max_depth(self) -> int:
        """How deep the ladder may go (§6.7 `follow_up_aggression`).

        0.4 → 2, 0.7 → 4, 0.9 → 5. Never below 2: one follow-up is not a
        probe ladder, and a persona that gentle should not be asking.
        """
        return max(2, min(DEPTH_CAP, math.ceil(self.follow_up_aggression * DEPTH_CAP)))

    @property
    def max_generic_rungs(self) -> int:
        """Generic "why does that work?" rungs allowed on a question that has
        run out of follow-ups of its own. A gentle interviewer asks none; a
        bar-raiser keeps going with two."""
        if self.follow_up_aggression < 0.35:
            return 0
        return 2 if self.follow_up_aggression >= 0.95 else 1

    @property
    def idle_after_s(self) -> int:
        """EC-6.1 in text mode: silence before the first gentle prompt.

        Patience 0.4 → 46 s, the spec's 45; 0.9 → 66 s; 0.2 → 38 s.
        """
        return round(30 + 40 * self.patience)

    @property
    def sound(self) -> str:
        """What this persona sounds like, for "never two alike on one panel":
        its M11 voice, or itself when it names none."""
        return self.voice or f"persona:{self.id}"

    @property
    def backchannels(self) -> tuple[str, ...]:
        """M11's FR-11.11: what this interviewer says while the student talks."""
        return BACKCHANNELS[self.speech]

    @property
    def backchannel_every_s(self) -> float:
        """FR-11.11: the least time between two of them — the warmer, the more
        often. Warmth 0.9 → 6.8 s; 0.5 → 10 s; 0.3 → 11.6 s."""
        return round(6 + 8 * (1 - self.warmth), 1)

    @property
    def long_answer_words(self) -> int:
        """§6.7 `interruption_threshold` in text: a typed answer longer than
        this gets one "let's keep it moving" per round."""
        return round(80 + 320 * self.interruption_threshold)

    def card(self) -> dict:
        """What a student's browser may know about who is asking."""
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "register": self.speech,
            "style": self.style,
            "idle_after_s": self.idle_after_s,
            "long_answer_words": self.long_answer_words,
            "hints_available": self.hints_available,
            "voice_id": self.voice_id,
            # M11's timing (FR-11.10, FR-11.11): how long this interviewer
            # waits before answering is read from its patience, and what it
            # says while the student talks, how often. Neither is the ladder.
            "patience": self.patience,
            "backchannels": list(self.backchannels),
            "backchannel_every_s": self.backchannel_every_s,
        }


def load_personas(directory: Path = PERSONA_DIR) -> dict[str, Persona]:
    """Every persona file, validated. Raises `PersonaError` naming the file."""
    found: dict[str, Persona] = {}
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise PersonaError(f"no persona files in {directory}")
    for path in files:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PersonaError(f"{path.name}: not valid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise PersonaError(f"{path.name}: expected a mapping")
        try:
            persona = Persona.model_validate(raw)
        except ValidationError as exc:
            raise PersonaError(f"{path.name}: {exc}") from exc
        if persona.id != path.stem:
            raise PersonaError(f"{path.name}: id {persona.id!r} must equal the file name")
        found[persona.id] = persona
    if FALLBACK_PERSONA not in found:
        raise PersonaError(f"the fallback persona {FALLBACK_PERSONA!r} is missing")
    return found


@functools.cache
def personas() -> dict[str, Persona]:
    return load_personas()


def persona(persona_id: str | None) -> Persona:
    """The persona by id — or the fallback, never an error mid-interview."""
    table = personas()
    return table.get(persona_id or "", table[FALLBACK_PERSONA])


__all__ = [
    "FALLBACK_PERSONA",
    "LINE_NAMES",
    "PERSONA_DIR",
    "Persona",
    "PersonaError",
    "load_personas",
    "persona",
    "personas",
]
