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

    START ─┬─ answer? ─┬─► strategist ─┐
           │           └─► guard ──────┴─► decide ─┬─ rung/move ──► probe ────────┐
           │                                       ├─ break, Practice ► offer_retry┤
           ├─ decided ───────────────► replay ─────┤                               │
           │                                       ├─ move on ────► select ─┬─ phrase ┤
           └─ opening ─────────────────────────────┼───────────────►┘       └─ finish ┤
                                                   └─ conduct (2nd) ─────► finish ────┤
                                                                                     END

**The strategist and the guard run in parallel** (EC-6.6). The guard model
takes 230–680 ms; run first it would sit on every turn, run beside the
strategist (~800 ms) it costs a turn nothing. `decide` waits for both.

**Who is speaking is read from the state, per step** (FR-6.3). A mock is a
panel — the persona is the current segment's — so the line table, the ladder's
depth and the interviewer's style are looked up for the segment being run, not
baked into the compiled graph.

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

from ..agents.guard import AnswerScreen, SafetyGuard, neutralise, rule_screen
from ..agents.interviewer import Interviewer, Utterance
from ..agents.strategist import ProbeStrategist
from ..contracts import Move, ProbeLadderState, StrategistVerdict
from ..items import Item
from ..ladder import LadderConfig, Outcome, decide
from ..llm import LLMResult
from ..personas import Persona
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
    #: §3.2.3. Set when selecting crossed into a new segment: the step's own
    #: `inp.state` was read before that happened, so the line has to travel
    #: with the item rather than be looked up again afterwards.
    bridge: str | None = None
    #: The persona of the segment the item belongs to — also read before the
    #: crossing, so it travels with the item for the same reason.
    persona: Persona | None = None


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
    #: EC-6.4 / EC-6.6: what the guard found in the answer. Trace only.
    screen: AnswerScreen | None = None
    #: §15.4: the step offered a Practice retry instead of moving on.
    offer_retry: bool = False
    #: §6.7: the step said "let's keep it moving" for an over-long answer.
    nudged: bool = False


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class StepState(TypedDict, total=False):
    inp: StepInput
    verdict: StrategistVerdict
    strategist_fallback: str | None
    screen: AnswerScreen
    outcome: Outcome
    item: Item | None
    new_question: bool
    selection: dict | None
    utterance: Utterance
    hint_level: int
    finish: str
    bridge: str | None
    persona: Persona | None
    offer_retry: bool
    nudged: bool
    calls: Annotated[list[LLMResult], operator.add]
    degraded: Annotated[dict[str, str], _merge]


PROBE_MOVES = frozenset(
    {"rung", "clarify", "redirect_once", "answer_briefly", "hint", "steelman", "redirect_conduct"}
)

#: The moves "let's keep it moving" may precede (§6.7).
NUDGEABLE = frozenset({"rung", "redirect_once", "answer_briefly"})

#: Leave room for a real answer. Below this a new question is not asked.
MIN_SECONDS_FOR_A_QUESTION = 60


@dataclass
class Deps:
    strategist: ProbeStrategist
    interviewer: Interviewer
    guard: SafetyGuard
    #: The persona of the segment being run (FR-6.3) — its lines, its depth,
    #: its style. Read per step, never compiled in.
    persona_for: Callable[[SessionState], Persona]
    #: The ladder's rules for this state: the persona's depth, the mode's
    #: hints and steelman flag, the drill's own ladder.
    ladder_for: Callable[[SessionState], LadderConfig]
    #: New questions this session asks before it closes (the plan's budgets).
    question_budget: Callable[[SessionState], int]
    #: §15.4: whether a Practice retry may be offered for the open question.
    retry_allowed: Callable[[SessionState], bool] = lambda _state: False


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


def _nudge_due(state: SessionState, persona: Persona, answer: str | None) -> bool:
    """§6.7 `interruption_threshold`, in text: once per round, for an answer
    longer than the persona will sit through."""
    if not answer or state.current_segment in state.nudged_segments:
        return False
    return len(answer.split()) > persona.long_answer_words


