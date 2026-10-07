"""In-process stand-ins for the five upstreams.

Two uses, deliberately kept apart:

* **`LocalQuestions` is production code.** It is what M06 asks when M05 cannot
  be reached (spec §10): M06's own short playlist, never sent to M13.
* **Everything else is for tests and for running M06 alone.** Each one answers
  in the upstream's captured shape (`fixtures/contracts/`) and records what it
  was sent, so a test can assert on the outbound side of a contract as well as
  the inbound one. None of them opens a socket.

The M02 fixture is never a production fallback: a fixture coverage plan would
tell a student their session was tailored to a job description when it was
not. When M02 is down the engine plans without it and says so.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@lru_cache(maxsize=1)
def fallback_playlist() -> dict[str, Any]:
    return json.loads((FIXTURES / "fallback_playlist.json").read_text(encoding="utf-8"))


class LocalQuestions:
    """M06's own playlist, in M05's `Question` shape. Selection is in order."""

    source = "local_fallback"

    def __init__(self, items: list[dict[str, Any]] | None = None):
        self.items = items if items is not None else fallback_playlist()["items"]
        self.by_id = {UUID(item["id"]): item for item in self.items}
        self.selected: list[dict[str, Any]] = []
        self.observed: list[tuple[UUID, str, dict[str, Any]]] = []
        self.seeded: dict[UUID, dict[str, float]] = {}

    def select(self, request: dict[str, Any]) -> dict[str, Any] | None:
        self.selected.append(request)
        seen = {UUID(str(i)) for i in request.get("seen_item_ids", [])}
        for item in self.items:
            item_id = UUID(item["id"])
            if item_id in seen or request["round_type"] not in item["round_types"]:
                continue
            if item["time_budget_s"] > request.get("time_remaining_s", 1800):
                continue
            return {
                "question_id": str(item_id),
                "round_type": request["round_type"],
                "reason": "fallback",
                "expected_information": 0.0,
                "predicted_score": 0.0,
                "n_categories": 5,
                "theta_eligible": False,
                "params_source": "prior",
                "disclosure": None,
                "alternatives": [],
            }
        return None

    def question(self, question_id: UUID) -> dict[str, Any]:
        return self.by_id[UUID(str(question_id))]

    def tracks(self) -> dict[str, Any]:
        """M05's `/v1/bank/tracks` shape, for the round types this set holds.
        No names: the playlist does not have any, and the planner's own
        fallback is the honest one."""
        found: dict[str, int] = {}
        for item in self.items:
            for round_type in item["round_types"]:
                found[round_type] = found.get(round_type, 0) + 1
        return {
            "groups": [],
            "tracks": [
                {"round_type": rt, "kind": "technical", "approved": n, "drafts": 0}
                for rt, n in found.items()
            ],
        }

    def seed(
        self, session_id: UUID, candidate_id: UUID, posterior: dict[str, float], snapshot_id: str
    ) -> dict[str, Any]:
        self.seeded[session_id] = dict(posterior)
        return {"session_id": str(session_id), "seeded_from": snapshot_id}

    def observe(
        self,
        session_id: UUID,
        concept_id: str,
        outcome: dict[str, Any],
        candidate_id: UUID | None = None,
    ) -> float | None:
        self.observed.append((session_id, concept_id, outcome))
        step = {"below": -0.4, "at": 0.0, "above": 0.4}[outcome["band"]]
        return step

    def close(
        self,
        session_id: UUID,
        posterior: dict[str, float],
        candidate_id: UUID | None = None,
    ) -> dict[str, Any]:
        self.seeded.pop(session_id, None)
        return {"session_id": str(session_id), "closed": True}

    def flag(self, question_id: UUID, reason: str, note: str, candidate_id: UUID) -> dict[str, Any]:
        return {"question_id": str(question_id), "excluded_from_selection": True}


class FixtureCoveragePlanner:
    """M02, answering in `CoveragePlan`'s captured shape."""

    def __init__(
        self,
        plan: dict[str, Any] | None = None,
        jd: dict[str, Any] | None = None,
        requirements: list[dict[str, Any]] | None = None,
    ):
        self._plan = plan
        self._jd = jd
        self._requirements = requirements
        self.ledger: list[dict[str, Any]] = []
        self.plan_calls: list[tuple[UUID, UUID, int]] = []
        self.drive_calls: list[tuple[UUID, str]] = []
        #: Set to M02's sentence to answer `from_drive` as M02 does when it
        #: cannot build a requirement set for the drive.
        self.drive_refusal: str | None = None

    def from_drive(self, company_id: UUID, drive_id: str, candidate_id: UUID) -> dict[str, Any]:
        self.drive_calls.append((company_id, drive_id))
        if self.drive_refusal is not None:
            return {"detail": self.drive_refusal}
        # M02 keys a drive's requirement set on the drive, so the same drive
        # is the same JD every time.
        return {
            "id": str(uuid5(company_id, f"drive:{drive_id}")),
            "company_name": "Fixture Co",
            "role_title": "Fixture drive",
        }

    def plan(self, jd_id: UUID, candidate_id: UUID, minutes: int) -> dict[str, Any]:
        self.plan_calls.append((jd_id, candidate_id, minutes))
        if self._plan is not None:
            return self._plan
        return {
            "jd_id": str(jd_id),
            "candidate_id": str(candidate_id),
            "total_minutes": minutes,
            "allocated_minutes": 14.0,
            "allocations": [
                {
                    "requirement_id": "r1",
                    "requirement_text": "Data structures and algorithms",
                    "already_asked": 0,
                    "grounded": True,
                    "question_budget": 2,
                    "round_type": "verbal",
                    "priority": 0.8,
                    "rationale": (
                        "The posting lists data structures first and you have not "
                        "been measured on hashing yet."
                    ),
                    "minutes": 7.0,
                },
                {
                    "requirement_id": "r2",
                    "requirement_text": "Recursion",
                    "already_asked": 0,
                    "grounded": True,
                    "question_budget": 2,
                    "round_type": "verbal",
                    "priority": 0.6,
                    "rationale": "Recursion is named twice in the responsibilities.",
                    "minutes": 7.0,
                },
            ],
            "uncovered": [],
            "unmeasurable": ["Go-getter attitude"],
            "suggestion": None,
            "rounds": [
                {
                    "round_type": "verbal",
                    "minutes": 14.0,
                    "question_count": 4,
                    "requirement_ids": ["r1", "r2"],
                    "difficulty": "calibrated",
                }
            ],
            "difficulty": "calibrated",
            "difficulty_note": "",
            "saturated": False,
            "plan_version": "greedy-log-v1",
        }

    def requirements(self, jd_id: UUID, candidate_id: UUID) -> list[dict[str, Any]]:
        if self._requirements is not None:
            return self._requirements
        return [
            {
                "id": "r1",
                "text": "Data structures and algorithms",
                "measured_by": ["technical"],
                "concept_ids": ["concept:hashing"],
                "testable": True,
            },
            {
                "id": "r2",
                "text": "Recursion",
                "measured_by": ["technical"],
                "concept_ids": ["concept:recursion"],
                "testable": True,
            },
        ]

    def job_description(self, jd_id: UUID) -> dict[str, Any]:
        if self._jd is not None:
            return self._jd
        return {
            "id": str(jd_id),
            "company_name": "Fixture Labs",
            "role_title": "Software Engineer",
            "requirements": [
                {
                    "id": "r1",
                    "text": "Data structures and algorithms",
                    "measured_by": ["technical"],
                },
                {"id": "r2", "text": "Recursion", "measured_by": ["technical"]},
            ],
            "resolved_concepts": {
                "Data structures and algorithms": "concept:hashing",
                "Recursion": "concept:recursion",
            },
        }

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
        row = {
            "session_id": str(session_id),
            "candidate_id": str(candidate_id),
            "jd_id": str(jd_id),
            "requirement_id": requirement_id,
            "state": state,
            "turn_id": str(turn_id) if turn_id else None,
        }
        self.ledger.append(row)
        return {"id": str(uuid.uuid4()), "state": state}

    def session_coverage(self, session_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        asked: dict[str, int] = {}
        for row in self.ledger:
            if row["session_id"] == str(session_id) and row["state"] == "asked":
                asked[row["requirement_id"]] = asked.get(row["requirement_id"], 0) + 1
        return {
            "session_id": str(session_id),
            "candidate_id": str(candidate_id),
            "asked": asked,
            "scores": {},
            "requirements": [],
            "questions_asked": sum(asked.values()),
        }


class FixtureMemory:
    """M04. `consent_id=None` by default — the true state of the platform today."""

    def __init__(self, consent_id: UUID | None = None, posterior: dict[str, float] | None = None):
        self._consent = consent_id
        self._posterior = posterior or {}
        self.summaries: dict[UUID, dict[str, Any]] = {}
        #: turn_id -> the answer text M13's evidence will resolve against.
        self.artifacts: dict[UUID, str] = {}

    def profile_summary(self, candidate_id: UUID, session_id: UUID) -> dict[str, Any]:
        # Pinned: the same object for the life of the session (M04 AC-4.13).
        if session_id not in self.summaries:
            self.summaries[session_id] = {
                "session_id": str(session_id),
                "candidate_id": str(candidate_id),
                "summary_text": "Hashing: developing · Recursion: not measured",
                "payload": {
                    "candidate_id": str(candidate_id),
                    "ontology_version": "1.0",
                    "measured_concepts": 1,
                    "weakest": [
                        {
                            "concept_id": "concept:hashing",
                            "name": "Hashing",
                            "state": "developing",
                            "mastery_p": 0.42,
                            "n_direct": 3,
                            "stale": False,
                        }
                    ],
                    "strongest": [],
                    "bottlenecks": [],
                    "retests": [],
                    "recent_sessions": [],
                    "facts": [],
                },
                "summary_version": "1.0",
                "ontology_version": "1.0",
                "built_at": "2026-09-16T00:00:00+00:00",
                "pinned": True,
            }
        return self.summaries[session_id]

    def posterior(self, candidate_id: UUID, concepts: list[str]) -> dict[str, float]:
        return {c: v for c, v in self._posterior.items() if c in concepts}

    def register_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.artifacts[UUID(str(payload["turn_id"]))] = payload["content"]
        return {"artifact_id": payload["turn_id"], "created": True}

    def consent(self, candidate_id: UUID, purpose: str) -> UUID | None:
        return self._consent

    #: One hop of M04's ontology, in its shape, for the concepts the fixture
    #: playlist asks about. Stacks and hashing share arrays — which is what
    #: lets a test find the gap §6.4's first trigger looks for.
    ONTOLOGY: dict[str, tuple[str, list[str]]] = {
        "concept:time_complexity": ("Time complexity", ["concept:arrays"]),
        "concept:stacks": ("Stacks", ["concept:arrays"]),
        "concept:queues": ("Queues", ["concept:arrays"]),
        "concept:hashing": ("Hashing", ["concept:arrays"]),
        "concept:recursion": ("Recursion", ["concept:functions"]),
        "concept:arrays": ("Arrays", []),
        "concept:functions": ("Functions", []),
    }

    def concept(self, concept_id: str) -> dict[str, Any] | None:
        found = self.ONTOLOGY.get(concept_id)
        if found is None:
            return None
        name, prerequisites = found
        return {
            "id": concept_id,
            "name": name,
            "prerequisites": [{"concept_id": p, "strength": 0.6, "hops": 1} for p in prerequisites],
        }


class FixtureEvaluator:
    """M13. Records every request; answers with a minimal evaluation."""

    def __init__(self, round_types: tuple[str, ...] = ("dsa_verbal",)):
        self.round_types = round_types
        self.requests: list[dict[str, Any]] = []
        self.fail = False
        #: With `fail`, the status M13 "answered" with; None is an outage.
        self.fail_status: int | None = None
        #: M13's published credit table, as JSON delivers it — string keys.
        #: Settable so a test can republish it and check who kept the old one.
        self.hint_penalty: dict[str, float] = {"0": 1.0, "1": 0.85, "2": 0.7, "3": 0.5}
        #: Called while this request is "in flight", before it is answered.
        #: A test drains again from in here to stand in for a second sender.
        self.on_request: Callable[[dict[str, Any]], None] | None = None

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        from .base import UpstreamUnavailable

        if self.fail:
            # An outage, or (with `fail_status`) an upstream that answered
            # with an error — the outbox holds only the second.
            raise UpstreamUnavailable("M13", "fixture set to fail", status=self.fail_status)
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(request)
        return {
            "id": str(uuid.uuid4()),
            "turn_id": request["turn_id"],
            "status": "complete",
            "aggregated": [],
            "composite": None,
        }

    def rubrics(self) -> list[dict[str, Any]]:
        return [
            {
                "round_type": rt,
                "version": "1.0.0",
                "dimensions": ["correctness", "depth", "communication"],
                "concept_bearing": "correctness",
                "hint_penalty": dict(self.hint_penalty),
            }
            for rt in self.round_types
        ]

    def ensembles(self) -> list[dict[str, Any]]:
        # M13's shipped configs (`ensemble.py`): the count drops in Practice,
        # never the tier.
        return [{"name": "n1_practice", "size": 1}, {"name": "n3_het_v1", "size": 3}]

    def evaluation(self, turn_id: UUID) -> dict[str, Any] | None:
        return None

    def calibration(self) -> dict[str, Any]:
        return {"calibrations": [], "display_numeric": False}


class FixtureResumes:
    """M01, with one resume and one risky claim carrying a probe ladder."""

    def __init__(self, candidate_id: UUID | None = None):
        self.candidate_id = candidate_id
        self.resume_id = uuid.UUID("0b1e0000-0000-4000-8000-000000000001")

    def resumes_for(self, candidate_id: UUID) -> list[dict[str, Any]]:
        # M01's own shape (`GET /v1/resumes/candidate/{id}`): the current
        # resume is `is_active`; `confirmed` is the student's own say-so.
        # An older one first, as M01 lists them, so a test sees the choice.
        return [
            {
                "id": str(uuid5(self.resume_id, "older")),
                "candidate_id": str(candidate_id),
                "is_active": False,
                "confirmed": False,
            },
            {
                "id": str(self.resume_id),
                "candidate_id": str(candidate_id),
                "is_active": True,
                "confirmed": True,
            },
        ]

    def claims(self, resume_id: UUID, candidate_id: UUID) -> dict[str, Any]:
        if resume_id != self.resume_id:
            # The older resume has nothing shaky on it: picking it instead of
            # the current one loses the project round, and a test sees that.
            return {"resume_id": str(resume_id), "claims": []}
        claim = {
            "id": "c1",
            "text": "Built a crop-disease classifier reaching 94% accuracy",
            "risk_band": "risky",
            "risk_score": 0.8,
            "prominence": 0.9,
            "probes": [
                {
                    "depth": 0,
                    "question": "Walk me through the classifier you built.",
                    "expects": ["names the model and the data"],
                },
                {
                    "depth": 1,
                    "question": "How did you split the data for that 94%?",
                    "expects": ["a held-out test set"],
                },
                {
                    "depth": 2,
                    "question": "What was the baseline that 94% beats?",
                    "expects": ["a named baseline and its score"],
                },
            ],
        }
        return {
            "resume_id": str(resume_id),
            "claims": [claim],
            "counts": {"risky": 1},
            "total": 1,
            "fix_first": claim,
        }


__all__ = [
    "FixtureCoveragePlanner",
    "FixtureEvaluator",
    "FixtureMemory",
    "FixtureResumes",
    "LocalQuestions",
    "fallback_playlist",
]
