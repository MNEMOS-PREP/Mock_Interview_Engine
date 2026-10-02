"""What M06 needs from each upstream — as interfaces, with one failure type.

Every upstream is optional (module.json). So "the module is down" is not an
exception that escapes to a student: each live client raises
`UpstreamUnavailable`, and the engine turns that into the documented fallback
and the `on_missing` sentence (spec §10). A 409 from M05 is different — it is
a specified answer ("the bank cannot fill this round"), so it comes back as
`None`, not as an error.

Every method name and payload here was checked against the upstream's shipped
router, not its spec (M06_REVIEW Part 1). `tests/test_contracts.py` holds them
to the captured shapes in `fixtures/contracts/`, so an upstream change breaks a
test in this repo rather than a session.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class UpstreamUnavailable(Exception):
    """The module could not be reached, or answered with something unusable."""

    def __init__(self, module: str, detail: str):
        self.module = module
        self.detail = detail
        super().__init__(f"{module}: {detail}")


class CoveragePlanner(Protocol):
    """M02 — JD Parser & Coverage Planner."""

    def plan(self, jd_id: UUID, candidate_id: UUID, minutes: int) -> dict[str, Any]:
        """`POST /v1/jds/{jd_id}/plan/{candidate_id}` → `CoveragePlan`."""

    def job_description(self, jd_id: UUID) -> dict[str, Any]:
        """`GET /v1/jds/{jd_id}` — requirements and `resolved_concepts`."""

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
        """`POST /v1/sessions/{sid}/coverage/{cid}` — asked / answered / skipped."""

    def session_coverage(self, session_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        """`GET /v1/sessions/{sid}/coverage/{cid}` — the report's coverage block."""


class Memory(Protocol):
    """M04 — Skill Graph & MNEMOS Memory."""

    def profile_summary(self, candidate_id: UUID, session_id: UUID) -> dict[str, Any]:
        """`GET /v1/candidates/{cid}/profile-summary?session_id=` — pinned (AC-4.13)."""

    def posterior(self, candidate_id: UUID, concepts: list[str]) -> dict[str, float]:
        """`GET /v1/skill-graph/theta` reduced to `{concept_id: theta}`, measured only."""

    def consent(self, candidate_id: UUID, purpose: str) -> UUID | None:
        """`GET /v1/candidates/{cid}/consent?purpose=` — the active consent id, or None."""

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        """`GET /v1/concepts/{id}` — name and one hop of `prerequisites`.

        Public ontology, no student in it. §6.4's gap trigger asks it which
        prerequisite two broken concepts share. None for an unknown concept.
        """


class Questions(Protocol):
    """M05 — Question Intelligence."""

    def select(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """`POST /v1/questions/select`. None on 409 — the bank cannot fill it."""

    def question(self, question_id: UUID) -> dict[str, Any]:
        """`GET /v1/questions/{id}` — hint_ladder, follow_ups, key_points."""

    def seed(
        self,
        session_id: UUID,
        candidate_id: UUID,
        posterior: dict[str, float],
        snapshot_id: str,
    ) -> dict[str, Any]:
        """`POST /v1/sessions/{sid}/theta/seed`."""

    def observe(
        self,
        session_id: UUID,
        concept_id: str,
        outcome: dict[str, Any],
        candidate_id: UUID | None = None,
    ) -> float | None:
        """`POST /v1/sessions/{sid}/theta/observe` → the provisional θ, in memory only."""

    def close(
        self,
        session_id: UUID,
        posterior: dict[str, float],
        candidate_id: UUID | None = None,
    ) -> dict[str, Any]:
        """`POST /v1/sessions/{sid}/close`."""

    def flag(self, question_id: UUID, reason: str, note: str, candidate_id: UUID) -> dict[str, Any]:
        """`POST /v1/questions/{id}/flag` — the ⚑ button."""


class Evaluator(Protocol):
    """M13 — Evaluation Engine."""

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        """`POST /v1/evaluations`. Synchronous — only ever called from the outbox."""

    def ensembles(self) -> list[dict[str, Any]]:
        """`GET /v1/ensembles` — the configurations M13 will honour by name.

        Worth asking, because M13 falls back to its DEFAULT for a name it does
        not know, and that default is `n1_practice`: a typo in a mock-mode
        ensemble would silently score that session with one evaluator instead
        of three. Quieter than an error and harder to notice.
        """

    def rubrics(self) -> list[dict[str, Any]]:
        """`GET /v1/rubrics` → the round types M13 can score, with hint penalties."""

    def evaluation(self, turn_id: UUID) -> dict[str, Any] | None:
        """`GET /v1/evaluations/{turn_id}`. None when it does not exist yet."""

    def calibration(self) -> dict[str, Any]:
        """`GET /v1/calibration` — the display gate the report must honour."""


class Resumes(Protocol):
    """M01 — Resume Ingestion."""

    def resumes_for(self, candidate_id: UUID) -> list[dict[str, Any]]:
        """`GET /v1/resumes/candidate/{cid}`."""

    def claims(self, resume_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        """`GET /v1/resumes/{rid}/claims` — ordered by prominence × risk."""


__all__ = [
    "CoveragePlanner",
    "Evaluator",
    "Memory",
    "Questions",
    "Resumes",
    "UpstreamUnavailable",
]
