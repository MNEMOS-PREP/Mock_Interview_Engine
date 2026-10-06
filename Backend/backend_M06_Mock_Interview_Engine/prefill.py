"""Thinking while the student pauses — M11's FR-11.6, in its strict form.

Spec §6.4: when the student's words stabilise, start the model; if the final
words differ, cancel and start again. The user's rule (2026-10-07): "the
reply should be based on what the answer is — not assume what he or she is
going to say". So nothing kept here is ever used for words that were not said:

- When the student pauses mid-answer, the room may send what they have said so
  far. M06 runs the interviewer's step on it — in memory, writing nothing —
  only so that the model's answers are ready: each kept by its exact request
  (`Recording`).
- When the answer is sent, the real step runs as it always does, on the final
  words, and a model request it makes that is byte-for-byte one already made
  is answered from what was kept (`Replaying`). Any other request — a word
  more, a word different, a state that has moved on — goes to the model.

So the reply is always the reply to the answer as given; the prefill only
moves when the thinking starts. The room sends the words it will send as the
answer, cut from the same recording, so when the student says nothing more
the two are identical. The spec's 15% edit-distance tolerance is NOT used.

One prefill per session is kept, in this process: a newer one replaces it, the
answer takes it. Each answer records how many prefills its question had and
whether one was used — AC-11.7's cancel rate, `tried − used` over `tried`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .llm import LLM, LLMResult

#: How long an answer waits for a prefill still thinking: never longer than
#: starting again would take.
WAIT_S = 8.0


def _key(kind: str, **request: Any) -> str:
    raw = json.dumps([kind, request], sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Kept:
    """Model answers by their exact request. Only successful ones are kept."""

    calls: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def put(self, key: str, value: Any) -> None:
        with self.lock:
            self.calls[key] = value

    def get(self, key: str) -> Any | None:
        with self.lock:
            return self.calls.get(key)


class _Wrapping:
    """Everything a model client has that this does not say otherwise — and
    nothing it lacks: the guard asks `getattr(llm, "classify", None)`, so a
    client without a classifier must still look like one without it."""

    def __init__(self, inner: LLM, kept: Kept):
        self.inner = inner
        self.kept = kept

    def __getattr__(self, name: str) -> Any:
        if name == "classify":
            inner_classify = self.inner.classify  # AttributeError if absent
            return lambda *, job, text: self._classify(inner_classify, job=job, text=text)
        return getattr(self.inner, name)

    def _classify(self, call: Any, *, job: str, text: str) -> LLMResult:
        return call(job=job, text=text)

    @property
    def available(self) -> bool:
        return self.inner.available


class Recording(_Wrapping):
    """Calls through, keeping each successful answer by its request."""

    def structured(self, *, job: str, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        result = self.inner.structured(job=job, system=system, user=user, schema=schema)
        if result.ok:
            key = _key("structured", job=job, system=system, user=user, schema=schema)
            self.kept.put(key, copy.copy(result))
        return result

    def stream(self, *, job: str, system: str, user: str) -> Iterator[str | LLMResult]:
        parts: list[str | LLMResult] = []
        for part in self.inner.stream(job=job, system=system, user=user):
            parts.append(part)
            yield part
        last = parts[-1] if parts else None
        if isinstance(last, LLMResult) and last.ok:
            self.kept.put(_key("stream", job=job, system=system, user=user), parts)

    def _classify(self, call: Any, *, job: str, text: str) -> LLMResult:
        result = call(job=job, text=text)
        if result.ok:
            self.kept.put(_key("classify", job=job, text=text), copy.copy(result))
        return result


class Replaying(_Wrapping):
    """Answers a request seen in the prefill from what was kept; anything
    else goes to the model. A replayed answer took no time to wait for, and
    says so (`latency_ms` 0)."""

    def __init__(self, inner: LLM, kept: Kept):
        super().__init__(inner, kept)
        self.hits = 0

    def _replayed(self, result: LLMResult) -> LLMResult:
        self.hits += 1
        out = copy.copy(result)
        out.latency_ms = 0
        out.first_token_ms = 0 if out.first_token_ms is not None else None
        return out

    def structured(self, *, job: str, system: str, user: str, schema: dict[str, Any]) -> LLMResult:
        hit = self.kept.get(_key("structured", job=job, system=system, user=user, schema=schema))
        if hit is not None:
            return self._replayed(hit)
        return self.inner.structured(job=job, system=system, user=user, schema=schema)

    def stream(self, *, job: str, system: str, user: str) -> Iterator[str | LLMResult]:
        hit = self.kept.get(_key("stream", job=job, system=system, user=user))
        if hit is None:
            yield from self.inner.stream(job=job, system=system, user=user)
            return
        yield from hit[:-1]
        yield self._replayed(hit[-1])

    def _classify(self, call: Any, *, job: str, text: str) -> LLMResult:
        hit = self.kept.get(_key("classify", job=job, text=text))
        if hit is not None:
            return self._replayed(hit)
        return call(job=job, text=text)


@dataclass
class Pending:
    question_turn_id: uuid.UUID
    text: str
    kept: Kept = field(default_factory=Kept)
    done: threading.Event = field(default_factory=threading.Event)
    #: Prefills this question has had, this one included.
    tried: int = 1


_PENDING: dict[uuid.UUID, Pending] = {}
_LOCK = threading.Lock()


def begin(session_id: uuid.UUID, question_turn_id: uuid.UUID, text: str) -> Pending:
    """A new prefill for this session; it replaces the one before."""
    with _LOCK:
        before = _PENDING.get(session_id)
        tried = before.tried + 1 if before and before.question_turn_id == question_turn_id else 1
        entry = Pending(question_turn_id=question_turn_id, text=text, tried=tried)
        _PENDING[session_id] = entry
        return entry


def take(session_id: uuid.UUID, question_turn_id: uuid.UUID) -> Pending | None:
    """The session's prefill, if it was for this question. Taken once."""
    with _LOCK:
        entry = _PENDING.pop(session_id, None)
    if entry is None or entry.question_turn_id != question_turn_id:
        return None
    return entry


def forget(session_id: uuid.UUID) -> None:
    with _LOCK:
        _PENDING.pop(session_id, None)


__all__ = ["WAIT_S", "Kept", "Pending", "Recording", "Replaying", "begin", "forget", "take"]
