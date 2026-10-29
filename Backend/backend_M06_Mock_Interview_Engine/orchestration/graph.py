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

import hashlib
import logging
import operator
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from .. import panel as seating
from .. import thread
from ..agents.guard import AnswerScreen, SafetyGuard, neutralise, rule_screen
from ..agents.interviewer import Interviewer, Utterance
from ..agents.strategist import ProbeStrategist
from ..clarify import clarified, on_topic, question_unheard, unsure_term
from ..contracts import Move, ProbeLadderState, StrategistVerdict
from ..items import Item
from ..ladder import LadderConfig, Outcome, decide
from ..llm import LLMResult
from ..personas import Persona
from ..phrasebook import REACTIONS
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
    #: §2.3's pace line, recorded during this selection — after the step's
    #: state was read, so it travels with the item like the bridge does.
    pace_line: str | None = None


#: The QuestionPlanner's tool. Lives in the engine, which owns the adapters.
#: The third argument is this step's own decision — the answer that ended a
#: round has not been written to the log when the next question is selected,
#: and §6.4 decides the boundary on it (see `pending_decision`).
Selector = Callable[[SessionState, datetime, dict | None], Selected]


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
    #: FR-6.21: the answer was a question for the interviewer, to record.
    closing_question: bool = False


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
    pace_line: str | None
    offer_retry: bool
    nudged: bool
    closing_question: bool
    calls: Annotated[list[LLMResult], operator.add]
    degraded: Annotated[dict[str, str], _merge]


PROBE_MOVES = frozenset(
    {
        "rung",
        "clarify",
        "redirect_once",
        "answer_briefly",
        "hint",
        "steelman",
        "redirect_conduct",
        "didnt_catch",
        "clarify_term",
        "reoffer",
        "rephrase",
        # 2026-10-22: the moves that react to what an answer is.
        "challenge",
        "simplify",
        "probe_specifics",
        "ask_evidence",
        "confront",
        "probe_missing",
        "next_part",
        "give_time",
        "redirect_repeat",
        "resume_cut",
    }
)

#: The moves the interviewer model phrases from the student's words
#: (`Interviewer.react`); the rest are authored lines.
REACTING_MOVES = frozenset(
    {
        "rung",
        "challenge",
        "simplify",
        "probe_specifics",
        "ask_evidence",
        "confront",
        "probe_missing",
        "next_part",
        "redirect_repeat",
        "give_time",
        "resume_cut",
    }
)

#: Moves that ask about an answer instead of judging it: no verdict, nothing
#: owed to M13 for the answer they asked about.
UNJUDGED = frozenset(
    {"didnt_catch", "clarify_term", "reoffer", "rephrase", "give_time", "resume_cut"}
)

#: Spec §6.8: "max 3 per session — beyond that it's annoying".
MAX_CLARIFY_PER_SESSION = 3

#: M11's FR-11.16: below this the recogniser could not make the answer out.
#: Whisper's mean exp(log-probability) over clean speech sits around 0.6–0.9;
#: garbled or drowned speech falls under 0.4.
NOT_CAUGHT_BELOW = 0.4

#: The moves "let's keep it moving" may precede (§6.7) — never a pushback or
#: a simpler question, where it would read as impatience with a struggle.
NUDGEABLE = frozenset({"rung", "redirect_once", "answer_briefly", "next_part"})

#: Leave room for a real answer. Below this a new question is not asked.
MIN_SECONDS_FOR_A_QUESTION = 60

#: FR-6.21: how many questions the closing takes before it closes.
MAX_CLOSING_QUESTIONS = 2

#: FR-6.21: the whole answer says "nothing to ask". Only the whole answer —
#: "no, I wanted to ask about the team" is a question.
#: The phrases that, strung together with nothing else, mean "nothing to ask".
#: "I don't know" is one of them at the closing: recording it as a question
#: would put it in the student's notes as their ask for the panel.
_NOTHING = (
    r"no+",
    r"nope",
    r"nah",
    r"nothing( else)?",
    r"none",
    r"not really",
    r"no questions?( for (you|now))?",
    r"i'?m good",
    r"i am good",
    r"that'?s (all|it)",
    r"that is (all|it)",
    r"all good",
    r"thanks?( you)?",
    r"i\s*(do\s*n[o']?t|dont)\s*know",
    r"not sure",
    r"no idea",
    r"can'?t think of (any|anything)( right now)?",
)
NO_QUESTIONS = re.compile(
    r"^\s*(?:(?:" + "|".join(_NOTHING) + r")[\s.,!]*)+$",
    re.I,
)

#: The words a "no questions" is made of, in any order. A phrase list is
#: always one phrasing behind: two live runs (2026-10-06/07) heard "No,
#: that's all from me. Thank you." filed as the student's question for the
#: panel ("That's one to ask the real panel"), because "from me" was not on
#: it. An answer with no question mark whose every word is one of these says
#: nothing to ask; one word of substance ("ask", "team", "about") makes it a
#: question, as before. "Yes" is not here: alone, it means they have one.
_CLOSING_TALK = frozenset(
    "no nope nah nothing none not really question questions for now else from me my "
    "side that's thats that is all it everything i i'm im am good fine okay ok so well "
    "thanks thank you very much yeah actually at the moment right think don't dont do "
    "know sure idea can't cant of any anything sir ma'am maam".split()
)


