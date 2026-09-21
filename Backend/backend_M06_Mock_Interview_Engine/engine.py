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
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ai_core.timeutil import utcnow
from ai_core.versions import VersionStamp
from sqlmodel import Session, select

from . import PROMPT_VERSION, outbox, planner, store
from .adapters import Upstreams, UpstreamUnavailable
from .agents import Interviewer, ProbeStrategist
from .broker import TokenBroker, broker
from .contracts import (
    HintOffer,
    InterviewPlan,
    Move,
    PlannedSegment,
    SessionKind,
    SessionStatus,
)
from .items import Item, from_dict, from_drill, from_m05, to_dict
from .ladder import LadderConfig, Outcome
from .llm import LLM, LLMResult, get_llm
from .models import InterviewSession, LLMCall, SessionEvent
from .orchestration import Deps, Selected, StepInput, StepResult, build, enabled, run_step
from .phrasebook import lines
from .state import InvalidTransition, SessionState

log = logging.getLogger("uvicorn.error")

#: M05's rubric vocabulary, and the only round type its bank is authored for
#: today. Since day 5 the plan carries what M05 answered for at plan time;
#: this is the Rule-2 fallback, used when there is no plan or nothing probed.
DEFAULT_ROUND_TYPE = "dsa_verbal"

#: A session cannot skip more segments than it has. The bound is here rather
#: than in a `while True` so a plan that somehow loops cannot hang a request.
_MAX_SEGMENT_SKIPS = 8

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


def bridge_line(arriving: PlannedSegment) -> str:
    """§3.2.3 — what is said between two rounds.

    Authored, never generated: it is on the hot path, and it is one of the
    lines that must never telegraph how the round that just ended went. The
    topic is the segment's own title, which is M02's words for the
    requirement, so a student hears the posting's language rather than ours.
    """
    said = lines("neutral")
    if arriving.kind == "closing":
        return said.bridge_to_closing
    if arriving.kind == "warmup" or not arriving.title:
        return said.bridge
    return said.bridge_to.format(topic=arriving.title)


def hint_offer(state: SessionState) -> HintOffer:
    """What the next hint is and what it costs — FR-6.7, master plan §32.5.

    Answered BEFORE the hint is taken. A deduction discovered afterwards is a
    penalty; a deduction published beforehand is a choice, and §32.5 asks for
    the second. The factor is M13's, frozen on the plan at bootstrap, so the
    price quoted is the price paid even if the rubric is reloaded mid-session.

    A free function because `session_out` answers it on every read and has no
    Engine to ask — and because it is pure over the state, which is what makes
    it cheap enough to answer on every read.
    """
    if state.status is not SessionStatus.live or state.open_turn_id is None:
        return HintOffer(available=False, unavailable_reason="Nothing is open to hint about.")
    if state.mode == "final_boss":
        # §6.1's mode table. Day 9 makes modes full configs; the rule is the
        # same either way, and a student is told rather than left guessing.
        return HintOffer(available=False, unavailable_reason="Final Boss runs without hints.")
    ladder = list((state.current_item or {}).get("hint_ladder") or [])
    level = state.hint_level + 1
    if level > len(ladder):
        return HintOffer(
            available=False,
            unavailable_reason=(
                "No more hints on this one." if ladder else "This question doesn't come with hints."
            ),
        )
    penalty = state.plan.hint_penalty if state.plan is not None else {}
    return HintOffer(
        available=True,
        level=level,
        # Unlisted levels credit fully — M13's own rule (`Rubric.credit`).
        # Keys survive JSON as strings, so both spellings are tried: a lookup
        # that silently misses reads as "this hint is free".
        credit=float(penalty.get(level, penalty.get(str(level), 1.0))),
        hints_left=len(ladder) - state.hint_level,
    )


