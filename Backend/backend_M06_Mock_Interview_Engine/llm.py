"""The model client — M02's shape, plus the two things an interview loop needs.

This is the fourth copy of the platform's OpenAI-dialect client (M01, M02, M13,
and this). M02's docstring already says it belongs in `ai_core`; M06 keeps the
same `structured()` contract so promoting it is a move, not a merge. What M06
adds, and why each is needed here and nowhere else yet:

* **`stream()`**, with time-to-first-token. The text latency gate is TTFT
  (spec §11, AC-6.4): "the interviewer started talking" is what a student
  perceives, so it is what gets measured.
* **Reasoning control and full usage.** The gpt-oss models spend hidden
  reasoning tokens that count against `max_tokens` (`ai_core.models`). On a
  hot path that is latency, so each job names a reasoning effort, and every
  call records prompt, completion, reasoning and — only when the provider
  reports it — cached tokens (AC-6.11 is "not measured" otherwise).

**A parameter the provider rejects is dropped, once, and remembered.** Groq's
dialect is OpenAI's with extensions; a request field one model accepts can be
a 400 on another. Rather than hardcode which model takes what, a 400 that
names a field retries without it and the drop is cached for that model.

Every failure is an `LLMResult(ok=False, reason=...)`, never a raise. The
engine always has a deterministic path to fall back to (spec §10).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_core.models import USER_AGENT, Route, resolve

from . import PROMPT_VERSION
from .keys import KeyRing, load_keys

log = logging.getLogger("uvicorn.error")

JOB_STRATEGIST = "probe_strategist"
JOB_INTERVIEWER = "interviewer_phrasing"
JOB_SUMMARY = "segment_summary"
#: EC-6.6. The guard tier is a classifier, not a conversation: it takes the
#: text as the user message and answers with a probability (`classify`).
JOB_GUARD = "input_guard"


@dataclass(frozen=True)
class JobSpec:
    tier: str
    env: str
    #: gpt-oss spends these before any visible token. A hot-path job keeps it low.
    reasoning_effort: str | None
    max_tokens: int
    timeout_s: float
    temperature: float = 0.3


#: Tier per master plan §26.2, mapped onto the tiers `ai_core.models` actually
#: has. Budgets are ceilings, not targets; the latency harness says where they
#: sit in practice.
JOBS: dict[str, JobSpec] = {
    JOB_STRATEGIST: JobSpec(
        tier="classification",
        env="M06_MODEL_STRATEGIST",
        reasoning_effort="low",
        max_tokens=1500,
        timeout_s=float(os.getenv("M06_STRATEGIST_TIMEOUT", "4")),
        temperature=0.0,
    ),
    JOB_INTERVIEWER: JobSpec(
        tier="generation",
        env="M06_MODEL_INTERVIEWER",
        reasoning_effort="low",
        max_tokens=1200,
        timeout_s=float(os.getenv("M06_INTERVIEWER_TIMEOUT", "6")),
        temperature=0.5,
    ),
    JOB_SUMMARY: JobSpec(
        tier="extraction",
        env="M06_MODEL_SUMMARY",
        reasoning_effort="low",
        max_tokens=1500,
        timeout_s=10.0,
    ),
    JOB_GUARD: JobSpec(
        tier="guard",
        env="M06_MODEL_GUARD",
        reasoning_effort=None,
        max_tokens=16,
        # Measured 230–680 ms. It runs beside the strategist, so it only
        # delays a turn if it outlasts it — and past this it fails open.
        timeout_s=float(os.getenv("M06_GUARD_TIMEOUT", "1.5")),
        temperature=0.0,
    ),
}

#: Request fields that are extensions to the base dialect and may be refused.
OPTIONAL_FIELDS = ("reasoning_effort", "include_reasoning", "stream_options")


@dataclass
class LLMResult:
    ok: bool = False
    data: dict[str, Any] | None = None
    text: str = ""
    reason: str = ""
    job: str = ""
    tier: str = ""
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0
    first_token_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None


#: Called once per finished call, successful or not. The engine uses it to
#: write `m06_llm_call`, which is the model half of the trace (FR-6.19).
CallSink = Callable[[LLMResult], None]


class LLM(Protocol):
    @property
    def available(self) -> bool: ...

    def structured(
        self, *, job: str, system: str, user: str, schema: dict[str, Any]
    ) -> LLMResult: ...

    def stream(self, *, job: str, system: str, user: str) -> Iterator[str | LLMResult]: ...

    def classify(self, *, job: str, text: str) -> LLMResult: ...


@dataclass
class NullLLM:
    """No key. Every call declines with the reason — the normal state of CI."""

    reason: str = "no model configured"

    @property
    def available(self) -> bool:
        return False

    def structured(self, *, job: str, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        return LLMResult(ok=False, reason=self.reason, job=job)

    def stream(self, *, job: str, system: str, user: str) -> Iterator[str | LLMResult]:
        yield LLMResult(ok=False, reason=self.reason, job=job)

    def classify(self, *, job: str, text: str) -> LLMResult:
        return LLMResult(ok=False, reason=self.reason, job=job)


def _usage(result: LLMResult, usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    result.tokens_in = usage.get("prompt_tokens")
    result.tokens_out = usage.get("completion_tokens")
    details = usage.get("completion_tokens_details") or {}
    result.reasoning_tokens = details.get("reasoning_tokens")
    prompt_details = usage.get("prompt_tokens_details") or {}
    cached = prompt_details.get("cached_tokens")
    # Absent means "the provider did not say", which is different from zero.
    result.cached_tokens = cached if cached is not None else None


@dataclass
class OpenAICompatLLM:
    rings: dict[str, KeyRing] = field(default_factory=dict)
    #: model id -> request fields that model refused.
    refused: dict[str, set[str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def available(self) -> bool:
        return any(bool(resolve(spec.tier)) for spec in JOBS.values())  # type: ignore[arg-type]

    def _route(self, job: str) -> tuple[JobSpec, Route]:
        spec = JOBS[job]
        return spec, resolve(spec.tier, job_env=spec.env)  # type: ignore[arg-type]

    def _key(self, route: Route) -> str:
        assert route.provider is not None
        name = route.provider.name
        with self._lock:
            ring = self.rings.get(name)
            if ring is None or len(ring) != len(route.keys):
                ring = KeyRing(keys=list(route.keys))
                self.rings[name] = ring
        return ring.next()

    def _body(self, spec: JobSpec, route: Route, system: str, user: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": route.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }
        if route.profile is not None and route.profile.reasoning:
            if spec.reasoning_effort:
                body["reasoning_effort"] = spec.reasoning_effort
            body["include_reasoning"] = False
        for name in self.refused.get(route.model, ()):
            body.pop(name, None)
        return body

    def _open(
        self, route: Route, body: dict[str, Any], timeout: float
    ) -> tuple[Any | None, str | None]:
        """POST, dropping a refused optional field once. Returns (response, error).

        One retry for a 429 or a 5xx, on the next key, and no more: this is a
        hot path, and the caller always has a deterministic answer ready.
        """
        transient_retries = 0
        for _attempt in range(len(OPTIONAL_FIELDS) + 2):
            assert route.provider is not None
            request = urllib.request.Request(
                f"{route.provider.base_url}/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self._key(route)}",
                    "Content-Type": "application/json",
                    # A default urllib User-Agent is a Cloudflare 403 (ai_core.models).
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            try:
                return urllib.request.urlopen(request, timeout=timeout), None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code == 400:
                    culprit = next((f for f in OPTIONAL_FIELDS if f in body and f in detail), None)
                    if culprit is not None:
                        self.refused.setdefault(route.model, set()).add(culprit)
                        body.pop(culprit, None)
                        log.info("M06: %s refuses %s; dropped", route.model, culprit)
                        continue
                if (exc.code == 429 or exc.code >= 500) and transient_retries == 0:
                    # A 429 is usually this key's minute, so the retry takes the next key.
                    transient_retries += 1
                    time.sleep(0.2)
                    continue
                return None, f"HTTP {exc.code}: {detail}"
            except TimeoutError:
                return None, f"timeout after {timeout}s"
            except Exception as exc:  # noqa: BLE001 - every failure degrades
                return None, f"{type(exc).__name__}: {exc}"
        return None, "gave up after retries"

    def structured(self, *, job: str, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        spec, route = self._route(job)
        result = LLMResult(job=job, tier=spec.tier, model=route.model)
        if not route:
            result.reason = route.unusable or "no route"
            return result
        body = self._body(spec, route, system, user)
        if route.profile is not None and route.profile.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": job, "strict": True, "schema": schema},
            }
        started = time.perf_counter()
        response, error = self._open(route, body, spec.timeout_s)
        if response is None:
            result.reason = error or "no response"
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            return result
        with response:
            try:
                payload = json.loads(response.read())
            except (json.JSONDecodeError, TimeoutError) as exc:
                result.reason = f"unreadable response: {exc}"
                return result
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        _usage(result, payload.get("usage"))
        try:
            content = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            result.reason = "response had no message content"
            return result
        if not content.strip():
            result.reason = (
                f"empty content ({result.tokens_out} completion tokens, likely reasoning)"
            )
            return result
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            result.reason = f"unparseable JSON: {exc}"
            return result
        if not isinstance(parsed, dict):
            result.reason = "response was not a JSON object"
            return result
        result.ok, result.data, result.text = True, parsed, content
        return result

    def classify(self, *, job: str, text: str) -> LLMResult:
        """A classifier's score for `text`: `data = {"score": float}`.

        The guard tier (Llama Prompt Guard 2) answers with the probability,
        as text, that its input is an attack — measured, not documented. It
        takes no system prompt: the text is the whole input, because a system
        message is itself text it would classify.
        """
        spec, route = self._route(job)
        result = LLMResult(job=job, tier=spec.tier, model=route.model)
        if not route:
            result.reason = route.unusable or "no route"
            return result
        body: dict[str, Any] = {
            "model": route.model,
            "messages": [{"role": "user", "content": text}],
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }
        started = time.perf_counter()
        response, error = self._open(route, body, spec.timeout_s)
        if response is None:
            result.reason = error or "no response"
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            return result
        with response:
            try:
                payload = json.loads(response.read())
            except (json.JSONDecodeError, TimeoutError) as exc:
                result.reason = f"unreadable response: {exc}"
                return result
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        _usage(result, payload.get("usage"))
        try:
            content = str(payload["choices"][0]["message"]["content"] or "").strip()
            score = float(content)
        except (KeyError, IndexError, TypeError, ValueError):
            result.reason = "classifier answered with something that is not a score"
            return result
        result.ok, result.data, result.text = True, {"score": score}, content
        return result

    def stream(self, *, job: str, system: str, user: str) -> Iterator[str | LLMResult]:
        """Yields text deltas, then exactly one `LLMResult` (always last)."""
        spec, route = self._route(job)
        result = LLMResult(job=job, tier=spec.tier, model=route.model)
        if not route:
            result.reason = route.unusable or "no route"
            yield result
            return
        body = self._body(spec, route, system, user)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        response, error = self._open(route, body, spec.timeout_s)
        if response is None:
            result.reason = error or "no response"
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            yield result
            return
        parts: list[str] = []
        try:
            with response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                    if usage:
                        _usage(result, usage)
                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            if result.first_token_ms is None:
                                result.first_token_ms = int((time.perf_counter() - started) * 1000)
                            parts.append(delta)
                            yield delta
        except Exception as exc:  # noqa: BLE001 - a broken stream degrades
            result.reason = f"stream interrupted: {type(exc).__name__}: {exc}"
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        result.text = "".join(parts)
        result.ok = bool(result.text.strip()) and not result.reason
        if not result.ok and not result.reason:
            result.reason = "empty stream"
        yield result


_llm: LLM | None = None
_llm_lock = threading.Lock()


def get_llm(*, refresh: bool = False) -> LLM:
    global _llm
    with _llm_lock:
        if _llm is not None and not refresh:
            return _llm
        load_keys()
        usable = [job for job, spec in JOBS.items() if resolve(spec.tier)]  # type: ignore[arg-type]
        if not usable:
            reason = resolve("generation").unusable or "no model configured"
            log.info("M06 language model off: %s", reason)
            _llm = NullLLM(reason=reason)
        else:
            _llm = OpenAICompatLLM()
            log.info("M06 language model on for: %s", ", ".join(sorted(usable)))
        return _llm


def set_llm(llm: LLM | None) -> None:
    """Replace the client. For tests, and for nothing else."""
    global _llm
    with _llm_lock:
        _llm = llm


__all__ = [
    "JOBS",
    "JOB_GUARD",
    "JOB_INTERVIEWER",
    "JOB_STRATEGIST",
    "JOB_SUMMARY",
    "LLM",
    "CallSink",
    "JobSpec",
    "LLMResult",
    "NullLLM",
    "OpenAICompatLLM",
    "get_llm",
    "set_llm",
]
