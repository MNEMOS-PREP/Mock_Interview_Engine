"""The engine — turns a request into events (spec §6.1, §6.2, FR-6.23).

Routes call this; this calls the orchestration step and `store.record()`.
Nothing else writes a session.

**Every method ends in `continue_session()`,** which looks at the log and does
whatever the session is owed: the opening question, the step for an answer
that has no decision yet, the utterance for a decision that has no question
yet. A request that crashed half-way is finished by the next request that
touches the session — the idempotency keys make the parts already written
no-ops (AC-6.16). So `POST /start` on a live session is also "carry on".

**The provisional θ lives in `ThetaCache`, in process memory, and nowhere
else** (FR-6.25). It is handed to M05 on each selection and updated from each
observation. A restart loses it; the session re-seeds M05 from M04 and carries
on, having lost a few steps of an estimate it was never entitled to keep.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ai_core.timeutil import utcnow
from ai_core.versions import VersionStamp
from sqlmodel import Session, select

from . import PROMPT_VERSION, outbox, store
from .adapters import Upstreams, UpstreamUnavailable
from .agents import Interviewer, ProbeStrategist
from .broker import TokenBroker, broker
from .contracts import InterviewPlan, Move, PlannedSegment, SessionKind, SessionStatus
from .items import Item, from_dict, from_drill, from_m05, to_dict
from .ladder import LadderConfig, Outcome
from .llm import LLM, LLMResult, get_llm
from .models import InterviewSession, LLMCall, SessionEvent
from .orchestration import Deps, Selected, StepInput, StepResult, build, enabled, run_step
from .phrasebook import lines
from .state import InvalidTransition, SessionState

log = logging.getLogger("uvicorn.error")

#: M05's rubric vocabulary, and the only round type its bank is authored for
#: today. Day 5 replaces this with plan-time availability over M02's plan;
#: until then it is the Rule-2 fallback, used only when M13 names nothing.
DEFAULT_ROUND_TYPE = "dsa_verbal"

#: Spec §6.5 prices a verbal question at ~3.5 minutes; the closing takes one.
SECONDS_PER_VERBAL_QUESTION = 210
CLOSING_SECONDS = 60

DRILL_MINUTES = 2
MAX_ANSWER_CHARS = 8000


class SessionNotFound(Exception):
    pass


class AnswerRejected(Exception):
    """A 409: the question is not open, or the session is not live."""


# ─────────────────────────────────────────────────────────────────────────
#  The provisional θ — memory only
# ─────────────────────────────────────────────────────────────────────────


class ThetaCache:
    def __init__(self) -> None:
        self._values: dict[uuid.UUID, dict[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: uuid.UUID) -> dict[str, float]:
        with self._lock:
            return dict(self._values.get(session_id, {}))

    def set(self, session_id: uuid.UUID, concept_id: str, value: float) -> None:
        with self._lock:
            self._values.setdefault(session_id, {})[concept_id] = value

    def seeded(self, session_id: uuid.UUID) -> bool:
        with self._lock:
            return session_id in self._values

    def seed(self, session_id: uuid.UUID, posterior: dict[str, float]) -> None:
        with self._lock:
            self._values[session_id] = dict(posterior)

    def drop(self, session_id: uuid.UUID) -> None:
        with self._lock:
            self._values.pop(session_id, None)


theta_cache = ThetaCache()


# ─────────────────────────────────────────────────────────────────────────
#  The compiled step, built once per model client
# ─────────────────────────────────────────────────────────────────────────


def question_budget(state: SessionState) -> int:
    if state.kind == SessionKind.drill.value:
        return 1
    usable = state.requested_minutes * 60 - CLOSING_SECONDS
    return max(1, usable // SECONDS_PER_VERBAL_QUESTION)


#: (id(llm), strategist_on, interviewer_on) -> (llm, compiled). Keyed by
#: identity: the model clients are dataclasses, so equal-but-distinct clients
#: would otherwise share a graph bound to the wrong one. The client is kept in
#: the value so its id cannot be reused while the entry exists.
_COMPILED: dict[tuple[int, bool, bool], tuple[LLM, object]] = {}
_COMPILED_LOCK = threading.Lock()
_COMPILED_MAX = 8


def compiled_step(llm: LLM):
    key = (id(llm), enabled("ProbeStrategist"), enabled("TechnicalInterviewer"))
    with _COMPILED_LOCK:
        hit = _COMPILED.get(key)
        if hit is not None and hit[0] is llm:
            return hit[1]
        deps = Deps(
            strategist=ProbeStrategist(llm, enabled=key[1]),
            interviewer=Interviewer(llm, enabled=key[2]),
            lines=lines("neutral"),
            ladder_config=LadderConfig(),
            question_budget=question_budget,
        )
        graph = build(deps)
        if len(_COMPILED) >= _COMPILED_MAX:
            _COMPILED.pop(next(iter(_COMPILED)))
        _COMPILED[key] = (llm, graph)
        return graph


# ─────────────────────────────────────────────────────────────────────────
#  The engine
# ─────────────────────────────────────────────────────────────────────────


def _turn_id(session_id: uuid.UUID, turn_index: int) -> uuid.UUID:
    """Deterministic, so a retried write produces the same id."""
    return uuid.uuid5(session_id, f"turn:{turn_index}")


@dataclass
class Engine:
    db: Session
    upstreams: Upstreams
    llm: LLM = field(default_factory=get_llm)
    tokens: TokenBroker = field(default_factory=lambda: broker)
    thetas: ThetaCache = field(default_factory=lambda: theta_cache)
    clock: Callable[[], datetime] = utcnow

    # ── lookups ──────────────────────────────────────────────────────────

    def row(self, session_id: uuid.UUID) -> InterviewSession:
        row = store.get_session_row(self.db, session_id)
        if row is None:
            raise SessionNotFound(str(session_id))
        return row

    def state(self, session_id: uuid.UUID) -> SessionState:
        return store.load_state(self.db, session_id)

    # ── creating ─────────────────────────────────────────────────────────

    def create_drill(
        self,
        *,
        candidate_id: uuid.UUID,
        claim_id: str,
        claim_text: str,
        probes: list[dict[str, Any]],
        source_module: str,
    ) -> tuple[InterviewSession, SessionState]:
        drill = {"claim_id": claim_id, "claim_text": claim_text, "probes": probes}
        from_drill(drill)  # validates before anything is written
        row, _ = store.create_session(
            self.db,
            candidate_id=candidate_id,
            kind=SessionKind.drill.value,
            mode="practice",
            minutes=DRILL_MINUTES,
            source_module=source_module,
            source_ref=claim_id,
            drill=drill,
        )
        store.record(
            self.db, row, "plan.set", step="plan", payload={"plan": self._drill_plan(row, drill)}
        )
        state = self.state(row.id)
        return row, state

    def _drill_plan(self, row: InterviewSession, drill: dict[str, Any]) -> dict[str, Any]:
        plan = InterviewPlan(
            id=uuid.uuid5(row.id, "plan:drill"),
            session_id=row.id,
            mode="practice",
            total_minutes=DRILL_MINUTES,
            segments=[
                PlannedSegment(
                    index=0,
                    kind="project",
                    title="Defend a line from your resume",
                    persona_id="friendly_recruiter",
                    minutes=DRILL_MINUTES,
                    question_budget=1,
                    source="m01_claims",
                    rationale=drill["claim_text"],
                )
            ],
            versions=VersionStamp(prompt_version=PROMPT_VERSION),
        )
        return plan.model_dump(mode="json")

    # ── the lifecycle ────────────────────────────────────────────────────

    def start(self, session_id: uuid.UUID) -> SessionState:
        row = self.row(session_id)
        state = self.state(session_id)
        if state.status is SessionStatus.planned:
            prefix = self._bootstrap(row, state)
            store.record(
                self.db, row, "session.started", step="start", payload={"profile_prefix": prefix}
            )
        return self.continue_session(session_id)

    def _bootstrap(self, row: InterviewSession, state: SessionState) -> str:
        """Spec §6.1 steps 3–4, for what exists by day 2. Each part optional."""
        if state.kind == SessionKind.drill.value:
            return ""
        up = self.upstreams
        prefix = ""
        posterior: dict[str, float] = {}
        consent: uuid.UUID | None = None
        if up.available("M04"):
            try:
                prefix = str(
                    up.m04.profile_summary(row.candidate_id, row.id).get("summary_text", "")
                )
                consent = up.m04.consent(row.candidate_id, "practice")
            except UpstreamUnavailable as exc:
                self._degraded(row, "M04", exc)
        else:
            self._degraded(row, "M04")
        store.record(
            self.db,
            row,
            "consent.resolved",
            step="consent",
            payload={"consent_id": str(consent) if consent else None},
        )
        self._seed_m05(row, posterior)
        return prefix

    def _seed_m05(self, row: InterviewSession, posterior: dict[str, float]) -> None:
        self.thetas.seed(row.id, posterior)
        if not self.upstreams.available("M05"):
            return
        try:
            self.upstreams.m05.seed(
                row.id, row.candidate_id, posterior, "cold" if not posterior else "m04"
            )
        except UpstreamUnavailable as exc:
            log.info("M06: M05 seed failed for %s: %s", row.id, exc)

    def _degraded(self, row: InterviewSession, module: str, exc: Exception | None = None) -> None:
        if exc is not None:
            log.info("M06: %s unavailable for %s: %s", module, row.id, exc)
        store.record(
            self.db,
            row,
            "upstream.degraded",
            step=f"degraded:{module}",
            payload={"module": module, "sentence": self.upstreams.on_missing(module)},
        )

    def answer(self, session_id: uuid.UUID, question_turn_id: uuid.UUID, text: str) -> SessionState:
        row = self.row(session_id)
        state = self.state(session_id)
        asked = state.turn(question_turn_id)
        if asked is None or asked.role != "interviewer":
            raise AnswerRejected("That question isn't part of this interview.")
        answer_index = asked.turn_index + 1
        if state.status is SessionStatus.paused:
            raise AnswerRejected("The interview is paused. Resume it to answer.")
        text = text[:MAX_ANSWER_CHARS]
        already = state.turn(_turn_id(row.id, answer_index))
        if already is not None:
            # The same text again is a retry, and a retry is a no-op (AC-6.16).
            # Different text is a second answer to one question — a second tab.
            if already.text != text:
                raise AnswerRejected("That question has already been answered.")
            return self.continue_session(session_id)
        try:
            store.record(
                self.db,
                row,
                "answer.received",
                step="answer",
                turn_index=answer_index,
                payload={
                    "turn_id": str(_turn_id(row.id, answer_index)),
                    "turn_index": answer_index,
                    "text": text,
                    "question_turn_id": str(question_turn_id),
                    "completion_reason": "submit",
                    "modality": "verbal",
                },
            )
        except InvalidTransition as exc:
            raise AnswerRejected(str(exc)) from exc
        return self.continue_session(session_id)

    def end(self, session_id: uuid.UUID, reason: str) -> SessionState:
        """A student pressing End gets the same closing line as running out of
        time. `session.ended` already carries one — the engine's own finish
        path fills it in — and leaving it empty here ended the first live
        session on a repeated question, with the interviewer saying nothing."""
        row = self.row(session_id)
        state = self.state(session_id)
        aborted = state.status is SessionStatus.planned
        payload: dict = {"reason": reason}
        if not aborted:
            # Nothing was asked, so nothing is said: an aborted session never
            # got going, and its report says so instead.
            index = state.next_turn_index
            payload |= {
                "closing_text": self._closing_for(state),
                "closing_turn_id": str(_turn_id(row.id, index)),
                "closing_turn_index": index,
            }
        store.record(
            self.db,
            row,
            "session.aborted" if aborted else "session.ended",
            step="end",
            payload=payload,
        )
        self._close_m05(row, state)
        return self.state(session_id)

    def _closing_for(self, state: SessionState) -> str:
        said = lines("neutral")
        return said.drill_close if state.kind == SessionKind.drill.value else said.session_close

    def _close_m05(self, row: InterviewSession, state: SessionState) -> None:
        if state.kind != SessionKind.mock.value:
            return
        self.thetas.drop(row.id)
        if self.upstreams.available("M05"):
            try:
                self.upstreams.m05.close(row.id, {})
            except UpstreamUnavailable as exc:
                log.info("M06: M05 close failed for %s: %s", row.id, exc)

    # ── carrying on ──────────────────────────────────────────────────────

    def continue_session(self, session_id: uuid.UUID) -> SessionState:
        row = self.row(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.live or state.open_turn_id is not None:
            return state
        last = state.transcript[-1] if state.transcript else None
        if last is None:
            self._step(row, state, answer=None)
        elif last.role == "candidate":
            recorded = self._recorded_outcome(row, last.turn_index)
            self._step(row, state, answer=last.text, answer_turn=last, recorded=recorded)
        # Otherwise the last line was the interviewer's and nothing is open:
        # only the closing line looks like that, and it ends the session.
        return self.state(session_id)

    def _recorded_outcome(self, row: InterviewSession, turn_index: int) -> Outcome | None:
        event = self.db.exec(
            select(SessionEvent)
            .where(SessionEvent.session_id == row.id)
            .where(SessionEvent.turn_index == turn_index)
            .where(SessionEvent.step == "decide")
        ).first()
        if event is None:
            return None
        p = event.payload
        return Outcome(
            move=Move.model_validate(p["move"]),
            success=p.get("success"),
            break_depth=p.get("break_depth"),
            ceiling=p.get("ceiling"),
        )

    def _current_item(self, state: SessionState) -> Item | None:
        if state.current_item is not None:
            return from_dict(state.current_item)
        if state.kind == SessionKind.drill.value and state.drill:
            return from_drill(state.drill)
        return None

    def _step(
        self,
        row: InterviewSession,
        state: SessionState,
        *,
        answer: str | None,
        answer_turn=None,
        recorded: Outcome | None = None,
    ) -> None:
        now = self.clock()
        item = self._current_item(state)
        inp = StepInput(
            state=state,
            now=now,
            item=item,
            answer=answer,
            recorded=recorded,
            select=self._selector(row),
        )
        result = run_step(
            compiled_step(self.llm),
            inp,
            on_token=lambda token: self.tokens.publish(row.id, {"token": token}),
        )
        self._record_calls(row, state, result.calls)
        for module, sentence in result.degraded.items():
            store.record(
                self.db,
                row,
                "upstream.degraded",
                step=f"degraded:{module}",
                payload={"module": module, "sentence": sentence},
            )

        if answer_turn is not None and recorded is None and result.outcome is not None:
            self._record_decision(row, state, answer_turn, item, result)
            self._owe(row, answer_turn, item)

        if result.hint_level is not None and answer_turn is not None:
            store.record(
                self.db,
                row,
                "hint.given",
                step="hint",
                turn_index=answer_turn.turn_index,
                payload={"level": result.hint_level},
            )
        self._say(row, result)

    def _owe(self, row: InterviewSession, answer_turn, item: Item | None) -> None:
        """What this answer owes M13 and M02, written before it is delivered.

        In its own transaction rather than the turn's, because `store.record`
        owns that one — same guarantee either way: the row is on disk before
        anything tries to send it, so a crash costs a delay and not a score.
        """
        state = self.state(row.id)
        segment = (
            state.plan.segments[state.current_segment]
            if state.plan is not None and state.current_segment < len(state.plan.segments)
            else None
        )
        # The answer text goes to M04 before the evaluation goes to M13:
        # M13's evidence cites this turn, and M04 refuses an observation whose
        # evidence does not resolve.
        outbox.enqueue_artifact(self.db, state, answer_turn)
        queued = outbox.enqueue_evaluation(self.db, state, answer_turn, item)
        if segment is not None:
            outbox.enqueue_ledger(
                self.db,
                state,
                requirement_ids=segment.requirement_ids,
                ledger_state="answered",
                turn_id=answer_turn.turn_id,
            )
        self.db.commit()
        if queued is not None:
            store.record(
                self.db,
                row,
                "evaluation.queued",
                step="queue",
                turn_index=answer_turn.turn_index,
                payload={"delta": 1, "turn_id": str(answer_turn.turn_id)},
            )

    def deliver(self, session_id: uuid.UUID) -> outbox.Drained:
        """Send what is owed, and record what came back (FR-6.14).

        Called off the request that produced the work — a background task, or
        an explicit drain — so the ensemble is never on the conversation's
        path. Whatever cannot be sent stays queued and visible.
        """
        row = self.row(session_id)
        drained = outbox.drain(self.db, self.upstreams, session_id=session_id)
        for turn_id, outcome in drained.outcomes.items():
            turn = self.state(session_id).turn(turn_id)
            store.record(
                self.db,
                row,
                "evaluation.completed",
                step=f"scored:{turn_id}",
                turn_index=turn.turn_index if turn is not None else 0,
                payload={"turn_id": str(turn_id), **outcome},
            )
        return drained

    def _record_decision(
        self, row, state, answer_turn, item: Item | None, result: StepResult
    ) -> None:
        outcome = result.outcome
        assert outcome is not None
        verdict = result.verdict
        store.record(
            self.db,
            row,
            "probe.decided",
            step="decide",
            turn_index=answer_turn.turn_index,
            payload={
                "move": outcome.move.model_dump(mode="json"),
                "success": outcome.success,
                "break_depth": outcome.break_depth,
                "ceiling": outcome.ceiling,
                # The trace keeps the verdict; the fold drops it (FR-6.15).
                "verdict": verdict.model_dump(mode="json") if verdict else None,
                "strategist_fallback": result.strategist_fallback,
            },
        )
        if (
            verdict is not None
            and verdict.source == "model"
            and item is not None
            and item.source == "m05_bank"
            and item.concept_id
        ):
            self._observe(row, answer_turn.turn_id, item.concept_id, verdict)

    def _observe(self, row, turn_id: uuid.UUID, concept_id: str, verdict) -> None:
        """FR-6.25. The value comes back to memory, and only to memory."""
        if not self.upstreams.available("M05"):
            return
        outcome = {
            "turn_id": str(turn_id),
            "band": verdict.band,
            "confidence": verdict.confidence,
            "latency_ms": verdict.latency_ms,
        }
        for _attempt in range(2):
            try:
                value = self.upstreams.m05.observe(row.id, concept_id, outcome)
            except UpstreamUnavailable as exc:
                if "not seeded" in str(exc):
                    self._seed_m05(row, {})
                    continue
                log.info("M06: M05 observe failed for %s: %s", row.id, exc)
                return
            if value is not None:
                self.thetas.set(row.id, concept_id, value)
            return

    def _say(self, row: InterviewSession, result: StepResult) -> None:
        state = self.state(row.id)
        utterance = result.utterance
        if result.finish:
            index = state.next_turn_index
            store.record(
                self.db,
                row,
                "session.ended",
                step="end",
                payload={
                    "reason": result.finish,
                    "closing_text": utterance.text if utterance else "",
                    "closing_turn_id": str(_turn_id(row.id, index)),
                    "closing_turn_index": index,
                },
            )
            self._close_m05(row, state)
            return
        if utterance is None or result.item is None:
            log.warning("M06: step for %s produced nothing to say", row.id)
            return
        item = result.item
        move = result.outcome.move if (result.outcome and not result.new_question) else None
        ladder_depth = state.ladder.depth if state.ladder else 0
        depth = (
            move.depth
            if (move and move.depth is not None)
            else (0 if result.new_question else ladder_depth)
        )
        index = state.next_turn_index
        segment = (
            state.plan.segments[state.current_segment]
            if state.plan is not None and state.current_segment < len(state.plan.segments)
            else None
        )
        if result.new_question and segment is not None:
            outbox.enqueue_ledger(
                self.db,
                state,
                requirement_ids=segment.requirement_ids,
                ledger_state="asked",
                turn_id=_turn_id(row.id, index),
            )
        store.record(
            self.db,
            row,
            "question.asked",
            step="ask",
            turn_index=index,
            payload={
                "turn_id": str(_turn_id(row.id, index)),
                "turn_index": index,
                "segment_index": state.current_segment,
                "text": utterance.text,
                "question_text": utterance.question,
                "question_id": str(item.question_id) if item.question_id else None,
                "question_source": item.source,
                "rubric_round_type": item.rubric_round_type,
                "concept_id": item.concept_id,
                "probe_depth": depth,
                "probe_move": move.kind if move else None,
                "modality": "verbal",
                "new_question": result.new_question,
                "item": to_dict(item),
                "utterance_source": utterance.source,
                "utterance_fallback": utterance.fallback_reason,
                "selection_reason": (result.selection or {}).get("reason"),
            },
        )

    def _record_calls(
        self, row: InterviewSession, state: SessionState, calls: list[LLMResult]
    ) -> None:
        for call in calls:
            self.db.add(
                LLMCall(
                    session_id=row.id,
                    turn_index=state.next_turn_index,
                    job=call.job,
                    tier=call.tier,
                    model_id=call.model,
                    prompt_version=call.prompt_version,
                    ok=call.ok,
                    error=None if call.ok else call.reason[:500],
                    tokens_in=call.tokens_in,
                    tokens_out=call.tokens_out,
                    reasoning_tokens=call.reasoning_tokens,
                    cached_tokens=call.cached_tokens,
                    latency_ms=call.latency_ms,
                    first_token_ms=call.first_token_ms,
                )
            )
        if calls:
            self.db.commit()

    # ── the QuestionPlanner's tool ───────────────────────────────────────

    def _selector(self, row: InterviewSession):
        def select_next(state: SessionState, now: datetime) -> Selected:
            return self._select(row, state, now)

        return select_next

    def _round_type(self) -> str:
        """Day 2's choice: what M13 can score, else the Rule-2 fallback."""
        up = self.upstreams
        if up.available("M13"):
            try:
                served = [r["round_type"] for r in up.m13.rubrics()]
            except UpstreamUnavailable:
                served = []
            if served and DEFAULT_ROUND_TYPE not in served:
                return served[0]
        return DEFAULT_ROUND_TYPE

    def _select(self, row: InterviewSession, state: SessionState, now: datetime) -> Selected:
        up = self.upstreams
        round_type = self._round_type()
        seen = store.seen_item_ids(self.db, row.candidate_id, now=now)
        request = {
            "candidate_id": str(row.candidate_id),
            "session_id": str(row.id),
            "round_type": round_type,
            # In memory only — see ThetaCache.
            "theta_provisional": self.thetas.get(row.id),
            "seen_item_ids": sorted(str(i) for i in seen),
            "recent_item_ids": sorted(str(i) for i in seen),
            "time_remaining_s": int(state.time_remaining_s(now)),
            "is_first_of_round": state.questions_asked == 0,
            "round_progress": min(state.questions_asked / question_budget(state), 1.0),
            "modality_allowed": ["verbal"],
        }
        degraded: dict[str, str] = {}
        if up.available("M05"):
            try:
                chosen = up.m05.select(request)
                if chosen is None:
                    return Selected(None, empty_reason="bank_exhausted")
                question = up.m05.question(uuid.UUID(str(chosen["question_id"])))
                source = "m05_fallback" if chosen.get("reason") == "fallback" else "m05_bank"
                item = from_m05(question, round_type=chosen["round_type"], source=source)
                return Selected(item, chosen)
            except UpstreamUnavailable as exc:
                log.info("M06: M05 selection failed for %s: %s", row.id, exc)
                degraded["M05"] = up.on_missing("M05")
        else:
            degraded["M05"] = up.on_missing("M05")

        # §10: M06's own playlist. Never repeats within this session.
        asked_here = {str(t.question_id) for t in state.transcript if t.question_id is not None}
        local_request = {**request, "seen_item_ids": sorted(asked_here)}
        chosen = up.local_questions.select(local_request)
        if chosen is None:
            return Selected(None, degraded=degraded, empty_reason="fallback_exhausted")
        question = up.local_questions.question(uuid.UUID(chosen["question_id"]))
        item = from_m05(question, round_type=chosen["round_type"], source="local_fallback")
        return Selected(item, chosen, degraded=degraded)


__all__ = [
    "AnswerRejected",
    "Engine",
    "SessionNotFound",
    "ThetaCache",
    "compiled_step",
    "question_budget",
    "theta_cache",
]
