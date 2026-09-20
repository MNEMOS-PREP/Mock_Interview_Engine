"""Session state as a fold over the event log — spec §6.8.

``state = fold(events)``. Nothing else produces a `SessionState`, which buys
three things that Revision 1 had as three separate mechanisms:

* **the checkpoint** is this fold, cached, and a stale one is re-folded;
* **replay** (FR-6.19) is running the fold again and comparing;
* **the report survives a failed checkpoint write** (§10), because it is built
  from the same events.

`apply` is a pure function with no clock and no I/O. Every timestamp it uses is
the event's own, so folding the same events twice gives byte-identical state —
a property a test asserts, because a fold that reads `utcnow()` would make
replay a lie.

**Strict on purpose.** An event kind this file does not know raises. M06 is
the only writer of its own log; an unknown kind is a bug in this repository,
and silently ignoring it is how a resumed session quietly forgets a pause.

**What the state never holds:** an ability estimate (FR-6.25 — M05 owns the
provisional θ and forbids persisting it, and this object is exactly what gets
persisted), and the strategist's verdict band. The band is written to the
event log, which is the trace, but the fold reduces it to ladder mechanics
before anything the interviewer can read is built from this state (FR-6.15).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ai_core.timeutil import as_utc
from pydantic import BaseModel, Field

from .contracts import (
    DEPTH_CAP,
    InterviewPlan,
    Move,
    ProbeLadderState,
    SessionFlags,
    SessionStatus,
    TurnView,
)


class UnknownEvent(ValueError):
    """An event kind the fold does not handle. Always a bug in this repo."""


class InvalidTransition(ValueError):
    """An event that cannot follow the current status, e.g. an answer after the end."""


class SessionState(BaseModel):
    session_id: UUID
    candidate_id: UUID
    kind: str
    mode: str
    status: SessionStatus = SessionStatus.planned
    requested_minutes: int = 45
    jd_id: UUID | None = None
    source_module: str | None = None
    source_ref: str | None = None
    #: FR-6.23. M01's claim and probe ladder, exactly as handed over.
    drill: dict | None = None
    #: M04's pinned summary text (AC-4.13). The interviewer's cached prefix.
    profile_prefix: str = ""

    plan: InterviewPlan | None = None
    current_segment: int = 0
    #: The index the NEXT turn will take.
    next_turn_index: int = 0
    transcript: list[TurnView] = Field(default_factory=list)

    ladder: ProbeLadderState | None = None
    pending_move: Move | None = None
    #: The interviewer turn waiting for an answer, if any.
    open_turn_id: UUID | None = None
    #: The item behind the current question (`items.to_dict`). Authored
    #: content only — stem, follow-ups, key points — so a restart can carry on
    #: the ladder without asking M05 again.
    current_item: dict | None = None
    #: New questions put to the student, not counting rungs and moves.
    questions_asked: int = 0
    hint_level: int = 0
    #: FR-6.6: the shallowest depth each concept broke at in this session.
    break_depths: dict[str, int] = Field(default_factory=dict)

    flags: SessionFlags = Field(default_factory=SessionFlags)
    #: turn_id -> what M13 said about it. A STATUS, never a score: M13 owns
    #: the number and the display gate that decides who may see it, and a copy
    #: here would be the one that went stale (Rule 3).
    evaluation_status: dict[str, str] = Field(default_factory=dict)

    accrued_live_s: float = 0.0
    live_since: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    end_reason: str | None = None

    last_seq: int = 0

    # ── derived ──────────────────────────────────────────────────────────

    def time_used_s(self, now: datetime) -> float:
        """Live seconds only. A pause stops the clock (FR-6.12)."""
        running = (now - self.live_since).total_seconds() if self.live_since else 0.0
        return self.accrued_live_s + max(running, 0.0)

    def time_remaining_s(self, now: datetime) -> float:
        return max(self.requested_minutes * 60 - self.time_used_s(now), 0.0)

    @property
    def is_final(self) -> bool:
        return self.status in (SessionStatus.ended, SessionStatus.aborted)

    def turn(self, turn_id: UUID) -> TurnView | None:
        return next((t for t in self.transcript if t.turn_id == turn_id), None)

    def questions_in_segment(self, segment_index: int) -> int:
        """New questions asked in one segment — follow-up rungs are the same
        question going deeper, so they do not count against its budget."""
        return sum(
            1
            for t in self.transcript
            if t.role == "interviewer" and t.segment_index == segment_index and t.probe_move is None
        )


# ─────────────────────────────────────────────────────────────────────────
#  The reducer
# ─────────────────────────────────────────────────────────────────────────


def _stop_clock(s: SessionState, at: datetime) -> None:
    if s.live_since is not None:
        s.accrued_live_s += max((at - s.live_since).total_seconds(), 0.0)
        s.live_since = None


def _require_open(s: SessionState, kind: str) -> None:
    if s.is_final:
        raise InvalidTransition(f"{kind} after the session {s.status.value}")


def _created(_s: SessionState | None, p: dict, at: datetime) -> SessionState:
    return SessionState(
        session_id=UUID(str(p["session_id"])),
        candidate_id=UUID(str(p["candidate_id"])),
        kind=p.get("kind", "mock"),
        mode=p.get("mode", "mock"),
        requested_minutes=int(p.get("requested_minutes", 45)),
        jd_id=UUID(str(p["jd_id"])) if p.get("jd_id") else None,
        source_module=p.get("source_module"),
        source_ref=p.get("source_ref"),
        drill=p.get("drill"),
        created_at=at,
    )


def _plan_set(s: SessionState, p: dict, _at: datetime) -> None:
    _require_open(s, "plan.set")
    s.plan = InterviewPlan.model_validate(p["plan"])


def _started(s: SessionState, p: dict, at: datetime) -> None:
    if s.status is not SessionStatus.planned:
        raise InvalidTransition(f"session.started from {s.status.value}")
    s.status = SessionStatus.live
    s.started_at = at
    s.live_since = at
    s.profile_prefix = p.get("profile_prefix", "")


def _question_asked(s: SessionState, p: dict, at: datetime) -> None:
    _require_open(s, "question.asked")
    turn_id = UUID(str(p["turn_id"]))
    move = p.get("probe_move")
    if p.get("new_question", move is None):
        # A fresh question opens a fresh ladder; a rung or a clarify continues
        # the one already open.
        s.ladder = ProbeLadderState(concept_id=p.get("concept_id") or "")
        s.hint_level = 0
        s.questions_asked += 1
    if p.get("item") is not None:
        s.current_item = p["item"]
    s.transcript.append(
        TurnView(
            turn_id=turn_id,
            turn_index=int(p["turn_index"]),
            segment_index=int(p.get("segment_index", s.current_segment)),
            role="interviewer",
            text=p["text"],
            question_text=p.get("question_text") or p["text"],
            modality=p.get("modality", "verbal"),
            question_id=UUID(str(p["question_id"])) if p.get("question_id") else None,
            question_source=p.get("question_source"),
            rubric_round_type=p.get("rubric_round_type"),
            probe_depth=int(p.get("probe_depth", 0)),
            probe_move=move,
            at=at,
        )
    )
    s.open_turn_id = turn_id
    s.pending_move = None
    s.next_turn_index = max(s.next_turn_index, int(p["turn_index"]) + 1)


def _answer_received(s: SessionState, p: dict, at: datetime) -> None:
    _require_open(s, "answer.received")
    if s.status is SessionStatus.paused:
        raise InvalidTransition("answer.received while paused")
    # An answer answers the OPEN question and nothing else. This is what turns
    # two tabs submitting at once into one answer and a 409, rather than two
    # answers to one question.
    if s.open_turn_id is None or str(s.open_turn_id) != str(p.get("question_turn_id")):
        raise InvalidTransition("That question has already been answered.")
    asked = s.turn(s.open_turn_id)
    s.transcript.append(
        TurnView(
            turn_id=UUID(str(p["turn_id"])),
            turn_index=int(p["turn_index"]),
            segment_index=asked.segment_index if asked else s.current_segment,
            role="candidate",
            text=p["text"],
            modality=p.get("modality", "verbal"),
            question_id=asked.question_id if asked else None,
            question_source=asked.question_source if asked else None,
            rubric_round_type=asked.rubric_round_type if asked else None,
            probe_depth=asked.probe_depth if asked else 0,
            hint_level_used=s.hint_level,
            at=at,
        )
    )
    s.open_turn_id = None
    s.next_turn_index = max(s.next_turn_index, int(p["turn_index"]) + 1)


def _probe_decided(s: SessionState, p: dict, _at: datetime) -> None:
    """Reduce the verdict to ladder mechanics; the band itself is not kept."""
    _require_open(s, "probe.decided")
    move = Move.model_validate(p["move"])
    ladder = s.ladder
    if ladder is not None:
        ladder.moves.append(move.kind)
        if p.get("success") is True:
            ladder.consecutive_successes += 1
        elif p.get("success") is False:
            ladder.consecutive_successes = 0
        if move.is_rung and move.depth is not None:
            ladder.depth = min(move.depth, DEPTH_CAP)
        if p.get("break_depth") is not None:
            depth = int(p["break_depth"])
            ladder.break_depth = depth
            concept = ladder.concept_id
            if concept:
                s.break_depths[concept] = min(depth, s.break_depths.get(concept, depth))
        if p.get("ceiling") is not None:
            ladder.ceiling = int(p["ceiling"])
    s.pending_move = move


def _hint_given(s: SessionState, p: dict, _at: datetime) -> None:
    _require_open(s, "hint.given")
    s.hint_level = int(p["level"])


def _segment_transition(s: SessionState, p: dict, _at: datetime) -> None:
    _require_open(s, "segment.transition")
    s.current_segment = int(p["to"])
    s.ladder = None
    s.pending_move = None


def _paused(s: SessionState, _p: dict, at: datetime) -> None:
    if s.status is not SessionStatus.live:
        raise InvalidTransition(f"session.paused from {s.status.value}")
    _stop_clock(s, at)
    s.status = SessionStatus.paused
    s.flags.paused_at = at
    s.flags.pause_used = True


def _resumed(s: SessionState, _p: dict, at: datetime) -> None:
    if s.status is not SessionStatus.paused:
        raise InvalidTransition(f"session.resumed from {s.status.value}")
    s.status = SessionStatus.live
    s.flags.paused_at = None
    s.live_since = at


def _reconnected(s: SessionState, _p: dict, _at: datetime) -> None:
    s.flags.reconnect_count += 1


def _closing_line(s: SessionState, p: dict, at: datetime) -> None:
    if p.get("closing_text") and p.get("closing_turn_id"):
        s.transcript.append(
            TurnView(
                turn_id=UUID(str(p["closing_turn_id"])),
                turn_index=int(p.get("closing_turn_index", s.next_turn_index)),
                segment_index=s.current_segment,
                role="interviewer",
                text=p["closing_text"],
                at=at,
            )
        )
        s.next_turn_index += 1


def _ended(s: SessionState, p: dict, at: datetime) -> None:
    if s.is_final:
        raise InvalidTransition(f"session.ended after {s.status.value}")
    _stop_clock(s, at)
    s.status = SessionStatus.ended
    s.ended_at = at
    s.end_reason = p.get("reason", "completed")
    s.open_turn_id = None
    _closing_line(s, p, at)


def _aborted(s: SessionState, p: dict, at: datetime) -> None:
    if s.is_final:
        raise InvalidTransition(f"session.aborted after {s.status.value}")
    _stop_clock(s, at)
    s.status = SessionStatus.aborted
    s.ended_at = at
    s.end_reason = p.get("reason", "aborted")
    s.open_turn_id = None


def _degraded(s: SessionState, p: dict, _at: datetime) -> None:
    s.flags.degraded[p["module"]] = p["sentence"]


def _consent(s: SessionState, p: dict, _at: datetime) -> None:
    s.flags.consent_id = UUID(str(p["consent_id"])) if p.get("consent_id") else None


def _evaluation(s: SessionState, p: dict, _at: datetime) -> None:
    s.flags.evaluation_pending = max(s.flags.evaluation_pending + int(p.get("delta", 0)), 0)


def _evaluated(s: SessionState, p: dict, _at: datetime) -> None:
    s.flags.evaluation_pending = max(s.flags.evaluation_pending - 1, 0)
    s.evaluation_status[str(p["turn_id"])] = str(p.get("status", "unknown"))


_REDUCERS = {
    "plan.set": _plan_set,
    "session.started": _started,
    "question.asked": _question_asked,
    "answer.received": _answer_received,
    "probe.decided": _probe_decided,
    "hint.given": _hint_given,
    "segment.transition": _segment_transition,
    "session.paused": _paused,
    "session.resumed": _resumed,
    "session.reconnected": _reconnected,
    "session.ended": _ended,
    "session.aborted": _aborted,
    "upstream.degraded": _degraded,
    "consent.resolved": _consent,
    "evaluation.queued": _evaluation,
    "evaluation.completed": _evaluated,
}

EVENT_KINDS = frozenset({"session.created", *_REDUCERS})


def apply(
    state: SessionState | None, kind: str, payload: dict, at: datetime, seq: int
) -> SessionState:
    """One event. Returns a NEW state; the input is never mutated."""
    # SQLite hands timestamps back naive and Postgres aware. Normalise here so
    # a fold never mixes the two and `time_used_s(utcnow())` never raises.
    at = as_utc(at)
    if kind == "session.created":
        if state is not None:
            raise InvalidTransition("session.created on an existing session")
        out = _created(None, payload, at)
    else:
        if state is None:
            raise InvalidTransition(f"{kind} before session.created")
        reducer = _REDUCERS.get(kind)
        if reducer is None:
            raise UnknownEvent(kind)
        out = state.model_copy(deep=True)
        reducer(out, payload, at)
    out.last_seq = seq
    return out


def fold(events, start: SessionState | None = None) -> SessionState:
    """Fold `(kind, payload, at, seq)`-shaped rows, in `seq` order."""
    state = start
    for event in sorted(events, key=lambda e: e.seq):
        if start is not None and event.seq <= start.last_seq:
            continue
        state = apply(state, event.kind, event.payload, event.at, event.seq)
    if state is None:
        raise InvalidTransition("no events")
    return state


__all__ = [
    "EVENT_KINDS",
    "InvalidTransition",
    "SessionState",
    "UnknownEvent",
    "apply",
    "fold",
]