def says_nothing(answer: str) -> bool:
    """FR-6.21: the whole answer says "nothing to ask"."""
    if NO_QUESTIONS.match(answer):
        return True
    if "?" in answer:
        return False
    words = re.findall(r"[a-z']+", answer.lower().replace("’", "'"))
    return bool(words) and all(word in _CLOSING_TALK for word in words)


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
    #: Everyone on the panel (FR-6.3, `panel.py`), the lead first: who is
    #: introduced at the start, who may cut in, who closes.
    panel_for: Callable[[SessionState], list[Persona]] = lambda _state: []


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


def pending_decision(s: StepState) -> dict | None:
    """This step's decision, shaped like the `probe.decided` it will become.

    The engine writes the decision AFTER the step, and the step selects the
    next question INSIDE it — so a boundary that re-plans on the round's
    answers would miss the last one. Found by the day-10 tests: three
    failures read as two, and "struggling" fired as "gap".
    """
    outcome = s.get("outcome")
    verdict = s.get("verdict")
    inp = s["inp"]
    if outcome is None or verdict is None or inp.recorded is not None:
        return None
    answer = next((t for t in reversed(inp.state.transcript) if t.role == "candidate"), None)
    if answer is None:
        return None
    return {
        "turn_index": answer.turn_index,
        "payload": {
            "move": outcome.move.model_dump(mode="json"),
            "break_depth": outcome.break_depth,
            "ceiling": outcome.ceiling,
            "verdict": verdict.model_dump(mode="json"),
        },
    }


def _emit(text: str) -> None:
    try:
        get_stream_writer()({"token": text})
    except Exception:  # noqa: BLE001 - no stream consumer is fine
        pass


def _nudger(
    state: SessionState, panel: list[Persona], owner: Persona, answer: str | None
) -> Persona | None:
    """§6.7 `interruption_threshold`, in text: once per round, an answer
    longer than someone on the panel will sit through is cut short — by the
    least patient of them, who need not be the one asking. One person's
    question, another's watch: that is what makes it feel like a panel."""
    if not answer or state.current_segment in state.nudged_segments:
        return None
    words = len(answer.split())
    impatient = [p for p in (panel or [owner]) if words > p.long_answer_words]
    if not impatient:
        return None
    return min(impatient, key=lambda p: (p.long_answer_words, p.id != owner.id, p.id))


def _join(names: list[str]) -> str:
    """"A", "A and B", "A, B and C" — how a person lists people or topics."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _spoken(title: str) -> str:
    """A round's title as said mid-sentence: "Your projects" becomes "your
    projects"; "SQL" and "Spring Boot" keep their capitals."""
    words = title.split()
    if (
        len(words) >= 2
        and words[0][:1].isupper()
        and words[0][1:].islower()
        and words[1][:1].islower()
    ):
        return title[:1].lower() + title[1:]
    return title


def _topics_of(state: SessionState, persona_id: str) -> list[str]:
    """The rounds a panelist runs, as they would say them."""
    if state.plan is None:
        return []
    topics: list[str] = []
    for segment in state.plan.segments:
        if segment.dropped_reason is not None or segment.persona_id != persona_id:
            continue
        if segment.kind in ("warmup", "closing") or not segment.title:
            continue
        topic = _spoken(segment.title)
        if topic not in topics:
            topics.append(topic)
    return topics


def _panel_opening(
    state: SessionState, lead: Persona, panel: list[Persona]
) -> tuple[list[tuple[str, str]], str]:
    """FR-6.3: a panel introduces itself before anyone asks. The lead greets
    and names the others; each says hello and what they will ask about, in
    their own voice; then the lead asks. One interviewer simply greets."""
    said = lead.said()
    others = [p for p in panel if p.id != lead.id]
    if not others:
        return [], f"{said.greeting} {said.first_question_lead}".strip()
    names = _join([p.name for p in others])
    parts = [(lead.id, said.panel_greeting.format(name=lead.name, others=names))]
    for other in others:
        topics = _topics_of(state, other.id)
        hello = (
            other.said().panel_hello.format(topics=_join(topics))
            if topics
            else other.said().panel_sitting_in
        )
        parts.append((other.id, hello))
    return parts, said.first_question_lead


def opening_parts(
    state: SessionState, lead: Persona, panel: list[Persona]
) -> list[tuple[str, str]]:
    """The panel's opening, before its first question, as `(speaker, text)`
    parts — what the first step will say ahead of the question's stem. Known
    from the plan alone, so the voice can be made while the student reads the
    plan (2026-10-08: the first words came 5-6 s after the text)."""
    before, lead_line = _panel_opening(state, lead, panel)
    return [*before, (lead.id, lead_line)] if lead_line else before


log = logging.getLogger("uvicorn.error")  # as llm.py: printed under uvicorn


