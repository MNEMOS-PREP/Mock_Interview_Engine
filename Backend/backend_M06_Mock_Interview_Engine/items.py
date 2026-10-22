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

import re
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
class Part:
    """One part of a question asked one part at a time (`decompose.py`).

    Part 0 is the question as first asked; parts 1… come as follow-ups, each
    once the answer before it has been heard. `key_point_ids` are the points
    of the whole question this part asks about — so an answer that already
    covered them skips the part, and M13 scores only what was asked."""

    index: int
    text: str
    key_point_ids: tuple[str, ...] = ()


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
    #: M05's reference answer: *a* good answer. Never said during the
    #: interview — the guard refuses a line that repeats it — and shown in
    #: the notes afterwards as one way a strong answer goes.
    reference_answer: str = ""
    #: 2026-10-22: the question asked one part at a time — part 0 is `stem`
    #: as first said, the rest are follow-ups (`decompose.py`). Empty for a
    #: question asked whole.
    parts: tuple[Part, ...] = ()
    #: The full stem as authored, when `stem` is only its first part.
    full_stem: str = ""

    @property
    def answer_key(self) -> list[str]:
        """What must never be said to the student mid-interview."""
        key = [kp.statement for kp in self.key_points]
        key += [point for points in self.expects.values() for point in points]
        if self.reference_answer:
            key.append(self.reference_answer)
        return key

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
        reference_answer=str(question.get("reference_answer") or ""),
    )


#: Words M01's probe templates use themselves ("Walk me through this project",
#: "how did you split the work across the team"): sharing one with the claim
#: does not make a question say which line it is about.
_TEMPLATE_WORDS = frozenset(
    "walk through what actually build built words your this that project work team "
    "with from into about situation took split across track format were judged".split()
)
#: The most of a claim read out before its question.
CLAIM_QUOTE_WORDS = 30


def shorten(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word and marked when cut — a
    claim's label used to end "…reduced average order w"."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4} - _TEMPLATE_WORDS


def names_its_claim(question: str, claim: str) -> bool:
    """Whether a claim's question says which resume line it is about."""
    return bool(_content(question) & _content(claim))


def from_drill(drill: dict[str, Any]) -> Item:
    """M01's claim and probe ladder. Depth 0 is the opening question."""
    probes = sorted(drill.get("probes") or [], key=lambda p: int(p.get("depth", 0)))
    if not probes:
        raise ValueError("a drill needs at least one probe")
    opening = probes[0]
    stem = str(opening["question"])
    claim = " ".join(str(drill.get("claim_text", "")).split()).rstrip(" .;,")
    if claim and not names_its_claim(stem, claim):
        # 2026-10-23: M01's opening probes are generic by design ("Walk me
        # through this project", "What was the situation when you took this
        # on?") — its page shows the line beside them. Spoken, nothing does: a
        # live resume interview asked "walk me through this project" about two
        # different lines. The interviewer reads the line out first.
        words = claim.split()
        quoted = " ".join(words[:CLAIM_QUOTE_WORDS])
        if len(words) > CLAIM_QUOTE_WORDS:
            quoted += "…"
        stem = f"On your resume: “{quoted}”. {stem}"
    return Item(
        stem=stem,
        source="m01_probe",
        concept_id=f"claim:{drill.get('claim_id', '')}",
        rubric_round_type=None,
        follow_ups={int(p["depth"]): p["question"] for p in probes[1:] if int(p["depth"]) >= 1},
        expects=_expects({p["depth"]: p.get("expects") for p in probes}),
        time_budget_s=120,
        label=shorten(str(drill.get("claim_text", "")), 80),
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
        "reference_answer": item.reference_answer,
        "parts": [
            {"index": p.index, "text": p.text, "key_point_ids": list(p.key_point_ids)}
            for p in item.parts
        ],
        "full_stem": item.full_stem,
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
        reference_answer=str(data.get("reference_answer") or ""),
        parts=tuple(
            Part(
                index=int(p["index"]),
                text=str(p["text"]),
                key_point_ids=tuple(str(k) for k in p.get("key_point_ids") or ()),
            )
            for p in data.get("parts") or []
        ),
        full_stem=str(data.get("full_stem") or ""),
    )


__all__ = [
    "Item",
    "KeyPoint",
    "Part",
    "expected_statements",
    "from_dict",
    "from_drill",
    "from_m05",
    "to_dict",
]
