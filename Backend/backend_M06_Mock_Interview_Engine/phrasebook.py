"""The interviewer's fixed lines — spec §6.5, §3.2.3, §2.2.

Structural moves are templated, never generated (spec §6.2): the graceful
exit, the bridge between segments, the time warnings, the close. Two reasons.
They are on the hot path, and a template costs nothing. And they are the lines
that must NEVER say "wrong", "incorrect" or "you should know this" — copy
nobody generates is copy nobody has to police. No line praises an answer
mid-session either: "that's a solid way to think about it" telegraphs a
verdict as surely as "wrong" does (Trap 6).

One table per register. A persona (`personas/*.yaml`) chooses a register and
may override individual lines — its own greeting, its own exit — and every
override is screened at load by the same guard as everything else here, so a
persona file with a telegraphing or rude line fails the boot rather than a
session. Every string here is the string that ships (plan_in_depth README:
"microcopy in the docs is the actual string to ship").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Register = Literal["friendly", "neutral", "bar_raiser"]


@dataclass(frozen=True)
class Lines:
    greeting: str
    first_question_lead: str
    next_question_lead: str
    graceful_exit: str
    ceiling_exit: str
    moving_on: str
    clarify: str
    redirect: str
    answer_briefly: str
    defer_to_report: str
    drill_open: str
    drill_close: str
    session_close: str
    time_up: str
    #: §3.2.3 — the line between two rounds. Trap: "the transition between
    #: rounds is where immersion breaks. A hard cut from DSA to HR feels like
    #: a page load." It costs nothing and it matters a lot, so it is authored
    #: rather than generated, like every other structural move.
    bridge: str
    #: `bridge` plus what is coming next, which is the segment's own title —
    #: M02's words for the requirement, so "Let's switch gears. Next: SQL."
    bridge_to: str
    #: The bridge into the part where the student asks. There is no next
    #: topic to name, so it gets its own line.
    bridge_to_closing: str
    #: EC-6.4, the first time: one neutral redirect, then the question again.
    #: Neutral means it names no behaviour — "keep to the interview", never
    #: "that was inappropriate", which is a verdict on the student.
    redirect_conduct: str
    #: EC-6.4, the second time: the session ends, politely, and says what
    #: happens next rather than why.
    conduct_close: str
    #: §6.7: `interruption_threshold` in text mode — an over-long typed
    #: answer gets one "let's keep it moving" per round, not an interruption.
    keep_moving: str
    #: §6.7: `note_taking_cadence` — what a real interviewer says while
    #: writing. Realism only; it carries no information about the answer.
    note_taking: str
    #: §15.4, Practice only: after the graceful exit, the offer of another go.
    #: Said after the exit line, so it never reads as "that was wrong".
    retry_offer: str
    #: The question again, when the student takes the offer.
    retry_lead: str


LINES: dict[Register, Lines] = {
    "friendly": Lines(
        greeting="Hi — thanks for making the time. We'll keep this conversational.",
        first_question_lead="Let's start with something easy.",
        next_question_lead="Okay, here's the next one.",
        graceful_exit="That's fair — it's a detail people usually look up. Let's move on.",
        ceiling_exit="Thanks — that covers it. Let's move on.",
        moving_on="Thanks. Let's move on.",
        clarify="Could you say that a little differently? I want to make sure I follow.",
        redirect="I think that answers a slightly different question — let me put mine again.",
        answer_briefly="Good question — happy to talk about that at the end. Back to this one:",
        defer_to_report="I'll walk you through it in the report afterwards.",
        drill_open="Let's practise defending one line from your resume. Two minutes, no score.",
        drill_close="That's the drill. Your notes are ready.",
        session_close="That's time. Thanks — I'm putting your notes together now.",
        time_up="We're at time, so I'll stop us here.",
        bridge="Alright — let's switch gears.",
        bridge_to="Alright — let's switch gears. Next up: {topic}.",
        bridge_to_closing="That's everything I wanted to ask. Anything you'd like to ask me?",
        redirect_conduct="Let's keep this about the interview. Here's the question again:",
        conduct_close="I'm going to stop the interview here. Your notes cover what we got through.",
        keep_moving="Thanks — let's keep things moving.",
        note_taking="Let me jot that down.",
        retry_offer="Want another go at that one, or shall we move on?",
        retry_lead="Sure — take it from the top:",
    ),
    "neutral": Lines(
        greeting="Hello. Let's begin.",
        first_question_lead="First question.",
        next_question_lead="Next question.",
        graceful_exit="Okay, let's leave that there.",
        ceiling_exit="Okay. Let's move on.",
        moving_on="Okay. Let's move on.",
        clarify="Can you rephrase that?",
        redirect="That's a different question. Here's mine again.",
        answer_briefly="We can come back to that at the end. On this one:",
        defer_to_report="The report will walk through it.",
        drill_open="We'll go through one claim from your resume. Two minutes, not scored.",
        drill_close="That's the drill.",
        session_close="That's time. Your report is being prepared.",
        time_up="We're at time.",
        bridge="Let's move to the next part.",
        bridge_to="Let's move to the next part: {topic}.",
        bridge_to_closing="That's my questions. Do you have any for me?",
        redirect_conduct="Let's keep to the interview. The question again:",
        conduct_close="I'll stop the interview here. Your notes cover what we got through.",
        keep_moving="Let's keep it moving.",
        note_taking="Let me note that down.",
        retry_offer="Would you like to try that one again, or move on?",
        retry_lead="Okay. Again:",
    ),
    "bar_raiser": Lines(
        greeting="Let's get started.",
        first_question_lead="First.",
        next_question_lead="Next.",
        # The exits do not say "next": `next_question_lead` does, and a
        # bar-raiser saying "Alright. Next. Next." was heard in the first
        # live Final Boss (2026-09-30) — the register had never been spoken.
        graceful_exit="Alright.",
        ceiling_exit="Alright.",
        moving_on="Okay.",
        clarify="Say that again, more precisely.",
        redirect="That's not what I asked.",
        answer_briefly="Later. On this:",
        defer_to_report="The report covers it.",
        drill_open="One claim from your resume. Two minutes. Not scored.",
        drill_close="Done.",
        session_close="That's time. Report's being prepared.",
        time_up="Time.",
        bridge="Moving on.",
        bridge_to="Moving on. {topic}.",
        bridge_to_closing="That's my questions. Yours?",
        redirect_conduct="Let's stay on the interview. Again:",
        conduct_close="I'll stop here. Your notes cover what we got through.",
        keep_moving="Keep it moving.",
        note_taking="Noted.",
        retry_offer="Again, or move on?",
        retry_lead="Again:",
    ),
}

#: The rung names are the fallback when a question has no follow-up of its
#: own at that depth (spec §6.5). Phrased to be answerable about anything.
GENERIC_RUNGS: dict[int, str] = {
    1: "Can you say more about why that works?",
    2: "What is actually happening underneath that makes it work?",
    3: "What would change if that assumption stopped being true?",
    4: "Where else would you use the same idea?",
    5: "Where would that idea stop being the right choice?",
}

#: Words an interviewer line must never contain — they telegraph a verdict
#: (Trap 6, FR-6.15) or judge the student (§6.5). Checked by `guard.screen`.
TELEGRAPHS = (
    "correct",
    "incorrect",
    "wrong",
    "right answer",
    "exactly",
    "perfect",
    "great answer",
    "good answer",
    "good job",
    "well done",
    "nice work",
    "you should know",
    "obviously",
)


#: FR-6.9: "pressure via mechanics, never rudeness". Final Boss is harder
#: because of what it does — no hints, a hard clock, a deeper ladder — never
#: because of how it talks. These are the words that would make it the
#: second thing, checked on every persona line at load and on every model
#: line before it is said.
RUDE = (
    "stupid",
    "dumb",
    "idiot",
    "come on",
    "seriously?",
    "hurry up",
    "that's basic",
    "that is basic",
    "everyone knows",
    "waste of time",
    "pathetic",
    "ridiculous",
    "useless",
)


def lines(register: Register = "neutral") -> Lines:
    return LINES[register]


__all__ = ["GENERIC_RUNGS", "LINES", "RUDE", "TELEGRAPHS", "Lines", "Register", "lines"]
