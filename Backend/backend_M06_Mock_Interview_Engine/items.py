"""One shape for "the thing being asked", whatever it came from.

Three sources reach the ladder — an M05 bank item, M06's own fallback item,
and an M01 claim's probe ladder — and they spell the same ideas differently
(`follow_ups[].template` vs `probes[].question`, `key_points[].statement` vs
`probes[].expects`). The ladder and the agents read an `Item`, so a fourth
source is one constructor rather than a branch in every caller.

**Rungs are derived, not hardcoded** (spec §6.5, and the platform's standing
rule): the wording at depth *d* is the question's own follow-up at *d* when it
has one, and the generic rung only when it does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .phrasebook import GENERIC_RUNGS


@dataclass(frozen=True)
class KeyPoint:
    id: str
    statement: str
    required: bool = False


@dataclass(frozen=True)
class Item:
    stem: str
    source: str
    question_id: UUID | None = None
    concept_id: str = ""
    #: The rubric M13 scores this against. None → recorded, not scored.
    rubric_round_type: str | None = None
    key_points: tuple[KeyPoint, ...] = ()
    #: depth → the question's own wording for that rung.
    follow_ups: dict[int, str] = field(default_factory=dict)
    #: depth → what a good answer at that rung contains (M01 `expects`, a
    #: list of points — see `_points`).
    expects: dict[int, tuple[str, ...]] = field(default_factory=dict)
    hint_ladder: tuple[str, ...] = ()
    time_budget_s: int = 300
    label: str = ""

    def rung(self, depth: int) -> tuple[str, bool]:
        """(wording, is_own). `is_own` is False when the generic rung was used."""
        own = self.follow_ups.get(depth)
        if own:
            return own, True
        return GENERIC_RUNGS.get(depth, GENERIC_RUNGS[max(GENERIC_RUNGS)]), False

    @property
    def deepest_own_rung(self) -> int:
        return max(self.follow_ups, default=0)

    def expected_at(self, depth: int) -> list[str]:
        """What the strategist is told a good answer contains at this depth."""
        if depth in self.expects:
            return list(self.expects[depth])
        return [kp.statement for kp in self.key_points]


def _points(value: Any) -> tuple[str, ...]:
    """M01's `expects` for one rung, as points.

    M01 sends a list of strings (`claims.py`, `ProbeQuestion.expects`, since
    2026-08-23). M06 was written against a stub that sent one string, so a
    resume question's rungs were stored as lists inside a field typed `str`,
    and the notes failed for every session that asked one. Both shapes are
    read, so events stored either way still open.
    """
    if isinstance(value, str):
        value = [value]
    return tuple(s.strip() for s in value or () if isinstance(s, str) and s.strip())


def _expects(raw: dict[Any, Any] | None) -> dict[int, tuple[str, ...]]:
    out = {int(d): _points(v) for d, v in (raw or {}).items()}
    return {d: points for d, points in out.items() if points}


def expected_statements(raw: dict[Any, Any] | None) -> list[str]:
    """Every rung's points from a stored item's `expects`, opening rung first,
    each once — what the notes list under "what a strong answer covers"."""
    seen: dict[str, None] = {}
    for _, points in sorted(_expects(raw).items()):
        seen.update(dict.fromkeys(points))
    return list(seen)


def _primary_concept(concepts: list[dict[str, Any]]) -> str:
    primary = next((c for c in concepts if c.get("role") == "primary"), None)
    chosen = primary or (concepts[0] if concepts else None)
    return str(chosen.get("concept_id", "")) if chosen else ""


def from_m05(question: dict[str, Any], *, round_type: str, source: str) -> Item:
    """An M05 `Question` (or M06's fallback copy of one), as selected for `round_type`."""
    raw_id = question.get("id")
    return Item(
        stem=question["stem"],
        source=source,
        question_id=UUID(str(raw_id)) if raw_id else None,
        concept_id=_primary_concept(question.get("concepts") or []),
        # M06's own fallback items are never sent to M13 — it cannot find them.
        rubric_round_type=round_type if source == "m05_bank" else None,
        key_points=tuple(
            KeyPoint(id=str(kp["id"]), statement=kp["statement"], required=bool(kp.get("required")))
            for kp in question.get("key_points") or []
        ),
        follow_ups={
            int(f["depth"]): f["template"]
            for f in question.get("follow_ups") or []
            if int(f["depth"]) >= 1 and f.get("template")
        },
        hint_ladder=tuple(question.get("hint_ladder") or ()),
        time_budget_s=int(question.get("time_budget_s") or 300),
        label=str(question.get("label") or ""),
    )


def from_drill(drill: dict[str, Any]) -> Item:
    """M01's claim and probe ladder. Depth 0 is the opening question."""
    probes = sorted(drill.get("probes") or [], key=lambda p: int(p.get("depth", 0)))
    if not probes:
        raise ValueError("a drill needs at least one probe")
    opening = probes[0]
    return Item(
        stem=opening["question"],
        source="m01_probe",
        concept_id=f"claim:{drill.get('claim_id', '')}",
        rubric_round_type=None,
        follow_ups={int(p["depth"]): p["question"] for p in probes[1:] if int(p["depth"]) >= 1},
        expects=_expects({p["depth"]: p.get("expects") for p in probes}),
        time_budget_s=120,
        label=str(drill.get("claim_text", ""))[:80],
    )


def to_dict(item: Item) -> dict[str, Any]:
    """JSON-safe. Stored on the `question.asked` event, so the item behind an
    open question survives a restart without asking M05 again."""
    return {
        "stem": item.stem,
        "source": item.source,
        "question_id": str(item.question_id) if item.question_id else None,
        "concept_id": item.concept_id,
        "rubric_round_type": item.rubric_round_type,
        "key_points": [
            {"id": kp.id, "statement": kp.statement, "required": kp.required}
            for kp in item.key_points
        ],
        # JSON object keys are strings; `from_dict` turns them back.
        "follow_ups": {str(d): t for d, t in item.follow_ups.items()},
        "expects": {str(d): list(points) for d, points in item.expects.items()},
        "hint_ladder": list(item.hint_ladder),
        "time_budget_s": item.time_budget_s,
        "label": item.label,
    }


def from_dict(data: dict[str, Any]) -> Item:
    return Item(
        stem=data["stem"],
        source=data["source"],
        question_id=UUID(data["question_id"]) if data.get("question_id") else None,
        concept_id=data.get("concept_id", ""),
        rubric_round_type=data.get("rubric_round_type"),
        key_points=tuple(KeyPoint(**kp) for kp in data.get("key_points", [])),
        follow_ups={int(d): t for d, t in (data.get("follow_ups") or {}).items()},
        expects=_expects(data.get("expects")),
        hint_ladder=tuple(data.get("hint_ladder") or ()),
        time_budget_s=int(data.get("time_budget_s", 300)),
        label=data.get("label", ""),
    )


__all__ = [
    "Item",
    "KeyPoint",
    "expected_statements",
    "from_dict",
    "from_drill",
    "from_m05",
    "to_dict",
]
