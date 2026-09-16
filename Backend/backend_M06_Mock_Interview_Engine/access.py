"""Who is asking — FR-6.26, on `ai_core.identity`.

Declared once, on the ROUTER, so it runs on every endpoint including the ones
nobody has written yet. A per-route check is the one somebody omits on the
sixteenth endpoint, and the sixteenth endpoint is the one that leaks.

Three ways a route names a student, and each is resolved to a candidate id
before `may_see` is asked:

    /candidates/{candidate_id}/…   the path names the candidate
    /sessions/{session_id}/…       the session names its candidate
    POST /sessions, POST /drills   the BODY names the candidate — checked in
                                   the handler with `require_candidate`, and
                                   stated here so the gap is a known one

Meta routes name nobody and are not gated.

**Service callers forward the student's identity.** `ai_core.identity` has
four roles and no `service` role, and this module does not invent one. M02
forwards `X-Role: student` and `X-Candidate-Id` when it calls M01; M01 must do
the same when it hands M06 a drill (M06_REVIEW Part 5), and M06 does the same
when it calls M02 and M05 on a student's behalf.
"""

from __future__ import annotations

import uuid

from ai_core.db import get_session
from ai_core.identity import Principal, may_see, principal_from_headers
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from .models import InterviewSession


def enforce_access(request: Request, db: Session = Depends(get_session)) -> Principal | None:
    principal = principal_from_headers(dict(request.headers))

    candidate_id = request.path_params.get("candidate_id")
    session_id = request.path_params.get("session_id")

    if session_id is not None and candidate_id is None:
        try:
            row = db.get(InterviewSession, uuid.UUID(str(session_id)))
        except ValueError:
            return principal
        if row is None:
            # Not this dependency's job to 404, and refusing here would tell a
            # caller which ids exist.
            return principal
        candidate_id = str(row.candidate_id)

    if candidate_id is None:
        return principal

    decision = may_see(principal, str(candidate_id))
    if not decision:
        # 403 with the reason, not 404. Pretending the record does not exist
        # would be a lie to the student it belongs to.
        raise HTTPException(status_code=403, detail=decision.reason)
    return principal


def require_candidate(principal: Principal | None, candidate_id: uuid.UUID | str) -> None:
    """The body-scoped half. Call it before acting on a candidate in a body."""
    decision = may_see(principal, str(candidate_id))
    if not decision:
        raise HTTPException(status_code=403, detail=decision.reason)


def identity_headers(candidate_id: uuid.UUID | str) -> dict[str, str]:
    """What M06 forwards when it calls another module for this student."""
    return {"X-Role": "student", "X-Candidate-Id": str(candidate_id)}


__all__ = ["enforce_access", "identity_headers", "require_candidate"]
