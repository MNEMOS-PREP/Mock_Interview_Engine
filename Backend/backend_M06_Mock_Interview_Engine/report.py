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

from .contracts import M05_OWNED, SessionStatus
from .items import expected_statements
from .models import SessionEvent
from .modes import mode_config
from .personas import persona
from .state import SessionState

#: §10 "Everything fails": what was still queued when the session failed.
VOIDED = "Not scored — the session failed on our side, so it doesn't count."
#: EC-6.1: the student moved on after a silence, so there was no answer.
MOVED_ON = "We moved on from this one after a pause, so there was nothing to score."

NOT_SCORED = {
    "m01_probe": "Practice drill — drills are not scored yet.",
    "local_fallback": (
        "Asked from the backup set while the question bank was offline, so it was not scored."
    ),
    "template": "Not a scored question.",
}

WARM_UP_SHARE = 0.25

#: Consent lives in M04, so when M04 is absent its own degradation sentence
#: already tells the student the session will not count. See `notes` below.
CONSENT_OWNER = "M04"


class Exchange(BaseModel):
    role: str
    text: str
    move: str | None = None
    depth: int = 0
    #: §15.4: part of a Practice retry — shown, and never the scored attempt.
    retry: bool = False


class Feedback(BaseModel):
    """M13's words about an answer, per dimension — never its numbers (§2.2;
    M13's display gate holds those until they agree with human raters)."""

    dimension: str
    reasoning: str = ""
    #: Key points the answer did not reach.
    missing: list[str] = Field(default_factory=list)
    #: The student's own sentences that counted, verified against the text.
    quotes: list[str] = Field(default_factory=list)


class QuestionReport(BaseModel):
    question: str
    source: str
    scored: bool
    not_scored_reason: str | None = None
    #: `not_scored` · `queued` (with M13) · `scored` — never a number. M13 owns
    #: the number and the gate that decides whether anyone may see it, and
    #: today that gate is closed everywhere because no calibration is fitted.
    scoring_status: str = "not_scored"
    exchanges: list[Exchange] = Field(default_factory=list)
    depth_reached: int = 0
    #: The rung where the reasoning stopped holding. None means it never did.
    break_depth: int | None = None
    #: Two clears in a row at depth ≥ 4 — the student was stretched and held.
    ceiling: int | None = None
    hints_used: int = 0
    #: What a strong answer covers. Shown only once the session is over.
    strong_answer_covers: list[str] = Field(default_factory=list)
    #: Who asked it (FR-6.3) — a panel is several people, and the notes say
    #: which of them this was.
    asked_by: str | None = None
    #: §15.4: the student took a Practice retry on this one. The first
    #: attempt is the one scored; the retry is recorded beside it.
    retried: bool = False
    #: EC-6.1: after a silence, the interviewer offered to move on and the
    #: student took it. Not a break and not a fail — nothing was answered.
    moved_on: bool = False
    #: What M13 said about the answer, once it has scored it and the session
    #: is over. Mid-session it would be a live verdict (§2.2).
    feedback: list[Feedback] = Field(default_factory=list)
    #: The concept the item measures, so the notes can offer "practise this
    #: topic again" as a focused interview rather than a generic one.
    concept_id: str | None = None
    #: The item's own name for its topic, when it has one.
    topic: str | None = None
    #: The first answer's turn — what M13's evidence page (`/turns/{id}`)
    #: is keyed on, so "how was this marked?" is one link.
    turn_id: str | None = None


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
    #: FR-6.21: what the student asked the interviewer, in their words.
    #: Recorded, not scored — there is no rubric for a question yet.
    your_questions: list[str] = Field(default_factory=list)
    #: §6.4: "I changed the plan here because…" — each re-plan's reason, in
    #: full, now that the session is over and it can no longer be a tell.
    plan_changes: list[str] = Field(default_factory=list)
    notes: list[str]
    #: Spec §6.7 tells M06 to say this, "so students don't think Practice mode
    #: inflates their score" — which means it has to be exactly right, not
    #: reassuring. Two facts, and the second one was missing: the STANDARD is
    #: identical (same rubric, same blind payload, same model tier — gated by
    #: `test_fairness.py`), and the PRECISION is not, because Practice runs
    #: M13's `n1_practice`: one evaluator rather than three. Saying only the
    #: first half lets a student read a Practice result as a mock-grade one.
    persona_note: str = (
        "The interviewer's manner never changes the standard: a friendly interviewer and a "
        "bar-raiser judge the same answer against the same rubric. Practice checks each "
        "answer once rather than three times, so it is less precise — not more generous."
    )


def _framing(state: SessionState, now: datetime) -> str:
    used = state.time_used_s(now)
    planned = state.requested_minutes * 60
    if state.end_reason == "system_failure":
        # §10 "Everything fails": the honest version, said once.
        return (
            "This one's on us — something on our side stopped working, so this session "
            "doesn't count. Here's what we got through before it did."
        )
    if state.status is SessionStatus.aborted:
        return "This session didn't get going, so there is nothing to review yet."
    if state.end_reason == "conduct":
        # EC-6.4. Neutral: it says what happened, not what the student is.
        return "This session ended early. Here's what was covered before it did."
    if state.kind == "drill":
        return "A two-minute drill on one line from your resume. Not scored — it's practice."
    if state.end_reason == "ended_by_student" and planned and used < WARM_UP_SHARE * planned:
        # EC-6.10: framed as a warm-up, not a failure.
        return "A short warm-up. Nothing here counts against you — come back for a full session."
    if not state.is_final:
        return "This interview is still in progress."
    return "Here's how each question went."


