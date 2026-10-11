"""A model call is given up on at its deadline (2026-10-11).

A slow night: the guard (1.5 s) took 6.3 s and the strategist (4 s) 6.7 s,
because the socket's timeout bounds each read, not the call; the student
waited 8.5 s for a reply. Past the deadline the call fails like any other,
and the caller's fallback answers.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from backend_M06_Mock_Interview_Engine import llm


def test_a_call_past_its_deadline_fails_at_the_deadline(monkeypatch):
    client = object.__new__(llm.OpenAICompatLLM)
    spec = SimpleNamespace(tier="guard", timeout_s=0.3, temperature=0.0, max_tokens=1)
    route = SimpleNamespace(model="slow-model")
    monkeypatch.setattr(client, "_route", lambda job: (spec, route), raising=False)

    def hangs(route, body, timeout):
        time.sleep(2)
        raise AssertionError("the answer came too late to be used")

    monkeypatch.setattr(client, "_open", hangs, raising=False)
    started = time.perf_counter()
    result = client.classify(job=llm.JOB_GUARD, text="an answer")
    took = time.perf_counter() - started
    assert not result.ok
    assert "within 0.3s" in result.reason
    assert took < 1.0, took
