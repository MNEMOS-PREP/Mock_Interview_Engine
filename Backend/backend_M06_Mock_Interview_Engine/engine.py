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
from types import SimpleNamespace
from typing import Any

from ai_core.timeutil import utcnow
from ai_core.versions import VersionStamp
from sqlmodel import Session, select

from . import PROMPT_VERSION, degrade, outbox, pacing, planner, prefill, presence, replan, store
from .adapters import Upstreams, UpstreamUnavailable
from .agents import Interviewer, ProbeStrategist, Summariser, summariser
from .agents.guard import SafetyGuard
from .broker import TokenBroker, broker
from .contracts import (
    DEPTH_CAP,
    M05_OWNED,
    PHASE1_MODALITIES,
    HintOffer,
    InterviewPlan,
    Move,
    PlannedSegment,
    SessionKind,
    SessionStatus,
    TurnView,
)
from .items import Item, from_dict, from_drill, from_m05, to_dict
from .ladder import LadderConfig, Outcome
from .llm import LLM, LLMResult, get_llm
from .models import InterviewSession, LLMCall, SessionEvent
from .modes import mode_config
from .orchestration import Deps, Selected, StepInput, StepResult, build, enabled, run_step
from .orchestration.graph import MIN_SECONDS_FOR_A_QUESTION, UNJUDGED
from .personas import Persona, persona
from .state import InvalidTransition, SessionState
from .state import apply as apply_event

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


def current_segment(state: SessionState) -> PlannedSegment | None:
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


def speaker(state: SessionState) -> Persona:
    """Who is asking right now (FR-6.3): whoever asked the question being
    worked on — or, before any question, the current segment's persona.

    Not simply the current segment's. A crossing into the next round is
    recorded while the next question is being selected, so a step that
    crashed after that and is replayed would otherwise hand the leaving
    interviewer's exit line to the one arriving. The question's own segment
    is the fact that does not move.
    """
    asked = state.open_question_turn()
    segment = (
        next((s for s in state.plan.segments if s.index == asked.segment_index), None)
        if asked is not None and state.plan is not None
        else current_segment(state)
    )
    if segment is not None and segment.persona_id:
        return persona(segment.persona_id)
    return persona(mode_config(state.mode).persona_for("default"))


def arriving_speaker(state: SessionState) -> Persona:
    """Who asks the NEXT question: the interviewer of the segment now running.

    `speaker` is who asked the last one, on purpose (see there). Across a
    crossing the two differ, and the step's line needs both — the one leaving
    closes their question and hands over, the one arriving asks. Until
    2026-10-06 the selector named `speaker` for both, so an arriving
    interviewer's own lead-in was never said and their first question was
    shown under the previous interviewer's name.
    """
    segment = current_segment(state)
    if segment is not None and segment.persona_id:
        return persona(segment.persona_id)
    return speaker(state)


def seated(state: SessionState) -> list[Persona]:
    """The panel (FR-6.3, `panel.py`): everyone this plan seats, in the order
    the student meets them — the lead first. One person for a drill."""
    if state.plan is None or state.kind == SessionKind.drill.value:
        return [speaker(state)]
    # The plan's panel, then anyone a re-plan handed a round to since.
    ids = dict.fromkeys(
        [
            *state.plan.panel,
            *(s.persona_id for s in planner.live_segments(state.plan) if s.persona_id),
        ]
    )
    return [persona(i) for i in ids] or [speaker(state)]


def ladder_config(state: SessionState) -> LadderConfig:
    """The ladder's rules for this state — the persona's depth, the mode's
    hints and steelman flag.

    A drill keeps the ladder it was handed: M01 wrote the probes, and their
    depth is the drill (FR-6.23), so no persona shortens it.
    """
    mode = mode_config(state.mode)
    if state.kind == SessionKind.drill.value:
        return LadderConfig(hints_available=False)
    who = speaker(state)
    # §6.9: ahead of schedule at 70%, one follow-up deeper from then on. Not
    # for that round only: the check runs before the step's crossing, so a
    # 70% step that also ends a round granted the depth to the round it left.
    ahead = state.extra_depth_segment is not None
    extra = 1 if ahead and state.current_segment >= state.extra_depth_segment else 0
    return LadderConfig(
        steelman_enabled=mode.steelman_enabled,
        steelman_rate=mode.steelman_rate,
        hints_available=mode.hints and who.hints_available,
        max_depth=min(who.max_depth + extra, DEPTH_CAP),
        max_generic_rungs=who.max_generic_rungs,
    )


def retry_allowed(state: SessionState) -> bool:
    """§15.4: Practice only, once per question, never in a drill, and never
    for a retry itself — the second attempt is the last one."""
    if state.kind == SessionKind.drill.value or not mode_config(state.mode).retry_allowed:
        return False
    if state.ladder_is_retry:
        return False
    asked = state.open_question_turn()
    return asked is not None and str(asked.turn_id) not in state.retried


def introduced(state: SessionState) -> frozenset[str]:
    """The personas who have already spoken in this session — anyone who
    said part of an interviewer line, which includes everyone the panel's
    opening introduced."""
    if state.plan is None:
        return frozenset()
    spoke: set[str] = set()
    for turn in state.transcript:
        if turn.role != "interviewer":
            continue
        spoke.update(part.speaker_id for part in turn.parts)
        if turn.speaker_id:
            spoke.add(turn.speaker_id)
    return frozenset(spoke)


def bridge_line(
    arriving: PlannedSegment,
    introduced: frozenset[str] | None = None,
    *,
    forced_by_time: bool = False,
    panel: bool = False,
) -> str:
    """§3.2.3 — what is said between two rounds.

    Authored, never generated: it is on the hot path, and it is one of the
    lines that must never telegraph how the round that just ended went. The
    topic is the segment's own title, which is M02's words for the
    requirement, so a student hears the posting's language rather than ours.

    Said by the ARRIVING segment's persona: in a panel, the next interviewer
    is the one who picks the conversation up — and one the student has not
    met yet introduces themselves instead, with their own greeting, the way
    a real panel hands over. `introduced` is who has spoken so far; None
    means "do not introduce anybody". A `panel` closes as "we", asking the
    student what they would like to ask any of us.
    """
    who = persona(arriving.persona_id)
    said = who.said()
    if introduced is not None and arriving.kind != "closing" and who.id not in introduced:
        # Nobody has spoken yet: their opening greeting. Joining an interview
        # already under way: a joining line, then the round's own topic.
        if not introduced:
            return said.greeting
        joining = said.panel_joining.format(name=who.name)
        if arriving.title and arriving.kind != "warmup":
            return f"{joining} {said.bridge_to.format(topic=arriving.title)}"
        return joining
    if arriving.kind == "closing":
        if panel:
            return said.panel_to_closing_early if forced_by_time else said.panel_to_closing
        if forced_by_time:
            return said.bridge_to_closing_early
        return said.bridge_to_closing
    if arriving.kind == "warmup" or not arriving.title:
        return said.bridge
    return said.bridge_to.format(topic=arriving.title)


def _parts_payload(spoken: list[tuple]) -> list[dict]:
    """A line's voices for its event — none for a line one person said in
    one breath. A pause inside a line (M11's FR-11.12) rides on its part."""
    if len(spoken) < 2:
        return []
    out = []
    for part in spoken:
        entry = {"speaker_id": part[0], "text": part[1]}
        if len(part) > 2:
            entry["pause_after_ms"] = part[2]
        out.append(entry)
    return out


#: EC-6.1: a gentle prompt, a second, then the offer to move on.
IDLE_OFFER_AT = 3


