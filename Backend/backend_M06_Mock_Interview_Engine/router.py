"""M06 routes — spec §7, Revision 2.

Every route except `/v1/deps` and `/v1/agents` names a student, and
`enforce_access` sits on the router so none can be written without it
(FR-6.26). `POST /drills` and `POST /sessions` name the student in the BODY,
and check it in the handler.

Routes do not write sessions; `engine.Engine` does, through `store.record()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime

from ai_core.db import engine as db_engine
from ai_core.db import get_session
from ai_core.dependencies import DependencyStatus
from ai_core.identity import Principal, Role
from ai_core.timeutil import utcnow
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import degrade, outbox, presence, store
from . import report as report_module
from .access import enforce_access, require_candidate
from .adapters import Upstreams, get_upstreams
from .broker import broker
from .contracts import (
    HintOffer,
    InterviewPlan,
    Mode,
    SessionFlags,
    SessionKind,
    SessionStatus,
    TurnView,
)
from .dependencies import deps
from .engine import (
    MAX_ANSWER_CHARS,
    AnswerRejected,
    Engine,
    SessionNotFound,
    compiled_step,
    hint_offer,
    speaker,
    welcome_line,
)
from .llm import get_llm
from .models import InterviewSession, LLMCall, SessionEvent
from .modes import MODES, mode_config
from .orchestration import mermaid, snapshot
from .personas import personas
from .public import public_event
from .state import InvalidTransition, SessionState

log = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/v1", tags=["M06 Mock Interview Engine"], dependencies=[Depends(enforce_access)]
)

#: FR-6.12.
PAUSE_LIMIT_S = 5 * 60
#: §6.8: turns a returning page shows before the full transcript loads.
RESUME_TAIL = 6
#: A session shorter than this is not an interview; longer is not a session
#: anyone finishes. The UI offers 15–60.
MIN_MINUTES, MAX_MINUTES = 2, 90
#: The stream is push-driven (`store.NOTIFY`); it waits this long on the broker
#: for the next frame before doing anything else.
SSE_WAIT_S = 0.2
#: The safety net: how often it reads the log anyway, for events written by
#: another process — and the first read, which replays what a reconnecting
#: client missed. Deliberately slow, because a reader competing with the writer
#: for SQLite's lock is what made the "live" preview arrive late.
SSE_SWEEP_S = 2.0
SSE_HEARTBEAT_S = 15.0


# ─────────────────────────────────────────────────────────────────────────
#  Dependencies
# ─────────────────────────────────────────────────────────────────────────


def get_engine(
    db: Session = Depends(get_session), upstreams: Upstreams = Depends(get_upstreams)
) -> Engine:
    return Engine(db=db, upstreams=upstreams, llm=get_llm())


def session_factory() -> Callable[[], Session]:
    """For the SSE stream, which outlives the request's own session."""
    return lambda: Session(db_engine)


# ─────────────────────────────────────────────────────────────────────────
#  Shapes
# ─────────────────────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    #: Optional: a student creates their own session and the principal says
    #: who they are. Staff tooling may name one, and `may_see` decides.
    candidate_id: uuid.UUID | None = None
    jd_id: uuid.UUID | None = None
    mode: Mode = "mock"
    minutes: int = Field(default=45, ge=MIN_MINUTES, le=MAX_MINUTES)


class DrillProbe(BaseModel):
    depth: int = Field(ge=0, le=5)
    question: str = Field(min_length=1, max_length=500)
    expects: str | None = Field(default=None, max_length=500)


class DrillCreate(BaseModel):
    """M01's hand-off, exactly as `resume-ingestion` sends it (router.py:1416)."""

    candidate_id: uuid.UUID
    source_module: str = "M01"
    claim_id: str = Field(min_length=1, max_length=200)
    claim_text: str = Field(min_length=1, max_length=2000)
    probes: list[DrillProbe] = Field(min_length=1, max_length=6)


class DrillCreated(BaseModel):
    session_id: uuid.UUID
    #: M06 owns the URL shape (M01's DrillHandoff docstring). Relative to the
    #: web app, which mounts this module under /mock in Platform_Shell.
    url: str


class AnswerIn(BaseModel):
    question_turn_id: uuid.UUID
    text: str = Field(max_length=MAX_ANSWER_CHARS)


