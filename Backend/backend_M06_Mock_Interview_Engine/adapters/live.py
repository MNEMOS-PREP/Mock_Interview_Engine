"""HTTP clients for the five upstreams, against their shipped routers.

Route and payload per call are cited in M06_REVIEW Part 1. Candidate-scoped
calls forward the student's identity (`access.identity_headers`) exactly as
M02 does when it calls M01; M04's service routes take `X-Service-Secret`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..access import identity_headers
from .base import UpstreamUnavailable
from .http import JSONClient


class LiveCoveragePlanner:
    #: The plan is built once, at plan time, behind the preview's spinner — not
    #: on a turn. M02's first plan for a posting does real work (mastery from
    #: M04, availability from M05) and took longer than the 3 s a turn's call
    #: is allowed: the first live run of the full chain (2026-10-02) planned
    #: every session on the even split, with "the planner is offline" shown to
    #: a student whose planner was up. A turn's budget is for turns.
    PLAN_TIMEOUT_S = 20.0

    def __init__(self, base_url: str):
        self.http = JSONClient("M02", base_url)

    def plan(self, jd_id: UUID, candidate_id: UUID, minutes: int) -> dict[str, Any]:
        return self.http.post(
            f"/v1/jds/{jd_id}/plan/{candidate_id}",
            {"minutes": minutes},
            headers=identity_headers(candidate_id),
            timeout_s=self.PLAN_TIMEOUT_S,
        ).body

    def job_description(self, jd_id: UUID) -> dict[str, Any]:
        return self.http.get(f"/v1/jds/{jd_id}").body

    def requirements(self, jd_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
        """Each requirement with its `concept_ids` and `measured_by`.

        The plan names requirement ids; this is what turns them into the
        concepts M05 selects on and the modality M06 has to be able to serve.
        M02 resolved those against the same ontology M05 uses, so there is
        nothing to translate — only to look up.
        """
        body = self.http.get(
            f"/v1/jds/{jd_id}/requirements/{candidate_id}",
            headers=identity_headers(candidate_id),
            timeout_s=self.PLAN_TIMEOUT_S,
        ).body
        return list((body or {}).get("requirements") or [])

    def record_coverage(
        self,
        session_id: UUID,
        candidate_id: UUID,
        *,
        jd_id: UUID,
        requirement_id: str,
        state: str,
        turn_id: UUID | None,
    ) -> dict[str, Any]:
        return self.http.post(
            f"/v1/coverage/{session_id}/{candidate_id}",
            {
                "jd_id": str(jd_id),
                "requirement_id": requirement_id,
                "state": state,
                "turn_id": str(turn_id) if turn_id else None,
            },
            headers=identity_headers(candidate_id),
        ).body

    def session_coverage(self, session_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        return self.http.get(
            f"/v1/coverage/{session_id}/{candidate_id}",
            headers=identity_headers(candidate_id),
        ).body


class LiveMemory:
    def __init__(self, base_url: str):
        self.http = JSONClient("M04", base_url)

    def profile_summary(self, candidate_id: UUID, session_id: UUID) -> dict[str, Any]:
        return self.http.get(
            f"/v1/candidates/{candidate_id}/profile-summary",
            query={"session_id": str(session_id)},
            service=True,
            # The secret says M06 is calling; the student says for whom. M04
            # guards every candidate route on the second since 2026-09-23.
            headers=identity_headers(candidate_id),
        ).body

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        """The public ontology: no candidate in it, so no identity to forward."""
        response = self.http.get(f"/v1/concepts/{concept_id}", accept=(404,))
        return None if response.status == 404 else response.body

    def posterior(self, candidate_id: UUID, concepts: list[str]) -> dict[str, float]:
        if not concepts:
            return {}
        body = self.http.get(
            "/v1/skill-graph/theta",
            query={"candidate": str(candidate_id), "concepts": ",".join(concepts)},
            service=True,
            headers=identity_headers(candidate_id),
        ).body
        # A resolved concept with nothing measured comes back as theta=None,
        # never 0.0 (M04 AC-4.2). Dropping it here keeps it that way: M05
        # seeds an absent concept at the prior, which is the honest belief.
        return {
            concept: float(row["theta"])
            for concept, row in (body or {}).get("per_topic", {}).items()
            if row.get("theta") is not None
        }

    def register_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store the answer text M13's evidence quotes (M04 §5.1).

        A service route: M06 is writing on a student's behalf with no student
        in the room. `X-Service-Secret` says M06 is the caller; the forwarded
        identity says which student, and M04's guard checks it. 200 and 201 are
        both success — the second means the turn was already registered, which
        a retry should be.
        """
        return (
            self.http.post(
                f"/v1/candidates/{payload['candidate_id']}/artifacts",
                payload,
                service=True,
                headers=identity_headers(payload["candidate_id"]),
            ).body
            or {}
        )

    def consent(self, candidate_id: UUID, purpose: str) -> UUID | None:
        """The consent id M13 cites on every observation it writes.

        M06 resolves this at session start rather than at scoring time,
        because consent is a fact about the session, not about the score.
        Until M04 grew this route (2026-09-20) it returned None on every
        session, which was honest and also meant no scored answer ever moved
        a student's skill graph.

        404 or an empty list means "not recorded", not "M04 is down": the
        module answered. A student with no consent runs an interview that is
        scored and says so in the report — it just does not update anything.
        """
        response = self.http.get(
            f"/v1/candidates/{candidate_id}/consent",
            query={"purpose": purpose},
            headers=identity_headers(candidate_id),
            accept=(404,),
        )
        rows = response.body if isinstance(response.body, list) else []
        for row in rows:
            if row.get("active") and row.get("consent_id"):
                return UUID(str(row["consent_id"]))
        return None


