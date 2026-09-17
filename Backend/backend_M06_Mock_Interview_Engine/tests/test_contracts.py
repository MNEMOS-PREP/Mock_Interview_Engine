"""M06's adapters against the upstreams' SHIPPED shapes.

`fixtures/contracts/*.json` is captured from each upstream's own models by
`tools/capture_contracts.py` (or written by hand, with a source line, where
the upstream builds a dict). If an upstream changes a model, re-capture: the
test that breaks names the call that would have failed in a session.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from backend_M06_Mock_Interview_Engine.adapters.fixtures import (
    FixtureCoveragePlanner,
    FixtureMemory,
    FixtureResumes,
    LocalQuestions,
    fallback_playlist,
)
from backend_M06_Mock_Interview_Engine.dependencies import MANIFEST

CONTRACTS = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"


def contract(module: str, model: str) -> dict:
    return json.loads((CONTRACTS / f"{module}.json").read_text(encoding="utf-8"))[model]


def conforms(payload: dict, shape: dict) -> None:
    keys = set(payload)
    unknown = keys - set(shape["properties"])
    missing = set(shape["required"]) - keys
    assert not unknown, f"fields the upstream does not declare: {sorted(unknown)}"
    assert not missing, f"required fields absent: {sorted(missing)}"


# ── M02 ──────────────────────────────────────────────────────────────────


def test_fixture_coverage_plan_is_m02s_shape():
    plan = FixtureCoveragePlanner().plan(uuid.uuid4(), uuid.uuid4(), 30)
    conforms(plan, contract("M02", "CoveragePlan"))
    for allocation in plan["allocations"]:
        conforms(allocation, contract("M02", "CoverageAllocation"))
    for planned in plan["rounds"]:
        conforms(planned, contract("M02", "PlannedRound"))


def test_ledger_write_is_m02s_shape():
    planner = FixtureCoveragePlanner()
    planner.record_coverage(
        uuid.uuid4(),
        uuid.uuid4(),
        jd_id=uuid.uuid4(),
        requirement_id="r1",
        state="asked",
        turn_id=uuid.uuid4(),
    )
    body = {k: v for k, v in planner.ledger[0].items() if k not in ("session_id", "candidate_id")}
    conforms(body, contract("M02", "LedgerEventIn"))


def test_plan_request_is_m02s_shape():
    conforms({"minutes": 30}, contract("M02", "PlanIn"))


# ── M05 ──────────────────────────────────────────────────────────────────


def test_fallback_playlist_items_are_m05_questions():
    shape = contract("M05", "Question")
    for item in fallback_playlist()["items"]:
        body = {k: v for k, v in item.items() if k != "label"}
        # `provenance` is required on M05's model; ours are copies, not M05 items.
        conforms({**body, "provenance": "curated"}, shape)
        for kp in item["key_points"]:
            conforms(kp, contract("M05", "KeyPoint"))
        for follow_up in item["follow_ups"]:
            conforms(follow_up, contract("M05", "FollowUpTemplate"))
            assert follow_up["depth"] in contract("M05", "FollowUpTemplate")["enums"]["depth"]


def test_local_selection_answers_in_m05s_result_shape():
    result = LocalQuestions().select(
        {
            "candidate_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "round_type": "dsa_verbal",
        }
    )
    conforms(result, contract("M05", "SelectionResult"))


def test_local_selection_returns_none_when_it_cannot_fill_the_round():
    local = LocalQuestions()
    base = {"candidate_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4())}
    assert local.select({**base, "round_type": "cs_core"}) is None
    seen = [item["id"] for item in fallback_playlist()["items"]]
    assert local.select({**base, "round_type": "dsa_verbal", "seen_item_ids": seen}) is None


def test_seed_observe_close_bodies_are_m05s_shapes():
    conforms(
        {"candidate_id": str(uuid.uuid4()), "posterior": {}, "snapshot_id": "cold"},
        contract("M05", "SeedRequest"),
    )
    outcome = {"turn_id": str(uuid.uuid4()), "band": "at", "confidence": 0.6, "latency_ms": 900}
    conforms(outcome, contract("M05", "ProvisionalOutcome"))
    conforms(
        {"concept_id": "concept:hashing", "outcome": outcome}, contract("M05", "ObserveRequest")
    )
    conforms({"posterior": {}}, contract("M05", "CloseRequest"))
    conforms(
        {"reason": "unclear", "note": "", "candidate_id": str(uuid.uuid4())},
        contract("M05", "FlagRequest"),
    )


# ── M13 ──────────────────────────────────────────────────────────────────


def test_m13_accepts_every_field_m06_will_send():
    """The outbound keys from spec §6.3's `evaluation_request`."""
    sent = {
        "turn_id",
        "session_id",
        "candidate_id",
        "question_id",
        "answer_text",
        "hint_level_used",
        "consent_id",
        "round_type",
        "ensemble",
    }
    shape = contract("M13", "EvaluateRequest")
    assert sent <= set(shape["properties"])
    assert set(shape["required"]) <= sent


# ── M04 / M01 (hand-captured) ────────────────────────────────────────────


def test_fixture_profile_summary_is_m04s_pinned_shape():
    summary = FixtureMemory().profile_summary(uuid.uuid4(), uuid.uuid4())
    conforms(summary, contract("M04", "ProfileSummaryResponse"))
    conforms(summary["payload"], contract("M04", "ProfileSummaryPayload"))


def test_fixture_profile_summary_is_pinned_per_session():
    memory = FixtureMemory()
    cid, sid = uuid.uuid4(), uuid.uuid4()
    assert memory.profile_summary(cid, sid) is memory.profile_summary(cid, sid)


def test_fixture_claims_carry_m01s_probe_shape():
    claims = FixtureResumes().claims(uuid.uuid4(), uuid.uuid4())
    for probe in claims["claims"][0]["probes"]:
        conforms(probe, contract("M01", "DrillProbe"))


# ── the shell's one-origin proxy ─────────────────────────────────────────


@pytest.mark.gate
def test_m06s_nouns_are_its_own_in_the_platform_shell():
    """Revision 2's `/v1/sessions` would have been proxied to M05, and
    `/v1/candidates/.../sessions` to M04 — silently, the day M06 was mounted."""
    from backend_M06_Mock_Interview_Engine.router import router

    shell = json.loads((CONTRACTS / "shell_nouns.json").read_text(encoding="utf-8"))
    nouns = {route.path.split("/")[2] for route in router.routes}
    clashes = (nouns & set(shell["owned_by_others"])) - set(shell["shared"])
    assert not clashes, {n: shell["owned_by_others"][n] for n in clashes}
    assert nouns - set(shell["shared"]) == {"interviews", "drills", "agents"}


# ── the manifest ─────────────────────────────────────────────────────────


@pytest.mark.gate
def test_manifest_declares_every_upstream_optional_with_a_sentence():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    upstreams = {d["module"]: d for d in manifest["depends_on"]}
    assert set(upstreams) == {"M01", "M02", "M04", "M05", "M13"}
    for module, dep in upstreams.items():
        assert dep["required"] is False, f"{module} would make someone else's outage ours"
        assert dep["on_missing"].strip(), f"{module} has nothing to tell a student"
        # launch.ps1 finds siblings by the last segment of this URL.
        assert dep["repo"].rstrip("/").split("/")[-1], module
    assert manifest["repo"].endswith("/Mock_Interview_Engine")
    assert manifest["ports"] == {"backend": 8106, "frontend": 5206}
