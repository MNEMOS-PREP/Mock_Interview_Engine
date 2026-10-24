"""Routing a job to a model, and reading what comes back (2026-10-24).

Three things the notes writer needed from the client, each a way the whole
model layer — not just the notes — could go down:

* the writing tier is newer than the ai_core most modules install, and an
  ai_core without it raised KeyError out of `get_llm()`;
* a write-up holds a thread for 10–25 s, which must not be a thread a live
  turn's strategist is waiting on;
* a provider that ignores `response_format` wraps its JSON, and that is an
  answer, not a failure.
"""

from __future__ import annotations

import json
import threading

import pytest
from ai_core.models import Route

from backend_M06_Mock_Interview_Engine import llm


def _old_ai_core(tier, *, job_env=None):
    """`resolve` as ai_core < 0.40.0 has it: a KeyError for a tier it lacks."""
    if tier == "writing":
        raise KeyError(tier)
    return Route(tier=tier, model="openai/gpt-oss-120b", keys=["k"])


def test_a_tier_the_installed_ai_core_lacks_is_one_unusable_job(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _old_ai_core)

    notes = llm.route_for(llm.JOBS[llm.JOB_NOTES])
    fallback = llm.route_for(llm.JOBS[llm.JOB_NOTES_FALLBACK])

    assert not notes
    assert notes.unusable is not None and "upgrade" in notes.unusable
    assert fallback, "the notes' fallback is on the generation tier, which every ai_core has"


def test_an_old_ai_core_leaves_every_other_job_on(monkeypatch):
    monkeypatch.setattr(llm, "resolve", _old_ai_core)
    monkeypatch.setattr(llm, "load_keys", lambda: None)
    try:
        client = llm.get_llm(refresh=True)
        assert isinstance(client, llm.OpenAICompatLLM)
        assert client.available
    finally:
        llm.set_llm(None)


@pytest.mark.parametrize(
    "content",
    [
        '{"headline": "x"}',
        '<think>the student said sorted…</think>\n{"headline": "x"}',
        'Here it is:\n```json\n{"headline": "x"}\n```',
        'Sure. {"headline": "x"} Hope that helps.',
    ],
)
def test_wrapped_json_is_still_the_answer(content):
    assert llm.json_object(content) == {"headline": "x"}


def test_prose_with_no_json_is_still_a_failure():
    with pytest.raises(json.JSONDecodeError):
        llm.json_object("I cannot help with that.")


def _client_answering(monkeypatch, content: str, seen: list[str]):
    client = llm.OpenAICompatLLM()
    spec = llm.JOBS[llm.JOB_NOTES]
    route = Route(tier="writing", model="m", keys=["k"])
    monkeypatch.setattr(client, "_route", lambda job: (spec, route))

    def fetch(route, body, timeout):
        seen.append(threading.current_thread().name)
        return {"choices": [{"message": {"content": content}}], "usage": {}}, None

    monkeypatch.setattr(client, "_fetch", fetch)
    return client


def test_a_background_job_runs_off_the_hot_path_pool(monkeypatch):
    seen: list[str] = []
    client = _client_answering(monkeypatch, '{"headline": "x"}', seen)

    result = client.structured(job=llm.JOB_NOTES, system="s", user="u", schema={})

    assert result.ok and result.data == {"headline": "x"}
    assert seen and seen[0].startswith("m06-llm-bg"), seen
    assert not llm.JOBS[llm.JOB_STRATEGIST].background
    assert not llm.JOBS[llm.JOB_GUARD].background


def test_a_fenced_structured_answer_is_parsed(monkeypatch):
    seen: list[str] = []
    client = _client_answering(monkeypatch, '```json\n{"headline": "x"}\n```', seen)
    result = client.structured(job=llm.JOB_NOTES, system="s", user="u", schema={})
    assert result.ok and result.data == {"headline": "x"}


def test_an_unparseable_structured_answer_says_so(monkeypatch):
    seen: list[str] = []
    client = _client_answering(monkeypatch, "no json here", seen)
    result = client.structured(job=llm.JOB_NOTES, system="s", user="u", schema={})
    assert not result.ok
    assert result.reason and "unparseable" in result.reason
