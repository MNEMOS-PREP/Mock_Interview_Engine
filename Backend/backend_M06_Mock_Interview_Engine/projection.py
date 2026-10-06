"""What the interviewer may know — spec §6.3, FR-6.15, AC-6.3.

**The enforcement is the type, not the prompt.** The interviewer's model is
handed an `InterviewerView` and nothing else, and `reaches_forbidden()` walks
that type's graph for any path to a score, a verdict, an ability estimate or
the student's identity. It runs as a release gate; a field added tomorrow that
leaks fails the day it lands.

Same idea as M13's `projection.py`, deliberately: two modules enforcing two
different blind boundaries with the same mechanism.

What the view carries is WHAT to do next (`move`), never WHY. "The strategist
said below" is a verdict; "ask the next rung" is an instruction.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Literal

from pydantic import BaseModel, Field

from .contracts import MoveKind
from .heard import for_interviewer

#: Class names a view's type graph may never reach, matched by name so the
#: check does not need M13's or M05's types importable here.
FORBIDDEN_TYPE_NAMES = frozenset(
    {
        "StrategistVerdict",
        "ProvisionalOutcome",
        "TurnEvaluation",
        "DimensionScore",
        "SessionState",
        "SessionFlags",
        "Observation",
        "Mastery",
        "Principal",
    }
)

#: Field names that carry a verdict or an identity whatever their type.
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "band",
        "verdict",
        "score",
        "scores",
        "raw_score",
        "confidence",
        "justification",
        "theta",
        "theta_provisional",
        "mastery",
        "mastery_p",
        "candidate_id",
        "candidate_name",
        "email",
        "consent_id",
        "break_depth",
        "key_points_missing",
    }
)


#: `agents.summariser.MAX_CHARS`, imported by value rather than by module to
#: keep the projection free of agent imports — it is the file that must be
#: readable end to end when asking what the interviewer can see.
SUMMARY_MAX_CHARS = 1200


class ViewTurn(BaseModel):
    role: Literal["interviewer", "candidate", "system"]
    text: str


class InterviewerView(BaseModel):
    """Everything the interviewer's model receives."""

    persona_register: Literal["friendly", "neutral", "bar_raiser"] = "neutral"
    #: The persona's one authored sentence (`personas/*.yaml` `style`). The
    #: experience, which §6.7 lets differ — never the standard.
    persona_style: str = ""
    #: The persona's `verbosity_target`: the most words a phrased probe may use.
    max_words: int = 30
    segment_title: str = ""
    recent_turns: list[ViewTurn] = Field(default_factory=list, max_length=6)
    #: §6.6's rolling note: what happened BEFORE the six turns above. Bounded
    #: by `summariser.MAX_CHARS`, so a long session costs no more context
    #: than a short one (AC-6.10).
    round_summary: str = ""
    #: M04's pinned summary text — byte-stable for the session (AC-4.13).
    profile_prefix: str = ""
    move: MoveKind
    ladder_depth: int = 0
    time_remaining_s: int = 0


def project_for_interviewer(
    *,
    transcript: list[Any],
    move: MoveKind,
    ladder_depth: int,
    time_remaining_s: float,
    segment_title: str = "",
    profile_prefix: str = "",
    register: str = "neutral",
    round_summary: str = "",
    persona_style: str = "",
    max_words: int = 30,
) -> InterviewerView:
    return InterviewerView(
        persona_register=register,  # type: ignore[arg-type]
        persona_style=persona_style,
        max_words=max_words,
        segment_title=segment_title,
        round_summary=round_summary[:SUMMARY_MAX_CHARS],
        # A line the student cut in on reads as far as it was heard (M11's
        # FR-11.9), so a follow-up does not assume what they never heard.
        recent_turns=[
            ViewTurn(role=t.role, text=for_interviewer(t) if t.role == "interviewer" else t.text)
            for t in transcript[-6:]
        ],
        profile_prefix=profile_prefix,
        move=move,
        ladder_depth=ladder_depth,
        time_remaining_s=int(time_remaining_s),
    )


def _annotations(tp: Any) -> list[Any]:
    origin = typing.get_origin(tp)
    if origin is None:
        return [tp]
    if origin is Literal:
        return []
    return [a for arg in typing.get_args(tp) for a in _annotations(arg)]


def reaches_forbidden(model: type[BaseModel], _seen: set[type] | None = None) -> list[str]:
    """Every path from `model` to a forbidden type or field name."""
    seen = _seen if _seen is not None else set()
    if model in seen:
        return []
    seen.add(model)
    found: list[str] = []
    for name, info in model.model_fields.items():
        if name.lower() in FORBIDDEN_FIELD_NAMES:
            found.append(f"{model.__name__}.{name}")
        for tp in _annotations(info.annotation):
            if isinstance(tp, types.UnionType):
                continue
            if isinstance(tp, type):
                if tp.__name__ in FORBIDDEN_TYPE_NAMES:
                    found.append(f"{model.__name__}.{name} -> {tp.__name__}")
                elif issubclass(tp, BaseModel):
                    found.extend(
                        f"{model.__name__}.{name} -> {p}" for p in reaches_forbidden(tp, seen)
                    )
    return found


__all__ = [
    "FORBIDDEN_FIELD_NAMES",
    "FORBIDDEN_TYPE_NAMES",
    "InterviewerView",
    "ViewTurn",
    "project_for_interviewer",
    "reaches_forbidden",
]
