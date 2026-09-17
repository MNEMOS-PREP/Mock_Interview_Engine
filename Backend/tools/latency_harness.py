"""Measure the hot path against the live model account — build order day 2.

    .venv\\Scripts\\python tools\\latency_harness.py            # 12 rounds
    .venv\\Scripts\\python tools\\latency_harness.py --rounds 30

OPENS SOCKETS and spends quota. Never run by the test suite.

Each round makes the two calls a text turn makes (spec §6.2, §11):

    ProbeStrategist        structured, classification tier
    TechnicalInterviewer   streamed rung phrasing, generation tier

with the real prompts, on the fallback playlist's items and a spread of
answers (strong, partial, wrong, off-topic). It reports p50/p95 per call —
latency, time to first token, prompt/completion/reasoning tokens, and whether
the provider reported cached tokens at all (AC-6.11 is "not measured" if not).

The JSON goes to `reports/latency-<date>.json`, so the numbers a design
decision was made on are in the repository beside the decision.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))

from ai_core.models import resolve  # noqa: E402

from backend_M06_Mock_Interview_Engine.adapters.fixtures import fallback_playlist  # noqa: E402
from backend_M06_Mock_Interview_Engine.agents import Interviewer, ProbeStrategist  # noqa: E402
from backend_M06_Mock_Interview_Engine.agents.interviewer import (  # noqa: E402
    PROMPT_VERSION as INTERVIEWER_PROMPT,
)
from backend_M06_Mock_Interview_Engine.agents.strategist import (  # noqa: E402
    PROMPT_VERSION as STRATEGIST_PROMPT,
)
from backend_M06_Mock_Interview_Engine.items import from_m05  # noqa: E402
from backend_M06_Mock_Interview_Engine.llm import JOBS, get_llm  # noqa: E402
from backend_M06_Mock_Interview_Engine.projection import project_for_interviewer  # noqa: E402

#: Per fallback item (by label): a strong answer and a weak one, so the
#: verdicts in the report can be read as well as timed.
ANSWERS: dict[str, tuple[str, str]] = {
    "fb_complexity_of_a_loop": (
        "O(n). The body does constant work and runs once per element, so the total grows with n.",
        "O(n log n), because loops are usually log n.",
    ),
    "fb_stack_vs_queue": (
        "A stack for matching brackets, since the last opened must close first; a queue for a "
        "printer buffer, served in arrival order.",
        "I'd use a stack for both, they're basically the same.",
    ),
    "fb_dictionary_use_case": (
        "A hash map from word to count — average O(1) update on arbitrary string keys.",
        "An array, and I'd loop over it each time to find the word.",
    ),
    "fb_recursion_in_your_own_words": (
        "A function that calls itself on a smaller input until a base case it can answer directly.",
        "It's like a loop but it uses more memory, I think.",
    ),
}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return float(ordered[index])


def summarise(rows: list[dict], key: str) -> dict:
    values = [r[key] for r in rows if r.get(key) is not None]
    return {
        "n": len(values),
        "p50": pct(values, 0.5),
        "p95": pct(values, 0.95),
        "max": max(values) if values else None,
        "mean": round(statistics.fmean(values), 1) if values else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--pause", type=float, default=0.6, help="seconds between calls")
    args = parser.parse_args()

    llm = get_llm(refresh=True)
    if not llm.available:
        print("No model configured — set GROQ_API_KEYS (see required_keys.txt).")
        return 2

    items = [
        from_m05(q, round_type="dsa_verbal", source="m05_bank")
        for q in fallback_playlist()["items"]
    ]
    strategist = ProbeStrategist(llm)
    interviewer = Interviewer(llm)
    strategist_rows: list[dict] = []
    interviewer_rows: list[dict] = []

    for i in range(args.rounds):
        item = items[i % len(items)]
        strong, weak = ANSWERS[item.label]
        answer = strong if i % 2 == 0 else weak
        depth = (i % 3) + 1

        started = time.perf_counter()
        decision = strategist.decide(item, 0, item.stem, answer)
        wall = int((time.perf_counter() - started) * 1000)
        call = decision.call
        strategist_rows.append(
            {
                "round": i,
                "ok": decision.verdict.source == "model",
                "fallback": decision.fallback_reason,
                "latency_ms": call.latency_ms if call else wall,
                "tokens_in": call.tokens_in if call else None,
                "tokens_out": call.tokens_out if call else None,
                "reasoning_tokens": call.reasoning_tokens if call else None,
                "cached_tokens": call.cached_tokens if call else None,
                "item": item.label,
                "answer_kind": "strong" if i % 2 == 0 else "weak",
                "band": decision.verdict.band,
                "justification": decision.verdict.justification,
            }
        )
        time.sleep(args.pause)

        view = project_for_interviewer(
            transcript=[], move="rung", ladder_depth=depth, time_remaining_s=900
        )
        first_visible: list[int] = []
        t0 = time.perf_counter()

        def on_token(_text: str, _t0: float = t0, _seen: list[int] = first_visible) -> None:
            if not _seen:
                _seen.append(int((time.perf_counter() - _t0) * 1000))

        said = interviewer.probe(item, depth, view=view, last_answer=answer, on_token=on_token)
        call = said.call
        interviewer_rows.append(
            {
                "round": i,
                "ok": said.source == "model",
                "fallback": said.fallback_reason,
                "latency_ms": call.latency_ms if call else None,
                "first_token_ms": call.first_token_ms if call else None,
                # After the guard's word-boundary hold-back: what a student sees.
                "first_visible_ms": first_visible[0] if first_visible else None,
                "tokens_in": call.tokens_in if call else None,
                "tokens_out": call.tokens_out if call else None,
                "reasoning_tokens": call.reasoning_tokens if call else None,
                "cached_tokens": call.cached_tokens if call else None,
                "text": said.text,
            }
        )
        print(
            f"round {i + 1:>2}: strategist {strategist_rows[-1]['latency_ms']:>5} ms "
            f"({'model' if strategist_rows[-1]['ok'] else 'FALLBACK'})  "
            f"interviewer first-visible {interviewer_rows[-1]['first_visible_ms']} ms / "
            f"total {interviewer_rows[-1]['latency_ms']} ms "
            f"({'model' if interviewer_rows[-1]['ok'] else 'TEMPLATE: ' + str(said.fallback_reason)})"
        )
        time.sleep(args.pause)

    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "machine": platform.node(),
        "rounds": args.rounds,
        "routes": {
            job: {
                "tier": spec.tier,
                "model": resolve(spec.tier).model,
                "reasoning_effort": spec.reasoning_effort,
            }  # type: ignore[arg-type]
            for job, spec in JOBS.items()
        },
        "prompt_versions": {"strategist": STRATEGIST_PROMPT, "interviewer": INTERVIEWER_PROMPT},
        "refused_fields": {k: sorted(v) for k, v in getattr(llm, "refused", {}).items()},
        "strategist": {
            "model_verdicts": sum(r["ok"] for r in strategist_rows),
            "latency_ms": summarise(strategist_rows, "latency_ms"),
            "reasoning_tokens": summarise(strategist_rows, "reasoning_tokens"),
            "tokens_in": summarise(strategist_rows, "tokens_in"),
            "cached_tokens_reported": any(r["cached_tokens"] is not None for r in strategist_rows),
            "fallbacks": sorted({r["fallback"] for r in strategist_rows if r["fallback"]}),
        },
        "interviewer": {
            "model_lines": sum(r["ok"] for r in interviewer_rows),
            "latency_ms": summarise(interviewer_rows, "latency_ms"),
            "first_token_ms": summarise(interviewer_rows, "first_token_ms"),
            "first_visible_ms": summarise(interviewer_rows, "first_visible_ms"),
            "reasoning_tokens": summarise(interviewer_rows, "reasoning_tokens"),
            "cached_tokens_reported": any(r["cached_tokens"] is not None for r in interviewer_rows),
            "fallbacks": sorted({r["fallback"] for r in interviewer_rows if r["fallback"]}),
        },
        "turn_estimate_ms": {
            "note": "strategist p95 + interviewer first-visible p95: what a student waits for a rung",
        },
        "rows": {"strategist": strategist_rows, "interviewer": interviewer_rows},
    }
    s95 = report["strategist"]["latency_ms"]["p95"]
    i95 = report["interviewer"]["first_visible_ms"]["p95"]
    if s95 is not None and i95 is not None:
        report["turn_estimate_ms"]["rung_first_visible_p95"] = s95 + i95

    out_dir = HERE.parents[1] / "reports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"latency-{datetime.now(UTC).date().isoformat()}.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    print(
        "\n"
        + json.dumps(
            {k: report[k] for k in ("routes", "refused_fields", "turn_estimate_ms")}, indent=2
        )
    )
    for name in ("strategist", "interviewer"):
        print(name, json.dumps({k: v for k, v in report[name].items()}, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
