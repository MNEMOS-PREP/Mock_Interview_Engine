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
    def __init__(self, base_url: str):
        self.http = JSONClient("M02", base_url)

    def plan(self, jd_id: UUID, candidate_id: UUID, minutes: int) -> dict[str, Any]:
        return self.http.post(
            f"/v1/jds/{jd_id}/plan/{candidate_id}",
            {"minutes": minutes},
            headers=identity_headers(candidate_id),
        ).body

    def job_description(self, jd_id: UUID) -> dict[str, Any]:
        return self.http.get(f"/v1/jds/{jd_id}").body

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
            f"/v1/sessions/{session_id}/coverage/{candidate_id}",
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
            f"/v1/sessions/{session_id}/coverage/{candidate_id}",
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
        ).body

    def posterior(self, candidate_id: UUID, concepts: list[str]) -> dict[str, float]:
        if not concepts:
            return {}
        body = self.http.get(
            "/v1/skill-graph/theta",
            query={"candidate": str(candidate_id), "concepts": ",".join(concepts)},
            service=True,
        ).body
        # A resolved concept with nothing measured comes back as theta=None,
        # never 0.0 (M04 AC-4.2). Dropping it here keeps it that way: M05
        # seeds an absent concept at the prior, which is the honest belief.
        return {
            concept: float(row["theta"])
            for concept, row in (body or {}).get("per_topic", {}).items()
            if row.get("theta") is not None
        }

    def consent(self, candidate_id: UUID, purpose: str) -> UUID | None:
        # M04 stores consent (m04_consent) and exposes no route to read it
        # (M06_REVIEW 1.3). Asking would 404 on every session; saying "not
        # recorded" is the true answer until the route exists.
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

    def observe(self, session_id: UUID, concept_id: str, outcome: dict[str, Any]) -> float | None:
        response = self.http.post(
            f"/v1/sessions/{session_id}/theta/observe",
            {"concept_id": concept_id, "outcome": outcome},
            accept=(404,),
        )
        if response.status == 404:
            # M05 restarted and lost its in-memory session. The engine
            # re-seeds; nothing about the student is wrong.
            raise UpstreamUnavailable("M05", "session not seeded")
        value = (response.body or {}).get("theta_provisional")
        return float(value) if value is not None else None

    def close(self, session_id: UUID, posterior: dict[str, float]) -> dict[str, Any]:
        response = self.http.post(
            f"/v1/sessions/{session_id}/close", {"posterior": posterior}, accept=(404,)
        )
        return response.body if response.status != 404 else {"closed": False}

    def flag(self, question_id: UUID, reason: str, note: str, candidate_id: UUID) -> dict[str, Any]:
        return self.http.post(
            f"/v1/questions/{question_id}/flag",
            {"reason": reason, "note": note, "candidate_id": str(candidate_id)},
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
