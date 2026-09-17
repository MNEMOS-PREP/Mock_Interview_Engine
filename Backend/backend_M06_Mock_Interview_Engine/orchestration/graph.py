"""One interview step, as a LangGraph graph — master plan §26.1, §26.4.

LangGraph is the graph; this module is the only file that imports it. The rest
of M06 calls `run_step()` and gets a `StepResult` back, which is §26.1's
"hidden behind our own `orchestration` package interface so the framework is
swappable".

**A step decides; it does not write.** The graph reads a `StepInput` (the
folded session state plus the answer, if any) and returns what should happen
next. The engine records it. So there is exactly one persistence mechanism —
the event log — and the graph runs without a checkpointer of its own: a step is
short, and resuming one after a crash is re-running it against the log, whose
idempotency keys make the parts already written no-ops.

The shape of a step (§26.4's round loop, one turn of it):

    START ─┬─ answer?  ─► strategist ─► decide ─┬─ rung/move ─► probe ─────────┐
           │                                    ├─ move on  ──► select ─┬─ phrase ┤
           ├─ decided ─────────────────────────►┘                       └─ finish ┤
           └─ opening ─────────────────────────────► select                       ▼
                                                                                 END

Interviewer tokens are streamed through LangGraph's custom stream channel, so
the engine can forward them to SSE while the step is still running.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..agents.interviewer import Interviewer, Utterance
from ..agents.strategist import ProbeStrategist
from ..contracts import Move, ProbeLadderState, StrategistVerdict
from ..items import Item
from ..ladder import LadderConfig, Outcome, decide
from ..llm import LLMResult
from ..phrasebook import Lines
from ..projection import project_for_interviewer
from ..state import SessionState


@dataclass(frozen=True)
class Selected:
    """What the QuestionPlanner found, or why it found nothing."""

    item: Item | None
    selection: dict | None = None
    #: module → the sentence the student is owed, when an upstream was missing.
    degraded: dict[str, str] = field(default_factory=dict)
    empty_reason: str | None = None


#: The QuestionPlanner's tool. Lives in the engine, which owns the adapters.
Selector = Callable[[SessionState, datetime], Selected]


@dataclass(frozen=True)
class StepInput:
    state: SessionState
    now: datetime
    item: Item | None
    answer: str | None = None
    #: A decision already on the log for this answer (crash recovery).
    recorded: Outcome | None = None
    #: The QuestionPlanner's tool, request-scoped because it holds a DB session.
    select: Selector | None = None


@dataclass
class StepResult:
    verdict: StrategistVerdict | None = None
    strategist_fallback: str | None = None
    outcome: Outcome | None = None
    item: Item | None = None
    new_question: bool = False
    selection: dict | None = None
    utterance: Utterance | None = None
    hint_level: int | None = None
    finish: str | None = None
    calls: list[LLMResult] = field(default_factory=list)
    degraded: dict[str, str] = field(default_factory=dict)


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class StepState(TypedDict, total=False):
    inp: StepInput
    verdict: StrategistVerdict
    strategist_fallback: str | None
    outcome: Outcome
    item: Item | None
    new_question: bool
    selection: dict | None
    utterance: Utterance
    hint_level: int
    finish: str
    calls: Annotated[list[LLMResult], operator.add]
    degraded: Annotated[dict[str, str], _merge]


PROBE_MOVES = frozenset({"rung", "clarify", "redirect_once", "answer_briefly", "hint", "steelman"})

#: Leave room for a real answer. Below this a new question is not asked.
MIN_SECONDS_FOR_A_QUESTION = 60


@dataclass
class Deps:
    strategist: ProbeStrategist
    interviewer: Interviewer
    lines: Lines
    ladder_config: LadderConfig
    #: New questions a mock may ask before it closes (day 5 replaces this
    #: with the plan's segment budgets).
    question_budget: Callable[[SessionState], int]


def _last_question_text(state: SessionState) -> str:
    """What the student was actually shown. The strategist judges against this
    because an adapted probe, not the authored rung, is what was asked."""
    return next((t.text for t in reversed(state.transcript) if t.role == "interviewer"), "")


def _question_to_repeat(state: SessionState) -> str:
    """The open question with its transition stripped off.

    `redirect_once` and `answer_briefly` both say a line and then ask the
    question again. Repeating the rendered turn would repeat the greeting or
    the hand-off with it — the first live run produced "That's a different
    question. Here's mine again. Okay, let's leave that there. Next question.
    Two keys hash to the same bucket." — so the turn keeps the question apart
    from the words that introduced it.
    """
    turn = next((t for t in reversed(state.transcript) if t.role == "interviewer"), None)
    if turn is None:
        return ""
    return turn.question_text or turn.text


def _emit(text: str) -> None:
    try:
        get_stream_writer()({"token": text})
    except Exception:  # noqa: BLE001 - no stream consumer is fine
        pass


def build(deps: Deps):
    def entry(s: StepState) -> str:
        inp = s["inp"]
        if inp.recorded is not None:
            return "replay_decision"
        if inp.answer is not None:
            return "strategist"
        return "select"

    def strategist(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        assert inp.item is not None and inp.answer is not None
        ladder = inp.state.ladder or ProbeLadderState(concept_id=inp.item.concept_id)
        d = deps.strategist.decide(
            inp.item, ladder.depth, _last_question_text(inp.state), inp.answer
        )
        return {
            "verdict": d.verdict,
            "strategist_fallback": d.fallback_reason,
            "calls": [d.call] if d.call is not None else [],
        }

    def decide_node(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        assert inp.item is not None
        item = inp.item
        ladder = inp.state.ladder or ProbeLadderState(concept_id=item.concept_id)
        outcome = decide(
            ladder,
            s["verdict"],
            config=deps.ladder_config,
            has_own_rung=lambda d: d in item.follow_ups,
            hints_left=max(len(item.hint_ladder) - inp.state.hint_level, 0),
        )
        return {"outcome": outcome}

    def replay_decision(s: StepState) -> dict[str, Any]:
        return {"outcome": s["inp"].recorded}

    def after_decide(s: StepState) -> str:
        if s["outcome"].move.kind in PROBE_MOVES:
            return "probe"
        return "select"

    def probe(s: StepState) -> dict[str, Any]:
        inp, outcome = s["inp"], s["outcome"]
        item = inp.item
        assert item is not None
        move: Move = outcome.move
        repeat_q = _question_to_repeat(inp.state)
        last_answer = next(
            (t.text for t in reversed(inp.state.transcript) if t.role == "candidate"),
            inp.answer or "",
        )
        out: dict[str, Any] = {"item": item, "new_question": False}
        if move.kind == "rung":
            assert move.depth is not None
            view = project_for_interviewer(
                transcript=inp.state.transcript,
                move=move.kind,
                ladder_depth=move.depth,
                time_remaining_s=inp.state.time_remaining_s(inp.now),
                profile_prefix=inp.state.profile_prefix,
            )
            utterance = deps.interviewer.probe(
                item, move.depth, view=view, last_answer=last_answer, on_token=_emit
            )
            if utterance.call is not None:
                out["calls"] = [utterance.call]
        elif move.kind == "clarify":
            utterance = Utterance(deps.lines.clarify, "template")
        elif move.kind == "redirect_once":
            utterance = Utterance(
                f"{deps.lines.redirect} {repeat_q}", "template", question=repeat_q
            )
        elif move.kind == "answer_briefly":
            utterance = Utterance(
                f"{deps.lines.answer_briefly} {repeat_q}", "template", question=repeat_q
            )
        elif move.kind == "hint":
            level = inp.state.hint_level + 1
            utterance = Utterance(item.hint_ladder[level - 1], "template")
            out["hint_level"] = level
        else:  # steelman — unreachable while FR-6.20 is blocked
            raise RuntimeError(f"move {move.kind} has no utterance in Phase 1")
        if move.kind != "rung":
            _emit(utterance.text)
        out["utterance"] = utterance
        return out

    def select(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        state = inp.state
        if state.kind == "drill":
            if state.questions_asked == 0 and inp.item is not None:
                return {"item": inp.item, "new_question": True}
            return {"finish": "drill_complete"}
        if state.questions_asked >= deps.question_budget(state):
            return {"finish": "plan_complete"}
        if state.time_remaining_s(inp.now) < MIN_SECONDS_FOR_A_QUESTION:
            return {"finish": "time"}
        if inp.select is None:
            return {"finish": "no_question_source"}
        found = inp.select(state, inp.now)
        if found.item is None:
            return {"finish": found.empty_reason or "bank_exhausted", "degraded": found.degraded}
        return {
            "item": found.item,
            "new_question": True,
            "selection": found.selection,
            "degraded": found.degraded,
        }

    def after_select(s: StepState) -> str:
        return "finish" if s.get("finish") else "phrase"

    def lead_for(s: StepState) -> str:
        inp = s["inp"]
        outcome = s.get("outcome")
        lines = deps.lines
        if inp.state.questions_asked == 0:
            opening = lines.drill_open if inp.state.kind == "drill" else lines.greeting
            return f"{opening} {lines.first_question_lead}".strip()
        exit_line = (
            ""
            if outcome is None
            else Interviewer.exit_then(
                lines, graceful=outcome.move.graceful, ceiling=outcome.ceiling is not None
            )
        )
        return f"{exit_line} {lines.next_question_lead}".strip()

    def phrase(s: StepState) -> dict[str, Any]:
        item = s["item"]
        assert item is not None
        utterance = deps.interviewer.open_question(item, lead=lead_for(s))
        _emit(utterance.text)
        return {"utterance": utterance}

    def finish(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        outcome = s.get("outcome")
        reason = s["finish"]
        lines = deps.lines
        parts = []
        if outcome is not None:
            parts.append(
                Interviewer.exit_then(
                    lines, graceful=outcome.move.graceful, ceiling=outcome.ceiling is not None
                )
            )
        if reason == "time":
            parts.append(lines.time_up)
        parts.append(lines.drill_close if inp.state.kind == "drill" else lines.session_close)
        text = " ".join(p for p in parts if p)
        _emit(text)
        return {"utterance": Utterance(text, "template")}

    graph = StateGraph(StepState)
    graph.add_node("strategist", strategist)
    graph.add_node("decide", decide_node)
    graph.add_node("replay_decision", replay_decision)
    graph.add_node("probe", probe)
    graph.add_node("select", select)
    graph.add_node("phrase", phrase)
    graph.add_node("finish", finish)
    graph.add_conditional_edges(
        START,
        entry,
        {"strategist": "strategist", "replay_decision": "replay_decision", "select": "select"},
    )
    graph.add_edge("strategist", "decide")
    for node in ("decide", "replay_decision"):
        graph.add_conditional_edges(node, after_decide, {"probe": "probe", "select": "select"})
    graph.add_conditional_edges("select", after_select, {"phrase": "phrase", "finish": "finish"})
    graph.add_edge("probe", END)
    graph.add_edge("phrase", END)
    graph.add_edge("finish", END)
    return graph.compile()


def run_step(compiled, inp: StepInput, on_token: Callable[[str], None] | None = None) -> StepResult:
    final: dict[str, Any] = {}
    for mode, chunk in compiled.stream(
        {"inp": inp, "calls": [], "degraded": {}}, stream_mode=["custom", "values"]
    ):
        if mode == "custom":
            if on_token is not None and isinstance(chunk, dict) and "token" in chunk:
                on_token(chunk["token"])
        else:
            final = chunk
    return StepResult(
        verdict=final.get("verdict"),
        strategist_fallback=final.get("strategist_fallback"),
        outcome=final.get("outcome"),
        item=final.get("item"),
        new_question=bool(final.get("new_question")),
        selection=final.get("selection"),
        utterance=final.get("utterance"),
        hint_level=final.get("hint_level"),
        finish=final.get("finish"),
        calls=list(final.get("calls") or []),
        degraded=dict(final.get("degraded") or {}),
    )


def mermaid(compiled) -> str:
    """The step graph as a mermaid diagram — for `/v1/agents` and the viva."""
    return compiled.get_graph().draw_mermaid()


__all__ = [
    "Deps",
    "Selected",
    "Selector",
    "StepInput",
    "StepResult",
    "build",
    "mermaid",
    "run_step",
]