def _asked_by(state: SessionState, segment_index: int | None) -> str | None:
    if state.plan is None or segment_index is None:
        return None
    segment = next((s for s in state.plan.segments if s.index == segment_index), None)
    if segment is None:
        return None
    who = persona(segment.persona_id)
    return f"{who.name}, {who.title}"


def build(state: SessionState, events: list[SessionEvent], now: datetime) -> SessionReport:
    questions: list[QuestionReport] = []
    current: QuestionReport | None = None
    final = state.is_final

    by_turn: dict[str, QuestionReport] = {}
    for event in sorted(events, key=lambda e: e.seq):
        p = event.payload
        if event.kind == "evaluation.completed":
            entry = by_turn.get(str(p.get("turn_id")))
            if entry is not None and final:
                entry.feedback.extend(Feedback.model_validate(f) for f in p.get("feedback") or [])
            continue
        if event.kind == "question.asked" and p.get("question_source") == "closing":
            # FR-6.21: the closing is not one of our questions. Its answers
            # are the student's own, and are listed on their own below.
            current = None
            continue
        if event.kind == "question.asked" and p.get("retry") and current is not None:
            # §15.4: the same question again, on the same entry — the notes
            # show both attempts together, and the first stays the scored one.
            current.retried = True
            current.exchanges.append(
                Exchange(role="interviewer", text=p.get("text", ""), retry=True)
            )
            continue
        if event.kind == "question.asked":
            if p.get("new_question", p.get("probe_move") is None) or current is None:
                item = p.get("item") or {}
                source = p.get("question_source") or "template"
                scored = bool(p.get("rubric_round_type")) and source in M05_OWNED
                current = QuestionReport(
                    question=item.get("stem") or p.get("text", ""),
                    source=source,
                    scored=scored,
                    not_scored_reason=None
                    if scored
                    else NOT_SCORED.get(source, NOT_SCORED["template"]),
                    strong_answer_covers=(
                        [kp["statement"] for kp in item.get("key_points", [])]
                        or expected_statements(item.get("expects"))
                    )
                    if final
                    else [],
                    asked_by=_asked_by(state, p.get("segment_index")),
                    concept_id=item.get("concept_id"),
                    topic=item.get("label"),
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
            by_turn[str(p.get("turn_id"))] = current
            retry_turn = state.turn_retry(p.get("turn_id"))
            if current.turn_id is None and not retry_turn and p.get("turn_id"):
                current.turn_id = str(p["turn_id"])
            current.exchanges.append(
                Exchange(role="candidate", text=p.get("text", ""), retry=retry_turn)
            )
            if current.scored and not retry_turn:
                # Queued the moment the turn was written; `scored` once M13 has
                # accepted it. Either way, no number appears here.
                current.scoring_status = state.evaluation_status.get(
                    str(p.get("turn_id")), "queued"
                )
        elif event.kind == "probe.decided" and current is not None:
            if p.get("break_depth") is not None:
                current.break_depth = int(p["break_depth"])
            if p.get("ceiling") is not None:
                current.ceiling = int(p["ceiling"])
        elif event.kind == "hint.given" and current is not None:
            current.hints_used = int(p.get("level", current.hints_used))
        elif event.kind == "idle.moved_on" and current is not None and not p.get("closing"):
            current.moved_on = True
            if not any(e.role == "candidate" for e in current.exchanges):
                current.scored = False
                current.scoring_status = "not_scored"
                current.not_scored_reason = MOVED_ON

    if state.end_reason == "system_failure":
        for question in questions:
            if question.scoring_status != "scored":
                question.scored = False
                question.scoring_status = "not_scored"
                question.not_scored_reason = VOIDED
    notes = list(dict.fromkeys(state.flags.degraded.values()))
    # A student is told a consequence once. M04 owns consent, so when M04 is
    # absent its degradation sentence is already the whole story; adding this
    # one underneath reads like a second, separate problem.
    if (
        state.kind != "drill"
        and state.flags.consent_id is None
        and state.started_at is not None
        and CONSENT_OWNER not in state.flags.degraded
    ):
        notes.append("This session didn't update your skill graph — consent isn't recorded yet.")
    if any(q.scoring_status == "queued" for q in questions):
        notes.append("Some answers are still with the evaluator — check back in a minute.")
    if any(q.scored for q in questions):
        notes.append(
            "Each answer's band is the share of a strong answer's key points it covered. "
            "Numerical scores appear once they are calibrated against human raters."
        )
    if any(q.retried for q in questions):
        notes.append("Where you took another go, the first attempt is the one that was scored.")
    if state.flags.inputs_flagged:
        # EC-6.6. Said once, plainly: part of an answer read as instructions
        # to the system, so it was set aside rather than judged.
        notes.append(
            "Part of one of your answers read as instructions to the system rather than an "
            "answer, so that part was set aside and the rest was judged as usual."
        )
    mode_note = mode_config(state.mode).persona_note
    if mode_note and state.kind != "drill":
        notes.append(mode_note)
    if state.closing_questions:
        notes.append(
            "Your questions for the interviewer are in these notes but not scored — there is "
            "no rubric for a question yet, and the real panel is who can answer them."
        )
    plan_changes = (
        [r.student_sentence for r in state.plan.replans] if state.plan is not None and final else []
    )

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
        your_questions=list(state.closing_questions),
        plan_changes=plan_changes,
        notes=notes,
    )


__all__ = ["Exchange", "QuestionReport", "SessionReport", "build"]
