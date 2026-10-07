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

from datetime import datetime, timedelta
from uuid import UUID

from ai_core.timeutil import as_utc
from pydantic import BaseModel, Field

from . import degrade
from .contracts import (
    DEPTH_CAP,
    InterviewPlan,
    Move,
    ProbeLadderState,
    SessionFlags,
    SessionStatus,
    SpokenPart,
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
    #: Concepts the student asked to practise ("Practise Recursion" on Today,
    #: from M04's bottleneck). Planned as one focused segment when there is
    #: no job description; the label is for display only.
    focus_concepts: list[str] = Field(default_factory=list)
    focus_label: str | None = None
    #: What the student chose on the setup page (2026-10-07): the track (a
    #: round type) or None for a mixed interview, and whether — and from
    #: which resume — to ask about their own work.
    track: str | None = None
    include_resume: bool = False
    resume_id: UUID | None = None
    #: M04's pinned summary text (AC-4.13). The interviewer's cached prefix.
    profile_prefix: str = ""

    plan: InterviewPlan | None = None
    current_segment: int = 0
    #: The bridge line owed to the student, set by a segment transition and
    #: cleared by the question that carries it. Held on the state rather than
    #: said immediately because in text mode nothing is "said" until the next
    #: question is asked — a bridge with no question after it is a page that
    #: changed for no reason.
    pending_bridge: str | None = None
    #: §6.6's rolling note, regenerated every four turns. It REPLACES the
    #: turns that fall out of the last-six window rather than being added to
    #: them — that is what keeps the context a constant size (AC-6.10).
    round_summary: str = ""
    #: `next_turn_index` when the summary was written, so "four turns since"
    #: is arithmetic rather than a counter something has to remember to reset.
    summary_at_turn: int = 0
    #: §6.7: the rounds that have had their one "let's keep it moving".
    nudged_segments: list[int] = Field(default_factory=list)
    #: §15.4, Practice: the question a retry was offered for, while the
    #: student decides. Nothing is selected until they do.
    retry_offer: dict | None = None
    #: Question turn ids already retried — one retry each.
    retried: list[str] = Field(default_factory=list)
    #: True while the ladder open is a retry's, so its rungs and answers are
    #: recorded as the retry they are and never sent to be scored.
    ladder_is_retry: bool = False
    #: The student has chosen to move on and nothing has been asked since —
    #: what `continue_session` reads to know a question is owed.
    awaiting_next: bool = False
    #: §6.9's checkpoints already announced (70, 90).
    time_warnings: list[int] = Field(default_factory=list)
    #: Live seconds used when the current segment began — what a round's
    #: own clock (EC-6.9) is measured from.
    segment_started_used_s: float = 0.0
    #: §2.3's pace line, owed with the next question like a bridge.
    pending_pace_line: str | None = None
    #: §6.9's ahead-of-schedule rule: the segment from which one extra
    #: follow-up is allowed, or None until the 70% check finds us ahead.
    extra_depth_segment: int | None = None
    #: FR-6.21: how many times the closing has asked "anything for me?".
    closing_asked: int = 0
    #: FR-6.21: what the student asked, in their words. Recorded, not scored.
    closing_questions: list[str] = Field(default_factory=list)
    #: EC-6.1, for the line now open: prompts given for silence (1, 2), the
    #: last one said, and whether the third — the offer to move on — has
    #: been made. Never a turn: the answer box keeps posting to the question.
    idle_prompts: int = 0
    idle_line: str | None = None
    idle_offer: bool = False
    #: Skips (2026-10-07). A question skipped at number N is replaced by a
    #: different one at the same number; skip that one too and it is left,
    #: counted as not answered. `skips_at` is how many skips each number has
    #: had; `pending_skip` is what the next question's lead says about the
    #: last one ("replaced" or "left"), cleared when it is asked.
    skips_at: dict[int, int] = Field(default_factory=dict)
    pending_skip: str | None = None
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

    def turn_retry(self, turn_id: object) -> bool:
        """Whether the turn with this id (any spelling) was part of a retry."""
        found = next((t for t in self.transcript if str(t.turn_id) == str(turn_id)), None)
        return bool(found and found.retry)

    def questions_in_segment(self, segment_index: int) -> int:
        """New questions asked in one segment — follow-up rungs are the same
        question going deeper, and a retry is the same question again, so
        neither counts against its budget. Neither does a line that asked
        nothing (a retry offer, a closing line): it has no source. Nor does a
        question skipped and replaced: the replacement takes its place."""
        return sum(
            1
            for t in self.transcript
            if t.role == "interviewer"
            and t.segment_index == segment_index
            and t.probe_move is None
            and t.question_source is not None
            and not t.retry
            and not t.replaced
        )

    @property
    def opened(self) -> bool:
        """Whether the opening has been said: any question asked, including
        one since skipped and replaced. Not `questions_asked == 0` — a
        replaced question gives its number back, and the first one's
        replacement must not have the panel introduce itself again."""
        return any(
            t.role == "interviewer" and t.question_source is not None for t in self.transcript
        )

    @property
    def skips_left(self) -> int:
        """Questions skipped twice: left, and counted as not answered."""
        return sum(
            1 for t in self.transcript if t.skipped and not t.replaced and not t.follow_up_skip
        )

    def open_question_turn(self) -> TurnView | None:
        """The question the current ladder belongs to: the last NEW question
        asked, ignoring the rungs, hints and redirects that followed it."""
        return next(
            (
                t
                for t in reversed(self.transcript)
                if t.role == "interviewer"
                and t.probe_move is None
                and t.question_source is not None
            ),
            None,
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
        focus_concepts=[str(c) for c in p.get("focus_concepts") or []],
        focus_label=p.get("focus_label"),
        track=p.get("track"),
        # Sessions created before 2026-10-07 always read the resume.
        include_resume=bool(p.get("include_resume", "track" not in p)),
        resume_id=UUID(str(p["resume_id"])) if p.get("resume_id") else None,
        flags=SessionFlags(pauses_allowed=pause_allowance(int(p.get("requested_minutes", 45)))),
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


def _persona_at(s: SessionState, segment_index: int) -> str | None:
    """Who runs a segment — the speaker of a line whose event predates
    `speaker_id` (2026-10-06), and of every line one person said whole."""
    if s.plan is None:
        return None
    found = next((seg for seg in s.plan.segments if seg.index == segment_index), None)
    return found.persona_id if found is not None else None


def _parts(p: dict, key: str = "parts") -> list[SpokenPart]:
    return [SpokenPart.model_validate(part) for part in p.get(key) or []]


def _question_asked(s: SessionState, p: dict, at: datetime) -> None:
    _require_open(s, "question.asked")
    turn_id = UUID(str(p["turn_id"]))
    move = p.get("probe_move")
    retry = bool(p.get("retry"))
    closing = p.get("question_source") == "closing"
    if closing:
        # FR-6.21: the closing asks, but it asks the student to ask. It is not
        # a question of ours, and it does not count as one.
        s.closing_asked += 1
    if p.get("new_question", move is None) and not closing:
        # A fresh question opens a fresh ladder; a rung or a clarify continues
        # the one already open.
        s.ladder = ProbeLadderState(concept_id=p.get("concept_id") or "")
        s.hint_level = 0
        s.ladder_is_retry = retry
        if retry:
            # §15.4: the same question again. It does not count as a new
            # one against the budget, and it can be retried only once.
            s.retry_offer = None
            if p.get("retry_of") and str(p["retry_of"]) not in s.retried:
                s.retried.append(str(p["retry_of"]))
        else:
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
            concept_id=str(p.get("concept_id") or ""),
            probe_depth=int(p.get("probe_depth", 0)),
            probe_move=move,
            retry=retry or s.ladder_is_retry,
            speaker_id=p.get("speaker_id")
            or _persona_at(s, int(p.get("segment_index", s.current_segment))),
            parts=_parts(p),
            at=at,
        )
    )
    s.open_turn_id = turn_id
    s.pending_move = None
    s.awaiting_next = False
    if not closing:
        s.pending_skip = None
    s.flags.step_failures = 0
    _clear_idle(s)
    # Said with this question, like the bridge, so not owed twice.
    s.pending_pace_line = None
    if p.get("nudged") and s.current_segment not in s.nudged_segments:
        s.nudged_segments.append(s.current_segment)
    # Said with this question, so it is not owed twice.
    s.pending_bridge = None
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
            retry=asked.retry if asked else False,
            asr_confidence=(p.get("asr") or {}).get("mean_confidence"),
            unsure=[tuple(r) for r in (p.get("asr") or {}).get("unsure") or []],
            language=(p.get("asr") or {}).get("language"),
            prefill=p.get("prefill"),
            at=at,
        )
    )
    s.open_turn_id = None
    _clear_idle(s)
    s.next_turn_index = max(s.next_turn_index, int(p["turn_index"]) + 1)


