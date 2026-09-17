"""The orchestration interface — master plan §26.1.

The engine imports from here and nowhere deeper. LangGraph is an
implementation detail of `graph.py`; swapping the framework means rewriting
that one file against the same `Deps` / `StepInput` / `StepResult` contract.
"""

from .graph import Deps, Selected, Selector, StepInput, StepResult, build, mermaid, run_step
from .registry import AGENTS, AgentSpec, enabled, snapshot

__all__ = [
    "AGENTS",
    "AgentSpec",
    "Deps",
    "Selected",
    "Selector",
    "StepInput",
    "StepResult",
    "build",
    "enabled",
    "mermaid",
    "run_step",
    "snapshot",
]