def question_budget(state: SessionState) -> int:
    """How many questions this session asks.

    M02 priced each round and M06 carried those prices into the plan, so when
    a plan exists the budget is a sum rather than a second estimate — two
    numbers for the same thing is how a session runs over (Trap 8). The
    arithmetic below is the no-plan fallback.
    """
    if state.kind == SessionKind.drill.value:
        return 1
    if state.plan is not None:
        planned = sum(
            segment.question_budget
            for segment in state.plan.segments
            if segment.dropped_reason is None
        )
        if planned:
            return planned
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
        already_planned = state.plan is not None
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
        if not already_planned:
            # The preview built it already; rebuilding would throw away the
            # student's edits and ask M02 to price the same session twice.
            self._plan(row, self.state(row.id))
        return prefix

    # ── the plan (FR-6.1, FR-6.2, spec §6.1 steps 5–6) ───────────────────

    def plan(self, session_id: uuid.UUID) -> SessionState:
        """Build the plan without starting the interview — FR-6.2.

        The preview screen calls this: a student should see what they are
        about to be asked, and be able to drop a part of it, before the first
        question arrives. `start` calls the same code and is a no-op if the
        preview already built one, so previewing costs the bootstrap once.
        """
        row = self.row(session_id)
        state = self.state(session_id)
        if state.plan is None and state.kind != SessionKind.drill.value:
            self._plan(row, state)
        return self.state(session_id)

    def drop_segment(self, session_id: uuid.UUID, index: int) -> SessionState:
        """FR-6.2's drop-a-segment. Before the interview starts, not during.

        The segment is not removed — it keeps its place with the student's
        reason on it, because the report has to be able to say what was
        planned as well as what happened. Its requirements go to M02's ledger
        as `skipped`, exactly as a segment M06 dropped itself.
        """
        row = self.row(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.planned:
            raise InvalidTransition("The plan can only be changed before the interview starts.")
        if state.plan is None:
            raise InvalidTransition("There is no plan to change yet.")
        segment = next((s for s in state.plan.segments if s.index == index), None)
        if segment is None:
            raise InvalidTransition(f"No segment {index} in this plan.")
        if segment.is_reserved:
            raise InvalidTransition("The closing stays — it is where you ask your questions.")
        if segment.dropped_reason is not None:
            return state

        plan = state.plan.model_copy(deep=True)
        for candidate in plan.segments:
            if candidate.index == index:
                candidate.dropped_reason = "You removed this part of the plan."
        store.record(
            self.db,
            row,
            "plan.set",
            step=f"plan:drop:{index}",
            payload={"plan": plan.model_dump(mode="json")},
        )
        if segment.requirement_ids:
            outbox.enqueue_ledger(
                self.db,
                self.state(session_id),
                requirement_ids=list(segment.requirement_ids),
                ledger_state="skipped",
                turn_id=None,
            )
            self.db.commit()
        return self.state(session_id)

    def _plan(self, row: InterviewSession, state: SessionState) -> None:
        """Assemble it, record it, and owe M02 a `skipped` row for what fell.

        Seeding M05 comes first because the availability probe below asks M05
        to select against this session — an unseeded session would be probed
        at the prior rather than at the student's own estimate, and a round
        type that can serve them might answer 409.
        """
        coverage, requirements = self._coverage(row, state)
        rubrics = self._rubrics()
        scoreable = tuple(str(r["round_type"]) for r in rubrics) or (DEFAULT_ROUND_TYPE,)
        round_types = self._available_round_types(row, state, scoreable)
        plan = planner.assemble(
            planner.PlanInputs(
                session_id=row.id,
                mode=state.mode,
                requested_minutes=state.requested_minutes,
                jd_id=state.jd_id,
                coverage=coverage,
                requirements={str(r.get("id")): r for r in requirements if r.get("id")},
                available_round_types=round_types,
                claims=self._claims(row),
                hint_penalty=self._hint_penalty(rubrics, round_types),
            )
        )
        store.record(
            self.db, row, "plan.set", step="plan", payload={"plan": plan.model_dump(mode="json")}
        )
        skipped = planner.skipped_requirements(plan)
        if skipped:
            # FR-6.24: planned, then dropped, so no turn will ever reach them.
            # M02's ledger has to hear that from the module that dropped them.
            outbox.enqueue_ledger(
                self.db,
                self.state(row.id),
                requirement_ids=skipped,
                ledger_state="skipped",
                turn_id=None,
            )
            self.db.commit()

    def _claims(self, row: InterviewSession) -> tuple[dict, ...]:
        """M01's risky and vague claims, for the project segment (§6.1).

        Optional like every upstream: no M01, no resume, or a resume nobody
        has confirmed means no project segment — not a degraded one. A student
        with nothing shaky on their resume is not missing a feature.
        """
        up = self.upstreams
        if not up.available("M01"):
            return ()
        try:
            resumes = up.m01.resumes_for(row.candidate_id)
            confirmed = next(
                (r for r in resumes if str(r.get("status")) == "confirmed"),
                resumes[0] if resumes else None,
            )
            if confirmed is None:
                return ()
            found = up.m01.claims(uuid.UUID(str(confirmed["id"])), row.candidate_id)
        except (UpstreamUnavailable, KeyError, ValueError) as exc:
            log.info("M06: M01 claims unavailable for %s: %s", row.id, exc)
            return ()
        return tuple(found.get("claims") or [])

    def _coverage(
        self, row: InterviewSession, state: SessionState
    ) -> tuple[dict | None, list[dict]]:
        """M02's plan and the requirements behind it. Both optional (§10)."""
        if state.jd_id is None:
            return None, []
        up = self.upstreams
        if not up.available("M02"):
            self._degraded(row, "M02")
            return None, []
        minutes = planner.minutes_for_m02(state.requested_minutes)
        try:
            coverage = up.m02.plan(state.jd_id, row.candidate_id, minutes)
        except UpstreamUnavailable as exc:
            self._degraded(row, "M02", exc)
            return None, []
        try:
            requirements = up.m02.requirements(state.jd_id, row.candidate_id)
        except UpstreamUnavailable as exc:
            # The plan stands; only the concept ids and the segment titles are
            # thinner. Not a degradation the student needs a sentence about.
            log.info("M06: M02 requirements unavailable for %s: %s", row.id, exc)
            requirements = []
        return coverage, requirements

    def _available_round_types(
        self,
        row: InterviewSession,
        state: SessionState,
        candidates: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        """Spec §6.1 step 5: ask M05 for one item per candidate rubric round
        type, and keep the ones it can serve.

        The probe is a real `POST /v1/questions/select`, which reads this
        session's estimate and writes nothing — M05 records an item as
        administered when M06 reports an outcome, not when it selects one. A
        409 means the bank is thin for that round type, which is an answer
        (M05 §6.8) and removes it from the plan rather than being discovered
        mid-interview.
        """
        candidates = candidates or self._rubric_round_types()
        if not self.upstreams.available("M05"):
            return candidates
        served: list[str] = []
        for round_type in candidates:
            try:
                chosen = self.upstreams.m05.select(
                    {
                        "candidate_id": str(row.candidate_id),
                        "session_id": str(row.id),
                        "round_type": round_type,
                        "theta_provisional": self.thetas.get(row.id),
                        "is_first_of_round": True,
                        "time_remaining_s": state.requested_minutes * 60,
                        "modality_allowed": ["verbal"],
                    }
                )
            except UpstreamUnavailable as exc:
                log.info("M06: M05 availability probe failed for %s: %s", row.id, exc)
                return candidates
            if chosen is not None:
                served.append(round_type)
        return tuple(served)

    def _rubrics(self) -> list[dict]:
        """M13's rubric table: which round types it can score, and what each
        one credits a hinted answer at (§32.5). One call, because both
        questions have the same answer and the plan needs both."""
        up = self.upstreams
        if not up.available("M13"):
            return []
        try:
            return [r for r in up.m13.rubrics() if r.get("round_type")]
        except UpstreamUnavailable as exc:
            log.info("M06: M13 rubrics unavailable: %s", exc)
            return []

    def _rubric_round_types(self) -> tuple[str, ...]:
        """What M13 can score. Nothing else is worth probing M05 for: a
        question M13 has no rubric for is a question with no score."""
        served = [str(r["round_type"]) for r in self._rubrics()]
        return tuple(served) if served else (DEFAULT_ROUND_TYPE,)

    @staticmethod
    def _hint_penalty(rubrics: list[dict], round_types: tuple[str, ...]) -> dict[int, float]:
        """M13's credit table for the round type this session will use.

        Keys arrive as strings over JSON and as ints in-process; both are
        normalised here, because a lookup that silently misses reads as "this
        hint is free" — the one wrong answer a published deduction can give.
        """
        wanted = round_types[0] if round_types else None
        table = next(
            (r.get("hint_penalty") or {} for r in rubrics if r.get("round_type") == wanted), {}
        )
        out: dict[int, float] = {}
        for level, factor in table.items():
            try:
                out[int(level)] = float(factor)
            except (TypeError, ValueError):
                continue
        return out

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

    # ── hints (FR-6.7, master plan §32.5) ────────────────────────────────

    def hint(self, session_id: uuid.UUID) -> SessionState:
        """Give the hint the student asked for, at the published price.

        Asked for explicitly, by a button, rather than inferred from the words
        of an answer. The strategist's `asks_for_answer` still works and is
        how somebody who simply types "can I have a hint" gets one — but a
        student should not have to phrase a request to use a feature.
        """
        row = self.row(session_id)
        state = self.state(session_id)
        offer = hint_offer(state)
        if not offer.available:
            raise InvalidTransition(offer.unavailable_reason or "No hint is available.")

        item = state.current_item or {}
        text = list(item.get("hint_ladder") or [])[offer.level - 1]
        asked = state.turn(state.open_turn_id) if state.open_turn_id else None
        store.record(
            self.db,
            row,
            "hint.given",
            step=f"hint:{offer.level}",
            turn_index=asked.turn_index if asked else 0,
            payload={"level": offer.level, "credit": offer.credit},
        )
        # And it is SAID. A hint recorded but never shown is a deduction the
        # student paid for and did not receive. It re-opens the SAME question
        # — `probe_move="hint"`, same `question_id` — so the answer that
        # follows still belongs to the question the hint was about.
        state = self.state(row.id)
        index = state.next_turn_index
        store.record(
            self.db,
            row,
            "question.asked",
            step=f"hint-said:{offer.level}",
            turn_index=index,
            payload={
                "turn_id": str(_turn_id(row.id, index)),
                "turn_index": index,
                "segment_index": state.current_segment,
                "text": text,
                "question_text": text,
                "question_id": str(asked.question_id) if asked and asked.question_id else None,
                "question_source": asked.question_source if asked else None,
                "rubric_round_type": asked.rubric_round_type if asked else None,
                "concept_id": asked.concept_id if asked else "",
                "probe_depth": asked.probe_depth if asked else 0,
                "probe_move": "hint",
                "modality": "verbal",
                "new_question": False,
                "item": item,
                "utterance_source": "template",
            },
        )
        return self.state(row.id)

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

    def segment(self, state: SessionState) -> PlannedSegment | None:
        """The segment being run, or None before the plan exists.

        Looked up by the plan's own index rather than by position, because a
        dropped segment keeps its place in the list and `current_segment` is
        that index — counting positions in the live list would silently run
        the wrong segment the moment anything is dropped.
        """
        if state.plan is None:
            return None
        live = planner.live_segments(state.plan)
        if not live:
            return None
        found = next((s for s in live if s.index == state.current_segment), None)
        return found or live[0]

    def _advance_segment(
        self, row: InterviewSession, state: SessionState, now: datetime
    ) -> tuple[SessionState, str | None]:
        """Move on once this segment has had the questions M02 priced for it.

        This is the whole of sequencing that day 5 needs: without it the plan
        is a screen, because the session stays on the warm-up for ever and
        never asks the requirements it promised to cover. Day 6 adds the
        bridge line and the honest 409 ending; the arithmetic is here.
        """
        live = planner.live_segments(state.plan) if state.plan is not None else []
        if not live:
            return state, None
        bridge: str | None = None
        position = next((i for i, s in enumerate(live) if s.index == state.current_segment), 0)
        while (
            position + 1 < len(live)
            and state.questions_in_segment(live[position].index) >= live[position].question_budget
        ):
            leaving, arriving = live[position], live[position + 1]
            store.record(
                self.db,
                row,
                "segment.transition",
                step=f"segment:{arriving.index}",
                payload={
                    "from": leaving.index,
                    "to": arriving.index,
                    "from_title": leaving.title,
                    "to_title": arriving.title,
                    "line": bridge_line(arriving),
                },
            )
            state = self.state(row.id)
            bridge = state.pending_bridge
            position += 1
        return state, bridge

    def _round_type(self, state: SessionState) -> str:
        """The plan's answer, because the plan already asked M05 at plan time.

        Asking M13 again here would let a session drift onto a round type the
        plan never probed — and then discover mid-interview that the bank is
        thin for it, which is exactly the 409 §6.1 step 5 exists to prevent.
        """
        segment = self.segment(state)
        if segment is not None and segment.rubric_round_types:
            return segment.rubric_round_types[0]
        return self._rubric_round_types()[0]

    def _select(self, row: InterviewSession, state: SessionState, now: datetime) -> Selected:
        """The next question, or why there is none — and a 409 ends a SEGMENT.

        M05 answering "nothing left for this round type" is a known state with
        a specified behaviour (M05 §6.8), not a crash and not the end of the
        interview: §6.1's plan-time probe should have caught it, and when it
        did not, the honest thing is to close that round and open the next
        one. Ending the whole session on it would throw away the segments
        behind it, which is how a thin corner of the bank becomes a short
        interview about nothing.
        """
        state, bridge = self._advance_segment(row, state, now)
        for _ in range(_MAX_SEGMENT_SKIPS):
            found = self._select_from_bank(row, state, now)
            if found.item is not None:
                return replace(found, bridge=bridge or found.bridge)
            moved, state, next_bridge = self._abandon_segment(row, state, found.empty_reason)
            if not moved:
                # Nothing left to move to. The session ends, and `empty_reason`
                # is what the report says about it.
                return replace(found, bridge=bridge or found.bridge)
            bridge = next_bridge or bridge
        return Selected(None, empty_reason="bank_exhausted", bridge=bridge)

    def _select_a_claim(self, state: SessionState) -> Selected:
        """The project segment's questions are M01's probes, not M05's items.

        Never scored: M13 resolves a question package from M05, and a claim
        probe is not a bank item (`outbox.scoreable` says the same). The
        report says so rather than leaving a student to wonder why one round
        has no status beside it.
        """
        asked = {t.concept_id for t in state.transcript if t.role == "interviewer"}
        for claim in state.plan.claims if state.plan is not None else []:
            item = from_drill(
                {
                    "claim_id": str(claim.get("id", "")),
                    "claim_text": claim.get("text", ""),
                    "probes": claim.get("probes") or [],
                }
            )
            if item.concept_id not in asked:
                return Selected(item, {"reason": "m01_claim"})
        return Selected(None, empty_reason="claims_exhausted")

    def _abandon_segment(
        self, row: InterviewSession, state: SessionState, reason: str | None
    ) -> tuple[bool, SessionState, str | None]:
        """Close the segment M05 cannot fill and open the next. `(moved, …)`.

        Its requirements are owed to M02 as `skipped`: nothing will ask about
        them now, and a ledger that still expects them is a ledger that says
        coverage is coming when it is not.
        """
        live = planner.live_segments(state.plan) if state.plan is not None else []
        position = next((i for i, s in enumerate(live) if s.index == state.current_segment), None)
        if position is None or position + 1 >= len(live):
            return False, state, None
        leaving, arriving = live[position], live[position + 1]
        store.record(
            self.db,
            row,
            "segment.transition",
            step=f"segment:{arriving.index}",
            payload={
                "from": leaving.index,
                "to": arriving.index,
                "from_title": leaving.title,
                "to_title": arriving.title,
                "line": bridge_line(arriving),
                "reason": reason or "bank_exhausted",
            },
        )
        state = self.state(row.id)
        if leaving.requirement_ids:
            outbox.enqueue_ledger(
                self.db,
                state,
                requirement_ids=list(leaving.requirement_ids),
                ledger_state="skipped",
                turn_id=None,
            )
            self.db.commit()
        log.info(
            "M06: %s has nothing left for %r, moving to %r", row.id, leaving.title, arriving.title
        )
        return True, state, state.pending_bridge

    def _select_from_bank(
        self, row: InterviewSession, state: SessionState, now: datetime
    ) -> Selected:
        segment = self.segment(state)
        if segment is not None and segment.kind == "project":
            return self._select_a_claim(state)
        up = self.upstreams
        round_type = self._round_type(state)
        segment = self.segment(state)
        seen = store.seen_item_ids(self.db, row.candidate_id, now=now)
        request = {
            "candidate_id": str(row.candidate_id),
            "session_id": str(row.id),
            "round_type": round_type,
            # What this segment is FOR. M05 matches `coverage_debt` against
            # item concept ids whatever its name says (M06_REVIEW 1.2), and
            # `required_requirement_ids` is how a plan's promise to cover a
            # requirement becomes the question that covers it.
            "coverage_debt": {c: 1.0 for c in (segment.concept_ids if segment else [])},
            "required_requirement_ids": list(segment.requirement_ids) if segment else [],
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
