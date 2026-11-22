"""Every closed answer reaches M17, the communication coach (good_and_bads #16).

Until 2026-11-22 the coach was mounted at /coach and no interview answer ever
reached it: the M17 team's patch sat unapplied in their repo. These pin what is
sent, that it can be turned off, and that the interview never waits on it.
"""

from __future__ import annotations

import threading

from backend_M06_Mock_Interview_Engine import m17_emit


def test_on_by_default_at_the_ports_address(monkeypatch):
    monkeypatch.delenv("M06_M17_BASE_URL", raising=False)
    assert m17_emit.base_url() == "http://127.0.0.1:8117"


def test_off_and_moved(monkeypatch):
    for off in ("off", "0", "", "none"):
        monkeypatch.setenv("M06_M17_BASE_URL", off)
        assert m17_emit.base_url() is None
    monkeypatch.setenv("M06_M17_BASE_URL", "http://coach.local:9000/")
    assert m17_emit.base_url() == "http://coach.local:9000"


def test_the_body_is_m17s_turn_in():
    body = m17_emit.payload(
        turn_id="t1",
        candidate_id="c1",
        text="I would use a hash map.",
        spoken=True,
        duration_ms=4200,
        question="Why?",
    )
    assert body["source_module"] == "M06"
    assert body["modality"] == "spoken" and body["recogniser"] == "m11"
    assert body["question"] == "Why?" and body["duration_ms"] == 4200
    typed = m17_emit.payload(turn_id="t2", candidate_id="c1", text="x", spoken=False)
    assert typed["modality"] == "typed" and typed["recogniser"] is None


def test_sent_on_a_thread_and_a_dead_coach_is_not_an_error(monkeypatch):
    # Nothing listens on this port: the send fails on its own thread, and
    # send_turn returns at once without raising.
    monkeypatch.setenv("M06_M17_BASE_URL", "http://127.0.0.1:9")
    started = []
    real = threading.Thread

    class Spy(real):  # type: ignore[misc, valid-type]
        def start(self):  # noqa: D401
            started.append(self)
            return super().start()

    monkeypatch.setattr(m17_emit.threading, "Thread", Spy)
    m17_emit.send_turn(turn_id="t1", candidate_id="c1", text="an answer", spoken=False)
    assert len(started) == 1
    started[0].join(timeout=10)


def test_an_empty_answer_is_not_sent(monkeypatch):
    monkeypatch.setenv("M06_M17_BASE_URL", "http://127.0.0.1:9")
    started = []
    monkeypatch.setattr(m17_emit.threading, "Thread", lambda *a, **k: started.append(1))
    m17_emit.send_turn(turn_id="t1", candidate_id="c1", text="   ", spoken=False)
    assert started == []