def _clear_idle(s: SessionState) -> None:
    s.idle_prompts = 0
    s.idle_line = None
    s.idle_offer = False


def _idle_prompted(s: SessionState, p: dict, _at: datetime) -> None:
    """EC-6.1: one gentle prompt, a second, then the offer to move on —
    and never a fourth. The line is shown beside the question, not asked."""
    _require_open(s, "idle.prompted")
    if s.open_turn_id is None or str(s.open_turn_id) != str(p.get("for")):
        raise InvalidTransition("That question has already been answered.")
    if s.idle_offer:
        raise InvalidTransition("The offer to move on has already been made.")
    s.idle_prompts = int(p["n"])
    s.idle_line = str(p["line"])
    s.idle_offer = bool(p.get("offer"))


def _idle_moved_on(s: SessionState, p: dict, _at: datetime) -> None:
    """EC-6.1's third step, taken: the question is left unanswered and the
    next one is owed. §6.4 reads these as silences."""
    _require_open(s, "idle.moved_on")
    if not s.idle_offer or s.open_turn_id is None or str(s.open_turn_id) != str(p.get("for")):
        raise InvalidTransition("There is no offer to move on.")
    s.open_turn_id = None
    s.pending_move = None
    s.awaiting_next = True
    _clear_idle(s)


