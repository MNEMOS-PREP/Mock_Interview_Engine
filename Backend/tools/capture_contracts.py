"""Capture the shapes M06 depends on, from each upstream's SHIPPED models.

Run with the UPSTREAM's interpreter, from anywhere:

    ..\\Question_Intelligence\\Backend\\.venv\\Scripts\\python tools\\capture_contracts.py M05

It imports the upstream package, dumps each named model's JSON-schema field
set, and writes `backend_M06_Mock_Interview_Engine/fixtures/contracts/<M>.json`.
`tests/test_contracts.py` then holds M06's adapters to those files. Re-run it
when an upstream changes a model; a diff in the output is the review.

Shapes that are dicts in the upstream's code rather than models (M04's pinned
summary, M01's drill payload) are written by hand in the same directory, with
the file and line they were read from.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

TARGETS: dict[str, list[tuple[str, str]]] = {
    "M02": [
        ("backend_M02_JD_Parser.plan", "CoveragePlan"),
        ("backend_M02_JD_Parser.plan", "CoverageAllocation"),
        ("backend_M02_JD_Parser.plan", "PlannedRound"),
        ("backend_M02_JD_Parser.router", "PlanIn"),
        ("backend_M02_JD_Parser.router", "LedgerEventIn"),
    ],
    "M05": [
        ("backend_M05_Question_Intelligence.contracts", "SelectionRequest"),
        ("backend_M05_Question_Intelligence.contracts", "SelectionResult"),
        ("backend_M05_Question_Intelligence.contracts", "ProvisionalOutcome"),
        ("backend_M05_Question_Intelligence.contracts", "Question"),
        ("backend_M05_Question_Intelligence.contracts", "KeyPoint"),
        ("backend_M05_Question_Intelligence.contracts", "FollowUpTemplate"),
        ("backend_M05_Question_Intelligence.router", "SeedRequest"),
        ("backend_M05_Question_Intelligence.router", "ObserveRequest"),
        ("backend_M05_Question_Intelligence.router", "CloseRequest"),
        ("backend_M05_Question_Intelligence.router", "FlagRequest"),
    ],
    "M13": [
        ("backend_M13_Evaluation_Engine.router", "EvaluateRequest"),
    ],
}

OUT = (
    Path(__file__).resolve().parents[1]
    / "backend_M06_Mock_Interview_Engine"
    / "fixtures"
    / "contracts"
)


def shape(model) -> dict:
    schema = model.model_json_schema()
    props = schema.get("properties", {})
    return {
        "properties": sorted(props),
        "required": sorted(schema.get("required", [])),
        "enums": {
            name: spec["enum"]
            for name, spec in props.items()
            if isinstance(spec, dict) and "enum" in spec
        },
    }


def main(module: str) -> None:
    out: dict[str, dict] = {}
    for dotted, name in TARGETS[module]:
        out[name] = shape(getattr(importlib.import_module(dotted), name))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{module}.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(out)} models)")


if __name__ == "__main__":
    main(sys.argv[1])
