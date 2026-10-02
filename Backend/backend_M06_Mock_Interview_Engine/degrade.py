"""The degradation ladder — spec §10, EC-6.12, and §8's "Degraded (L2/L3)" badge.

The spec names the rungs (`L0`–`L3`, `panic`) and the fallback for each
failure. It does not say what moves a session from one rung to the next, so
this module does — from what the session actually saw, never from a guess
about the provider:

  L0     Nothing is degraded.
  L1     An upstream module is down and served by its documented fallback
         (§10's second table). The interview runs as designed; the notes say
         what was missing.
  L2     The model failed on the last turn, and a template or the rule
         strategist carried it. The student hears "a slightly generic
         transition" (§10) and nothing else changes.
  L3     The model failed `WRAP_AFTER` turns running. A templated interview
         judged by rules measures less with every turn, so the session WRAPS
         UP A LITTLE EARLY (§8's badge): what is left of the plan gives way
         to the round in progress and the closing. One-way — the plan that
         was cut stays cut, and the badge stays true.
  panic  `PANIC_AFTER` turns running (EC-6.12). The model is not asked again:
         questions and probes come from the items' own stems and follow-ups
         verbatim, the strategist is the rule, evaluation waits in the outbox,
         and the session completes. Every `PROBE_EVERY_S` one turn is let
         through to the real model; when it answers, the session climbs back
         down (the cut plan stays cut).

Past the ladder is §10's "Everything fails": a step that crashes `ABORT_AFTER`
times running ends the session as `aborted`, with the partial report, no
score, and the apology — "this one's on us, it doesn't count".

What does NOT move with the ladder is the standard. The evaluation ensemble
is the mode's (AC-6.17), and a session whose interviewer was templated is
scored by M13 exactly as any other: the student's answers are the same
answers whatever phrased the question.
"""

from __future__ import annotations

from datetime import datetime

from .llm import JOB_GUARD, NullLLM

#: Turns the model must fail running before the session wraps up early (L3).
WRAP_AFTER = 2
#: Before it stops being asked at all (panic, EC-6.12).
PANIC_AFTER = 3
#: While in panic, how often one turn is let through to try the model again.
PROBE_EVERY_S = 60.0
#: §10 "Everything fails": crashed steps running before the session is ended.
ABORT_AFTER = 2

#: In order, lowest first. A session's level is the highest that applies.
LEVELS = ("L0", "L1", "L2", "L3", "panic")


#: §10's apology, said as the session ends. Microcopy that ships.
APOLOGY = (
    "I'm sorry — something on our side has stopped working, so I'm going to end "
    "this here. This one's on us: it doesn't count, and your notes keep what we "
    "got through."
)
#: §8's badge, for L3 and panic.
BADGE = "Wrapping up a little early"


def level(*, model_failures: int, upstream_degraded: bool, wrapped: bool) -> str:
    """The rung a session is on, from what it has seen."""
    if model_failures >= PANIC_AFTER:
        return "panic"
    if model_failures >= WRAP_AFTER or wrapped:
        return "L3"
    if model_failures >= 1:
        return "L2"
    if upstream_degraded:
        return "L1"
    return "L0"


def at_least(current: str, floor: str) -> bool:
    return LEVELS.index(current) >= LEVELS.index(floor)


def circuit_open(model_failures: int, last_attempt: datetime | None, now: datetime) -> bool:
    """Panic, and not yet time to try the model again."""
    if model_failures < PANIC_AFTER:
        return False
    if last_attempt is None:
        return False
    return (now - last_attempt).total_seconds() < PROBE_EVERY_S


class CircuitOpenLLM(NullLLM):
    """What the step runs on while the circuit is open: every agent sees no
    model, takes its own documented fallback, and makes no call — so a panic
    turn costs nothing and writes no failed call to the trace."""

    reason = "the model failed several turns running; templates and rules until it is back"


#: One instance, so the compiled step graph for it is built once.
CIRCUIT_OPEN = CircuitOpenLLM()


def model_turn(calls) -> bool | None:
    """Whether this turn's model calls worked: True, False, or None when the
    turn made none (a rule-only turn, or the circuit was open) and so says
    nothing about the model either way."""
    # The guard is a separate classifier that fails open by design (EC-6.6):
    # its outages are not the interview degrading.
    relevant = [c for c in calls if getattr(c, "job", None) != JOB_GUARD]
    if not relevant:
        return None
    return all(c.ok for c in relevant)


__all__ = [
    "ABORT_AFTER",
    "APOLOGY",
    "BADGE",
    "CIRCUIT_OPEN",
    "LEVELS",
    "PANIC_AFTER",
    "PROBE_EVERY_S",
    "WRAP_AFTER",
    "CircuitOpenLLM",
    "at_least",
    "circuit_open",
    "level",
    "model_turn",
]