def _question_skipped(s: SessionState, p: dict, _at: datetime) -> None:
    """The student skipped the open question (2026-10-07).

    At its opening, the first skip at this question number REPLACES it: the
    number is given back, so the next question asked takes it and the
    segment's budget does not count the skipped one. A second skip at the
    same number LEAVES it: it counts, as not answered. Past the opening —
    a follow-up open, the question already answered once — a skip moves on
    and the question counts as asked, with nothing against it.
    """
    _require_open(s, "question.skipped")
    if s.open_turn_id is None or str(s.open_turn_id) != str(p.get("for")):
        raise InvalidTransition("That question has already moved on.")
    question = next(
        (t for t in s.transcript if str(t.turn_id) == str(p.get("question_turn"))), None
    )
    number = int(p.get("number", s.questions_asked))
    follow_up = bool(p.get("follow_up"))
    replaced = bool(p.get("replaced"))
    if question is not None:
        question.skipped = True
        question.replaced = replaced
        question.follow_up_skip = follow_up
    if not follow_up:
        s.skips_at[number] = s.skips_at.get(number, 0) + 1
    if replaced:
        # The number is given back: the replacement is asked as this one.
        s.questions_asked = max(s.questions_asked - 1, 0)
    s.pending_skip = "replaced" if replaced else ("left" if not follow_up else None)
    s.open_turn_id = None
    s.pending_move = None
    s.awaiting_next = True
    s.ladder = None
    s.hint_level = 0
    _clear_idle(s)


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
    if p.get("conduct"):
        # EC-6.4: counted, because the second one ends the session.
        s.flags.conduct_warnings += 1
    if (p.get("screen") or {}).get("injection"):
        s.flags.inputs_flagged += 1
    s.pending_move = move


def _retry_offered(s: SessionState, p: dict, at: datetime) -> None:
    """§15.4: the exit line and the offer, said; nothing open until a choice."""
    _require_open(s, "retry.offered")
    s.transcript.append(
        TurnView(
            turn_id=UUID(str(p["turn_id"])),
            turn_index=int(p["turn_index"]),
            segment_index=int(p.get("segment_index", s.current_segment)),
            role="interviewer",
            text=p["text"],
            speaker_id=p.get("speaker_id")
            or _persona_at(s, int(p.get("segment_index", s.current_segment))),
            at=at,
        )
    )
    s.retry_offer = {"of": str(p["of"]), "item": p.get("item")}
    s.open_turn_id = None
    s.pending_move = None
    s.next_turn_index = max(s.next_turn_index, int(p["turn_index"]) + 1)