class SessionOut(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    kind: str
    mode: str
    status: SessionStatus
    requested_minutes: int
    time_used_s: float
    time_remaining_s: float
    jd_id: uuid.UUID | None
    plan: InterviewPlan | None
    current_segment: int
    questions_asked: int
    #: The interviewer turn waiting for an answer — what the answer box posts to.
    open_turn_id: uuid.UUID | None
    transcript: list[TurnView]
    #: What the next hint would cost, before it is taken (FR-6.7, §32.5).
    hint: HintOffer
    #: Who is asking (FR-6.3): the persona of the question being worked on.
    #: A card — name, title, patience — never the parameters behind the
    #: ladder, which would tell a student how deep this interviewer goes.
    interviewer: dict | None
    #: §15.4, Practice: a retry is on offer and nothing is open until the
    #: student chooses — the stage shows two buttons instead of the answer box.
    retry_offered: bool
    #: A sentence about the panel when it is not what the mode's name
    #: suggests (Real drive, until M15 can match a company's style).
    mode_note: str | None
    #: §6.4's live notes — what changed, neutrally. The reasons come with the
    #: report; mid-session "that round was hard" would be a live score.
    plan_notes: list[str]
    #: FR-6.21: the open turn is the closing, where the student asks.
    in_closing: bool
    #: §6.9's checkpoints passed (70, 90).
    time_warnings: list[int]
    #: EC-6.1 for the open line: prompts given for silence, the last one, and
    #: whether the offer to move on has been made (then `/move-on` takes it).
    idle_prompts: int
    idle_line: str | None
    idle_offered: bool
    #: §6.8: after more than two reconnects, what the student can do about a
    #: connection that keeps dropping. None until then.
    connection_note: str | None
    flags: SessionFlags
    drill_claim: str | None
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class EndRequest(BaseModel):
    reason: str = Field(default="ended_by_student", max_length=100)


class IdleIn(BaseModel):
    #: The line the student has been quiet on — a prompt for a question that
    #: has since been answered is refused, not applied to the next one.
    question_turn_id: uuid.UUID
    #: The prompt the browser expects next (1, 2, 3). A retried request
    #: names one already given and changes nothing (AC-6.16).
    n: int = Field(ge=1, le=3)


class ReliabilityOut(BaseModel):
    """AC-6.9 and §10, counted off the event log — not sampled, not estimated."""

    sessions: int
    #: `connection.lost` — disconnects long enough to be one (presence.py).
    disconnects: int
    #: `connection.resumed` — students who came back.
    returns: int
    #: AC-6.9: returns over disconnects. None until anyone has disconnected.
    reconnect_rate: float | None
    reconnect_target: float = 0.95
    #: §10's ladder: sessions that wrapped up early (L3) and that reached panic.
    wrapped_early: int
    reached_panic: int
    #: §10 "Everything fails": crashed steps, and the sessions they ended.
    crashed_steps: int
    ended_by_failure: int


class FlagIn(BaseModel):
    question_turn_id: uuid.UUID
    #: M05 takes any reason; the stage offers a short fixed list.
    reason: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=1000)


class FlagOut(BaseModel):
    question_id: uuid.UUID
    #: False when M05 was unreachable: the flag is on M06's log, and the item
    #: has not been excluded from selection yet.
    forwarded: bool


class ModalityIn(BaseModel):
    to: str = Field(min_length=1, max_length=20)


class ResumeStateOut(BaseModel):
    """§6.8: what a student coming back needs, in one read."""

    session_id: uuid.UUID
    status: SessionStatus
    #: The clock is stopped for a disconnect right now.
    away: bool
    #: "Welcome back — we were on question 4 of Data structures." None when
    #: there is nothing to come back to.
    welcome: str | None
    #: The line waiting for an answer, verbatim, or None.
    open_question: TurnView | None
    #: The last few turns, so the page can show where things were before
    #: the full transcript has loaded.
    transcript_tail: list[TurnView]
    time_remaining_s: float
    #: How long the clock waits once the student is back (§6.8).
    grace_s: float
    reconnect_count: int
    connection_note: str | None


class TraceOut(BaseModel):
    session_id: uuid.UUID
    events: list[dict]
    llm_calls: list[dict]
    #: FR-6.19. The checkpoint and a fold from nothing agree.
    replay_matches: bool


