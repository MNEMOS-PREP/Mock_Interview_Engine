"""Re-planning at a segment boundary — FR-6.4, spec §6.4. Pure.

Trap 4 is "re-planning too eagerly": a supervisor that re-plans after every
turn produces an interview that wanders. So: only at a boundary, at most two
per session, and only on the triggers §6.4 names.

**Every input is one M06 produced on its own hot path** — the strategist's
bands, the ladder's break depths, idle move-ons, the clock. M13's scores are
never read here: they arrive asynchronously (p95 ≤ 15 s), so at a boundary the
last turns' scores usually do not exist, and they are uncalibrated
(`display_numeric: false`) — a number nobody may show should not steer the
session either. A test holds this file to it.

**Two sentences per change.** The report says why, fully ("I changed the plan
here because…" — §6.4's transparency). The live toast says what, neutrally:
"that round was hard, so I eased off" mid-interview is a live score by another
name, which §2.2 forbids. So `live_note` never describes the student.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .contracts import InterviewPlan, PlannedSegment, Replan
from .modes import mode_config
from .pacing import segment_overrun
from .planner import live_segments
from .state import SessionState

#: §6.4's cap.
MAX_REPLANS = 2

#: "≥ 2 turns in this segment broke at depth ≤ 1 on concepts sharing a
#: prerequisite in M04's graph".
GAP_BREAKS = 2
SHALLOW = 1
#: "≥ 3 turns in the segment with band `below` and justification `failed` at
#: depth ≤ 1, or ≥ 2 silence timeouts".
STRUGGLING_FAILS = 3
STRUGGLING_SILENCES = 2

#: Who a recovery posture hands the rest of the session to when nobody on
#: the panel is warmer than its lead (§6.4: "friendly register"). Kept for
#: plans with no panel recorded; `recovery_persona` decides otherwise.
RECOVERY_PERSONA = "friendly_recruiter"


def recovery_persona(plan) -> str | None:
    """§6.4's recovery posture, on a panel (FR-6.3): the rest of a hard
    session goes to someone GENTLE — a persona whose own file gives it the
    friendly register — the warmest one already on the panel if there is one,
    else the warmest the mode admits, who joins and introduces themselves.
    None when the mode admits nobody gentle (Final Boss): the panel stays,
    and the pace eases by mechanics alone.

    Until 2026-10-07 any panelist warmer than the lead counted, so a live
    mock handed the rest of the interview — its DSA round and its closing —
    to the professor (warmth 0.6 against the lead's 0.5): nothing got
    gentler, and the panel's shape broke."""
    from . import panel as seating
    from .modes import mode_config
    from .personas import personas

    people = personas()
    warmest = lambda found: max(found, key=lambda p: (p.warmth, p.patience, p.id)).id  # noqa: E731
    seated = [people[p] for p in dict.fromkeys(plan.panel) if p in people]
    gentle = [p for p in seated if p.speech == "friendly"]
    if gentle:
        return warmest(gentle)
    temperament = mode_config(plan.mode).temperament
    admitted = [
        p for p in people.values() if p.speech == "friendly" and seating.fits(p, temperament)
    ]
    return warmest(admitted) if admitted else None


#: concept id -> M04's concept (name, prerequisites), or None when unknown or
#: M04 is not there. The gap trigger degrades to "not fired" without it.
ConceptLookup = Callable[[str], dict | None]


@dataclass
class Signals:
    """What happened in one segment, from M06's own hot path only."""

    #: Concepts whose ladder broke at depth ≤ 1, in the order they broke.
    shallow_breaks: list[str] = field(default_factory=list)
    #: Answers judged `below` and `failed` at depth ≤ 1.
    shallow_fails: int = 0
    #: Idle prompts that ran out and moved on (EC-6.1).
    silences: int = 0
    #: The segment's stretch item (M05 `reason = stretch`) was answered `above`.
    stretch_above: bool = False
    #: How far past its budget the segment ran, as a fraction.
    overrun: float = 0.0

    def as_numbers(self) -> dict[str, float]:
        return {
            "shallow_breaks": float(len(self.shallow_breaks)),
            "shallow_fails": float(self.shallow_fails),
            "silences": float(self.silences),
            "stretch_above": 1.0 if self.stretch_above else 0.0,
            "overrun": round(self.overrun, 3),
        }


def signals(state: SessionState, events, segment: PlannedSegment, now: datetime) -> Signals:
    """Read one segment's hot-path signals from the log. Never an M13 field."""
    out = Signals()
    in_segment = {t.turn_index: t for t in state.transcript if t.segment_index == segment.index}
    # question turn index -> (concept, selection reason), for the ladder the
    # answers below belong to.
    asked: dict[int, tuple[str, str | None]] = {}
    for event in sorted(events, key=lambda e: e.seq):
        p = event.payload
        if event.kind == "question.asked" and p.get("new_question"):
            index = int(p.get("turn_index", -1))
            if index in in_segment:
                asked[index] = (str(p.get("concept_id") or ""), p.get("selection_reason"))
        elif event.kind == "probe.decided":
            answer = in_segment.get(int(event.turn_index))
            if answer is None or answer.role != "candidate":
                continue
            verdict = p.get("verdict") or {}
            question = max((i for i in asked if i < answer.turn_index), default=None)
            concept, reason = (
                asked.get(question, ("", None)) if question is not None else ("", None)
            )
            if (
                verdict.get("band") == "below"
                and verdict.get("justification") == "failed"
                and answer.probe_depth <= SHALLOW
            ):
                out.shallow_fails += 1
            if p.get("break_depth") is not None and int(p["break_depth"]) <= SHALLOW and concept:
                out.shallow_breaks.append(concept)
            if reason == "stretch" and verdict.get("band") == "above":
                out.stretch_above = True
        elif event.kind == "idle.moved_on" and int(p.get("segment_index", -1)) == segment.index:
            out.silences += 1
    if segment.kind not in ("warmup", "closing"):
        # The same exemption as the round's own clock (`pacing.over_time`):
        # the warm-up is one question by construction, and the closing is
        # the student's.
        out.overrun = segment_overrun(
            state, segment, now, mode_config(state.mode).overrun_allowance
        )
    return out


def _shared_prerequisite(concepts: list[str], lookup: ConceptLookup) -> tuple[str, str] | None:
    """(id, name) of a prerequisite two of these concepts share, or None."""
    seen: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for concept in dict.fromkeys(concepts):
        found = lookup(concept)
        if not found:
            continue
        for prerequisite in found.get("prerequisites") or []:
            pid = str(prerequisite.get("concept_id") or prerequisite.get("id") or "")
            if not pid:
                continue
            seen.setdefault(pid, set()).add(concept)
            if len(seen[pid]) >= GAP_BREAKS:
                named = lookup(pid) or {}
                names[pid] = str(named.get("name") or pid.split(":")[-1].replace("_", " "))
                return pid, names[pid]
    return None


def evaluate(
    state: SessionState,
    events,
    leaving: PlannedSegment,
    now: datetime,
    lookup: ConceptLookup,
) -> Replan | None:
    """The one re-plan this boundary earns, if any. First trigger wins.

    Order: the clock first (a session over time must protect its closing
    before anything else), then struggling (the student's experience), then
    the gap (what to ask next), then the ceiling (how much more to ask).
    """
    plan = state.plan
    if plan is None or len(plan.replans) >= MAX_REPLANS:
        return None
    upcoming = _upcoming(plan, leaving)
    if not upcoming:
        return None
    s = signals(state, events, leaving, now)
    before = [seg.model_copy(deep=True) for seg in plan.segments]

    if s.overrun > 0:
        return _time_overrun(plan, leaving, upcoming, s, before)
    if s.shallow_fails >= STRUGGLING_FAILS or s.silences >= STRUGGLING_SILENCES:
        return _struggling(plan, leaving, upcoming, s, before)
    if len(s.shallow_breaks) >= GAP_BREAKS:
        shared = _shared_prerequisite(s.shallow_breaks, lookup)
        if shared is not None:
            return _gap(plan, leaving, upcoming, s, before, shared)
    if s.stretch_above:
        return _ceiling(plan, leaving, upcoming, s, before)
    return None


def _upcoming(plan: InterviewPlan, leaving: PlannedSegment) -> list[PlannedSegment]:
    """The live segments after `leaving`, the reserved closing excluded."""
    live = live_segments(plan)
    position = next((i for i, seg in enumerate(live) if seg.index == leaving.index), None)
    if position is None:
        return []
    return [seg for seg in live[position + 1 :] if not seg.is_reserved]


def _after(before: list[PlannedSegment], change) -> list[PlannedSegment]:
    after = [seg.model_copy(deep=True) for seg in before]
    change({seg.index: seg for seg in after})
    return after


def _time_overrun(plan, leaving, upcoming, s: Signals, before) -> Replan:
    """§6.4: compress the next segment, protect the closing."""
    target = upcoming[0].index
    keep = max(0.0, 1.0 - s.overrun)

    def change(by_index):
        seg = by_index[target]
        seg.question_budget = max(1, math.floor(seg.question_budget * keep))
        seg.minutes = round(max(seg.minutes * keep, 1.0), 1)

    return Replan(
        at_segment=leaving.index,
        trigger="time_overrun",
        signals=s.as_numbers(),
        before=before,
        after=_after(before, change),
        student_sentence=(
            f"“{leaving.title}” ran over its time, so I shortened the next part rather than cut "
            "into the time for your questions at the end."
        ),
        live_note="Adjusting — the next part is a little shorter, so we keep time at the end.",
    )


def _listed(items: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _struggling(plan, leaving, upcoming, s: Signals, before) -> Replan:
    """§6.4: drop one non-reserved segment, extend the closing, and a
    recovery posture — a friendly register for the rest of the session."""
    closing = next((seg for seg in plan.segments if seg.is_reserved), None)
    dropped = upcoming[-1] if len(upcoming) > 1 else None

    gentler = recovery_persona(plan)

    def change(by_index):
        if dropped is not None:
            seg = by_index[dropped.index]
            seg.dropped_reason = "Left out to give the rest of the session more room."
            if closing is not None:
                by_index[closing.index].minutes = round(
                    by_index[closing.index].minutes + seg.minutes, 1
                )
        if gentler is None:
            return  # nobody gentle in this mode: the panel stays
        for seg in upcoming:
            if seg.index in by_index and by_index[seg.index].dropped_reason is None:
                by_index[seg.index].persona_id = gentler
        if closing is not None:
            by_index[closing.index].persona_id = gentler

    return Replan(
        at_segment=leaving.index,
        trigger="struggling",
        signals=s.as_numbers(),
        before=before,
        after=_after(before, change),
        student_sentence=(
            f"“{leaving.title}” was a hard round, so I eased the pace for the rest: "
            + _listed(
                [
                    *(["one part less"] if dropped is not None else []),
                    *(["a gentler interviewer"] if gentler is not None else []),
                    "more time at the end for your questions",
                ]
            )
            + "."
        ),
        live_note="Adjusting the plan — a slightly different shape for the rest of the session.",
    )


def _gap(plan, leaving, upcoming, s: Signals, before, shared: tuple[str, str]) -> Replan:
    """§6.4: re-target the next segment to the prerequisite two breaks share."""
    concept_id, name = shared
    target = upcoming[0].index

    def change(by_index):
        seg = by_index[target]
        seg.concept_ids = [concept_id, *[c for c in seg.concept_ids if c != concept_id]]
        seg.rationale = f"Checking {name} first — it sits underneath what we just covered."

    return Replan(
        at_segment=leaving.index,
        trigger="gap_discovered",
        signals=s.as_numbers(),
        before=before,
        after=_after(before, change),
        student_sentence=(
            f"Two questions in “{leaving.title}” stopped early on ideas that both build on "
            f"{name}, so I asked about {name} next."
        ),
        # §8's own example copy: it names a topic, not a performance.
        live_note=f"Adjusting — I want to check {name} first.",
    )


def _ceiling(plan, leaving, upcoming, s: Signals, before) -> Replan:
    """§6.4: one extra question per remaining segment (§6.9's ahead rule)."""

    def change(by_index):
        for seg in upcoming:
            if seg.index in by_index and by_index[seg.index].dropped_reason is None:
                by_index[seg.index].question_budget += 1

    return Replan(
        at_segment=leaving.index,
        trigger="ceiling_hit",
        signals=s.as_numbers(),
        before=before,
        after=_after(before, change),
        student_sentence=(
            f"You handled the stretch question in “{leaving.title}”, so I added a question to "
            "each part that was left, to find where your edge actually is."
        ),
        live_note="Adjusting — one more question in each part that's left.",
    )


__all__ = [
    "MAX_REPLANS",
    "RECOVERY_PERSONA",
    "ConceptLookup",
    "Signals",
    "evaluate",
    "signals",
]
