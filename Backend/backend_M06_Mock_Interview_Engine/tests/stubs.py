"""Test doubles that stand in for a live model and a live M05."""

from __future__ import annotations

import uuid
from typing import Any

from backend_M06_Mock_Interview_Engine.adapters.fixtures import LocalQuestions
from backend_M06_Mock_Interview_Engine.llm import LLMResult


def verdict(**overrides) -> dict[str, Any]:
    base = {
        "band": "at",
        "confidence": 0.8,
        "justification": "held",
        "ambiguous": False,
        "off_question": False,
        "asks_interviewer": False,
        "asks_for_answer": False,
        "key_points_missing": [],
    }
    base.update(overrides)
    return base


class StubLLM:
    """A model that says what it is told to. Records every call.

    `verdicts` are returned in order by `structured()`; when they run out the
    last one repeats. `probe` is streamed word by word by `stream()`.
    """

    def __init__(
        self,
        verdicts: list[dict[str, Any]] | None = None,
        probe: str = "You mentioned a slot — what decides which slot a key lands in?",
        *,
        fail_structured: str | None = None,
        fail_stream: str | None = None,
    ):
        self.verdicts = list(verdicts or [verdict()])
        self.probe = probe
        self.fail_structured = fail_structured
        self.fail_stream = fail_stream
        self.structured_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        return True

    def structured(self, *, job, system, user, schema) -> LLMResult:
        self.structured_calls.append({"job": job, "system": system, "user": user, "schema": schema})
        if self.fail_structured:
            return LLMResult(ok=False, reason=self.fail_structured, job=job, model="stub")
        data = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        return LLMResult(
            ok=True,
            data=dict(data),
            job=job,
            tier="classification",
            model="stub",
            latency_ms=7,
            tokens_in=300,
            tokens_out=40,
            reasoning_tokens=20,
        )

    def stream(self, *, job, system, user):
        self.stream_calls.append({"job": job, "system": system, "user": user})
        if self.fail_stream:
            yield LLMResult(ok=False, reason=self.fail_stream, job=job, model="stub")
            return
        words = self.probe.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
        yield LLMResult(
            ok=True,
            text=self.probe,
            job=job,
            tier="generation",
            model="stub",
            latency_ms=12,
            first_token_ms=3,
        )


class BankQuestions(LocalQuestions):
    """M05 as if it were live: same items, but selected as bank items."""

    def select(self, request):
        chosen = super().select(request)
        if chosen is not None:
            chosen["reason"] = "max_info"
        return chosen


class DownPlanner:
    """M02 that fails every call."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M02", "connection refused")

    plan = job_description = record_coverage = session_coverage = _fail


class DownQuestions:
    """M05 that fails every call."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M05", "connection refused")

    select = question = seed = observe = close = flag = _fail


class DownMemory:
    """M04 that fails every call — no history, no consent, no pinned prefix."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M04", "connection refused")

    profile_summary = posterior = consent = _fail


def drill_body(candidate: uuid.UUID) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate),
        "source_module": "M01",
        "claim_id": "c-7",
        "claim_text": "Built a crop-disease classifier reaching 94% accuracy",
        "probes": [
            {
                "depth": 0,
                "question": "Walk me through the classifier.",
                "expects": "names model and data",
            },
            {
                "depth": 1,
                "question": "How did you split the data?",
                "expects": "a held-out test set",
            },
            {"depth": 2, "question": "What baseline does 94% beat?", "expects": "a named baseline"},
        ],
    }
