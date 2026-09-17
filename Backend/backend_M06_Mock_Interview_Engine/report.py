"""The session report — FR-6.18, the Phase 1 version (spec §15.7).

Built from the event log alone, so it exists for every session that has one:
ended, aborted, or crashed half-way (AC-6.1). M19 will project the same events
into the real report; this one is deleted when that ships.

What it does NOT contain yet is any score. M13's evaluations arrive on day 4,
and even then `display_numeric` is false everywhere until calibration is
fitted — so the honest Phase 1 report is the ladder: what was asked, how far
each question went, where it stopped, and why a turn was not scored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .contracts import SessionStatus
from .models import SessionEvent
from .state import SessionState

NOT_SCORED = {
    "m01_probe": "Practice drill — drills are not scored yet.",
    "local_fallback": (
        "Asked from the backup set while the question bank was offline, so it was not scored."
    ),
    "template": "Not a scored question.",
}

WARM_UP_SHARE = 0.25


class Exchange(BaseModel):
    role: str
    text: str
    move: str | None = None
    depth: int = 0


class QuestionReport(BaseModel):
    question: str
    source: str
    scored: bool
    not_scored_reason: str | None = None
    exchanges: list[Exchange] = Field(default_factory=list)
    depth_reached: int = 0
    #: The rung where the reasoning stopped holding. None means it never did.
    break_depth: int | None = None
    #: Two clears in a row at depth ≥ 4 — the student was stretched and held.
    ceiling: int | None = None
    hints_used: int = 0
    #: What a strong answer covers. Shown only once the session is over.
    strong_answer_covers: list[str] = Field(default_factory=list)


class SessionReport(BaseModel):
    session_id: str
    kind: str
    mode: str
    status: SessionStatus
    end_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    minutes_used: float
    minutes_planned: int
    framing: str
    questions: list[QuestionReport]
    notes: list[str]
    persona_note: str = (
        "The interviewer's manner never changes the standard: the same answer is judged "
        "the same way in Practice and in Final Boss."
    )


def _framing(state: SessionState, now: datetime) -> str:
    used = state.time_used_s(now)
    planned = state.requested_minutes * 60
    if state.status is SessionStatus.aborted:
        return "This session didn't get going, so there is nothing to review yet."
    if state.kind == "drill":
        return "A two-minute drill on one line from your resume. Not scored — it's practice."
    if state.end_reason == "ended_by_student" and planned and used < WARM_UP_SHARE * planned:
        # EC-6.10: framed as a warm-up, not a failure.
        return "A short warm-up. Nothing here counts against you — come back for a full session."
    if not state.is_final:
        return "This interview is still in progress."
    return "Here's how each question went."


def build(state: SessionState, events: list[SessionEvent], now: datetime) -> SessionReport:
    questions: list[QuestionReport] = []
    current: QuestionReport | None = None
    final = state.is_final

    for event in sorted(events, key=lambda e: e.seq):
        p = event.payload
        if event.kind == "question.asked":
            if p.get("new_question", p.get("probe_move") is None) or current is None:
                item = p.get("item") or {}
                source = p.get("question_source") or "template"
                scored = bool(p.get("rubric_round_type")) and source in ("m05_bank", "m05_fallback")
                current = QuestionReport(
                    question=item.get("stem") or p.get("text", ""),
                    source=source,
                    scored=scored,
                    not_scored_reason=None
                    if scored
                    else NOT_SCORED.get(source, NOT_SCORED["template"]),
                    strong_answer_covers=(
                        [kp["statement"] for kp in item.get("key_points", [])]
                        or list((item.get("expects") or {}).values())
                    )
                    if final
                    else [],
                )
                questions.append(current)
            current.exchanges.append(
                Exchange(
                    role="interviewer",
                    text=p.get("text", ""),
                    move=p.get("probe_move"),
                    depth=int(p.get("probe_depth") or 0),
                )
            )
            current.depth_reached = max(current.depth_reached, int(p.get("probe_depth") or 0))
        elif event.kind == "answer.received" and current is not None:
            current.exchanges.append(Exchange(role="candidate", text=p.get("text", "")))
        elif event.kind == "probe.decided" and current is not None:
            if p.get("break_depth") is not None:
                current.break_depth = int(p["break_depth"])
            if p.get("ceiling") is not None:
                current.ceiling = int(p["ceiling"])
        elif event.kind == "hint.given" and current is not None:
            current.hints_used = int(p.get("level", current.hints_used))

    notes = list(dict.fromkeys(state.flags.degraded.values()))
    if state.kind != "drill" and state.flags.consent_id is None and state.started_at is not None:
        notes.append("This session didn't update your skill graph — consent isn't recorded yet.")
    if any(q.scored for q in questions):
        notes.append("Scores appear here once they are calibrated against human raters.")

    return SessionReport(
        session_id=str(state.session_id),
        kind=state.kind,
        mode=state.mode,
        status=state.status,
        end_reason=state.end_reason,
        started_at=state.started_at,
        ended_at=state.ended_at,
        minutes_used=round(state.time_used_s(now) / 60, 1),
        minutes_planned=state.requested_minutes,
        framing=_framing(state, now),
        questions=questions,
        notes=notes,
    )


__all__ = ["Exchange", "QuestionReport", "SessionReport", "build"]
