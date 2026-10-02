"""Who is asking — FR-6.26, on `ai_core.guard` (Platform_Core v0.11.0).

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

**The check itself is Platform_Core's** since 2026-10-02. This file held its
own copy of it from day 1 — M01, M02 and M06 each wrote one before
`candidate_guard` existed, and copies drift. What stays here is the one thing
only M06 knows: which student an interview id belongs to, read through the
request's own database session (a resolver bound at import time could not see
the database a test swaps in). Since v0.11.0 the shared guard also reads a
student named in the query.

**Service callers forward the student's identity.** `ai_core.identity` has
four roles and no `service` role, and this module does not invent one. M02
forwards `X-Role: student` and `X-Candidate-Id` when it calls M01; M01 must do
the same when it hands M06 a drill (M06_REVIEW Part 5), and M06 does the same
when it calls M02 and M05 on a student's behalf.
"""

from __future__ import annotations

import uuid

from ai_core.db import get_session
from ai_core.guard import candidate_guard, identity_headers, require_candidate
from ai_core.identity import Principal
from fastapi import Depends, Request
from sqlmodel import Session

from .models import InterviewSession


def enforce_access(request: Request, db: Session = Depends(get_session)) -> Principal | None:
    """`candidate_guard`, with interview ids resolved to their student."""

    def owner(session_id: str) -> str | None:
        try:
            row = db.get(InterviewSession, uuid.UUID(str(session_id)))
        except ValueError:
            return None
        # Unknown: not this dependency's job to 404, and refusing here would
        # tell a caller which ids exist.
        return str(row.candidate_id) if row is not None else None

    return candidate_guard({"session_id": owner})(request)


__all__ = ["enforce_access", "identity_headers", "require_candidate"]
