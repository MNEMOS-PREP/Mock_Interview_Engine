"""The rolling round summary — FR-6.16, spec §6.6.

The interviewer sees the last six turns. In a twenty-turn round that means
everything before turn fourteen is simply gone: the interviewer asks about
hashing again because it cannot remember asking, and a student who explained
something at turn three is asked to explain it at turn seventeen. §6.6's
answer is a ~300-token summary regenerated every four turns, which **replaces
the dropped turns** rather than being added to them — that is what keeps the
context a constant size instead of a growing one (AC-6.10).

**Extraction tier, off the hot path.** It runs in the background task that
already follows an answer, so it is ready for the next turn and costs that
turn nothing. A summary that is one cycle stale is a rolling summary working
as intended; a summary that delays the next question is a latency bug.

**It is as blind as the interviewer it feeds** (FR-6.15, AC-6.3). It reads
the transcript and nothing else — no verdicts, no bands, no θ — because
anything it could see, the interviewer can read back out of it.

**No model, no summary.** The fallback is an empty string, not a stitched-up
one: an interviewer told "the student discussed hashing" by a template that
does not know what was discussed is worse than one told nothing.

**And it goes through the same guard as every interviewer line.** The prompt
forbids judgement; `guard.screen` is what enforces it. One definition of a
word that gives the game away, applied to everything the interviewer can
read — a note saying "the candidate was incorrect on collisions" is dropped,
because the interviewer would read it back out (Trap 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..llm import JOB_SUMMARY, LLM, LLMResult
from .guard import screen

PROMPT_VERSION = "summary-1"

#: Every four turns, per §6.6. Cheap enough to be frequent, rare enough that
#: three quarters of turns pay nothing at all.
EVERY_N_TURNS = 4

#: ~300 tokens. The cap is in characters because that is what can be enforced
#: without a tokenizer, and it is the reason the context stays fixed: a
#: summary that grows with the session defeats the thing it exists for.
MAX_CHARS = 1200

SYSTEM = """You keep notes for an interviewer during a technical interview.

Write a short factual summary of what has been covered so far, for an
interviewer who will read it before asking the next question.

RULES
- Only what was actually said. Never infer, never fill gaps.
- Topics asked about, and in one clause what the candidate said about each.
- No judgement of any kind: not "well", "poorly", "struggled", "confidently",
  "correct" or "incorrect". You are recording what was discussed, not how it
  went. Another part of the system does that and this note must not pre-empt it.
- No advice about what to ask next.
- Under 120 words, plain sentences, no headings or bullets.
"""


@dataclass
class Summary:
    text: str
    call: LLMResult | None = None
    fallback_reason: str | None = None


def is_due(turns_since_last: int) -> bool:
    return turns_since_last >= EVERY_N_TURNS


def user_message(turns: list[Any]) -> str:
    lines = "\n".join(f"{t.role.upper()}: {t.text}" for t in turns)
    return f"TRANSCRIPT SO FAR:\n{lines}"


class Summariser:
    """§6.6's note-taker. One extraction call, or nothing."""

    def __init__(self, llm: LLM, *, enabled: bool = True):
        self.llm = llm
        self.enabled = enabled

    def write(self, turns: list[Any]) -> Summary:
        if not turns:
            return Summary("", fallback_reason="nothing to summarise")
        if not self.enabled:
            return Summary("", fallback_reason="summariser disabled (ablation)")
        if not self.llm.available:
            return Summary("", fallback_reason="no model configured")

        call = None
        for part in self.llm.stream(job=JOB_SUMMARY, system=SYSTEM, user=user_message(turns)):
            if isinstance(part, LLMResult):
                call = part
        if call is not None:
            call.prompt_version = PROMPT_VERSION
        if call is None or not call.ok:
            return Summary(
                "", call=call, fallback_reason=(call.reason if call else None) or "no summary"
            )
        text = (call.text or "").strip()
        if not text:
            return Summary("", call=call, fallback_reason="empty summary")
        checked = screen(text)
        if not checked.ok:
            # Dropped, not repaired: a note with the verdict edited out is
            # still a note written by something that was thinking about the
            # verdict, and six turns of context is a cheaper loss.
            return Summary("", call=call, fallback_reason=f"telegraphs: {checked.reason}")
        return Summary(text[:MAX_CHARS], call=call)


__all__ = ["EVERY_N_TURNS", "MAX_CHARS", "PROMPT_VERSION", "Summariser", "Summary", "is_due"]