def welcome_line(state: SessionState) -> str | None:
    """§6.8's "welcome back — we were on question 4 of the DSA round", in the
    voice of whoever was asking. None when there is nothing to come back to.

    The number is the question within its round, as the student counted it:
    new questions only, not the follow-ups that went deeper on one.
    """
    if state.status not in (SessionStatus.live, SessionStatus.paused) or not state.transcript:
        return None
    said = speaker(state).said()
    asked = state.open_question_turn()
    if asked is not None and asked.question_source == "closing":
        return said.welcome_back_closing
    if asked is None:
        return said.welcome_back.format(n=max(state.questions_asked, 1), topic="the interview")
    segment = (
        next((s for s in state.plan.segments if s.index == asked.segment_index), None)
        if state.plan is not None
        else None
    )
    if state.kind == SessionKind.drill.value:
        topic = "the drill"
    elif segment is not None and segment.kind == "warmup":
        topic = "the warm-up"
    elif segment is None or not segment.title:
        topic = "the interview"
    else:
        topic = segment.title
    n = state.questions_in_segment(asked.segment_index) if segment is not None else 1
    return said.welcome_back.format(n=max(n, 1), topic=topic)


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
    mode = mode_config(state.mode)
    if not mode.hints:
        # §6.1's mode table, from the one place it lives. A student is told
        # rather than left guessing whether the button broke.
        return HintOffer(
            available=False, unavailable_reason=mode.no_hints_reason or "No hints in this mode."
        )
    who = speaker(state)
    if not who.hints_available:
        return HintOffer(available=False, unavailable_reason=f"{who.name} doesn't give hints.")
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


#: (id(llm), strategist_on, interviewer_on, guard_on) -> (llm, compiled). Keyed by
#: identity: the model clients are dataclasses, so equal-but-distinct clients
#: would otherwise share a graph bound to the wrong one. The client is kept in
#: the value so its id cannot be reused while the entry exists.
_COMPILED: dict[tuple[int, bool, bool, bool], tuple[LLM, object]] = {}
_COMPILED_LOCK = threading.Lock()
_COMPILED_MAX = 8