def _retry_declined(s: SessionState, _p: dict, _at: datetime) -> None:
    _require_open(s, "retry.declined")
    if s.retry_offer is None:
        raise InvalidTransition("There is no retry on offer.")
    s.retry_offer = None
    s.awaiting_next = True


def _hint_given(s: SessionState, p: dict, _at: datetime) -> None:
    _require_open(s, "hint.given")
    s.hint_level = int(p["level"])


def _segment_transition(s: SessionState, p: dict, _at: datetime) -> None:
    _require_open(s, "segment.transition")
    s.current_segment = int(p["to"])
    # The round's own clock starts here (EC-6.9). Recorded by the writer,
    # because the fold has no clock of its own.
    s.segment_started_used_s = float(p.get("used_s", s.segment_started_used_s))
    s.ladder = None
    s.pending_move = None
    s.pending_bridge = p.get("line") or None
    # A new round summarises itself. Carrying the last round's note across
    # would have the interviewer open by referring to a topic it has left.
    s.round_summary = ""
    s.summary_at_turn = s.next_turn_index


def _plan_changed(s: SessionState, p: dict, _at: datetime) -> None:
    """FR-6.4: the new plan, with its `Replan` appended — the before stays."""
    _require_open(s, "plan.changed")
    s.plan = InterviewPlan.model_validate(p["plan"])
    _relevel(s)


def _time_warning(s: SessionState, p: dict, _at: datetime) -> None:
    mark = int(p["at"])
    if mark not in s.time_warnings:
        s.time_warnings.append(mark)
    if p.get("line"):
        s.pending_pace_line = str(p["line"])
    if p.get("extra_depth"):
        s.extra_depth_segment = s.current_segment


def _closing_question(s: SessionState, p: dict, _at: datetime) -> None:
    """FR-6.21: recorded in the student's own words."""
    text = str(p.get("text") or "").strip()
    if text:
        s.closing_questions.append(text)


