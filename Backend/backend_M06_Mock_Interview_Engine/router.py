"""M06 routes — spec §7, Revision 2.

Day 1 of the build order: the session lifecycle, the event trace and the
student's own history. Planning (day 5), the turn loop and drills (day 2) land
on this same router.

Every route except `/v1/deps` names a student, and `enforce_access` sits on
the router so none can be written without it (FR-6.26).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ai_core.db import get_session
from ai_core.dependencies import DependencyStatus
from ai_core.identity import Principal
from ai_core.timeutil import utcnow
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import store
from .access import enforce_access, require_candidate
from .contracts import (
    InterviewPlan,
    Mode,
    SessionFlags,
    SessionKind,
    SessionStatus,
    TurnView,
)
from .dependencies import deps
from .models import LLMCall
from .state import InvalidTransition, SessionState

router = APIRouter(
    prefix="/v1", tags=["M06 Mock Interview Engine"], dependencies=[Depends(enforce_access)]
)

#: FR-6.12.
PAUSE_LIMIT_S = 5 * 60
#: A session shorter than this is not an interview; longer is not a session
#: anyone finishes. The UI offers 15–60.
MIN_MINUTES, MAX_MINUTES = 2, 90


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
    turns: int
    flags: SessionFlags
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class EndRequest(BaseModel):
    reason: str = "ended_by_student"


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
        plan=state.plan,
        current_segment=state.current_segment,
        turns=len(state.transcript),
        flags=state.flags,
        created_at=state.created_at,
        started_at=state.started_at,
        ended_at=state.ended_at,
        end_reason=state.end_reason,
    )


def _row_or_404(db: Session, session_id: uuid.UUID):
    row = store.get_session_row(db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such session.")
    return row


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────
#  Meta
# ─────────────────────────────────────────────────────────────────────────


@router.get("/deps", response_model=list[DependencyStatus], tags=["meta"])
def dependencies(force: bool = False) -> list[DependencyStatus]:
    """Each upstream, whether it is up, and the sentence a student sees if not."""
    return deps().statuses(force=force)


# ─────────────────────────────────────────────────────────────────────────
#  Session lifecycle
# ─────────────────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionOut, status_code=201)
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
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "You already have an interview in progress. Finish or end it "
                    "before starting another — two at once would overwrite each other."
                ),
                "session_id": str(exc.session_id),
            },
        ) from exc
    return session_out(state)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def read_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    _row_or_404(db, session_id)
    return session_out(store.load_state(db, session_id))


@router.post("/sessions/{session_id}/start", response_model=SessionOut)
def start_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    row = _row_or_404(db, session_id)
    try:
        recorded = store.record(db, row, "session.started", step="start")
    except store.LiveSessionExists as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "You already have an interview in progress.",
                "session_id": str(exc.session_id),
            },
        ) from exc
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return session_out(recorded.state)


@router.post("/sessions/{session_id}/pause", response_model=SessionOut)
def pause_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    row = _row_or_404(db, session_id)
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


@router.post("/sessions/{session_id}/resume", response_model=SessionOut)
def resume_session(session_id: uuid.UUID, db: Session = Depends(get_session)) -> SessionOut:
    row = _row_or_404(db, session_id)
    state = store.load_state(db, session_id)
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
        recorded = store.record(db, row, "session.resumed", step="resume", at=at)
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return session_out(recorded.state)


@router.post("/sessions/{session_id}/end", response_model=SessionOut)
def end_session(
    session_id: uuid.UUID,
    body: EndRequest | None = None,
    db: Session = Depends(get_session),
) -> SessionOut:
    """EC-6.10: ending early still produces a report — framed as a warm-up."""
    row = _row_or_404(db, session_id)
    reason = (body or EndRequest()).reason
    state = store.load_state(db, session_id)
    kind = "session.aborted" if state.status is SessionStatus.planned else "session.ended"
    try:
        recorded = store.record(db, row, kind, step="end", payload={"reason": reason})
    except (InvalidTransition, store.ConcurrentWrite) as exc:
        raise _conflict(exc) from exc
    return session_out(recorded.state)


@router.get("/sessions/{session_id}/transcript", response_model=list[TurnView])
def transcript(session_id: uuid.UUID, db: Session = Depends(get_session)) -> list[TurnView]:
    _row_or_404(db, session_id)
    return store.load_state(db, session_id).transcript


@router.get("/sessions/{session_id}/trace", response_model=TraceOut)
def trace(session_id: uuid.UUID, db: Session = Depends(get_session)) -> TraceOut:
    """FR-6.19 — the event log and every model call, and whether replay agrees."""
    _row_or_404(db, session_id)
    events = store.events_for(db, session_id)
    calls = db.exec(
        select(LLMCall).where(LLMCall.session_id == session_id).order_by(LLMCall.at)
    ).all()
    replayed = store.replay(db, session_id)
    current = store.load_state(db, session_id)
    return TraceOut(
        session_id=session_id,
        events=[e.model_dump(mode="json") for e in events],
        llm_calls=[c.model_dump(mode="json") for c in calls],
        replay_matches=replayed.model_dump(mode="json") == current.model_dump(mode="json"),
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


@router.get("/candidates/{candidate_id}/sessions", response_model=list[SessionSummary])
def candidate_sessions(
    candidate_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_session),
) -> list[SessionSummary]:
    return _summaries(store.sessions_for(db, candidate_id, limit=limit))


@router.get("/candidates/{candidate_id}/sessions/recent", response_model=list[SessionSummary])
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


__all__ = ["router", "session_out"]