def compiled_step(llm: LLM):
    key = (
        id(llm),
        enabled("ProbeStrategist"),
        enabled("TechnicalInterviewer"),
        enabled("SafetyGuard"),
    )
    with _COMPILED_LOCK:
        hit = _COMPILED.get(key)
        if hit is not None and hit[0] is llm:
            return hit[1]
        deps = Deps(
            strategist=ProbeStrategist(llm, enabled=key[1]),
            interviewer=Interviewer(llm, enabled=key[2]),
            guard=SafetyGuard(llm, enabled=key[3]),
            persona_for=speaker,
            panel_for=seated,
            ladder_for=ladder_config,
            question_budget=question_budget,
            retry_allowed=retry_allowed,
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
    #: One plan change per step (§6.4, Trap 4). Reset by `_step`.
    _changed_this_step: bool = field(default=False, init=False, repr=False)
    #: M11's FR-11.6: the model answers a prefill kept for this answer's exact
    #: words, for the step about to run. Taken by `_step`.
    _replay: prefill.Kept | None = field(default=None, init=False, repr=False)

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
        if not already_planned:
            # `_plan` seeds M05 from M04's posterior on its way (§6.1 steps
            # 3–4), before it probes availability against the session.
            self._plan(row, self.state(row.id))
        else:
            # The preview built the plan — in this process, or before a
            # restart that dropped the in-memory θ. Seed if it is not.
            planned = self.state(row.id).plan
            concepts = [c for s in (planned.segments if planned else []) for c in s.concept_ids]
            self._seed_for(row, concepts)
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
        # §6.1 steps 3–4: M04's posterior for what this posting asks about,
        # handed to M05 BEFORE the availability probe selects against it.
        # Until 2026-09-30 nothing fetched it, so every session's CAT started
        # at the prior — "adaptive" from a standing start, every time.
        self._seed_for(
            row,
            [c for r in requirements for c in (r.get("concept_ids") or [])]
            + list(state.focus_concepts),
        )
        rubrics = self._rubrics()
        scoreable = tuple(str(r["round_type"]) for r in rubrics) or (DEFAULT_ROUND_TYPE,)
        # The track the student picked is the only one asked about: an ML
        # interview that probes every round type and splits the time among
        # them asks DSA (2026-10-07). No track is a mixed interview.
        candidates = (state.track,) if state.track else scoreable
        round_types = self._available_round_types(row, state, candidates)
        plan = planner.assemble(
            planner.PlanInputs(
                session_id=row.id,
                mode=state.mode,
                requested_minutes=state.requested_minutes,
                jd_id=state.jd_id,
                coverage=coverage,
                requirements={str(r.get("id")): r for r in requirements if r.get("id")},
                available_round_types=round_types,
                claims=self._claims(row, state),
                hint_penalty=self._hint_penalty(rubrics, round_types),
                focus_concepts=tuple(state.focus_concepts),
                focus_label=state.focus_label,
                track=state.track,
                tracks=self._tracks(),
                resume_included=state.include_resume,
                resume_id=state.resume_id,
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

    def _claims(self, row: InterviewSession, state: SessionState) -> tuple[dict, ...]:
        """M01's risky and vague claims, for the project segment (§6.1).

        Only when the student asked for them (2026-10-07): an interview is
        not a resume review, and one that always opened on the resume was
        "too much into my resume … preventing me from actual interview
        content". From the resume they picked, when they picked one.

        Optional like every upstream: no M01, no resume, or a resume nobody
        has confirmed means no project segment — not a degraded one. A student
        with nothing shaky on their resume is not missing a feature.
        """
        up = self.upstreams
        if not state.include_resume or not up.available("M01"):
            return ()
        if state.resume_id is not None:
            try:
                found = up.m01.claims(state.resume_id, row.candidate_id)
            except (UpstreamUnavailable, KeyError, ValueError) as exc:
                log.info("M06: M01 claims unavailable for %s: %s", row.id, exc)
                return ()
            return tuple(found.get("claims") or [])
        try:
            resumes = up.m01.resumes_for(row.candidate_id)
            # The student's CURRENT resume: M01 marks it `is_active` (the one
            # they chose, or the newest that parsed). Until 2026-10-07 this
            # read a `status` field M01 never sends — the stub had invented it
            # — so the first resume in M01's list was taken, which for the
            # demo student was an old seed with no claims: no project round,
            # and no professor on the panel.
            chosen = (
                next((r for r in resumes if r.get("is_active") is True), None)
                or next((r for r in resumes if r.get("confirmed") is True), None)
                or (resumes[0] if resumes else None)
            )
            if chosen is None:
                return ()
            found = up.m01.claims(uuid.UUID(str(chosen["id"])), row.candidate_id)
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
                        # As `_select_from_bank` will ask: a track with only
                        # drafted items is still a track (FR-5.6 — asked,
                        # not scored).
                        "allow_drafts": True,
                    }
                )
            except UpstreamUnavailable as exc:
                log.info("M06: M05 availability probe failed for %s: %s", row.id, exc)
                return candidates
            if chosen is not None:
                served.append(round_type)
        return tuple(served)

    # ── what the setup page offers (2026-10-07) ──────────────────────────

    def offered_tracks(self) -> dict[str, Any]:
        """The tracks a student can pick: M05's, each a round type the bank
        holds questions for, and whether an answer in it can be scored — M13
        has a rubric for it and the bank has an approved item. A track with
        drafts only is still offered: it is practised, and says so.

        Without M05, the backup set's round types, and the sentence saying
        why the list is short."""
        up = self.upstreams
        note: str | None = None
        body: dict[str, Any] = {}
        if up.available("M05"):
            try:
                body = up.m05.tracks() or {}
            except UpstreamUnavailable as exc:
                log.info("M06: M05 tracks unavailable: %s", exc)
                note = up.on_missing("M05")
        else:
            note = up.on_missing("M05")
        if not body.get("tracks"):
            body = up.local_questions.tracks()
        scoreable = {str(r["round_type"]) for r in self._rubrics()}
        tracks = []
        for track in body.get("tracks") or []:
            round_type = str(track.get("round_type") or "")
            if not round_type:
                continue
            approved = int(track.get("approved") or 0)
            tracks.append(
                {
                    "round_type": round_type,
                    "title": track.get("title") or planner.round_type_title(round_type),
                    "group": track.get("group") or "Other",
                    "blurb": track.get("blurb") or "",
                    "kind": track.get("kind") or "technical",
                    "approved": approved,
                    "drafts": int(track.get("drafts") or 0),
                    "scored": round_type in scoreable and approved > 0,
                }
            )
        return {"groups": list(body.get("groups") or []), "tracks": tracks, "note": note}

    def resumes(self, candidate_id: uuid.UUID) -> dict[str, Any]:
        """The student's resumes, for the setup page's picker: newest first,
        by file name, the current one marked, and how many of its lines an
        interviewer would push on — a resume with none gets no project round,
        and the picker says so before the plan does."""
        up = self.upstreams
        if not up.available("M01"):
            return {"resumes": [], "note": up.on_missing("M01")}
        try:
            rows = up.m01.resumes_for(candidate_id)
        except UpstreamUnavailable as exc:
            log.info("M06: M01 resumes unavailable for %s: %s", candidate_id, exc)
            return {"resumes": [], "note": up.on_missing("M01")}
        return {
            "resumes": [
                {
                    "id": str(r["id"]),
                    "filename": r.get("filename"),
                    "created_at": r.get("created_at"),
                    "is_active": bool(r.get("is_active")),
                    "defendable": len(planner.defendable(r.get("claims") or [])),
                }
                for r in rows
                if r.get("id")
            ],
            "note": None,
        }

    def _tracks(self) -> dict[str, dict]:
        """M05's names for its tracks, by round type — what the plan calls a
        part and who runs it. Empty when M05 cannot say; the planner then
        names the round type itself."""
        up = self.upstreams
        if not up.available("M05"):
            return {}
        try:
            body = up.m05.tracks()
        except (UpstreamUnavailable, AttributeError) as exc:
            log.info("M06: M05 tracks unavailable: %s", exc)
            return {}
        return {str(t["round_type"]): t for t in body.get("tracks") or [] if t.get("round_type")}

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

    def _seed_for(self, row: InterviewSession, concepts: list[str]) -> None:
        """Seed M05 once per process, from M04's posterior for `concepts`.

        A concept M04 has measured nothing on comes back absent, never 0.0
        (M04 AC-4.2), and M05 seeds it at the prior — the honest belief.
        """
        if self.thetas.seeded(row.id):
            return
        posterior: dict[str, float] = {}
        wanted = sorted({c for c in concepts if c})
        if wanted and self.upstreams.available("M04"):
            try:
                posterior = self.upstreams.m04.posterior(row.candidate_id, wanted)
            except UpstreamUnavailable as exc:
                log.info("M06: M04 posterior unavailable for %s: %s", row.id, exc)
        self._seed_m05(row, posterior)

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

    def answer(
        self,
        session_id: uuid.UUID,
        question_turn_id: uuid.UUID,
        text: str,
        *,
        asr: dict | None = None,
    ) -> SessionState:
        row = self.row(session_id)
        self.back(session_id)
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
        payload = self._answer_payload(row, answer_index, question_turn_id, text, asr)
        # M11's FR-11.6: the thinking done while the student paused is used
        # only for these exact words — anything else and the model is asked.
        ahead = prefill.take(session_id, question_turn_id)
        if ahead is not None:
            used = ahead.text == text
            payload["prefill"] = {"tried": ahead.tried, "used": used}
            if used:
                ahead.done.wait(timeout=prefill.WAIT_S)
                self._replay = ahead.kept
        try:
            store.record(
                self.db,
                row,
                "answer.received",
                step="answer",
                turn_index=answer_index,
                payload=payload,
            )
        except InvalidTransition as exc:
            self._replay = None
            raise AnswerRejected(str(exc)) from exc
        try:
            return self.continue_session(session_id)
        finally:
            self._replay = None

    def _answer_payload(
        self,
        row: InterviewSession,
        answer_index: int,
        question_turn_id: uuid.UUID,
        text: str,
        asr: dict | None,
    ) -> dict:
        """What `answer.received` records — one shape for the answer and for
        the prefill that thinks ahead of it, so their requests can match."""
        return {
            "turn_id": str(_turn_id(row.id, answer_index)),
            "turn_index": answer_index,
            "text": text,
            "question_turn_id": str(question_turn_id),
            "completion_reason": "submit",
            "modality": "verbal",
            # M11's recogniser: how sure, and which words were not.
            **({"asr": asr} if asr else {}),
        }

    def prefill(
        self,
        session_id: uuid.UUID,
        question_turn_id: uuid.UUID,
        text: str,
        *,
        asr: dict | None = None,
    ) -> bool:
        """M11's FR-11.6: think about what the student has said so far, while
        they pause — in memory, writing nothing. The model's answers are kept
        by their exact requests for the answer that follows (`prefill.py`).
        False when there was nothing to think about."""
        row = self.row(session_id)
        state = self.state(session_id)
        asked = state.turn(question_turn_id)
        if (
            state.status is not SessionStatus.live
            or state.open_turn_id != question_turn_id
            or asked is None
            or state.retry_offer is not None
        ):
            return False
        now = self.clock()
        if degrade.circuit_open(state.flags.model_failures, state.flags.model_tried_at, now):
            return False  # the model is resting; nothing to get ready
        text = text[:MAX_ANSWER_CHARS]
        entry = prefill.begin(session_id, question_turn_id, text)
        try:
            answer_index = asked.turn_index + 1
            payload = self._answer_payload(row, answer_index, question_turn_id, text, asr)
            ahead = apply_event(state, "answer.received", payload, now, state.last_seq + 1)
            inp = StepInput(
                state=ahead,
                now=now,
                item=self._current_item(ahead),
                answer=text,
                recorded=None,
                # No selecting ahead: choosing the next question writes to the
                # log, and nothing here may. Its phrasing is asked for fresh.
                select=None,
            )
            run_step(compiled_step(prefill.Recording(self.llm, entry.kept)), inp)
        except Exception as exc:  # noqa: BLE001 - a failed prefill costs nothing
            log.info("M06: prefill for %s did not finish: %r", session_id, exc)
        finally:
            entry.done.set()
        return True

    def end(self, session_id: uuid.UUID, reason: str) -> SessionState:
        """A student pressing End gets the same closing line as running out of
        time. `session.ended` already carries one — the engine's own finish
        path fills it in — and leaving it empty here ended the first live
        session on a repeated question, with the interviewer saying nothing."""
        row = self.row(session_id)
        self.back(session_id)
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
                "closing_speaker_id": seated(state)[0].id,
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
        # The lead says goodbye, as they said hello — whoever was asking.
        said = seated(state)[0].said()
        return said.drill_close if state.kind == SessionKind.drill.value else said.session_close

    def _close_m05(self, row: InterviewSession, state: SessionState) -> None:
        if state.kind != SessionKind.mock.value:
            return
        self.thetas.drop(row.id)
        if self.upstreams.available("M05"):
            try:
                self.upstreams.m05.close(row.id, {}, candidate_id=row.candidate_id)
            except UpstreamUnavailable as exc:
                log.info("M06: M05 close failed for %s: %s", row.id, exc)

    # ── carrying on ──────────────────────────────────────────────────────

    def continue_session(self, session_id: uuid.UUID) -> SessionState:
        row = self.row(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.live or state.open_turn_id is not None:
            return state
        if state.retry_offer is not None:
            # §15.4: the student is choosing. Nothing is asked until they do.
            return state
        last = state.transcript[-1] if state.transcript else None
        if last is None or state.awaiting_next:
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
        self._changed_this_step = False
        item = self._current_item(state)
        inp = StepInput(
            state=state,
            now=now,
            item=item,
            answer=answer,
            recorded=recorded,
            select=self._selector(row),
        )
        # §10, EC-6.12: in panic the model is not asked, except for one turn
        # a minute to see whether it is back.
        llm = self.llm
        if degrade.circuit_open(state.flags.model_failures, state.flags.model_tried_at, now):
            llm = degrade.CIRCUIT_OPEN
        elif self._replay is not None:
            # FR-11.6: requests the prefill made for these exact words are
            # answered from what it kept; any other goes to the model.
            llm = prefill.Replaying(llm, self._replay)
        self._replay = None
        try:
            result = run_step(
                compiled_step(llm),
                inp,
                on_token=lambda token: self.tokens.publish(row.id, {"token": token}),
            )
        except Exception as exc:
            if self._step_crashed(row, state, exc):
                return  # §10 "Everything fails": ended, with the apology
            raise
        self._record_calls(row, state, result.calls)
        self._model_health(row, state, result.calls)
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
            # Words the recogniser could not make out, a word it was unsure
            # of, an answer to a question never heard: asked about, not scored
            # — the answer that follows is (M11's FR-11.16, EC-11.1).
            if result.outcome.move.kind not in UNJUDGED:
                self._owe(row, answer_turn, item)
        if result.offer_retry:
            self._offer_retry(row, result)
            return
        if result.closing_question and answer_turn is not None:
            # FR-6.21: in the student's own words, recorded; scoring them
            # waits on a rubric.
            store.record(
                self.db,
                row,
                "closing.question",
                step="closing-question",
                turn_index=answer_turn.turn_index,
                payload={"turn_id": str(answer_turn.turn_id), "text": answer_turn.text},
            )

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

    # ── the degradation ladder (§10, EC-6.12) ────────────────────────────

    def _model_health(self, row: InterviewSession, state: SessionState, calls) -> None:
        """Record whether this turn's model calls worked, and act on the rung
        it puts the session on: at L3, wrap up a little early."""
        ok = degrade.model_turn(calls)
        if ok is None:
            return
        recorded = store.record(
            self.db,
            row,
            "model.health",
            step=f"model:{state.last_seq}",
            payload={"ok": ok},
        )
        after = recorded.state
        wrapped = after.plan is not None and any(
            r.trigger == "degraded" for r in after.plan.replans
        )
        if not ok and not wrapped and degrade.at_least(after.flags.degradation_level, "L3"):
            self._wrap_up(row, after)

    def _wrap_up(self, row: InterviewSession, state: SessionState) -> None:
        """§8's "wrapping up a little early": the round in progress finishes
        and the closing stays; the rounds after it give way, and M02 hears
        `skipped` for them. Outside the two-re-plan cap — this is the session
        protecting the student, not the plan wandering."""
        from .contracts import Replan

        segment = current_segment(state)
        if state.plan is None or segment is None:
            return
        live = planner.live_segments(state.plan)
        position = next((i for i, s in enumerate(live) if s.index == segment.index), 0)
        later = {s.index for s in live[position + 1 :] if s.kind != "closing"}
        before = [s.model_copy(deep=True) for s in state.plan.segments]
        after = [s.model_copy(deep=True) for s in state.plan.segments]
        for s in after:
            if s.index in later:
                s.dropped_reason = (
                    "Left out to wrap up early — the interviewer's model was failing."
                )
        change = Replan(
            at_segment=segment.index,
            trigger="degraded",
            signals={"model_failures": float(state.flags.model_failures)},
            before=before,
            after=after,
            student_sentence=(
                "The interviewer's model kept failing, so I wrapped up early rather than run "
                "the rest of the plan on templates. The answers you gave are scored as usual."
            ),
            live_note=f"{degrade.BADGE}.",
        )
        self._record_plan_change(row, state, change)

    def _step_crashed(self, row: InterviewSession, state: SessionState, exc: Exception) -> bool:
        """§10 "Everything fails". The first crash is the caller's to retry —
        the answer is on the log and the next request finishes the step. The
        `ABORT_AFTER`th in a row ends the session honestly instead of leaving
        the student watching a spinner: aborted, the apology said, nothing
        still queued sent to be scored. True when it ended the session."""
        log.warning("M06: step crashed for %s: %r", row.id, exc)
        failures = state.flags.step_failures + 1
        recorded = store.record(
            self.db,
            row,
            "step.failed",
            step=f"crash:{state.last_seq}:{failures}",
            payload={"error": type(exc).__name__, "detail": str(exc)[:200]},
        )
        if recorded.state.flags.step_failures < degrade.ABORT_AFTER:
            return False
        state = recorded.state
        closing_index = state.next_turn_index
        store.record(
            self.db,
            row,
            "session.aborted",
            step="end",
            payload={
                "reason": "system_failure",
                "closing_text": degrade.APOLOGY,
                "closing_turn_id": str(_turn_id(row.id, closing_index)),
                "closing_turn_index": closing_index,
            },
        )
        outbox.void_evaluations(self.db, row.id, "the session failed on our side")
        self._close_m05(row, self.state(row.id))
        return True

    # ── the rolling summary (FR-6.16, spec §6.6) ─────────────────────────

    def summarise_if_due(self, session_id: uuid.UUID) -> bool:
        """Rewrite §6.6's round note when four turns have passed.

        Called from the background task that already follows an answer, so it
        is ready for the next turn and costs that turn nothing. A note one
        cycle stale is a rolling summary working; a note that delays the next
        question is a latency bug.
        """
        row = self.row(session_id)
        state = self.state(session_id)
        if state.is_final or not summariser.is_due(state.next_turn_index - state.summary_at_turn):
            return False
        # The turns of THIS segment only: the note is a round summary, and a
        # bridge already clears it when the round changes.
        turns = [t for t in state.transcript if t.segment_index == state.current_segment]
        written = Summariser(self.llm, enabled=enabled("ReportComposer")).write(turns)
        if written.call is not None:
            self._record_calls(row, state, [written.call])
        if not written.text:
            log.info("M06: no summary for %s (%s)", session_id, written.fallback_reason)
            return False
        store.record(
            self.db,
            row,
            "summary.written",
            step=f"summary:{state.next_turn_index}",
            payload={"text": written.text, "at_turn": state.next_turn_index},
        )
        return True

    # ── hints (FR-6.7, master plan §32.5) ────────────────────────────────

    def hint(self, session_id: uuid.UUID) -> SessionState:
        """Give the hint the student asked for, at the published price.

        Asked for explicitly, by a button, rather than inferred from the words
        of an answer. The strategist's `asks_for_answer` still works and is
        how somebody who simply types "can I have a hint" gets one — but a
        student should not have to phrase a request to use a feature.
        """
        row = self.row(session_id)
        self.back(session_id)
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
        if answer_turn.retry:
            # §15.4: a retry is practice on top of the measurement. It owes
            # M13 nothing (the first attempt is scored) and M02 nothing (the
            # requirement was already asked and answered once).
            return
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
                # EC-6.4: counted by the fold; the second ends the session.
                "conduct": outcome.conduct,
                # EC-6.6: what the guard found. Trace only — `public.py`
                # passes the move and nothing else to a browser.
                "screen": result.screen.as_payload() if result.screen else None,
            },
        )
        flagged = result.screen is not None and result.screen.injection
        if (
            verdict is not None
            and verdict.source == "model"
            and item is not None
            and item.source == "m05_bank"
            and item.concept_id
            # An answer that talked to the system moves no θ: its verdict may
            # be the one it asked for (EC-6.6). A retry moves none either —
            # the first attempt is the measurement (§15.4).
            and not flagged
            and not answer_turn.retry
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
                value = self.upstreams.m05.observe(
                    row.id, concept_id, outcome, candidate_id=row.candidate_id
                )
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
            spoken = list(utterance.parts) if utterance else []
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
                    "closing_speaker_id": spoken[-1][0] if spoken else speaker(state).id,
                    "closing_parts": _parts_payload(spoken),
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
            else (0 if result.new_question or item.source == "closing" else ladder_depth)
        )
        index = state.next_turn_index
        segment = (
            state.plan.segments[state.current_segment]
            if state.plan is not None and state.current_segment < len(state.plan.segments)
            else None
        )
        # Who says it (FR-6.3): the graph names each voice of a panel line;
        # a line it did not split is the segment's interviewer's.
        spoken = list(utterance.parts)
        if spoken:
            speaker_id = spoken[-1][0]
        elif segment is not None and segment.persona_id:
            speaker_id = segment.persona_id
        else:
            speaker_id = speaker(state).id
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
                "nudged": result.nudged,
                "speaker_id": speaker_id,
                "parts": _parts_payload(spoken),
            },
        )

    def _offer_retry(self, row: InterviewSession, result: StepResult) -> None:
        """§15.4: say the exit and the offer; open nothing until they choose."""
        state = self.state(row.id)
        asked = state.open_question_turn()
        if asked is None or result.utterance is None:
            return
        index = state.next_turn_index
        store.record(
            self.db,
            row,
            "retry.offered",
            step="retry-offer",
            turn_index=index,
            payload={
                "turn_id": str(_turn_id(row.id, index)),
                "turn_index": index,
                "segment_index": state.current_segment,
                "text": result.utterance.text,
                "of": str(asked.turn_id),
                "item": state.current_item,
                "speaker_id": speaker(state).id,
            },
        )

    # ── §15.4: the student's choice ──────────────────────────────────────

    def retry(self, session_id: uuid.UUID) -> SessionState:
        """Take the offered retry: the same question, a fresh ladder, not scored."""
        row = self.row(session_id)
        self.back(session_id)
        state = self.state(session_id)
        offer = state.retry_offer
        if offer is None:
            raise InvalidTransition("There is no retry on offer.")
        original = state.turn(uuid.UUID(offer["of"]))
        item = from_dict(offer["item"]) if offer.get("item") else None
        if original is None or item is None:
            raise InvalidTransition("That question can't be asked again.")
        lead = speaker(state).said().retry_lead
        index = state.next_turn_index
        store.record(
            self.db,
            row,
            "question.asked",
            step="retry",
            turn_index=index,
            payload={
                "turn_id": str(_turn_id(row.id, index)),
                "turn_index": index,
                "segment_index": state.current_segment,
                "text": f"{lead} {item.stem}",
                "question_text": item.stem,
                "question_id": str(item.question_id) if item.question_id else None,
                "question_source": original.question_source,
                "rubric_round_type": item.rubric_round_type,
                "concept_id": item.concept_id,
                "probe_depth": 0,
                "probe_move": None,
                "modality": "verbal",
                "new_question": True,
                "retry": True,
                "retry_of": str(original.turn_id),
                "item": to_dict(item),
                "utterance_source": "template",
            },
        )
        return self.state(session_id)

    def move_on(self, session_id: uuid.UUID) -> SessionState:
        """Take the next question: declining a retry (§15.4), or taking the
        interviewer's offer after a silence (EC-6.1). At the closing, taking
        that offer ends the session — there is nothing after the closing."""
        row = self.row(session_id)
        self.back(session_id)
        state = self.state(session_id)
        if state.retry_offer is not None:
            store.record(
                self.db,
                row,
                "retry.declined",
                step="retry-declined",
                turn_index=state.next_turn_index,
            )
            return self.continue_session(session_id)
        asked = state.turn(state.open_turn_id) if state.open_turn_id is not None else None
        if not state.idle_offer or asked is None:
            raise InvalidTransition("There is nothing to move on from.")
        store.record(
            self.db,
            row,
            "idle.moved_on",
            step="idle-moved-on",
            turn_index=asked.turn_index,
            payload={
                "for": str(asked.turn_id),
                # §6.4 counts these per round, as silences.
                "segment_index": asked.segment_index,
                "closing": asked.question_source == "closing",
            },
        )
        return self.continue_session(session_id)

    def skip(self, session_id: uuid.UUID, question_turn_id: uuid.UUID) -> SessionState:
        """The student skips the open question (2026-10-07): "if a candidate
        skips a question another question should come as replacement — 2
        skips of same question number means points go down".

        At a question's opening, the first skip at its number brings a
        different question at the same number, and the skipped one costs
        nothing. Skipping that one too leaves it: it counts against the
        segment's questions, as not answered, and the session's estimate for
        its concept goes down (`_count_unanswered`) — so what follows is
        pitched lower, as it would be after a failed answer. Past the
        opening, with a follow-up open, a skip is moving on: the question was
        answered once and counts as asked, with nothing against it.

        `question_turn_id` is the line the student meant: a double-click or a
        retried request names a line that has moved on, and is refused rather
        than skipping the replacement too.
        """
        row = self.row(session_id)
        self.back(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.live:
            raise InvalidTransition("The interview isn't running.")
        if state.kind == SessionKind.drill.value:
            raise InvalidTransition("A drill is one question — end it instead.")
        if state.open_turn_id is None or state.open_turn_id != question_turn_id:
            raise InvalidTransition("That question has already moved on.")
        asked = state.turn(state.open_turn_id)
        question = state.open_question_turn()
        if asked is None or question is None or "closing" in (
            asked.question_source,
            question.question_source,
        ):
            raise InvalidTransition("This part is for your questions — there's nothing to skip.")
        follow_up = state.ladder is not None and state.ladder.depth > 0
        number = state.questions_asked
        replaced = not follow_up and state.skips_at.get(number, 0) == 0
        store.record(
            self.db,
            row,
            "question.skipped",
            step=f"skip:{asked.turn_index}",
            turn_index=asked.turn_index,
            payload={
                "for": str(asked.turn_id),
                "question_turn": str(question.turn_id),
                "number": number,
                "segment_index": question.segment_index,
                "concept_id": question.concept_id,
                "replaced": replaced,
                "follow_up": follow_up,
            },
        )
        if not follow_up and not replaced:
            self._count_unanswered(row, question)
        return self.continue_session(session_id)

    def _count_unanswered(self, row: InterviewSession, question) -> None:
        """A question skipped twice is not answered, and the session's
        estimate says so: a `below` for its concept, FR-6.25's route.

        Only for an approved bank item, as for any verdict — a drafted or
        backup question moves no θ (FR-5.6), and a resume probe has no
        concept M05 estimates. The estimate is the session's own; what moves
        the student's skill graph is M13 scoring an answer, and a skip is no
        answer (the notes say it counted)."""
        if question.question_source != "m05_bank" or not question.concept_id:
            return
        self._observe(row, question.turn_id, question.concept_id, _DECLINED)

    def idle(self, session_id: uuid.UUID, question_turn_id: uuid.UUID, n: int) -> SessionState:
        """EC-6.1: the student has gone quiet. One gentle prompt, a second,
        then the offer to move on — and never a fourth ("never loop forever").

        The browser says when, because it knows about typing and the server
        does not. The server decides what, and holds a floor: prompt `n`
        needs `n` times the interviewer's patience since the line was asked,
        so a page cannot talk the interviewer into skipping a question early.
        `n` is the prompt the browser expects, which makes a retried request
        a no-op rather than a second prompt (AC-6.16).
        """
        row = self.row(session_id)
        self.back(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.live:
            raise InvalidTransition("The interview isn't running.")
        if state.open_turn_id is None or state.open_turn_id != question_turn_id:
            raise InvalidTransition("That question has already been answered.")
        if n <= state.idle_prompts:
            return state
        if n != state.idle_prompts + 1 or state.idle_offer:
            raise InvalidTransition("That prompt isn't next.")
        asked = state.turn(state.open_turn_id)
        who = speaker(state)
        quiet_s = (self.clock() - asked.at).total_seconds()
        if quiet_s < who.idle_after_s * n:
            raise InvalidTransition("Not yet — there's still time on this one.")
        said = who.said()
        offer = n >= IDLE_OFFER_AT
        if not offer:
            line = said.idle_first if n == 1 else said.idle_second
        elif asked.question_source == "closing":
            line = said.idle_offer_closing
        else:
            line = said.idle_offer
        store.record(
            self.db,
            row,
            "idle.prompted",
            step=f"idle:{n}",
            turn_index=asked.turn_index,
            payload={"for": str(asked.turn_id), "n": n, "line": line, "offer": offer},
        )
        return self.state(session_id)

    def repeat(self, session_id: uuid.UUID) -> TurnView:
        """§7 "say that again": the open question, verbatim — never a new
        phrasing, which could change what is being asked, and never a turn,
        so the answer box still answers the question it was asked.

        Recorded once per question for the trace; asking again returns the
        same words without writing anything.
        """
        row = self.row(session_id)
        self.back(session_id)
        state = self.state(session_id)
        asked = state.open_question_turn() if state.open_turn_id is not None else None
        if state.status is not SessionStatus.live or asked is None:
            raise InvalidTransition("There's no question open to repeat.")
        store.record(
            self.db,
            row,
            "question.repeated",
            step=f"repeat:{asked.turn_index}",
            turn_index=asked.turn_index,
            payload={"for": str(asked.turn_id)},
        )
        return asked

    def heard(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, part_index: int | None, heard: float
    ) -> SessionState:
        """M11's FR-11.9: the student started speaking over an interviewer line
        — here, in this part, this far through. Recorded once per line: the
        first cut is the one that happened."""
        row = self.row(session_id)
        state = self.state(session_id)
        turn = state.turn(turn_id)
        if turn is None or turn.role != "interviewer":
            raise InvalidTransition("That line is not an interviewer's.")
        store.record(
            self.db,
            row,
            "turn.heard",
            step=f"heard:{turn.turn_index}",
            turn_index=turn.turn_index,
            payload={"turn_id": str(turn_id), "part_index": part_index, "heard": heard},
        )
        return self.state(session_id)

    def flag(
        self, session_id: uuid.UUID, question_turn_id: uuid.UUID, reason: str, note: str
    ) -> dict[str, Any]:
        """§7's ⚑: the student says a question is broken. Forwarded to M05,
        which owns the item and excludes it from selection (FR-5.19); recorded
        here either way, so a flag M05 never heard about is still on the log
        and the student is told which of the two happened."""
        row = self.row(session_id)
        state = self.state(session_id)
        asked = state.turn(question_turn_id)
        if (
            asked is None
            or asked.role != "interviewer"
            or asked.question_id is None
            or asked.question_source not in M05_OWNED
        ):
            raise InvalidTransition("Only a question from the bank can be flagged.")
        forwarded = False
        if self.upstreams.available("M05"):
            try:
                self.upstreams.m05.flag(asked.question_id, reason, note, row.candidate_id)
                forwarded = True
            except UpstreamUnavailable as exc:
                log.info("M06: M05 flag failed for %s: %s", asked.question_id, exc)
        store.record(
            self.db,
            row,
            "question.flagged",
            step=f"flag:{asked.question_id}",
            turn_index=asked.turn_index,
            payload={
                "question_id": str(asked.question_id),
                "reason": reason,
                "forwarded": forwarded,
            },
        )
        return {"question_id": str(asked.question_id), "forwarded": forwarded}

    def switch_modality(self, session_id: uuid.UUID, to: str) -> SessionState:
        """FR-6.11: the contract is fixed now; Phase 1 has one modality. A
        switch to it is a no-op, and a switch to anything else says which
        module it is waiting on, rather than pretending."""
        self.row(session_id)
        state = self.state(session_id)
        if to not in {m.value for m in PHASE1_MODALITIES}:
            waiting = {"coding": "the code editor (M07)", "design": "the design canvas (M08)"}
            raise InvalidTransition(
                f"Only typed answers for now — {waiting.get(to, to)} isn't built yet."
            )
        return state

    def interrupted(self, session_id: uuid.UUID, *, away: bool) -> SessionState:
        """M11's EC-11.12: the device took the microphone — a phone call, most
        often — and, later, gave it back. The clock stops as for a lost
        connection: not a pause, which is the student's to spend. It restarts
        on the way back with no grace; the room has already counted the
        student back in (its five-second re-entry)."""
        row = self.row(session_id)
        state = self.state(session_id)
        if state.status is not SessionStatus.live:
            return state
        try:
            if away:
                if state.flags.away_since is not None:
                    return state  # already away: the stream went first
                n = state.flags.interruptions + 1
                return store.record(
                    self.db,
                    row,
                    "connection.lost",
                    step=f"interrupted:{n}",
                    payload={"reason": "interruption"},
                ).state
            if state.flags.away_since is None:
                return state
            away_s = max((self.clock() - state.flags.away_since).total_seconds(), 0.0)
            return store.record(
                self.db,
                row,
                "connection.resumed",
                step=f"interruption-back:{state.flags.interruptions}",
                payload={"grace_s": 0.0, "away_s": round(away_s, 1), "reason": "interruption"},
            ).state
        except (InvalidTransition, store.ConcurrentWrite):
            return self.state(session_id)

    def back(self, session_id: uuid.UUID, *, grace_s: float = 0.0) -> SessionState | None:
        """The student is here (§6.8). From an action the clock restarts at
        once; the stream re-attaching passes the 30-second grace instead."""
        return presence.back(self.db, session_id, self.clock(), grace_s=grace_s)

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
        def select_next(state: SessionState, now: datetime, pending=None) -> Selected:
            return self._select(row, state, now, pending)

        return select_next

    def segment(self, state: SessionState) -> PlannedSegment | None:
        """The segment being run — see `current_segment`."""
        return current_segment(state)

    def _advance_segment(
        self,
        row: InterviewSession,
        state: SessionState,
        now: datetime,
        pending: dict | None = None,
    ) -> tuple[SessionState, str | None]:
        """Move on when a round is done — by its questions, or by its clock.

        Three reasons to leave a round, checked at a question boundary and
        never mid-ladder (§6.9: no hard cut):

          * it has had the questions M02 priced for it (day 5);
          * its own clock is over by the mode's allowance — 25%, 0% in Final
            Boss (EC-6.9, FR-6.9's hard clock);
          * the session's clock says the closing is due (§6.9's 90%), in
            which case everything between here and the closing gives way to
            it, and M02 hears `skipped` for what will not be asked.

        At each ordinary boundary §6.4 gets its one chance to re-plan.
        """
        if state.plan is None or not planner.live_segments(state.plan):
            return state, None
        bridge: str | None = None
        allowance = mode_config(state.mode).overrun_allowance
        for _ in range(_MAX_SEGMENT_SKIPS):
            live = planner.live_segments(state.plan)
            position = next((i for i, s in enumerate(live) if s.index == state.current_segment), 0)
            if position + 1 >= len(live):
                break
            leaving = live[position]
            if leaving.kind == "closing":
                break
            closing = pacing.closing_segment(state)
            if closing is not None and pacing.read(state, now).closing_due:
                state, bridge = self._jump_to_closing(row, state, now, leaving, closing)
                break
            exhausted = state.questions_in_segment(leaving.index) >= leaving.question_budget
            timed_out = pacing.over_time(state, leaving, now, allowance)
            if not (exhausted or timed_out):
                break
            state = self._replan_at(row, state, leaving, now, pending)
            live = planner.live_segments(state.plan)
            position = next((i for i, s in enumerate(live) if s.index == leaving.index), None)
            if position is None or position + 1 >= len(live):
                break
            arriving = live[position + 1]
            state = self._record_transition(
                row, state, now, leaving, arriving, reason="time" if timed_out else "budget"
            )
            bridge = state.pending_bridge
        return state, bridge

    def _record_transition(
        self,
        row: InterviewSession,
        state: SessionState,
        now: datetime,
        leaving: PlannedSegment,
        arriving: PlannedSegment,
        *,
        reason: str,
        forced_by_time: bool = False,
    ) -> SessionState:
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
                "line": bridge_line(
                    arriving,
                    introduced(state),
                    forced_by_time=forced_by_time,
                    panel=len(seated(state)) > 1,
                ),
                "reason": reason,
                # The round's own clock starts here (EC-6.9). The writer
                # supplies it: the fold has no clock.
                "used_s": round(state.time_used_s(now), 1),
            },
        )
        return self.state(row.id)

    def _jump_to_closing(
        self,
        row: InterviewSession,
        state: SessionState,
        now: datetime,
        leaving: PlannedSegment,
        closing: PlannedSegment,
    ) -> tuple[SessionState, str | None]:
        """§6.9's 90%: the closing is reserved, so whatever is left gives way.

        The rounds skipped are not dropped from the plan — they were planned,
        and the report says so — but M02's ledger hears `skipped` for their
        requirements, because nothing will ask about them now.
        """
        live = planner.live_segments(state.plan)
        position = next((i for i, s in enumerate(live) if s.index == leaving.index), 0)
        skipped = [
            r for s in live[position + 1 :] if s.kind != "closing" for r in s.requirement_ids
        ]
        state = self._record_transition(
            row, state, now, leaving, closing, reason="closing_due", forced_by_time=True
        )
        if skipped:
            outbox.enqueue_ledger(
                self.db, state, requirement_ids=skipped, ledger_state="skipped", turn_id=None
            )
            self.db.commit()
        return state, state.pending_bridge

    def _replan_at(
        self,
        row: InterviewSession,
        state: SessionState,
        leaving: PlannedSegment,
        now: datetime,
        pending: dict | None = None,
    ) -> SessionState:
        """§6.4 at a boundary: at most one change, from hot-path signals only.

        And at most one per step. A 70% narrowing in this same step has
        already changed the plan for the clock, and the clock is what a
        boundary answers first anyway (`replan.evaluate` checks
        `time_overrun` before anything else). Two changes at one crossing is
        two live notes at once and a plan that wanders (Trap 4).
        """
        if self._changed_this_step:
            return state
        found = replan.evaluate(
            state, self._log_with(row, pending), leaving, now, self._concept_lookup()
        )
        if found is None:
            return state
        return self._record_plan_change(row, state, found)

    def _log_with(self, row: InterviewSession, pending: dict | None) -> list:
        """The log, plus this step's decision as the event it is about to be."""
        log_ = list(store.events_for(self.db, row.id))
        if pending is not None:
            last = log_[-1].seq if log_ else 0
            log_.append(
                SimpleNamespace(
                    seq=last + 1,
                    kind="probe.decided",
                    turn_index=pending["turn_index"],
                    payload=pending["payload"],
                )
            )
        return log_

    def _record_plan_change(
        self, row: InterviewSession, state: SessionState, change
    ) -> SessionState:
        self._changed_this_step = True
        plan = state.plan.model_copy(deep=True)
        plan.segments = [s.model_copy(deep=True) for s in change.after]
        plan.replans = [*plan.replans, change]
        store.record(
            self.db,
            row,
            "plan.changed",
            step=f"replan:{len(plan.replans)}",
            payload={"plan": plan.model_dump(mode="json"), "live_note": change.live_note},
        )
        state = self.state(row.id)
        dropped_before = {s.index for s in change.before if s.dropped_reason is not None}
        dropped = [
            r
            for s in change.after
            if s.dropped_reason is not None and s.index not in dropped_before
            for r in s.requirement_ids
        ]
        if dropped:
            # FR-6.24: planned, then dropped by a re-plan — M02 hears it.
            outbox.enqueue_ledger(
                self.db, state, requirement_ids=dropped, ledger_state="skipped", turn_id=None
            )
            self.db.commit()
        return state

    def _concept_lookup(self):
        """M04's ontology, one call per concept per step, and nothing if M04
        is not there — the gap trigger then simply does not fire."""
        cache: dict[str, dict | None] = {}

        def lookup(concept_id: str) -> dict | None:
            if concept_id not in cache:
                found = None
                if self.upstreams.available("M04"):
                    try:
                        found = self.upstreams.m04.concept(concept_id)
                    except (UpstreamUnavailable, AttributeError):
                        found = None
                cache[concept_id] = found
            return cache[concept_id]

        return lookup

    # ── pacing (FR-6.17, §6.9, §2.3) ─────────────────────────────────────

    def _pace(self, row: InterviewSession, state: SessionState, now: datetime) -> SessionState:
        """§6.9's checkpoints: announced once each, and acted on at 70%.

        Not acted on when the closing is already due: a focus line about a
        round that is about to give way to the closing would be the
        interviewer contradicting itself in one breath.
        """
        closing_due = pacing.read(state, now).closing_due
        for mark in pacing.warnings_due(state, now):
            payload: dict = {"at": mark}
            if mark == pacing.WARN_AT[0] and not closing_due:
                state, extra = self._at_seventy(row, state, now)
                payload |= extra
            store.record(self.db, row, "time.warning", step=f"time:{mark}", payload=payload)
            state = self.state(row.id)
        return state

    def _at_seventy(
        self, row: InterviewSession, state: SessionState, now: datetime
    ) -> tuple[SessionState, dict]:
        """§2.3's pace check: more planned than time → narrow, and say so.

        Practice OFFERS and forces nothing (§6.1's table), so it only says
        how long is left. Ahead of schedule, the round may go one follow-up
        deeper (§6.9).
        """
        reading = pacing.read(state, now)
        minutes = max(1, round(reading.time_for_questions_s / 60))
        said = speaker(state).said()
        segment = current_segment(state)
        if reading.coverage_debt and segment is not None:
            if not mode_config(state.mode).pacing_enforced:
                return state, {"line": said.pace_note.format(minutes=minutes)}
            state, focus = self._narrow(row, state, reading, segment)
            return state, {
                "line": said.pace_focus.format(minutes=minutes, topic=focus.title),
                "focus": focus.index,
            }
        if reading.ahead_by >= 1:
            return state, {"extra_depth": True}
        return state, {}

    def _narrow(self, row, state: SessionState, reading, segment: PlannedSegment):
        """Keep what fits, by M02's priority; drop the rest out loud."""
        from .contracts import Replan

        plan = state.plan
        remaining = pacing.remaining_segments(state)
        future = [s for s in remaining if s.index != segment.index]
        owed_now = max(segment.question_budget - state.questions_in_segment(segment.index), 0)
        available = (
            reading.time_for_questions_s - owed_now * planner.MINUTES_PER_VERBAL_QUESTION * 60
        )
        priority = _priorities(plan)
        per_question_s = planner.MINUTES_PER_VERBAL_QUESTION * 60
        kept, dropped = [], []
        trimmed: dict[int, int] = {}
        for candidate in sorted(future, key=lambda s: -priority.get(s.index, 0.0)):
            cost = candidate.question_budget * per_question_s
            if cost <= available:
                kept.append(candidate)
                available -= cost
            elif not kept and not owed_now and available >= MIN_SECONDS_FOR_A_QUESTION:
                # Nothing fits whole: the most important round is trimmed to
                # what does, rather than every round dropped and the student
                # sent straight to the closing — found by the day-10 tests.
                trimmed[candidate.index] = max(1, int(available // per_question_s))
                kept.append(candidate)
                available = 0.0
            else:
                dropped.append(candidate)
        focus = segment if owed_now or not kept else kept[0]
        if (not dropped and not trimmed) or len(plan.replans) >= replan.MAX_REPLANS:
            return state, focus
        before = [s.model_copy(deep=True) for s in plan.segments]
        after = [s.model_copy(deep=True) for s in plan.segments]
        gone = {s.index for s in dropped}
        for s in after:
            if s.index in gone:
                s.dropped_reason = "Left out at the 70% mark to fit the time that was left."
            if s.index in trimmed:
                s.question_budget = trimmed[s.index]
                s.minutes = round(trimmed[s.index] * planner.MINUTES_PER_VERBAL_QUESTION, 1)
        titles = ", ".join(f"“{s.title}”" for s in dropped) or "part of the plan"
        change = Replan(
            at_segment=segment.index,
            trigger="time_overrun",
            signals={
                "fraction_used": round(reading.fraction, 3),
                "questions_owed": float(reading.questions_owed),
                "minutes_left": round(reading.time_for_questions_s / 60, 1),
            },
            before=before,
            after=after,
            student_sentence=(
                f"At the 70% mark there was more planned than time, so I left out {titles} to "
                f"finish “{focus.title}” properly and keep your time at the end."
            ),
            live_note=f"Adjusting — focusing on {focus.title} with the time left.",
        )
        return self._record_plan_change(row, state, change), focus

    # ── FR-6.21: the closing ─────────────────────────────────────────────

    def _closing_item(self, state: SessionState, bridge: str | None) -> Selected:
        """The closing asks the student to ask. Once; the reply node does the rest."""
        if state.closing_asked > 0:
            return Selected(None, empty_reason="plan_complete", bridge=bridge)
        item = Item(stem="", source="closing", concept_id="closing", label="Your questions")
        return Selected(
            item, {"reason": "closing"}, bridge=bridge, persona=arriving_speaker(state)
        )

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

    def _select(
        self,
        row: InterviewSession,
        state: SessionState,
        now: datetime,
        pending: dict | None = None,
    ) -> Selected:
        """The next question, or why there is none — and a 409 ends a SEGMENT.

        M05 answering "nothing left for this round type" is a known state with
        a specified behaviour (M05 §6.8), not a crash and not the end of the
        interview: §6.1's plan-time probe should have caught it, and when it
        did not, the honest thing is to close that round and open the next
        one. Ending the whole session on it would throw away the segments
        behind it, which is how a thin corner of the bank becomes a short
        interview about nothing.
        """
        state = self._pace(row, state, now)
        state, bridge = self._advance_segment(row, state, now, pending)
        segment = self.segment(state)
        if segment is not None and segment.kind == "closing":
            return self._closing_item(state, bridge)
        if segment is not None and state.time_remaining_s(now) < MIN_SECONDS_FOR_A_QUESTION:
            # No time for a real answer: the closing is reserved, so it runs
            # anyway (FR-6.17) — "at 100%: wrap-up utterance, no hard cut".
            closing = pacing.closing_segment(state)
            if closing is None:
                return Selected(None, empty_reason="time", bridge=bridge)
            state, bridge = self._jump_to_closing(row, state, now, segment, closing)
            return self._closing_item(state, bridge)
        if (
            segment is not None
            and state.questions_in_segment(segment.index) >= segment.question_budget
        ):
            # The last round is spent and there is no closing after it — the
            # plan is done. (Every plan has a closing today; an old one may not.)
            return Selected(None, empty_reason="plan_complete", bridge=bridge)
        for _ in range(_MAX_SEGMENT_SKIPS):
            found = self._select_from_bank(row, state, now)
            if found.item is not None:
                # Whoever runs the segment the item belongs to asks it — read
                # here because the step's own state predates the crossing.
                return replace(
                    found,
                    bridge=bridge or found.bridge,
                    persona=arriving_speaker(state),
                    pace_line=state.pending_pace_line,
                )
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
        state = self._record_transition(
            row, state, self.clock(), leaving, arriving, reason=reason or "bank_exhausted"
        )
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
        if segment is not None and segment.kind == "closing":
            return self._closing_item(state, None)
        if segment is not None and segment.kind == "project":
            return self._select_a_claim(state)
        up = self.upstreams
        round_type = self._round_type(state)
        segment = self.segment(state)
        # M05 §6.6 has two filters, and they are not the same thing. Asked in
        # THIS interview is never asked again — the hard one. Asked in the
        # student's recent history is freshness, which M05 may relax when the
        # bank runs thin, and then says so. Until 2026-10-06 both carried the
        # history: for a student who had seen the bank, relaxing could not
        # help, M05 fell to its playlist, and a live run heard the same
        # question at the warm-up and at the next two rounds.
        asked_here = {str(t.question_id) for t in state.transcript if t.question_id is not None}
        recent = {str(i) for i in store.seen_item_ids(self.db, row.candidate_id, now=now)}
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
            "seen_item_ids": sorted(asked_here),
            "recent_item_ids": sorted(recent | asked_here),
            "time_remaining_s": int(state.time_remaining_s(now)),
            "is_first_of_round": state.questions_asked == 0,
            "round_progress": min(state.questions_asked / question_budget(state), 1.0),
            "modality_allowed": ["verbal"],
            # 2026-10-07: twelve approved items, eleven of them DSA, made
            # every interview the same handful. A drafted item is asked when
            # nothing approved fits, and M05 says so (`scored_use`); it is
            # then practised, never scored and never moves θ (FR-5.6).
            "allow_drafts": True,
        }
        degraded: dict[str, str] = {}
        if up.available("M05"):
            try:
                chosen = up.m05.select(request)
                if chosen is None:
                    return Selected(None, empty_reason="bank_exhausted")
                if str(chosen["question_id"]) not in asked_here:
                    question = up.m05.question(uuid.UUID(str(chosen["question_id"])))
                    if chosen.get("scored_use") is False:
                        source = "m05_draft"
                    elif chosen.get("reason") == "fallback":
                        source = "m05_fallback"
                    else:
                        source = "m05_bank"
                    item = from_m05(question, round_type=chosen["round_type"], source=source)
                    return Selected(item, chosen)
                # A question this interview has already asked: never again,
                # whoever offers it. M06's own playlist below, or the round ends.
                log.info("M06: M05 offered %s again in %s", chosen["question_id"], row.id)
            except UpstreamUnavailable as exc:
                log.info("M06: M05 selection failed for %s: %s", row.id, exc)
                degraded["M05"] = up.on_missing("M05")
        else:
            degraded["M05"] = up.on_missing("M05")

        # §10: M06's own playlist. Never repeats within this session.
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
    "current_segment",
    "ladder_config",
    "retry_allowed",
    "speaker",
    "SessionNotFound",
    "ThetaCache",
    "compiled_step",
    "question_budget",
    "theta_cache",
]


@dataclass(frozen=True)
class _Declined:
    """What a second skip tells M05: not answered — a `below`, held with
    the confidence of a plain fail, not of an answer judged wrong."""

    band: str = "below"
    confidence: float = 0.6
    latency_ms: int = 0


_DECLINED = _Declined()


def _priorities(plan: InterviewPlan) -> dict[int, float]:
    """segment index -> M02's highest priority among its requirements.

    M02 priced the rounds; its priorities are what a narrowing keeps by. A
    segment M02 did not price (warm-up, project) keeps its place by order.
    """
    by_requirement: dict[str, float] = {}
    for allocation in (plan.coverage_plan or {}).get("allocations") or []:
        rid = str(allocation.get("requirement_id") or "")
        try:
            by_requirement[rid] = max(
                by_requirement.get(rid, 0.0), float(allocation.get("priority") or 0.0)
            )
        except (TypeError, ValueError):
            continue
    out: dict[int, float] = {}
    for position, segment in enumerate(plan.segments):
        values = [by_requirement.get(r, 0.0) for r in segment.requirement_ids]
        # Earlier segments win a tie: M02 ordered its rounds by priority too.
        out[segment.index] = (max(values) if values else 0.0) - position * 1e-6
    return out