def pause_allowance(requested_minutes: int) -> int:
    """One pause per 15 planned minutes, at least one (FR-6.12, revised)."""
    return max(1, requested_minutes // 15)


def _paused(s: SessionState, _p: dict, at: datetime) -> None:
    if s.status is not SessionStatus.live:
        raise InvalidTransition(f"session.paused from {s.status.value}")
    _stop_clock(s, at)
    s.status = SessionStatus.paused
    s.flags.paused_at = at
    s.flags.pauses_used += 1
    s.flags.pause_used = s.flags.pauses_used >= s.flags.pauses_allowed


def _resumed(s: SessionState, _p: dict, at: datetime) -> None:
    if s.status is not SessionStatus.paused:
        raise InvalidTransition(f"session.resumed from {s.status.value}")
    s.status = SessionStatus.live
    s.flags.paused_at = None
    s.live_since = at


def _connection_lost(s: SessionState, p: dict, at: datetime) -> None:
    """§8: "Disconnected — timer paused". Not a pause: the student's one
    pause (FR-6.12) is theirs to spend, and losing a connection is not
    spending it."""
    if s.status is not SessionStatus.live:
        raise InvalidTransition(f"connection.lost from {s.status.value}")
    if s.flags.away_since is not None:
        raise InvalidTransition("connection.lost while already away")
    _stop_clock(s, at)
    s.flags.away_since = at
    s.flags.away_reason = p.get("reason")
    if s.flags.away_reason == "interruption":
        s.flags.interruptions += 1


def _connection_resumed(s: SessionState, p: dict, at: datetime) -> None:
    """§6.8: back, and the clock restarts after the grace — "a 30-second
    grace before the timer restarts". A return that is an action (an
    answer, a hint) has no grace: the student is already going."""
    if s.flags.away_since is None:
        raise InvalidTransition("connection.resumed while not away")
    s.flags.away_since = None
    # A call taking the microphone is not a connection that dropped (§6.8's
    # "> 2 reconnects" is about the network), however the student comes back.
    if s.flags.away_reason != "interruption":
        s.flags.reconnect_count += 1
    s.flags.away_reason = None
    if s.status is SessionStatus.live:
        s.live_since = at + timedelta(seconds=float(p.get("grace_s") or 0.0))


def _closing_line(s: SessionState, p: dict, at: datetime) -> None:
    if p.get("closing_text") and p.get("closing_turn_id"):
        s.transcript.append(
            TurnView(
                turn_id=UUID(str(p["closing_turn_id"])),
                turn_index=int(p.get("closing_turn_index", s.next_turn_index)),
                segment_index=s.current_segment,
                role="interviewer",
                text=p["closing_text"],
                speaker_id=p.get("closing_speaker_id") or _persona_at(s, s.current_segment),
                parts=_parts(p, "closing_parts"),
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
    s.flags.away_since = None
    _clear_idle(s)
    _closing_line(s, p, at)


def _aborted(s: SessionState, p: dict, at: datetime) -> None:
    if s.is_final:
        raise InvalidTransition(f"session.aborted after {s.status.value}")
    _stop_clock(s, at)
    s.status = SessionStatus.aborted
    s.ended_at = at
    s.end_reason = p.get("reason", "aborted")
    s.open_turn_id = None
    s.flags.away_since = None
    _clear_idle(s)
    _closing_line(s, p, at)


def _summary_written(s: SessionState, p: dict, _at: datetime) -> None:
    s.round_summary = str(p.get("text") or "")
    s.summary_at_turn = int(p.get("at_turn", s.next_turn_index))


def _degraded(s: SessionState, p: dict, _at: datetime) -> None:
    s.flags.degraded[p["module"]] = p["sentence"]
    _relevel(s)


def _relevel(s: SessionState) -> None:
    """§10's rung, from what the session has seen (`degrade.level`)."""
    wrapped = s.plan is not None and any(r.trigger == "degraded" for r in s.plan.replans)
    s.flags.degradation_level = degrade.level(
        model_failures=s.flags.model_failures,
        upstream_degraded=bool(s.flags.degraded),
        wrapped=wrapped,
    )


def _model_health(s: SessionState, p: dict, at: datetime) -> None:
    """One turn's model calls, as one fact: they worked, or one failed."""
    s.flags.model_tried_at = at
    s.flags.model_failures = 0 if p.get("ok") else s.flags.model_failures + 1
    _relevel(s)


def _noted(s: SessionState, _p: dict, _at: datetime) -> None:
    _require_open(s, "a note on the log")


def _turn_heard(s: SessionState, p: dict, _at: datetime) -> None:
    """M11's FR-11.9: where the student came in over an interviewer line.
    An annotation, so it folds in any status — a cut can land just after the
    session ended — and onto a turn the log does not know, nothing."""
    turn = s.turn(UUID(str(p["turn_id"])))
    if turn is None or turn.role != "interviewer":
        return
    turn.heard_part = int(p.get("part_index") or 0)
    turn.heard = max(0.0, min(1.0, float(p.get("heard", 1.0))))


def _step_failed(s: SessionState, _p: dict, _at: datetime) -> None:
    _require_open(s, "step.failed")
    s.flags.step_failures += 1


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
    "retry.offered": _retry_offered,
    "retry.declined": _retry_declined,
    "plan.changed": _plan_changed,
    "time.warning": _time_warning,
    "closing.question": _closing_question,
    "segment.transition": _segment_transition,
    "session.paused": _paused,
    "session.resumed": _resumed,
    "connection.lost": _connection_lost,
    "connection.resumed": _connection_resumed,
    "idle.prompted": _idle_prompted,
    "idle.moved_on": _idle_moved_on,
    "question.skipped": _question_skipped,
    "session.ended": _ended,
    "session.aborted": _aborted,
    "upstream.degraded": _degraded,
    "model.health": _model_health,
    "step.failed": _step_failed,
    # §7's repeat and ⚑ are on the log for the trace; neither changes the
    # interview, so neither has anything to fold.
    "question.repeated": _noted,
    "question.flagged": _noted,
    "turn.heard": _turn_heard,
    "consent.resolved": _consent,
    "evaluation.queued": _evaluation,
    "evaluation.completed": _evaluated,
    "summary.written": _summary_written,
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
