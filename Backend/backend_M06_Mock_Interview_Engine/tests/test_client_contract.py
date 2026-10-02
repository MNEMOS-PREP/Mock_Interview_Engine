"""The route-client contract — `api.ts`: "One hook per endpoint, and no hook
without one."

Two ways that promise breaks, both silently. A route ships with no screen
behind it, and the feature exists only for curl — the shape that put three
§7 routes in the spec and none in the product until day 13. Or a hook calls a
path the backend renamed, and the screen renders an error nobody sees in a
test. This reads both sides — the frontend's source and the backend's own
OpenAPI document — and fails on either.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from backend_M06_Mock_Interview_Engine.app import app

FRONTEND = (
    pathlib.Path(__file__).resolve().parents[3]
    / "Frontend"
    / "frontend_M06_Mock_Interview_Engine"
    / "src"
)

#: Routes another module calls, not one of this module's screens — and who.
SERVICE_ONLY: dict[tuple[str, str], str] = {
    ("POST", "/v1/drills"): "M01's defend-drill hand-off (FR-6.23)",
    ("GET", "/v1/interviews/by-candidate/{}/recent"): "M04's `recent_sessions` slot",
    ("GET", "/v1/interviews/{}/trace"): "FR-6.19's replay input — read by the harness",
    ("GET", "/v1/interviews/{}/transcript"): "M19's report, when it exists (§15.7)",
    ("GET", "/v1/interviews/{}/outbox"): "operations: what is still owed upstream",
    ("POST", "/v1/interviews/{}/outbox/drain"): "operations: deliver now",
}

#: `@ai/core`'s client spells DELETE `del`.
_CALL = re.compile(r"api\.(get|post|put|del|delete|patch)<[^>]*>\(\s*[`\"](/v1/[^`\"]*)")
_VERB = {"del": "DELETE"}
_FETCH = re.compile(r"fetch\(\s*[`\"](/v1/[^`\"]*)")


def _shape(path: str) -> str:
    """`/v1/interviews/${id}/plan?x=1` and `/v1/interviews/{session_id}/plan`
    both become `/v1/interviews/{}/plan`."""
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    return re.sub(r"\{[^}]*\}", "{}", path)


def frontend_calls() -> set[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    for source in FRONTEND.rglob("*.ts*"):
        text = source.read_text(encoding="utf-8")
        calls |= {(_VERB.get(m, m.upper()), _shape(p)) for m, p in _CALL.findall(text)}
        calls |= {("GET", _shape(p)) for p in _FETCH.findall(text)}
    return calls


def backend_routes() -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {
        (method.upper(), _shape(path))
        for path, ops in paths.items()
        if path.startswith("/v1/")
        for method in ops
        if method in ("get", "post", "put", "delete", "patch")
    }


pytestmark = pytest.mark.skipif(
    not FRONTEND.exists(), reason="the frontend is not in this checkout"
)


@pytest.mark.gate
def test_every_route_has_a_screen_or_a_named_caller():
    missing = backend_routes() - frontend_calls() - set(SERVICE_ONLY)
    assert not missing, f"routes with no hook and no named caller: {sorted(missing)}"


@pytest.mark.gate
def test_every_hook_calls_a_route_that_exists():
    dangling = frontend_calls() - backend_routes()
    assert not dangling, f"hooks calling routes the backend does not serve: {sorted(dangling)}"


def test_the_service_list_names_only_real_routes():
    """A route removed from the backend must leave this list too."""
    stale = set(SERVICE_ONLY) - backend_routes()
    assert not stale, f"SERVICE_ONLY names routes that no longer exist: {sorted(stale)}"