def _timed(name: str, node: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """A step, its time logged (2026-10-11): a reply took 8 s in M06 while its
    two model calls, run side by side, took 2.4 s at most — the rest was
    somewhere in the step, and nothing said where."""

    def run(s: Any) -> Any:
        started = time.perf_counter()
        try:
            return node(s)
        finally:
            log.info("M06 step %s: %.2fs", name, time.perf_counter() - started)

    return run


def _runs_a_round(state: SessionState, persona_id: str) -> bool:
    return state.plan is not None and any(
        s.persona_id == persona_id and s.dropped_reason is None for s in state.plan.segments
    )


def _interjection(
    state: SessionState, panel: list[Persona], owner: Persona, item: Item, depth: int
) -> Persona | None:
    """FR-6.3: someone else on the panel comes in with a follow-up, at the
    second rung — after the asker's own first follow-up — and the asker takes
    the question back after.

    Two kinds of someone. A panelist who knows this question's topic clearly
    better than the one asking (`panel.interjector`) comes in once a round.
    Someone sitting in (`panel.sit_in`), with no round of their own, is the
    second interviewer at the table and comes in on about every other
    question of the round."""
    if state.kind == "drill" or depth not in (1, 2) or len(panel) < 2 or state.plan is None:
        return None
    here = [
        t
        for t in state.transcript
        if t.role == "interviewer" and t.segment_index == state.current_segment
    ]
    segment = next((s for s in state.plan.segments if s.index == state.current_segment), None)
    title = segment.title if segment is not None and segment.title else ""
    topic = seating.words(item.concept_id, item.label, title)
    if depth == 2 and not any(t.speaker_id not in (None, owner.id) for t in here):
        chosen = seating.interjector(
            [p.id for p in panel], owner.id, topic, {p.id: p for p in panel}
        )
        expert = next((p for p in panel if p.id == chosen), None)
        if expert is not None:
            return expert
    sitting = next(
        (p for p in panel if p.id != owner.id and not _runs_a_round(state, p.id)), None
    )
    if sitting is None:
        return None
    # Counted over the whole interview, not the round: per round the one
    # sitting in came in on the first question of every part (3 of 4).
    spoken = [t for t in state.transcript if t.role == "interviewer"]
    asked_here = sum(
        1
        for t in spoken
        if t.probe_move is None and t.question_source not in (None, "closing")
    )
    came_in = sum(1 for t in spoken if t.speaker_id == sitting.id and t.probe_move is not None)
    # The second interviewer at the table takes the FIRST follow-up of about
    # every other question (2026-10-11). It was the second rung, and a good
    # answer usually ends a question before that: in a short interview the
    # person sitting in said hello and was never heard again.
    return sitting if depth == 1 and came_in < (asked_here + 1) // 2 else None


def _came_in(state: SessionState, persona_id: str) -> bool:
    """They asked a follow-up of their own somewhere in this interview."""
    return any(
        t.role == "interviewer" and t.speaker_id == persona_id and t.probe_move is not None
        for t in state.transcript
    )


def _said_in_turn(*pieces: str) -> str:
    """Lines said one after another, one space between — whichever of them
    is empty. Live: "Thanks, Meera.  We're close to time" (2026-10-29)."""
    return " ".join(p.strip() for p in pieces if p and p.strip())


def _taken_back(
    state: SessionState, owner: Persona, panel: list[Persona], *, closing: bool = False
) -> str:
    """The asker's "Thanks, Vikram." after someone else's follow-up — the
    first time only. The user, 2026-10-21: the host thanking the second
    interviewer after every follow-up "becomes annoying; once in the
    beginning and once at the end should be enough". So the first hand-back
    from each colleague thanks them, later ones take the question back
    without a word, and at the `closing` the one asking thanks, once more,
    everyone who came in."""
    said = owner.said()
    already = " ".join(spoken_by(state, owner.id))
    thanked: list[Persona] = []
    last = next((t for t in reversed(state.transcript) if t.role == "interviewer"), None)
    if last is not None and last.speaker_id not in (None, owner.id):
        other = next((p for p in panel if p.id == last.speaker_id), None)
        if other is not None and said.take_over.format(name=other.name) not in already:
            thanked.append(other)
    if closing:
        thanked += [
            p
            for p in panel
            if p.id != owner.id and p.id not in {t.id for t in thanked} and _came_in(state, p.id)
        ]
    return "".join(f"{said.take_over.format(name=p.name)} " for p in thanked)


#: An answer that moves on gets no word before the next question this often…
SAY_NOTHING = 0.3
#: …and, when it counted, a credit word this often (the rest: a plain
#: acknowledgement). One draw per question, so a replay says the same.
SAY_CREDIT = 0.4


def _first_word(text: str) -> str:
    return (text.split() or [""])[0].strip(",.!?—").lower()


def word_draw(seed: str, key: str) -> float:
    """A number in [0, 1) for this question and word choice — the same on a
    replay, different from one question to the next. Its own, not the
    panel's `draw`: the suite pins the seating, and that must not silence
    every acknowledgement with it."""
    digest = hashlib.sha1(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def _acknowledgement(
    state: SessionState, persona: Persona, outcome: Outcome | None, then: str
) -> str:
    """What the interviewer says after an answer, before what comes `then`
    (2026-10-21, the user: "a mix of all possible words, and sometimes just
    the next question"). A credit word ("Very good.", "Nicely put.") only
    after an answer the ladder counted a success; a plain one ("Hmm, okay.")
    after any; and sometimes nothing. Never the word they used last, nor one
    that opens what follows — "Okay. Okay, here's the next one.\""""
    roll = word_draw(f"{state.session_id}:{state.questions_asked}", f"ack:{persona.id}")
    if roll < SAY_NOTHING:
        return ""
    counted = outcome is not None and outcome.success is True
    credit = counted and persona.credit and roll < SAY_NOTHING + SAY_CREDIT
    pool = persona.credit if credit else persona.acknowledgements
    recent = " ".join(spoken_by(state, persona.id)[-4:])
    opens = _first_word(then)
    fresh = [w for w in pool if w not in recent and _first_word(w) != opens]
    if not fresh:
        return ""
    pick = word_draw(f"{state.session_id}:{state.questions_asked}", f"pick:{persona.id}")
    return fresh[int(pick * len(fresh))]


def spoken_by(state: SessionState, persona_id: str) -> list[str]:
    """Everything this interviewer has said, in order, one entry per part —
    the parts of a two-voice line split between the two who said them."""
    out: list[str] = []
    for turn in state.transcript:
        if turn.role != "interviewer":
            continue
        if turn.parts:
            out.extend(p.text for p in turn.parts if p.speaker_id == persona_id)
        elif turn.speaker_id == persona_id:
            out.append(turn.text)
    return out


def _fresh_exit(
    state: SessionState, persona: Persona, line: str, others: tuple[str, ...] | None = None
) -> str:
    """Nobody closes a question the same way every time: a live panel run
    heard the professor say "That's where it gets subtle. Let's leave it
    there for now." eight answers running (2026-10-07). When this interviewer
    used `line` on their last line, another of their own authored exits is
    said instead — each of them neutral, none a verdict."""
    # Their last few lines, not just the last: a redirect between two exits
    # still let the professor's own exit come twice in a live run. Their OWN
    # words, part by part: a hand-over turn belongs to the one arriving, and
    # read whole it hid the leaving one's exit and lent them the other's
    # (2026-10-08: "Okay, let's leave that there." twice running).
    #
    # `others` are the exits that may stand in. The default borrowed any of
    # the three, so a struggled answer could close on "that covers it" and a
    # good one on "that's where it gets subtle" (2026-10-21): a borrowed line
    # carries the verdict of the answer it was written for.
    recent = " ".join(spoken_by(state, persona.id)[-3:])
    if not line or line not in recent:
        return line
    said = persona.said()
    if others is None:
        others = (said.moving_on, said.ceiling_exit, said.graceful_exit)
    for other in others:
        if other and other != line and other not in recent:
            return other
    return line


#: M11's FR-11.12: how long an interviewer is quiet after "let me note that
#: down" — long enough to be writing, short enough not to read as a stall.
NOTE_TAKING_PAUSE_MS = 1500


def _merge_voices(parts: list[tuple]) -> list[tuple]:
    """Adjacent words by one voice are one part — unless a pause sits
    between them (a third element, ms) — and empty ones are dropped."""
    out: list[tuple] = []
    for part in parts:
        who, text = part[0], part[1].strip()
        pause = int(part[2]) if len(part) > 2 else 0
        if not text:
            continue
        if out and out[-1][0] == who and len(out[-1]) == 2:
            text = f"{out[-1][1]} {text}"
            out[-1] = (who, text, pause) if pause else (who, text)
        else:
            out.append((who, text, pause) if pause else (who, text))
    return out


def _voiced(utterance: Utterance, parts: list[tuple[str, str]]) -> Utterance:
    """The utterance as its voices say it: the text is every part in order;
    the question (what a repeat says) is the asker's question alone."""
    merged = _merge_voices(parts)
    return Utterance(
        " ".join(part[1] for part in merged),
        utterance.source,
        call=utterance.call,
        fallback_reason=utterance.fallback_reason,
        question=utterance.question or utterance.text,
        parts=tuple(merged),
    )


def _not_caught(state: SessionState) -> bool:
    """M11's FR-11.16: the recogniser was unsure of the answer just given,
    and this question has not asked to hear it again yet."""
    last = state.transcript[-1] if state.transcript else None
    if last is None or last.role != "candidate" or last.asr_confidence is None:
        return False
    if last.asr_confidence >= NOT_CAUGHT_BELOW:
        return False
    return state.ladder is None or "didnt_catch" not in state.ladder.moves


def _answered(state: SessionState) -> Any | None:
    """The interviewer's line the last answer replied to."""
    if not state.transcript or state.transcript[-1].role != "candidate":
        return None
    return next((t for t in reversed(state.transcript[:-1]) if t.role == "interviewer"), None)


def _unheard(state: SessionState) -> bool:
    """M11's EC-11.1: the question the student answered was barely heard,
    and this question has not been put again yet."""
    if state.ladder is not None and "reoffer" in state.ladder.moves:
        return False
    return question_unheard(_answered(state))


def _term_to_check(state: SessionState, item: Item | None) -> tuple[str, str] | None:
    """M11's FR-11.16: (what was heard, the term it may have been) — when
    the recogniser was unsure of a word near one that decides the answer."""
    last = state.transcript[-1] if state.transcript else None
    if item is None or last is None or last.role != "candidate" or not last.unsure:
        return None
    if last.asr_confidence is not None and last.asr_confidence < NOT_CAUGHT_BELOW:
        return None  # nothing was made out: "didn't catch that" instead
    if state.ladder is not None and "clarify_term" in state.ladder.moves:
        return None  # once a question
    answered = _answered(state)
    if answered is not None and answered.probe_move == "clarify_term":
        return None  # never clarify a clarification
    asked = sum(
        1 for t in state.transcript if t.role == "interviewer" and t.probe_move == "clarify_term"
    )
    if asked >= MAX_CLARIFY_PER_SESSION:
        return None
    return unsure_term(last.text, last.unsure, item)


def ladder_depth(state: SessionState) -> int:
    return state.ladder.depth if state.ladder is not None else 0


#: How a question was left that the graceful exit's comfort would misdescribe
#: (2026-10-22): "it's a detail people usually look up" after a misunderstanding
#: is false reassurance, and the student hears it as "that was fine".
UNRESOLVED = frozenset(
    {
        "gap:misunderstanding",
        "gap:complete",
        "gap:surface",
        "gap:advanced",
        "unsupported",
        "avoided",
        "no_answer",
    }
)


def graceful_exit(persona: Persona, outcome: Outcome | None) -> str:
    """The exit after a struggle: the persona's own graceful line for a slip
    or a forgotten detail; a plain, honest one when the gap is real."""
    said = persona.said()
    if outcome is not None and outcome.left in UNRESOLVED:
        lines = REACTIONS.get(persona.speech, REACTIONS["neutral"]).get("leave_open")
        if lines:
            return lines[0]
    return said.graceful_exit


def _answer_given(state: SessionState, answer: str) -> str:
    """The answer as given: a reply to "did you say …?" with the answer it
    clarifies, that answer first."""
    last = state.transcript[-1] if state.transcript else None
    if last is None or last.role != "candidate":
        return answer
    original = clarified(state, last)
    return f"{original.text}\n{answer}" if original is not None else answer


def build(deps: Deps):
    def entry(s: StepState) -> str | list[str]:
        inp = s["inp"]
        if inp.recorded is not None:
            return "replay_decision"
        if inp.answer is not None and inp.item is not None and inp.item.source == "closing":
            # FR-6.21: the student's question for us is not an answer to judge.
            return "closing_reply"
        if inp.answer is not None and _unheard(inp.state):
            # They spoke before hearing the question: it is put again (EC-11.1).
            return "reoffer"
        if inp.answer is not None and _not_caught(inp.state):
            # Words nobody could make out are not judged: heard again first.
            return "not_caught"
        if inp.answer is not None and _term_to_check(inp.state, inp.item) is not None:
            # "Did you say quick sort or quick select?" (FR-11.16, §6.8).
            return "clarify_term"
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
        given = _answer_given(inp.state, inp.answer)
        answer = neutralise(given, rule_screen(given).spans)
        # The question WITHOUT the words that introduced it — §6.7's promise:
        # "the persona never changes the standard". The rendered turn carries
        # the register's lead ("Hello. Let's begin. First question." against a
        # bar-raiser's "Let's get started. First."), and feeding that to the
        # strategist would make the verdict — which becomes an M05 θ
        # observation (FR-6.25) — depend on the interviewer's manner. The
        # adapted probe IS the question and survives; only the lead is cut.
        d = deps.strategist.decide(
            inp.item,
            ladder.depth,
            _question_to_repeat(inp.state),
            answer,
            # 2026-10-22: the question's own thread, so a correction, a
            # contradiction and the same answer twice are visible — and the
            # student's earlier statements, for a direct contradiction only.
            thread=thread.thread_before_answer(inp.state),
            earlier=thread.earlier_statements(inp.state),
            claim=thread.claim_text(inp.state, inp.item),
            later=thread.not_asked_yet(inp.state, inp.item),
        )
        verdict = d.verdict
        if verdict.off_question and on_topic(answer, inp.item, _question_to_repeat(inp.state)):
            # 2026-10-07: a wrong attempt that uses the question's own words
            # is an attempt, not a different question. The model judged a
            # confused answer about BST lookup "off question"; the student
            # heard "That's a different question".
            update: dict[str, Any] = {"off_question": False}
            if verdict.category == "off_question":
                # Since strategist-5 the ladder reads the category too, and
                # clearing the flag alone overruled nothing. The model never
                # judged the content, so it is not called right or wrong:
                # unclear, and they are asked to say it differently.
                update.update(category="ambiguous", ambiguous=True)
            verdict = verdict.model_copy(update=update)
        return {
            "verdict": verdict,
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
            ctx=thread.context(inp.state, item, inp.answer or ""),
        )
        out: dict[str, Any] = {"outcome": outcome}
        if outcome.move.kind == "end_session":
            out["finish"] = "conduct"
        return out

    def not_caught(s: StepState) -> dict[str, Any]:
        """M11's FR-11.16: ask to hear it again — no verdict, no depth."""
        return {"outcome": Outcome(move=Move(kind="didnt_catch"), success=None)}

    def reoffer(s: StepState) -> dict[str, Any]:
        """M11's EC-11.1: put the question again — no verdict, no depth."""
        return {"outcome": Outcome(move=Move(kind="reoffer"), success=None)}

    def clarify_term(s: StepState) -> dict[str, Any]:
        """M11's FR-11.16: ask which word was meant — no verdict, no depth."""
        return {"outcome": Outcome(move=Move(kind="clarify_term"), success=None)}

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
        seated = deps.panel_for(inp.state)
        repeat_q = _question_to_repeat(inp.state)
        last_answer = _answer_given(
            inp.state,
            next(
                (t.text for t in reversed(inp.state.transcript) if t.role == "candidate"),
                inp.answer or "",
            ),
        )
        out: dict[str, Any] = {"item": item, "new_question": False}
        # One "keep it moving" per round, and only before a follow-up or a
        # redirect: before a hint or a request to rephrase it would read as
        # impatience with a student who asked for help. In a panel it comes
        # from whoever on it ran out of patience first.
        nudger = (
            _nudger(inp.state, seated, persona, inp.answer) if move.kind in NUDGEABLE else None
        )
        before: list[tuple[str, str]] = []
        prefix = ""
        if nudger is not None:
            out["nudged"] = True
            if nudger.id == persona.id:
                prefix = f"{lines.keep_moving} "
            else:
                before.append((nudger.id, nudger.said().keep_moving))
            _emit(f"{nudger.said().keep_moving} ")
        # FR-6.3: an expert on the panel may come in with this follow-up.
        asker = persona
        if move.kind == "rung" and nudger is None and move.depth is not None:
            asker = _interjection(inp.state, seated, persona, item, move.depth) or persona
        if asker.id != persona.id:
            prefix = f"{asker.said().interject} "
            _emit(prefix)
        back = _taken_back(inp.state, persona, seated) if asker.id == persona.id else ""
        if back:
            _emit(back)
        if move.kind in REACTING_MOVES:
            # 2026-10-22: the answer decided the move; the interviewer phrases
            # it from the student's own words, in the move's tone.
            view = project_for_interviewer(
                transcript=inp.state.transcript,
                move=move.kind,
                ladder_depth=move.depth if move.depth is not None else ladder_depth(inp.state),
                time_remaining_s=inp.state.time_remaining_s(inp.now),
                profile_prefix=inp.state.profile_prefix,
                # §6.6: what happened before the last six turns. Without it a
                # long round asks about hashing twice, because everything
                # older than six turns simply is not there.
                round_summary=inp.state.round_summary,
                register=asker.speech,
                persona_style=asker.style,
                max_words=asker.verbosity_target,
            )
            utterance = deps.interviewer.react(
                item,
                move,
                view=view,
                name=asker.name,
                last_answer=last_answer,
                asked=repeat_q,
                openers=thread.recent_openers(inp.state, asker.id),
                answer_key=item.answer_key,
                on_token=_emit,
                seed=f"{inp.state.session_id}:{len(inp.state.transcript)}",
            )
            calls = [c for c in (utterance.retried, utterance.call) if c is not None]
            if calls:
                out["calls"] = calls
            if move.kind in ("give_time", "resume_cut"):
                # Nothing new is asked: the question stays the one before.
                utterance.question = repeat_q
        elif move.kind == "clarify":
            # The question stays open: "Can you rephrase that?" is about the
            # answer. Without it a redirect after a clarify repeated the
            # clarify — "Here's mine again. Can you rephrase that?" (live run,
            # 2026-10-22).
            utterance = Utterance(lines.clarify, "template", question=repeat_q)
        elif move.kind == "didnt_catch":
            utterance = Utterance(lines.didnt_catch, "template", question=repeat_q)
        elif move.kind == "reoffer":
            utterance = Utterance(f"{lines.reoffer} {repeat_q}", "template", question=repeat_q)
        elif move.kind == "rephrase":
            view = project_for_interviewer(
                transcript=inp.state.transcript,
                move=move.kind,
                ladder_depth=inp.state.ladder.depth if inp.state.ladder else 0,
                time_remaining_s=inp.state.time_remaining_s(inp.now),
                profile_prefix=inp.state.profile_prefix,
                round_summary=inp.state.round_summary,
                register=persona.speech,
                persona_style=persona.style,
                max_words=persona.verbosity_target,
            )
            utterance = deps.interviewer.rephrase(
                repeat_q, view=view, lead=lines.rephrase_lead, on_token=_emit
            )
            if utterance.call is not None:
                out["calls"] = [utterance.call]
        elif move.kind == "clarify_term":
            found = _term_to_check(inp.state, item)
            if found is None:  # a replay of a decision whose answer has changed
                utterance = Utterance(lines.didnt_catch, "template", question=repeat_q)
            else:
                heard, term = found
                said = (
                    lines.clarify_term.format(heard=heard, term=term)
                    if re.fullmatch(r"[A-Za-z' -]+", heard)
                    else lines.clarify_term_one.format(term=term)
                )
                utterance = Utterance(said, "template", question=repeat_q)
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
        if (move.kind not in REACTING_MOVES and move.kind != "rephrase") or (
            utterance.source == "template"
        ):
            _emit(utterance.text)
        out["utterance"] = _voiced(
            utterance, [*before, (asker.id, f"{back}{prefix}{utterance.text}")]
        )
        return out

    def offer_retry(s: StepState) -> dict[str, Any]:
        """§15.4, Practice: the graceful exit, then the offer of another go.

        Said after the exit line, so it reads as an option rather than as a
        verdict — "that's fair, it's a detail people look up; want another
        go?" — and nothing is selected until the student chooses.
        """
        inp, outcome = s["inp"], s["outcome"]
        who = deps.persona_for(inp.state)
        lines = who.said()
        exit_line = (
            graceful_exit(who, outcome)
            if outcome.move.graceful
            else Interviewer.exit_then(lines, graceful=False, ceiling=outcome.ceiling is not None)
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
        if state.plan is None:
            # No plan, so no closing to reserve: the old arithmetic stands.
            if state.questions_asked >= deps.question_budget(state):
                return {"finish": "plan_complete"}
            if state.time_remaining_s(inp.now) < MIN_SECONDS_FOR_A_QUESTION:
                return {"finish": "time"}
        # With a plan, the selector decides — it is the one that knows a
        # round is spent, a clock is out, and the closing is still owed.
        if inp.select is None:
            return {"finish": "no_question_source"}
        found = inp.select(state, inp.now, pending_decision(s))
        if found.item is None:
            return {"finish": found.empty_reason or "bank_exhausted", "degraded": found.degraded}
        return {
            "item": found.item,
            "new_question": True,
            "selection": found.selection,
            "degraded": found.degraded,
            "bridge": found.bridge,
            "persona": found.persona,
            "pace_line": found.pace_line,
        }

    def after_select(s: StepState) -> str:
        return "finish" if s.get("finish") else "phrase"

    def lead_for(s: StepState) -> tuple[list[tuple[str, str]], str, bool]:
        """What is said before the question: what others on the panel say
        first, the asker's own words before it, and whether that includes the
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
        seated = deps.panel_for(inp.state)
        if not inp.state.opened:
            if inp.state.kind == "drill":
                opening = f"{said_arriving.drill_open} {said_arriving.first_question_lead}"
                return [], opening.strip(), False
            before, lead = _panel_opening(inp.state, arriving, seated)
            return before, lead, False
        graceful = outcome is not None and outcome.move.graceful
        nudger = None if graceful else _nudger(inp.state, seated, leaving, inp.answer)
        nudge = nudger is not None
        before: list[tuple[str, str]] = []
        if nudger is not None and nudger.id != leaving.id:
            # Someone else on the panel cuts a long answer short (§6.7).
            before.append((nudger.id, nudger.said().keep_moving))
        # §2.3's pace line rides with the next question, like a bridge — but
        # not into the closing, which supersedes whatever it promised.
        next_item = s.get("item")
        closing_next = next_item is not None and next_item.source == "closing"
        pace = "" if closing_next else (s.get("pace_line") or inp.state.pending_pace_line or "")
        skipped = inp.state.pending_skip
        if outcome is None and skipped == "left":
            # A second skip at one number (2026-10-07): the question is left.
            exit_line = said_leaving.skip_leave
        elif outcome is None or (nudger is not None and nudger.id != leaving.id):
            exit_line = ""
        elif nudge:
            exit_line = said_leaving.keep_moving
        else:
            recent = " ".join(spoken_by(inp.state, leaving.id)[-3:])
            if graceful:
                exit_line = _fresh_exit(
                    inp.state, leaving, graceful_exit(leaving, outcome), (said_leaving.moving_on,)
                )
            elif outcome.ceiling is not None and said_leaving.ceiling_exit not in recent:
                exit_line = said_leaving.ceiling_exit
            else:
                # An answer that moves on: a word that it was heard, varied,
                # and sometimes none (2026-10-21).
                then = (
                    said_leaving.hand_over.format(name=arriving.name)
                    if (s.get("bridge") or inp.state.pending_bridge) and arriving.id != leaving.id
                    else s.get("bridge")
                    or inp.state.pending_bridge
                    or (said_arriving.bridge_to_closing if closing_next else "")
                    or said_arriving.next_question_lead
                )
                exit_line = _acknowledgement(inp.state, leaving, outcome, then)
            cadence = leaving.note_taking_cadence
            if (
                not graceful
                and cadence
                and inp.state.questions_asked % cadence == 0
                and not s.get("bridge")
            ):
                # Realism only (§6.7): it says nothing about the answer, and
                # never follows a break, where it would read as a verdict.
                # Said on its own, then a pause while they write (FR-11.12).
                before.append((leaving.id, said_leaving.note_taking, NOTE_TAKING_PAUSE_MS))
        bridge = s.get("bridge") or inp.state.pending_bridge
        if bridge and arriving.id != leaving.id:
            # A hand-over (FR-6.3): the one leaving names the one arriving,
            # who thanks them and takes the round — two voices, not a cut.
            handing = _said_in_turn(
                exit_line, pace, said_leaving.hand_over.format(name=arriving.name)
            )
            # Into the closing, the one arriving also thanks, once, anyone
            # else who came in during the interview.
            also = "".join(
                f"{said_arriving.take_over.format(name=p.name)} "
                for p in seated
                if closing_next
                and p.id not in (leaving.id, arriving.id)
                and _came_in(inp.state, p.id)
            )
            taking = f"{said_arriving.take_over.format(name=leaving.name)} {also}{bridge}"
            return [*before, (leaving.id, handing)], taking, nudge
        # After someone else's follow-up, the asker takes the question back:
        # thanked the first time, and once more at the closing. The word for
        # the student's answer comes first: "Thanks, Meera. Nicely put." read
        # as praise of Meera (walkthrough, 2026-10-29).
        back = _taken_back(inp.state, leaving, seated, closing=closing_next)
        if bridge:
            # A new round starts. The bridge replaces "next question", because
            # saying both ("Okay, let's leave that there. Next question. Let's
            # move to the next part: SQL.") is three transitions for one.
            return before, _said_in_turn(exit_line, back, pace, bridge), nudge
        item = s.get("item")
        if item is not None and item.source == "closing":
            # The closing without a bridge (a crash replayed): it still asks.
            closing_lead = _said_in_turn(exit_line, back, pace, said_arriving.bridge_to_closing)
            return before, closing_lead, nudge
        if skipped == "replaced":
            # The same question number, a different question: "next" would
            # say the skipped one was used up, and it was not.
            return before, _said_in_turn(back, said_arriving.skip_lead), nudge
        return before, _said_in_turn(exit_line, back, pace, said_arriving.next_question_lead), nudge

    def phrase(s: StepState) -> dict[str, Any]:
        item = s["item"]
        assert item is not None
        before, lead, nudged = lead_for(s)
        # M05 §6.8: a question from the student's history, asked again because
        # the bank ran thin, is announced — "a silent repeat is the failure;
        # an announced one is a re-test the student can reason about".
        disclosure = ((s.get("selection") or {}).get("disclosure") or "").strip()
        if disclosure:
            lead = f"{lead} {disclosure}".strip()
        asker = s.get("persona") or deps.persona_for(s["inp"].state)
        asked = deps.interviewer.open_question(item, lead=lead)
        utterance = _voiced(asked, [*before, (asker.id, asked.text)])
        _emit(utterance.text)
        return {"utterance": utterance, "nudged": nudged}

    def closing_reply(s: StepState) -> dict[str, Any]:
        """FR-6.21: acknowledge, record, and either ask once more or close.

        M06 cannot speak for a company's panel, so it does not pretend to
        answer — it says so, and the question goes in the notes, where the
        company guide (M15) can answer it properly.
        """
        inp = s["inp"]
        lines = deps.persona_for(inp.state).said()
        answer = inp.answer or ""
        if rule_screen(answer).abusive:
            _emit(lines.conduct_close)
            return {"finish": "conduct", "utterance": Utterance(lines.conduct_close, "template")}
        nothing = says_nothing(answer)
        out: dict[str, Any] = {"closing_question": not nothing}
        reply = lines.closing_none
        if not nothing:
            # 2026-10-07: a question about the interview itself — "explain
            # the dynamic array question you asked me" — is answered, as a
            # real interviewer would once the mock is over. Only what the
            # company alone can answer goes to the real panel.
            persona = deps.persona_for(inp.state)
            view = project_for_interviewer(
                transcript=inp.state.transcript,
                move="answer_briefly",
                ladder_depth=0,
                time_remaining_s=inp.state.time_remaining_s(inp.now),
                profile_prefix=inp.state.profile_prefix,
                round_summary=inp.state.round_summary,
                register=persona.speech,
                persona_style=persona.style,
                max_words=persona.verbosity_target,
            )
            asked = [
                t.question_text
                for t in inp.state.transcript
                if t.role == "interviewer" and t.question_text and t.question_id is not None
            ]
            kind, explanation, call = deps.interviewer.closing_answer(
                answer, asked=list(dict.fromkeys(asked)), view=view
            )
            if call is not None:
                out["calls"] = [call]
            reply = (
                explanation
                if kind == "explain" and explanation
                else lines.defer_to_report
                if kind == "report"
                else lines.closing_ack
            )
        if (
            nothing
            or inp.state.closing_asked >= MAX_CLOSING_QUESTIONS
            or inp.state.time_remaining_s(inp.now) <= 0
        ):
            text = f"{reply} {lines.session_close}"
            _emit(text)
            out |= {"finish": "plan_complete", "utterance": Utterance(text, "template")}
            return out
        text = f"{reply} {lines.closing_more}"
        _emit(text)
        out |= {
            "utterance": Utterance(text, "template", question=lines.closing_more),
            "item": inp.item,
            "new_question": False,
        }
        return out

    def finish(s: StepState) -> dict[str, Any]:
        inp = s["inp"]
        outcome = s.get("outcome")
        reason = s["finish"]
        owner = deps.persona_for(inp.state)
        lines = owner.said()
        if reason == "conduct":
            # EC-6.4: polite, and says what happens next rather than why.
            text = lines.conduct_close
            _emit(text)
            return {"utterance": Utterance(text, "template")}
        # The lead closes, as they opened: an interview that ends inside
        # someone else's round has them close their question, then the lead
        # says goodbye.
        seated = deps.panel_for(inp.state)
        lead = seated[0] if seated else owner
        closing = lead.said()
        parts: list[tuple[str, str]] = []
        if outcome is not None:
            if outcome.move.graceful or outcome.ceiling is not None:
                exit_line = Interviewer.exit_then(
                    lines, graceful=outcome.move.graceful, ceiling=outcome.ceiling is not None
                )
            else:
                # "Let's move on" with nothing to move on to read oddly before
                # goodbye; an answer that moved on gets its acknowledgement.
                exit_line = _acknowledgement(inp.state, owner, outcome, closing.session_close)
            parts.append((owner.id, exit_line))
        if reason == "time":
            parts.append((lead.id, closing.time_up))
        parts.append(
            (lead.id, closing.drill_close if inp.state.kind == "drill" else closing.session_close)
        )
        utterance = _voiced(Utterance("", "template"), parts)
        utterance.question = None
        _emit(utterance.text)
        return {"utterance": utterance}

    graph = StateGraph(StepState)
    graph.add_node("strategist", _timed("strategist", strategist))
    graph.add_node("guard", _timed("guard", guard))
    graph.add_node("decide", _timed("decide", decide_node))
    graph.add_node("replay_decision", _timed("replay_decision", replay_decision))
    graph.add_node("not_caught", _timed("not_caught", not_caught))
    graph.add_node("reoffer", _timed("reoffer", reoffer))
    graph.add_node("clarify_term", _timed("clarify_term", clarify_term))
    graph.add_node("probe", _timed("probe", probe))
    graph.add_node("offer_retry", _timed("offer_retry", offer_retry))
    graph.add_node("select", _timed("select", select))
    graph.add_node("phrase", _timed("phrase", phrase))
    graph.add_node("finish", _timed("finish", finish))
    graph.add_node("closing_reply", _timed("closing_reply", closing_reply))
    graph.add_conditional_edges(
        START,
        entry,
        [
            "strategist",
            "guard",
            "replay_decision",
            "select",
            "closing_reply",
            "not_caught",
            "reoffer",
            "clarify_term",
        ],
    )
    graph.add_edge("closing_reply", END)
    # The join: decide runs once, after BOTH the strategist and the guard.
    graph.add_edge(["strategist", "guard"], "decide")
    for node in ("decide", "replay_decision", "not_caught", "reoffer", "clarify_term"):
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
        closing_question=bool(final.get("closing_question")),
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
