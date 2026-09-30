"""The agent registry — master plan §26.2, the part of it M06 runs.

An agent justifies its existence by a distinct model tier, a distinct tool
set, or a hard information boundary (§26.1). The ones here, and which of the
three each has:

    QuestionPlanner       tools (M05 selection) — no model of its own
    TechnicalInterviewer  tier (generation) + boundary (InterviewerView)
    ProbeStrategist       tier (classification) + boundary (narrow context)
    SafetyGuard           tier (guard) + rules — screens every line said, and
                          every answer received, beside the strategist
    ReportComposer        templates in Phase 1

**Ablation hooks** (§26.2): every agent can be switched off by config, which is
what turns "what does the multi-agent design buy us?" into an experiment.
`M06_AGENT_PROBESTRATEGIST=off` runs the rule fallback instead of the model;
the session still completes, and the trace records that it was ablated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Side = Literal["interviewer", "evaluation", "support"]


@dataclass(frozen=True)
class AgentSpec:
    name: str
    side: Side
    #: `ai_core.models` tier, or None for an agent with no model call.
    tier: str | None
    #: Soft token ceiling per invocation (§26.2 "Budget").
    budget_tokens: int
    timeout_s: float
    purpose: str

    @property
    def env(self) -> str:
        return f"M06_AGENT_{self.name.upper()}"

    @property
    def enabled(self) -> bool:
        return os.getenv(self.env, "on").strip().lower() not in {"off", "0", "false", "no"}


AGENTS: dict[str, AgentSpec] = {
    spec.name: spec
    for spec in (
        AgentSpec(
            "QuestionPlanner",
            "interviewer",
            None,
            0,
            3.0,
            "Asks M05 for the next item under this segment's constraints.",
        ),
        AgentSpec(
            "TechnicalInterviewer",
            "interviewer",
            "generation",
            3000,
            6.0,
            "Adapts a rung to the student's last answer; never rephrases a scored stem.",
        ),
        AgentSpec(
            "ProbeStrategist",
            "interviewer",
            "classification",
            1500,
            4.0,
            "Judges one answer, narrowly, so the ladder can deepen or exit.",
        ),
        AgentSpec(
            "SafetyGuard",
            "support",
            "guard",
            64,
            1.5,
            "Screens every interviewer line (verdicts, rudeness, personal questions) and every "
            "answer (instructions to the system, abuse), beside the strategist; fails open.",
        ),
        AgentSpec(
            "ReportComposer",
            "support",
            None,
            0,
            25.0,
            "Builds the session report from the event log (templated in Phase 1).",
        ),
    )
}


def enabled(name: str) -> bool:
    return AGENTS[name].enabled


def snapshot() -> list[dict]:
    """What `/v1/agents` reports — which agents run, and which are ablated."""
    return [
        {
            "name": s.name,
            "side": s.side,
            "tier": s.tier,
            "budget_tokens": s.budget_tokens,
            "timeout_s": s.timeout_s,
            "enabled": s.enabled,
            "switch": s.env,
            "purpose": s.purpose,
        }
        for s in AGENTS.values()
    ]


__all__ = ["AGENTS", "AgentSpec", "enabled", "snapshot"]
