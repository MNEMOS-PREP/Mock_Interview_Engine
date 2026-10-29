"""Per-topic difficulty — answer-driven, temporary, inspectable (2026-10-22).

The user's spec: when a student struggles, stop escalating that topic; when
they do well, go further *in that topic* — and "a candidate demonstrating
expertise in distributed systems should not automatically receive harder
questions about databases". Before this, the only memory of how a topic was
going was the ladder of the open question, and it went one rung deeper on any
answer that was not an outright failure.

So each topic carries a `TopicState` (contracts.py), folded from the answers
given in it, and nothing else:

    level   -2 … +2   where the next follow-up in this topic is pitched
    recent  the last few answers' QUALITY, 0–1

**How it moves** (`update`), on each judged answer in the topic:

    mean of the last two ≥ 0.85   one level up    (two strong answers running)
    mean of the last two ≤ 0.30   one level down  (two weak answers running)
    otherwise                     one step back toward 0 when the newest
                                  answer disagrees with the level

One answer is never a trend, so the first answer in a topic moves nothing.
And it is temporary by construction: it lives in this interview's state,
is keyed by concept, and is recomputed from that concept's own recent
answers — so a level earned on hashing never reaches DBMS, and a level left
behind by a bad patch walks back as soon as the answers improve.

**What it changes** — three things, each a plain function a test can hold:

* how deep a question may go (`allowed_depth`): one rung further when the
  topic is going well, one rung shorter when it is not;
* what kind of follow-up comes next (`angle_for`): edge cases, failure and
  scale when it is going well; the mechanism, plainly, when it is not;
* where M05 pitches the NEXT question in the topic (`selection_offset`),
  sent per concept as `difficulty_offset`.

Not an ability estimate. That is M05's θ, which M06 never holds (FR-6.25);
this is the interviewer's sense of how the conversation in one topic is
going, and the trace shows it on every decision.
"""

from __future__ import annotations

import re
from statistics import mean

from .contracts import DEPTH_CAP, TopicState

#: How many of a topic's answers the level is computed over.
WINDOW = 4
UP_AT = 0.85
DOWN_AT = 0.30
#: The newest answer "disagrees" with a raised level below this, and with a
#: lowered one at or above it.
AGREES_AT = 0.6
LEVEL_MIN, LEVEL_MAX = -2, 2
#: Logits per level, for M05's selection — half a logit is one difficulty
#: band's spacing in M05's band table (`models_irt.BAND_LOGITS`).
LOGITS_PER_LEVEL = 0.5

#: The kinds of harder follow-up, in the order a good interviewer reaches for
#: them on a topic that is going well…
HARDER = ("edge_case", "failure", "trade_off", "scale", "alternative")
#: …on a topic held at its level…
AS_ASKED = ("mechanism", "edge_case", "trade_off", "failure", "alternative")
#: …and on one that is not going well: the idea itself, plainly.
EASIER = ("mechanism", "example")
#: On the student's own resume: what they built, why, and what it cost.
RESUME = (
    "implementation",
    "decision",
    "trade_off",
    "failure",
    "measurement",
    "scale",
    "alternative",
)

_WORD = re.compile(r"[a-z0-9]+")
#: Two misconception labels name the same misunderstanding at this overlap.
SAME_MISCONCEPTION_AT = 0.5


def update(
    topic: TopicState | None,
    concept_id: str,
    *,
    quality: float | None,
    misconception: str | None = None,
    decision: str = "",
) -> TopicState:
    """The topic after one more answer. Pure: same inputs, same state."""
    state = topic.model_copy(deep=True) if topic is not None else TopicState(concept_id=concept_id)
    if decision:
        state.last_decision = decision
    if misconception:
        label = misconception.strip()
        if any(same_misconception(label, seen) for seen in state.misconceptions):
            if not any(same_misconception(label, seen) for seen in state.repeated):
                state.repeated.append(label)
        else:
            state.misconceptions.append(label)
    if quality is None:
        return state
    state.answers += 1
    state.recent = [*state.recent, round(float(quality), 2)][-WINDOW:]
    state.level = _relevel(state.level, state.recent)
    return state


def _relevel(level: int, recent: list[float]) -> int:
    if len(recent) < 2:
        return level
    last_two = mean(recent[-2:])
    if last_two >= UP_AT:
        return min(level + 1, LEVEL_MAX)
    if last_two <= DOWN_AT:
        return max(level - 1, LEVEL_MIN)
    newest = recent[-1]
    if level > 0 and newest < AGREES_AT:
        return level - 1
    if level < 0 and newest >= AGREES_AT:
        return level + 1
    return level


def allowed_depth(persona_max: int, level: int) -> int:
    """How deep a question in this topic may go, by the persona's own depth."""
    bonus = 1 if level >= 1 else (-1 if level <= -1 else 0)
    return max(1, min(DEPTH_CAP, persona_max + bonus))


def angle_for(level: int, used: list[str], *, resume: bool = False) -> str:
    """The next kind of follow-up in this question, never one it already used."""
    order = RESUME if resume else (HARDER if level >= 1 else EASIER if level <= -1 else AS_ASKED)
    fresh = [a for a in order if a not in used]
    return (fresh or list(order))[0]


def selection_offset(level: int) -> float:
    """Where M05 should pitch the next question in this topic, in logits."""
    return round(level * LOGITS_PER_LEVEL, 2)


def same_misconception(a: str, b: str) -> bool:
    words_a = set(_WORD.findall(a.lower()))
    words_b = set(_WORD.findall(b.lower()))
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / len(words_a | words_b) >= SAME_MISCONCEPTION_AT


def explain(topic: TopicState) -> str:
    """The level in plain words, for the notes, read after the interview.
    It said "going well: a harder follow-up next" — the interviewer's note to
    itself, which a student read as "thinking aloud: going well: a harder
    follow-up next" (walkthrough, 2026-10-29)."""
    if topic.level >= 2:
        return "strong — the follow-ups went to the hard end"
    if topic.level == 1:
        return "going well — the follow-ups got harder"
    if topic.level == -1:
        return "shaky — the follow-ups went back to the core idea"
    if topic.level <= -2:
        return "a gap to work on — the interviewer stopped going deeper"
    return "as asked"


__all__ = [
    "DOWN_AT",
    "UP_AT",
    "WINDOW",
    "allowed_depth",
    "angle_for",
    "explain",
    "same_misconception",
    "selection_offset",
    "update",
]