class LiveQuestions:
    def __init__(self, base_url: str):
        self.http = JSONClient("M05", base_url)

    def select(self, request: dict[str, Any]) -> dict[str, Any] | None:
        response = self.http.post(
            "/v1/questions/select",
            request,
            accept=(409,),
            headers=identity_headers(request["candidate_id"]),
        )
        return None if response.status == 409 else response.body

    def question(self, question_id: UUID) -> dict[str, Any]:
        return self.http.get(f"/v1/questions/{question_id}").body

    def seed(
        self,
        session_id: UUID,
        candidate_id: UUID,
        posterior: dict[str, float],
        snapshot_id: str,
    ) -> dict[str, Any]:
        return self.http.post(
            f"/v1/sessions/{session_id}/theta/seed",
            {"candidate_id": str(candidate_id), "posterior": posterior, "snapshot_id": snapshot_id},
            headers=identity_headers(candidate_id),
        ).body

    def observe(
        self,
        session_id: UUID,
        concept_id: str,
        outcome: dict[str, Any],
        candidate_id: UUID | None = None,
    ) -> float | None:
        # M05's session routes answer only the session's owner (its
        # Platform_Core v0.11.0 guard), so the student is forwarded here as it
        # is on `select` and `seed`.
        response = self.http.post(
            f"/v1/sessions/{session_id}/theta/observe",
            {"concept_id": concept_id, "outcome": outcome},
            accept=(404,),
            headers=identity_headers(candidate_id) if candidate_id else None,
        )
        if response.status == 404:
            # M05 restarted and lost its in-memory session. The engine
            # re-seeds; nothing about the student is wrong.
            raise UpstreamUnavailable("M05", "session not seeded")
        value = (response.body or {}).get("theta_provisional")
        return float(value) if value is not None else None

    def close(
        self,
        session_id: UUID,
        posterior: dict[str, float],
        candidate_id: UUID | None = None,
    ) -> dict[str, Any]:
        response = self.http.post(
            f"/v1/sessions/{session_id}/close",
            {"posterior": posterior},
            accept=(404,),
            headers=identity_headers(candidate_id) if candidate_id else None,
        )
        return response.body if response.status != 404 else {"closed": False}

    def flag(self, question_id: UUID, reason: str, note: str, candidate_id: UUID) -> dict[str, Any]:
        return self.http.post(
            f"/v1/questions/{question_id}/flag",
            {"reason": reason, "note": note, "candidate_id": str(candidate_id)},
            # M05 refuses an anonymous flag, and one made for somebody else.
            headers=identity_headers(candidate_id),
        ).body


class LiveEvaluator:
    #: M13 scores synchronously; the outbox drainer can afford to wait.
    TIMEOUT_S = 60.0

    def __init__(self, base_url: str):
        self.http = JSONClient("M13", base_url, timeout_s=self.TIMEOUT_S)

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.http.post("/v1/evaluations", request).body

    def rubrics(self) -> list[dict[str, Any]]:
        return list((self.http.get("/v1/rubrics", timeout_s=3.0).body or {}).get("rubrics", []))

    def ensembles(self) -> list[dict[str, Any]]:
        return list((self.http.get("/v1/ensembles", timeout_s=3.0).body or {}).get("ensembles", []))

    def evaluation(self, turn_id: UUID) -> dict[str, Any] | None:
        response = self.http.get(f"/v1/evaluations/{turn_id}", accept=(404,), timeout_s=3.0)
        return None if response.status == 404 else response.body

    def calibration(self) -> dict[str, Any]:
        return self.http.get("/v1/calibration", timeout_s=3.0).body or {}


class LiveResumes:
    def __init__(self, base_url: str):
        self.http = JSONClient("M01", base_url)

    def resumes_for(self, candidate_id: UUID) -> list[dict[str, Any]]:
        return list(
            self.http.get(
                f"/v1/resumes/candidate/{candidate_id}", headers=identity_headers(candidate_id)
            ).body
            or []
        )

    def claims(self, resume_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        return self.http.get(
            f"/v1/resumes/{resume_id}/claims", headers=identity_headers(candidate_id)
        ).body


__all__ = [
    "LiveCoveragePlanner",
    "LiveEvaluator",
    "LiveMemory",
    "LiveQuestions",
    "LiveResumes",
]
