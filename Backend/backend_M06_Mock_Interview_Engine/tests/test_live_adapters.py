"""The live clients, against a patched `urlopen` — no socket is opened.

What is asserted is the part a fixture cannot show: the exact path, the
identity headers forwarded on a student's behalf, the service secret on M04's
service routes, and which status codes are answers rather than failures.
"""

from __future__ import annotations

import io
import json
import urllib.error
import uuid

import pytest

from backend_M06_Mock_Interview_Engine.adapters import http as http_module
from backend_M06_Mock_Interview_Engine.adapters.base import UpstreamUnavailable
from backend_M06_Mock_Interview_Engine.adapters.live import (
    LiveCoveragePlanner,
    LiveEvaluator,
    LiveMemory,
    LiveQuestions,
)


class Recorder:
    def __init__(self, status: int = 200, body=None, error: Exception | None = None):
        self.status = status
        self.body = body if body is not None else {}
        self.error = error
        self.requests: list = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, self.status, "err", {}, io.BytesIO(json.dumps(self.body).encode())
            )
        return _Resp(self.status, self.body)

    @property
    def last(self):
        return self.requests[-1]


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wire(monkeypatch):
    def install(**kwargs) -> Recorder:
        recorder = Recorder(**kwargs)
        monkeypatch.setattr(http_module.urllib.request, "urlopen", recorder)
        return recorder

    return install


def header(request, name: str) -> str | None:
    return {k.lower(): v for k, v in request.header_items()}.get(name.lower())


def test_m02_plan_forwards_the_students_identity(wire):
    rec = wire(body={"jd_id": "x"})
    cid, jd = uuid.uuid4(), uuid.uuid4()
    LiveCoveragePlanner("http://m02").plan(jd, cid, 30)
    assert rec.last.full_url == f"http://m02/v1/jds/{jd}/plan/{cid}"
    assert rec.last.get_method() == "POST"
    assert json.loads(rec.last.data) == {"minutes": 30}
    assert header(rec.last, "X-Candidate-Id") == str(cid)
    assert header(rec.last, "X-Role") == "student"


def test_m04_service_routes_carry_the_secret_m04_checks(wire, monkeypatch):
    monkeypatch.setenv("M04_SERVICE_SECRET", "s3cret")
    monkeypatch.delenv("SERVICE_SECRET", raising=False)
    rec = wire(body={"session_id": "x", "pinned": True})
    cid, sid = uuid.uuid4(), uuid.uuid4()
    LiveMemory("http://m04").profile_summary(cid, sid)
    assert rec.last.full_url == f"http://m04/v1/candidates/{cid}/profile-summary?session_id={sid}"
    assert header(rec.last, "X-Service-Secret") == "s3cret"


def test_m04_posterior_drops_unmeasured_concepts(wire):
    wire(
        body={
            "per_topic": {
                "concept:hashing": {"theta": 0.4, "n_direct": 3},
                "concept:recursion": {"theta": None, "n_direct": 0},
            },
            "unresolved": [],
        }
    )
    got = LiveMemory("http://m04").posterior(uuid.uuid4(), ["concept:hashing", "concept:recursion"])
    assert got == {"concept:hashing": 0.4}


def test_m04_consent_is_honestly_unknown_without_a_call(wire):
    rec = wire()
    assert LiveMemory("http://m04").consent(uuid.uuid4(), "practice") is None
    assert rec.requests == []


def test_m05_409_is_an_answer_not_a_failure(wire):
    wire(status=409, body={"detail": "no item"})
    assert (
        LiveQuestions("http://m05").select(
            {"candidate_id": str(uuid.uuid4()), "round_type": "cs_core"}
        )
        is None
    )


def test_m05_observe_returns_theta_to_memory_only(wire):
    rec = wire(body={"concept_id": "c", "theta_provisional": 0.4, "updates": 1})
    sid = uuid.uuid4()
    value = LiveQuestions("http://m05").observe(sid, "c", {"turn_id": "t", "band": "above"})
    assert value == 0.4
    assert rec.last.full_url == f"http://m05/v1/sessions/{sid}/theta/observe"


def test_m05_lost_session_is_unavailable_so_the_engine_reseeds(wire):
    wire(status=404, body={"detail": "no such session; seed it first"})
    with pytest.raises(UpstreamUnavailable):
        LiveQuestions("http://m05").observe(uuid.uuid4(), "c", {"turn_id": "t", "band": "at"})


def test_m13_missing_evaluation_is_none(wire):
    wire(status=404, body={"detail": "no evaluation"})
    assert LiveEvaluator("http://m13").evaluation(uuid.uuid4()) is None


def test_a_5xx_or_a_refused_connection_is_one_failure_type(wire):
    wire(status=500, body={"detail": "boom"})
    with pytest.raises(UpstreamUnavailable, match="500"):
        LiveEvaluator("http://m13").evaluate({"answer_text": "x"})
    wire(error=urllib.error.URLError("refused"))
    with pytest.raises(UpstreamUnavailable):
        LiveCoveragePlanner("http://m02").job_description(uuid.uuid4())


def test_a_non_json_body_is_a_failure(wire, monkeypatch):
    class Bad(_Resp):
        def read(self):
            return b"<html>proxy error</html>"

    monkeypatch.setattr(
        http_module.urllib.request, "urlopen", lambda req, timeout=None: Bad(200, {})
    )
    with pytest.raises(UpstreamUnavailable, match="not JSON"):
        LiveEvaluator("http://m13").calibration()