class SessionSummary(BaseModel):
    id: uuid.UUID
    kind: str
    mode: str
    status: str
    requested_minutes: int
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


def session_out(state: SessionState, now: datetime | None = None) -> SessionOut:
    now = now or utcnow()
    return SessionOut(
        id=state.session_id,
        candidate_id=state.candidate_id,
        kind=state.kind,
        mode=state.mode,
        status=state.status,
        requested_minutes=state.requested_minutes,
        time_used_s=round(state.time_used_s(now), 1),
        time_remaining_s=round(state.time_remaining_s(now), 1),
        jd_id=state.jd_id,
        plan=_plan_view(state),
        current_segment=state.current_segment,
        questions_asked=state.questions_asked,
        open_turn_id=state.open_turn_id,
        transcript=state.transcript,
        hint=hint_offer(state),
        interviewer=_interviewer_card(state),
        retry_offered=state.retry_offer is not None,
        mode_note=mode_config(state.mode).persona_note,
        plan_notes=[r.live_note for r in state.plan.replans] if state.plan is not None else [],
        in_closing=_in_closing(state),
        time_warnings=list(state.time_warnings),
        idle_prompts=state.idle_prompts,
        idle_line=state.idle_line,
        idle_offered=state.idle_offer,
        connection_note=presence.suggestion(state),
        flags=state.flags,
        drill_claim=(state.drill or {}).get("claim_text"),
        created_at=state.created_at,
        started_at=state.started_at,
        ended_at=state.ended_at,
        end_reason=state.end_reason,
    )


def _plan_view(state: SessionState) -> InterviewPlan | None:
    """The plan as a student may see it now.

    During the session its re-plans carry no reasons or signals: "that round
    was a hard one" mid-interview is a live score by another name (§2.2), and
    the trigger names say the same thing in one word. The shape of the plan
    — what was dropped, what was added — stays visible; the why comes with
    the report.
    """
    plan = state.plan
    if plan is None or state.is_final or not plan.replans:
        return plan
    return plan.model_copy(update={"replans": []})


def _in_closing(state: SessionState) -> bool:
    if state.open_turn_id is None:
        return False
    turn = state.turn(state.open_turn_id)
    return turn is not None and turn.question_source == "closing"


def _interviewer_card(state: SessionState) -> dict | None:
    if state.plan is None:
        return None
    card = speaker(state).card()
    # What a student may know: who, and how long they wait for an answer —
    # the stage's idle timer reads it (EC-6.1). Never the ladder's depth.
    return {k: card[k] for k in ("id", "name", "title", "idle_after_s", "long_answer_words")}


def _row_or_404(db: Session, session_id: uuid.UUID):
    row = store.get_session_row(db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such session.")
    return row


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _live_conflict(exc: store.LiveSessionExists) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": (
                "You already have an interview in progress. Finish or end it "
                "before starting another — two at once would overwrite each other."
            ),
            "session_id": str(exc.session_id),
        },
    )


# ─────────────────────────────────────────────────────────────────────────
#  Meta
# ─────────────────────────────────────────────────────────────────────────


@router.get("/deps", response_model=list[DependencyStatus], tags=["meta"])
def dependencies(force: bool = False) -> list[DependencyStatus]:
    """Each upstream, whether it is up, and the sentence a student sees if not."""
    return deps().statuses(force=force)


@router.get("/agents", tags=["meta"])
def agents() -> dict:
    """Master plan §26.2: which agents run, which are ablated, and the step graph."""
    return {
        "agents": snapshot(),
        "model_on": get_llm().available,
        "step_graph": mermaid(compiled_step(get_llm())),
    }