def build(deps: Deps):
    def entry(s: StepState) -> str | list[str]:
        inp = s["inp"]
        if inp.recorded is not None:
            return "replay_decision"
        if inp.answer is not None:
            # Fan out: the strategist judges while the guard screens.
            return ["strategist", "guard"]
        return "select"

    def strategist(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        assert inp.item is not None and inp.answer is not None
        ladder = inp.state.ladder or ProbeLadderState(concept_id=inp.item.concept_id)
        # EC-6.6: what reads as an instruction to the system is set aside
        # before the strategist sees the answer. The rule half only — it is
        # the half that can say WHERE; the model half runs beside this.
        answer = neutralise(inp.answer, rule_screen(inp.answer).spans)
        # The question WITHOUT the words that introduced it — §6.7's promise:
        # "the persona never changes the standard". The rendered turn carries
        # the register's lead ("Hello. Let's begin. First question." against a
        # bar-raiser's "Let's get started. First."), and feeding that to the
        # strategist would make the verdict — which becomes an M05 θ
        # observation (FR-6.25) — depend on the interviewer's manner. The
        # adapted probe IS the question and survives; only the lead is cut.
        d = deps.strategist.decide(inp.item, ladder.depth, _question_to_repeat(inp.state), answer)
        return {
            "verdict": d.verdict,
            "strategist_fallback": d.fallback_reason,
            "calls": [d.call] if d.call is not None else [],
        }

    def guard(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        decision = deps.guard.screen_answer(inp.answer or "")
        return {
            "screen": decision.screen,
            "calls": [decision.call] if decision.call is not None else [],
        }

    def decide_node(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        assert inp.item is not None
        item = inp.item
        ladder = inp.state.ladder or ProbeLadderState(concept_id=item.concept_id)
        outcome = decide(
            ladder,
            s["verdict"],
            config=deps.ladder_for(inp.state),
            has_own_rung=lambda d: d in item.follow_ups,
            hints_left=max(len(item.hint_ladder) - inp.state.hint_level, 0),
            conduct_warnings=inp.state.flags.conduct_warnings,
        )
        out: dict[str, Any] = {"outcome": outcome}
        if outcome.move.kind == "end_session":
            out["finish"] = "conduct"
        return out

    def replay_decision(s: StepState) -> dict[str, Any]:
        out: dict[str, Any] = {"outcome": s["inp"].recorded}
        if s["inp"].recorded is not None and s["inp"].recorded.move.kind == "end_session":
            out["finish"] = "conduct"
        return out

    def after_decide(s: StepState) -> str:
        outcome = s["outcome"]
        kind = outcome.move.kind
        if kind == "end_session":
            return "finish"
        if kind in PROBE_MOVES:
            return "probe"
        if kind == "move_on" and outcome.move.graceful and deps.retry_allowed(s["inp"].state):
            return "offer_retry"
        return "select"

    def probe(s: StepState) -> dict[str, Any]:
        inp, outcome = s["inp"], s["outcome"]
        item = inp.item
        assert item is not None
        move: Move = outcome.move
        persona = deps.persona_for(inp.state)
        lines = persona.said()
        repeat_q = _question_to_repeat(inp.state)
        last_answer = next(
            (t.text for t in reversed(inp.state.transcript) if t.role == "candidate"),
            inp.answer or "",
        )
        out: dict[str, Any] = {"item": item, "new_question": False}
        # One "keep it moving" per round, and only before a follow-up or a
        # redirect: before a hint or a request to rephrase it would read as
        # impatience with a student who asked for help.
        nudge = move.kind in NUDGEABLE and _nudge_due(inp.state, persona, inp.answer)
        prefix = f"{lines.keep_moving} " if nudge else ""
        if nudge:
            out["nudged"] = True
            _emit(prefix)
        if move.kind == "rung":
            assert move.depth is not None
            view = project_for_interviewer(
                transcript=inp.state.transcript,
                move=move.kind,
                ladder_depth=move.depth,
                time_remaining_s=inp.state.time_remaining_s(inp.now),
                profile_prefix=inp.state.profile_prefix,
                # §6.6: what happened before the last six turns. Without it a
                # long round asks about hashing twice, because everything
                # older than six turns simply is not there.
                round_summary=inp.state.round_summary,
                register=persona.speech,
                persona_style=persona.style,
                max_words=persona.verbosity_target,
            )
            utterance = deps.interviewer.probe(
                item, move.depth, view=view, last_answer=last_answer, on_token=_emit
            )
            if utterance.call is not None:
                out["calls"] = [utterance.call]
        elif move.kind == "clarify":
            utterance = Utterance(lines.clarify, "template")
        elif move.kind == "redirect_once":
            utterance = Utterance(f"{lines.redirect} {repeat_q}", "template", question=repeat_q)
        elif move.kind == "answer_briefly":
            utterance = Utterance(
                f"{lines.answer_briefly} {repeat_q}", "template", question=repeat_q
            )
        elif move.kind == "redirect_conduct":
            # EC-6.4: neutral, names no behaviour, and asks the question again.
            utterance = Utterance(
                f"{lines.redirect_conduct} {repeat_q}", "template", question=repeat_q
            )
        elif move.kind == "hint":
            level = inp.state.hint_level + 1
            utterance = Utterance(item.hint_ladder[level - 1], "template")
            out["hint_level"] = level
        else:  # steelman — unreachable while FR-6.20 is blocked
            raise RuntimeError(f"move {move.kind} has no utterance in Phase 1")
        if move.kind != "rung":
            _emit(utterance.text)
        if prefix:
            utterance = Utterance(
                prefix + utterance.text,
                utterance.source,
                call=utterance.call,
                fallback_reason=utterance.fallback_reason,
                question=utterance.question or utterance.text,
            )
        out["utterance"] = utterance
        return out

    def offer_retry(s: StepState) -> dict[str, Any]:
        """§15.4, Practice: the graceful exit, then the offer of another go.

        Said after the exit line, so it reads as an option rather than as a
        verdict — "that's fair, it's a detail people look up; want another
        go?" — and nothing is selected until the student chooses.
        """
        inp, outcome = s["inp"], s["outcome"]
        lines = deps.persona_for(inp.state).said()
        exit_line = Interviewer.exit_then(
            lines, graceful=outcome.move.graceful, ceiling=outcome.ceiling is not None
        )
        text = f"{exit_line} {lines.retry_offer}".strip()
        _emit(text)
        return {"utterance": Utterance(text, "template"), "offer_retry": True, "item": inp.item}

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
            "bridge": found.bridge,
            "persona": found.persona,
        }

    def after_select(s: StepState) -> str:
        return "finish" if s.get("finish") else "phrase"

    def lead_for(s: StepState) -> tuple[str, bool]:
        """What is said before the question, and whether that includes the
        once-per-round "keep it moving"."""
        inp = s["inp"]
        outcome = s.get("outcome")
        # Two voices can meet in one line at a crossing: the LEAVING
        # interviewer closes their question, and the ARRIVING one (whose
        # bridge the engine already rendered) asks the next. The step's own
        # state predates the crossing, so it names the one leaving.
        leaving = deps.persona_for(inp.state)
        arriving = s.get("persona") or leaving
        said_leaving, said_arriving = leaving.said(), arriving.said()
        if inp.state.questions_asked == 0:
            opening = (
                said_arriving.drill_open if inp.state.kind == "drill" else said_arriving.greeting
            )
            return f"{opening} {said_arriving.first_question_lead}".strip(), False
        graceful = outcome is not None and outcome.move.graceful
        nudge = not graceful and _nudge_due(inp.state, leaving, inp.answer)
        if outcome is None:
            exit_line = ""
        elif nudge:
            exit_line = said_leaving.keep_moving
        else:
            exit_line = Interviewer.exit_then(
                said_leaving, graceful=graceful, ceiling=outcome.ceiling is not None
            )
            cadence = leaving.note_taking_cadence
            if (
                not graceful
                and cadence
                and inp.state.questions_asked % cadence == 0
                and not s.get("bridge")
            ):
                # Realism only (§6.7): it says nothing about the answer, and
                # never follows a break, where it would read as a verdict.
                exit_line = f"{said_leaving.note_taking} {exit_line}"
        bridge = s.get("bridge") or inp.state.pending_bridge
        if bridge:
            # A new round starts. The bridge replaces "next question", because
            # saying both ("Okay, let's leave that there. Next question. Let's
            # move to the next part: SQL.") is three transitions for one.
            return f"{exit_line} {bridge}".strip(), nudge
        return f"{exit_line} {said_arriving.next_question_lead}".strip(), nudge

    def phrase(s: StepState) -> dict[str, Any]:
        item = s["item"]
        assert item is not None
        lead, nudged = lead_for(s)
        utterance = deps.interviewer.open_question(item, lead=lead)
        _emit(utterance.text)
        return {"utterance": utterance, "nudged": nudged}

    def finish(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        outcome = s.get("outcome")
        reason = s["finish"]
        lines = deps.persona_for(inp.state).said()
        if reason == "conduct":
            # EC-6.4: polite, and says what happens next rather than why.
            text = lines.conduct_close
            _emit(text)
            return {"utterance": Utterance(text, "template")}
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
    graph.add_node("guard", guard)
    graph.add_node("decide", decide_node)
    graph.add_node("replay_decision", replay_decision)
    graph.add_node("probe", probe)
    graph.add_node("offer_retry", offer_retry)
    graph.add_node("select", select)
    graph.add_node("phrase", phrase)
    graph.add_node("finish", finish)
    graph.add_conditional_edges(
        START,
        entry,
        ["strategist", "guard", "replay_decision", "select"],
    )
    # The join: decide runs once, after BOTH the strategist and the guard.
    graph.add_edge(["strategist", "guard"], "decide")
    for node in ("decide", "replay_decision"):
        graph.add_conditional_edges(
            node,
            after_decide,
            {
                "probe": "probe",
                "select": "select",
                "finish": "finish",
                "offer_retry": "offer_retry",
            },
        )
    graph.add_conditional_edges("select", after_select, {"phrase": "phrase", "finish": "finish"})
    graph.add_edge("probe", END)
    graph.add_edge("offer_retry", END)
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
        screen=final.get("screen"),
        offer_retry=bool(final.get("offer_retry")),
        nudged=bool(final.get("nudged")),
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
