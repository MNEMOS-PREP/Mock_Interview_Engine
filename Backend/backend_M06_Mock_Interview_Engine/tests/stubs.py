"""Test doubles that stand in for a live model and a live M05."""

from __future__ import annotations

import uuid
from typing import Any

from backend_M06_Mock_Interview_Engine.adapters.fixtures import LocalQuestions
from backend_M06_Mock_Interview_Engine.llm import LLMResult


def answer(engine, row, text: str):
    """Answer the open question, as the suite's `say` helpers do.

    Since 2026-10-22 a give-up at a question's opening is met with ONE
    simpler question before the interviewer moves on (`ladder.decide`,
    case K). The tests that answer "I do not know." are about what happens
    after the move on — budgets, pacing, re-plans, retries — so this gives up
    on the simpler question too, and they still get there in one call. The
    simpler question itself is tested where it is the subject
    (`test_controller.py`, `test_answer_types.py`)."""
    from backend_M06_Mock_Interview_Engine.contracts import SessionStatus

    state = engine.answer(row.id, engine.state(row.id).open_turn_id, text)
    last = next((t for t in reversed(state.transcript) if t.role == "interviewer"), None)
    if (
        last is not None
        and last.probe_move == "simplify"
        and state.open_turn_id is not None
        and state.status is SessionStatus.live
    ):
        state = engine.answer(row.id, state.open_turn_id, text)
    return state


def close(engine, row):
    """End the session, closing the open question: since 2026-10-22 its
    evaluation is owed when the question closes, not when an answer lands."""
    return engine.end(row.id, "ended_by_student")


def scored_rows(db, session_id) -> list:
    """What this session queued for M13 — one row per closed question."""
    from sqlmodel import select

    from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox

    return list(
        db.exec(select(EvaluationOutbox).where(EvaluationOutbox.session_id == session_id)).all()
    )


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
        rephrased: str = "Put simply: what does that change, and when?",
        closing: str = "ROLE",
    ):
        self.verdicts = list(verdicts or [verdict()])
        self.probe = probe
        #: What the real model returns to the rephrase prompt (one question)
        #: and to the closing prompt (an explanation, or ROLE / REPORT).
        self.rephrased = rephrased
        self.closing = closing
        self.fail_structured = fail_structured
        self.fail_stream = fail_stream
        self.structured_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        return True

    #: What the question-split job is told (`decompose.py`): by default, ask
    #: every question whole — set `split` to a split's data to test one.
    split: dict[str, Any] | None = None

    def structured(self, *, job, system, user, schema) -> LLMResult:
        if job == "question_split":
            # Its own channel: a split is not a verdict, and must not eat one
            # of the verdicts a test scripted for its answers.
            self.split_calls = [*getattr(self, "split_calls", []), {"user": user}]
            data = self.split or {
                "split": False,
                "primary": "",
                "primary_key_point_ids": [],
                "parts": [],
            }
            return LLMResult(ok=True, data=dict(data), job=job, tier="extraction", model="stub")
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
        said = (
            self.closing
            if "output exactly ROLE" in system
            else self.rephrased
            if "asked for it another way" in system
            else self.probe
        )
        words = said.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
        yield LLMResult(
            ok=True,
            text=said,
            job=job,
            tier="generation",
            model="stub",
            latency_ms=12,
            first_token_ms=3,
        )


class GuardedStubLLM(StubLLM):
    """A stub with the guard tier too (EC-6.6). Separate from `StubLLM` so a
    test about the strategist or the interviewer is not also a test about
    how many model calls the guard adds.

    `guard_score` is what the classifier answers for every text; `fail_guard`
    makes it fail, which the guard must survive by failing open.
    """

    def __init__(self, *args, guard_score: float = 0.0, fail_guard: str | None = None, **kw):
        super().__init__(*args, **kw)
        self.guard_score = guard_score
        self.fail_guard = fail_guard
        self.classify_calls: list[str] = []

    def classify(self, *, job, text):
        self.classify_calls.append(text)
        if self.fail_guard:
            return LLMResult(ok=False, reason=self.fail_guard, job=job, model="stub-guard")
        return LLMResult(
            ok=True,
            data={"score": self.guard_score},
            text=str(self.guard_score),
            job=job,
            tier="guard",
            model="stub-guard",
            latency_ms=5,
        )


class BankQuestions(LocalQuestions):
    """M05 as if it were live: same items, but selected as bank items.

    Records every request, because half of what the plan does is decide what
    M05 is asked for — a plan nothing asks against only exists on a screen.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests: list[dict] = []

    def select(self, request):
        self.requests.append(dict(request))
        chosen = super().select(request)
        if chosen is not None:
            chosen["reason"] = "max_info"
        return chosen


class DownPlanner:
    """M02 that fails every call."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M02", "connection refused")

    plan = job_description = requirements = record_coverage = session_coverage = _fail


class DownQuestions:
    """M05 that fails every call."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M05", "connection refused")

    select = question = tracks = seed = observe = close = flag = _fail


class NoClaims:
    """M01 with a clean resume — nothing risky, so no project segment.

    The fixture M01 always has one shaky claim, which is right for the drill
    and is noise in a test about M02's rounds. A test that says which
    upstreams it cares about is a test whose failure means something.
    """

    def resumes_for(self, candidate_id: uuid.UUID) -> list[dict[str, Any]]:
        return []

    def claims(self, resume_id: uuid.UUID, candidate_id: uuid.UUID) -> dict[str, Any]:
        return {"resume_id": str(resume_id), "claims": [], "counts": {}, "total": 0}


class DownMemory:
    """M04 that fails every call — no history, no consent, no pinned prefix."""

    def _fail(self, *_a, **_k):
        from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable

        raise UpstreamUnavailable("M04", "connection refused")

    profile_summary = posterior = consent = register_artifact = concept = _fail


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
                "expects": ["names model and data"],
            },
            {
                "depth": 1,
                "question": "How did you split the data?",
                "expects": ["a held-out test set"],
            },
            {
                "depth": 2,
                "question": "What baseline does 94% beat?",
                "expects": ["a named baseline"],
            },
        ],
    }