@router.get("/interviews/reliability", response_model=ReliabilityOut, tags=["meta"])
def reliability(
    principal: Principal | None = Depends(enforce_access),
    db: Session = Depends(get_session),
) -> ReliabilityOut:
    """AC-6.9's reconnect rate and §10's ladder, across every session — staff
    only, because it counts other students' sessions.

    Declared before `/interviews/{session_id}`: a path parameter declared
    first would claim "reliability" as an id and 422 on it.
    """
    if principal is None or principal.role is not Role.admin:
        raise HTTPException(status_code=403, detail="Staff only.")
    kinds = (
        "connection.lost",
        "connection.resumed",
        "plan.changed",
        "model.health",
        "step.failed",
        "session.aborted",
    )
    rows = db.exec(
        select(SessionEvent)
        .where(SessionEvent.kind.in_(kinds))
        .order_by(SessionEvent.session_id, SessionEvent.seq)
    ).all()
    count = {kind: 0 for kind in kinds}
    wrapped: set = set()
    panicked: set = set()
    streak: dict = {}
    failed: set = set()
    for row in rows:
        count[row.kind] += 1
        p = row.payload or {}
        if row.kind == "plan.changed":
            replans = (p.get("plan") or {}).get("replans") or []
            if replans and replans[-1].get("trigger") == "degraded":
                wrapped.add(row.session_id)
        elif row.kind == "model.health":
            streak[row.session_id] = 0 if p.get("ok") else streak.get(row.session_id, 0) + 1
            if streak[row.session_id] >= degrade.PANIC_AFTER:
                panicked.add(row.session_id)
        elif row.kind == "session.aborted" and p.get("reason") == "system_failure":
            failed.add(row.session_id)
    sessions = len(db.exec(select(InterviewSession.id)).all())
    lost, back = count["connection.lost"], count["connection.resumed"]
    return ReliabilityOut(
        sessions=sessions,
        disconnects=lost,
        returns=back,
        reconnect_rate=round(back / lost, 3) if lost else None,
        wrapped_early=len(wrapped),
        reached_panic=len(panicked),
        crashed_steps=count["step.failed"],
        ended_by_failure=len(failed),
    )


@router.get("/interviews/modes", tags=["meta"])
def modes() -> list[dict]:
    """FR-6.8 — the four modes, and what each one actually does.

    The setup card lists these. Every summary names only mechanics the engine
    enforces today, because a mode that promises what the session cannot do
    is a promise the session breaks in front of the student.
    """
    return [
        {
            "id": config.id,
            "label": config.label,
            "summary": config.summary,
            "hints": config.hints,
            "retry_allowed": config.retry_allowed,
            "overrun_allowance": config.overrun_allowance,
        }
        for config in MODES.values()
    ]


@router.get("/interviews/personas", tags=["meta"])
def persona_cards() -> list[dict]:
    """§6.7 — who might interview a student, for the plan preview."""
    return [
        {k: card[k] for k in ("id", "name", "title", "style")}
        for card in (p.card() for p in personas().values())
    ]


# ─────────────────────────────────────────────────────────────────────────
#  Creating sessions
# ─────────────────────────────────────────────────────────────────────────


@router.post("/interviews", response_model=SessionOut, status_code=201)
def create_session(
    body: SessionCreate,
    principal: Principal | None = Depends(enforce_access),
    db: Session = Depends(get_session),
) -> SessionOut:
    candidate_id = body.candidate_id
    if candidate_id is None:
        if principal is None or principal.candidate_id is None:
            raise HTTPException(status_code=403, detail="Not signed in.")
        candidate_id = uuid.UUID(principal.candidate_id)
    require_candidate(principal, candidate_id)
    try:
        _row, state = store.create_session(
            db,
            candidate_id=candidate_id,
            kind=SessionKind.mock.value,
            mode=body.mode,
            minutes=body.minutes,
            jd_id=body.jd_id,
        )
    except store.LiveSessionExists as exc:
        raise _live_conflict(exc) from exc
    return session_out(state)


@router.post("/drills", response_model=DrillCreated, status_code=201)
def create_drill(
    body: DrillCreate,
    principal: Principal | None = Depends(enforce_access),
    engine: Engine = Depends(get_engine),
) -> DrillCreated:
    """FR-6.23 — M01's "Practise defending this" (M06_REVIEW 1.5).

    The caller is M01's backend, acting for the student; it must forward the
    student's identity headers, as M02 does to M01. The session is created in
    `planned`: the student lands on the drill page and starts it themselves.
    """
    require_candidate(principal, body.candidate_id)
    try:
        row, _state = engine.create_drill(
            candidate_id=body.candidate_id,
            claim_id=body.claim_id,
            claim_text=body.claim_text,
            probes=[p.model_dump() for p in body.probes],
            source_module=body.source_module,
        )
    except store.LiveSessionExists as exc:
        raise _live_conflict(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DrillCreated(session_id=row.id, url=f"/mock/{row.id}")


# ─────────────────────────────────────────────────────────────────────────
#  The session
# ─────────────────────────────────────────────────────────────────────────


@router.get("/interviews/{session_id}", response_model=SessionOut)
def read_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    _row_or_404(db, session_id)
    return session_out(store.load_state(db, session_id))


@router.post("/interviews/{session_id}/plan", response_model=SessionOut)
def build_plan(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> SessionOut:
    """FR-6.2 — what the interview will be, before it is (spec §6.1).

    Separate from `start` so a student sees the plan and can change it before
    the first question arrives. Idempotent: it builds one if there is none and
    returns the one there is otherwise, so refreshing the preview does not ask
    M02 to price the same session twice.
    """
    try:
        return session_out(engine.plan(session_id))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.delete("/interviews/{session_id}/plan/segments/{index}", response_model=SessionOut)
def drop_segment(
    session_id: uuid.UUID, index: int, engine: Engine = Depends(get_engine)
) -> SessionOut:
    """Drop one part of the plan before starting — FR-6.2.

    The segment stays in the plan with the student's reason on it: the report
    has to be able to say what was planned as well as what happened. Its
    requirements are owed to M02's ledger as `skipped`, exactly like a segment
    M06 dropped itself.
    """
    try:
        return session_out(engine.drop_segment(session_id, index))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/hint", response_model=SessionOut)
def take_hint(
    session_id: uuid.UUID,
    background: BackgroundTasks,
    engine: Engine = Depends(get_engine),
) -> SessionOut:
    """Take the hint the session is offering — FR-6.7.

    The price is on every read of the session (`hint.credit`), so a student
    presses this knowing what it costs. 409 with the reason when there is
    nothing to give: no hints on this question, none left, or Final Boss.
    """
    try:
        taken = session_out(engine.hint(session_id))
        background.add_task(_deliver, session_id)
        return taken
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/retry", response_model=SessionOut)
def take_retry(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> SessionOut:
    """§15.4, Practice: the question again, from the top. Not scored — the
    first attempt is the one that counts, and the notes say which is which."""
    try:
        return session_out(engine.retry(session_id))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/move-on", response_model=SessionOut)
def move_on(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> SessionOut:
    """The next question: declining a Practice retry (§15.4), or taking the
    interviewer's offer after a silence (EC-6.1)."""
    try:
        return session_out(engine.move_on(session_id))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/idle", response_model=SessionOut)
def idle_prompt(
    session_id: uuid.UUID, body: IdleIn, engine: Engine = Depends(get_engine)
) -> SessionOut:
    """EC-6.1: the student has been quiet on the open line. The browser
    says when (it can see typing); the interviewer decides what to say."""
    try:
        return session_out(engine.idle(session_id, body.question_turn_id, body.n))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/repeat", response_model=TurnView)
def repeat_question(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> TurnView:
    """§7: "say that again" — the open question, verbatim."""
    try:
        return engine.repeat(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/flag", response_model=FlagOut)
def flag_question(
    session_id: uuid.UUID, body: FlagIn, engine: Engine = Depends(get_engine)
) -> FlagOut:
    """§7's ⚑ — forwarded to M05's `/questions/{qid}/flag`."""
    try:
        out = engine.flag(session_id, body.question_turn_id, body.reason, body.note)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return FlagOut(question_id=uuid.UUID(out["question_id"]), forwarded=out["forwarded"])


@router.post("/interviews/{session_id}/switch-modality", response_model=SessionOut)
def switch_modality(
    session_id: uuid.UUID, body: ModalityIn, engine: Engine = Depends(get_engine)
) -> SessionOut:
    """FR-6.11: the contract, fixed in Phase 1 — typed answers only."""
    try:
        return session_out(engine.switch_modality(session_id, body.to))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except InvalidTransition as exc:
        raise _conflict(exc) from exc


@router.get("/interviews/{session_id}/resume-state", response_model=ResumeStateOut)
def resume_state(session_id: uuid.UUID, db: Session = Depends(get_session)) -> ResumeStateOut:
    """§6.8, FR-6.13: where the student was, after a disconnect or a refresh.

    A read and nothing else. The return itself is recorded by the stream
    re-attaching, or by whatever the student does next — so a page that
    fetches this twice, or a prefetch, never counts a reconnect.
    """
    _row_or_404(db, session_id)
    state = store.load_state(db, session_id)
    open_turn = state.turn(state.open_turn_id) if state.open_turn_id is not None else None
    return ResumeStateOut(
        session_id=state.session_id,
        status=state.status,
        away=state.flags.away_since is not None,
        welcome=welcome_line(state),
        open_question=open_turn,
        transcript_tail=state.transcript[-RESUME_TAIL:],
        time_remaining_s=round(state.time_remaining_s(utcnow()), 1),
        grace_s=presence.GRACE_S,
        reconnect_count=state.flags.reconnect_count,
        connection_note=presence.suggestion(state),
    )


@router.post("/interviews/{session_id}/start", response_model=SessionOut)
def start_session(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> SessionOut:
    """Starts a planned session — and, on a live one, carries on (idempotent).

    A client that reconnects calls this: whatever the session is owed (the
    opening question, the next step for an answer already recorded) happens
    once, however many times it is asked.
    """
    try:
        return session_out(engine.start(session_id))
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except store.LiveSessionExists as exc:
        raise _live_conflict(exc) from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.post("/interviews/{session_id}/answer", response_model=SessionOut)
def answer(
    session_id: uuid.UUID,
    body: AnswerIn,
    background: BackgroundTasks,
    engine: Engine = Depends(get_engine),
) -> SessionOut:
    """A typed answer. Returns the session with the interviewer's next line.

    Delivery to M13 and M02 is a background task: FR-6.14 — evaluation never
    blocks the conversation, and M13 scores synchronously at p95 15 s. The
    rows are already on disk by the time this returns, so nothing is lost if
    the task never runs.
    """
    try:
        state = engine.answer(session_id, body.question_turn_id, body.text)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (AnswerRejected, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    background.add_task(_deliver, session_id)
    return session_out(state)


def _deliver(session_id: uuid.UUID) -> None:
    """Drain one session's outbox, in its own session and its own transaction.

    The request's DB session is closed by the time a background task runs, and
    the upstreams are built from the registry the same way the request's were.
    """
    from .adapters import get_upstreams

    with Session(db_engine) as db:
        engine = Engine(db=db, upstreams=get_upstreams(), llm=get_llm())
        try:
            # §6.6's rolling note FIRST. It is what the next turn needs, and
            # delivery below can block for seconds on M13's ensemble — which
            # measurably made the note arrive a turn late. Delivery is also
            # the half with a retry behind it (`sweeper.py`); the note has
            # only the next answer.
            engine.summarise_if_due(session_id)
        except Exception:  # noqa: BLE001 - a missing note costs context, not a score
            log.warning("M06: summary for %s failed; the interviewer keeps the old one", session_id)
        try:
            engine.deliver(session_id)
        except Exception:  # noqa: BLE001 - a delivery failure is a queued row
            log.warning("M06: delivery for %s failed; rows stay queued", session_id)


@router.post("/interviews/{session_id}/outbox/drain")
def drain_outbox(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> dict:
    """Send what this session owes M13 and M02 now. Idempotent, safe to repeat."""
    _row_or_404(engine.db, session_id)
    drained = engine.deliver(session_id)
    return {
        "evaluations_sent": drained.evaluations_sent,
        "coverage_sent": drained.ledger_sent,
        "still_waiting": drained.failed,
        # Somebody else is already sending these, so a zero above is not a
        # zero owed. Without this the caller cannot tell the two apart.
        "already_sending": drained.in_flight,
        "held": drained.held,
        **outbox.status(engine.db, session_id),
    }


@router.post("/interviews/{session_id}/outbox/requeue")
def requeue_outbox(
    session_id: uuid.UUID,
    principal: Principal | None = Depends(enforce_access),
    engine: Engine = Depends(get_engine),
) -> dict:
    """Put this session's stuck rows back, after a person fixed what held them
    (a rejected or held row is listed with its reason on `/outbox`). Staff
    only: a student retrying a rejected request at will is a way to keep M13
    busy, and fixing the cause is not theirs to do."""
    if principal is None or principal.role is not Role.admin:
        raise HTTPException(status_code=403, detail="Staff only.")
    _row_or_404(engine.db, session_id)
    requeued = outbox.requeue(engine.db, session_id)
    drained = engine.deliver(session_id)
    return {"requeued": requeued, "sent": drained.moved, **outbox.status(engine.db, session_id)}


@router.get("/interviews/{session_id}/outbox")
def read_outbox(session_id: uuid.UUID, db: Session = Depends(get_session)) -> dict:
    """What is queued for this session, and why anything failed."""
    _row_or_404(db, session_id)
    return outbox.status(db, session_id)


@router.post("/interviews/{session_id}/pause", response_model=SessionOut)
def pause_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    row = _row_or_404(db, session_id)
    presence.back(db, session_id, utcnow(), grace_s=0.0)
    state = store.load_state(db, session_id)
    if state.flags.pause_used and state.status is not SessionStatus.paused:
        raise HTTPException(
            status_code=409,
            detail="You've already used your pause for this interview — it's once per session.",
        )
    try:
        recorded = store.record(db, row, "session.paused", step="pause")
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return session_out(recorded.state)


@router.post("/interviews/{session_id}/resume", response_model=SessionOut)
def resume_session(session_id: uuid.UUID, engine: Engine = Depends(get_engine)) -> SessionOut:
    row = _row_or_404(engine.db, session_id)
    engine.back(session_id)
    state = store.load_state(engine.db, session_id)
    now = utcnow()
    at = now
    if state.status is SessionStatus.paused and state.flags.paused_at is not None:
        # FR-6.12: the pause is at most five minutes. A student who comes back
        # later resumes with the clock having restarted at the five-minute mark,
        # rather than with a pause that silently lasted an hour.
        limit = state.flags.paused_at.timestamp() + PAUSE_LIMIT_S
        if now.timestamp() > limit:
            at = datetime.fromtimestamp(limit, tz=now.tzinfo)
    try:
        store.record(engine.db, row, "session.resumed", step="resume", at=at)
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return session_out(engine.continue_session(session_id))


@router.post("/interviews/{session_id}/end", response_model=SessionOut)
def end_session(
    session_id: uuid.UUID,
    background: BackgroundTasks,
    body: EndRequest | None = None,
    engine: Engine = Depends(get_engine),
) -> SessionOut:
    """EC-6.10: ending early still produces a report — framed as a warm-up."""
    try:
        ended = session_out(engine.end(session_id, (body or EndRequest()).reason))
        background.add_task(_deliver, session_id)
        return ended
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such session.") from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc


@router.get("/interviews/{session_id}/transcript", response_model=list[TurnView])
def transcript(session_id: uuid.UUID, db: Session = Depends(get_session)) -> list[TurnView]:
    _row_or_404(db, session_id)
    return store.load_state(db, session_id).transcript


@router.get("/interviews/{session_id}/report", response_model=report_module.SessionReport)
def session_report(
    session_id: uuid.UUID, db: Session = Depends(get_session)
) -> report_module.SessionReport:
    """FR-6.18 — for every session, finished or not (AC-6.1)."""
    _row_or_404(db, session_id)
    state = store.load_state(db, session_id)
    return report_module.build(state, store.events_for(db, session_id), utcnow())


@router.get("/interviews/{session_id}/trace", response_model=TraceOut)
def trace(
    session_id: uuid.UUID,
    principal: Principal | None = Depends(enforce_access),
    db: Session = Depends(get_session),
) -> TraceOut:
    """FR-6.19 — the event log and every model call, and whether replay agrees.

    The raw log holds the verdict bands and the open question's key points, so
    a student sees it only once their session is over (see `public.py`).
    """
    _row_or_404(db, session_id)
    current = store.load_state(db, session_id)
    is_admin = principal is not None and principal.role is Role.admin
    if not current.is_final and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="The full trace is available once the interview is over.",
        )
    events = store.events_for(db, session_id)
    calls = db.exec(
        select(LLMCall).where(LLMCall.session_id == session_id).order_by(LLMCall.at)
    ).all()
    replayed = store.replay(db, session_id)
    return TraceOut(
        session_id=session_id,
        events=[e.model_dump(mode="json") for e in events],
        llm_calls=[c.model_dump(mode="json") for c in calls],
        replay_matches=replayed.model_dump(mode="json") == current.model_dump(mode="json"),
    )


@router.get("/interviews/{session_id}/events")
async def session_events(
    session_id: uuid.UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    sessions: Callable[[], Session] = Depends(session_factory),
) -> StreamingResponse:
    """Text-mode live stream (spec §7): the event log, plus interviewer tokens.

    `id:` is the event's seq, so a browser that reconnects with
    `Last-Event-ID` resumes exactly where it left off. Token frames carry no
    id — they are a preview, and the `question.asked` that follows is the
    text of record.
    """
    with sessions() as db:
        _row_or_404(db, session_id)
    header = request.headers.get("last-event-id")
    cursor = after if after is not None else int(header) if (header or "").isdigit() else 0
    tokens = broker.subscribe(session_id)

    def frame(kind: str, data: dict, seq: int | None = None) -> str:
        head = f"id: {seq}\n" if seq is not None else ""
        return f"{head}event: {kind}\ndata: {json.dumps(data)}\n\n"

    def sweep(db_cursor: int) -> tuple[list[str], int, bool]:
        """The log after `db_cursor`, and whether the session is over."""
        out: list[str] = []
        with sessions() as db:
            rows = store.events_for(db, session_id, after_seq=db_cursor)
            final = store.load_state(db, session_id).is_final
        for row in rows:
            db_cursor = row.seq
            public = public_event(row)
            if public is not None:
                out.append(frame(row.kind, public, row.seq))
        return out, db_cursor, final

    def returned() -> None:
        # §6.8: a stage re-attaching is the student coming back — the
        # disconnect it ends (if it was long enough to be one) and the return
        # are written now, before the first sweep, so this stream carries them.
        with sessions() as db:
            presence.back(db, session_id, utcnow())

    async def stream() -> AsyncIterator[str]:
        nonlocal cursor
        idle = 0.0
        since_sweep = SSE_SWEEP_S  # sweep once at the start
        final = False
        presence.presence.attach(session_id)
        try:
            await asyncio.to_thread(returned)
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                sent = False
                if since_sweep >= SSE_SWEEP_S:
                    since_sweep = 0.0
                    out, cursor, final = await asyncio.to_thread(sweep, cursor)
                    for text in out:
                        yield text
                        sent = True
                    if final:
                        yield frame("stream.closed", {})
                        return
                # Wait on the broker rather than on the clock: a token or an
                # event that this process just wrote arrives here at once.
                try:
                    message = await asyncio.to_thread(tokens.get, True, SSE_WAIT_S)
                except queue.Empty:
                    message = None
                since_sweep += SSE_WAIT_S
                if message is None:
                    pass
                elif "token" in message:
                    yield frame("interviewer.token", message)
                    sent = True
                elif (event := message.get("event")) is not None:
                    seq = int(event.get("seq", 0))
                    if seq > cursor:
                        cursor = seq
                        yield frame(str(event.get("kind")), event, seq)
                        sent = True
                        if str(event.get("kind")) in ("session.ended", "session.aborted"):
                            yield frame("stream.closed", {})
                            return
                idle = 0.0 if sent else idle + SSE_WAIT_S
                if idle >= SSE_HEARTBEAT_S:
                    idle = 0.0
                    yield ": alive\n\n"
        finally:
            broker.unsubscribe(session_id, tokens)
            presence.presence.detach(session_id, utcnow())

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────
#  The student's history
# ─────────────────────────────────────────────────────────────────────────


def _summaries(rows) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=r.id,
            kind=r.kind,
            mode=r.mode,
            status=r.status,
            requested_minutes=r.requested_minutes,
            created_at=r.created_at,
            started_at=r.started_at,
            ended_at=r.ended_at,
            end_reason=r.end_reason,
        )
        for r in rows
    ]


@router.get("/interviews/by-candidate/{candidate_id}", response_model=list[SessionSummary])
def candidate_sessions(
    candidate_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_session),
) -> list[SessionSummary]:
    return _summaries(store.sessions_for(db, candidate_id, limit=limit))


@router.get("/interviews/by-candidate/{candidate_id}/recent", response_model=list[SessionSummary])
def recent_sessions(
    candidate_id: uuid.UUID, db: Session = Depends(get_session)
) -> list[SessionSummary]:
    """The source for M04's `recent_sessions` slot (M06_REVIEW 1.4). Finished only."""
    rows = [
        r
        for r in store.sessions_for(db, candidate_id, limit=20)
        if r.status in (SessionStatus.ended.value, SessionStatus.aborted.value)
    ]
    return _summaries(rows[:5])


__all__ = ["get_engine", "router", "session_factory", "session_out"]
