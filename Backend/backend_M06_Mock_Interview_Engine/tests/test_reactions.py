"""How the interviewer says what the answer decided (2026-10-22) — units.

The guard's tones, `Interviewer.react`'s refusals, the authored fallbacks, and
one question at a time (`decompose.py`). No engine here: the whole loop is
`test_answer_types.py`.
"""

from __future__ import annotations

import pytest

from backend_M06_Mock_Interview_Engine import decompose
from backend_M06_Mock_Interview_Engine.agents.guard import leaks, names_a_point, screen
from backend_M06_Mock_Interview_Engine.agents.interviewer import (
    Interviewer,
    opener,
    reaction_template,
)
from backend_M06_Mock_Interview_Engine.contracts import Move
from backend_M06_Mock_Interview_Engine.items import Item, KeyPoint
from backend_M06_Mock_Interview_Engine.phrasebook import REACTION_TONE, REACTIONS
from backend_M06_Mock_Interview_Engine.projection import InterviewerView

from .stubs import StubLLM

ITEM = Item(
    stem="Why is average-case lookup in a hash map O(1), and what has to be true for that to hold?",
    source="m05_bank",
    concept_id="concept:hashing",
    key_points=(
        KeyPoint("kp1", "States that the key is hashed to a bucket index rather than scanned for."),
        KeyPoint("kp2", "Names uniform distribution or a bounded load factor as a condition."),
    ),
    reference_answer=(
        "The key is hashed to a bucket index, so you go straight to a slot instead of scanning."
    ),
)
VIEW = InterviewerView(move="challenge", persona_register="neutral", max_words=26)


# ── the guard's tones ────────────────────────────────────────────────────


def test_a_challenge_may_doubt_and_may_not_praise():
    assert screen("I'm not sure that's right — can you look at it again?", "challenge").ok
    assert screen("That isn't quite correct. What happens to the order?", "challenge").ok
    assert screen("You're right about the index, but why is it constant?", "challenge").ok
    assert not screen("Excellent, but is that right?", "challenge").ok
    assert not screen("You're wrong. Try again?", "challenge").ok, "never a verdict on the person"


def test_a_line_after_an_answer_that_held_may_assent_and_may_not_doubt():
    assert screen("Right. What happens when the table fills up?", "credit").ok
    assert screen("That makes sense. Why does resizing help?", "credit").ok
    assert not screen("Not quite. Why does resizing help?", "credit").ok
    assert not screen("Perfect answer! What next?", "credit").ok


def test_a_neutral_line_says_nothing_about_the_answer_either_way():
    assert not screen("That's correct. Next?", "neutral").ok
    assert not screen("I'm not convinced. Next?", "neutral").ok
    assert screen("What goes wrong when every key collides?", "neutral").ok, (
        "a system going wrong is a failure question, not a verdict"
    )


def test_every_authored_reaction_passes_the_guard_in_its_own_tone():
    for register, table in REACTIONS.items():
        for key, lines in table.items():
            tone = REACTION_TONE[key]
            for line in lines:
                said = line.format(
                    focus="it is constant time",
                    credit="the bucket part",
                    other="it was stateless",
                    topic="hashing",
                    asked="Why?",
                )
                assert screen(said, tone).ok, (register, key, said, screen(said, tone).reason)


def test_a_line_that_repeats_the_answer_key_is_caught():
    key = [kp.statement for kp in ITEM.key_points]
    assert leaks("Is it that the key is hashed to a bucket index?", key, allowed=[ITEM.stem])
    assert not leaks("What decides which bucket a key goes to?", key, allowed=[ITEM.stem])
    said = "I said the key is hashed to a bucket index"
    assert not leaks(
        "You said the key is hashed to a bucket index — why does that help?", key, allowed=[said]
    ), "the student's own words are theirs to hear back"


# ── react(): the model phrases, the decision decides ─────────────────────


def _react(probe: str, move: Move, *, openers=()):
    llm = StubLLM(probe=probe)
    said = Interviewer(llm).react(
        ITEM,
        move,
        view=VIEW,
        name="Ananya",
        last_answer="It is always constant time, whatever the keys.",
        asked=ITEM.stem,
        openers=list(openers),
        answer_key=ITEM.answer_key,
    )
    return said, llm


CHALLENGE = Move(
    kind="challenge", focus="always constant time", tone="challenge", severity="material"
)


def test_a_challenge_is_phrased_by_the_model_when_its_line_holds():
    said, llm = _react("Always constant, whatever the keys? What if they all collide?", CHALLENGE)
    assert said.source == "model"
    system = llm.stream_calls[0]["system"]
    assert "always constant time" in system and "real error" in system


def test_praise_in_a_challenge_falls_back_to_the_authored_line_with_their_words():
    said, _ = _react("Excellent answer, but are you sure?", CHALLENGE)
    assert said.source == "template"
    assert "always constant time" in said.text


def test_an_opener_used_just_now_is_not_used_again():
    said, _ = _react("Hmm, okay. What if every key collides?", CHALLENGE, openers=["hmm okay"])
    assert said.source == "template"
    assert opener(said.text) != "hmm okay"


LIVE_ANSWER = (
    "Because the hash function gives you the index directly, so you just go to that slot "
    "in the array and get the value. That is why it is constant time."
)


def test_a_line_that_names_a_missed_point_in_its_own_words_is_caught():
    """Live, 2026-10-29: the follow-up named the very point the student had
    missed, with no five words of it in a row — so it passed."""
    points = [kp.statement for kp in ITEM.key_points]
    allowed = [ITEM.stem, LIVE_ANSWER]
    live = (
        "What assumptions about the hash function’s distribution and the table’s load factor "
        "are necessary to keep collisions rare enough that the expected lookup stays constant?"
    )
    assert names_a_point(live, points, allowed) == "load factor"
    for scenario in (
        "What if every key landed in the same bucket?",
        "What decides which bucket a key goes to?",
        "What happens to that lookup as you keep inserting into a fixed-size table?",
        "Is there any input where that constant time breaks down?",
    ):
        assert names_a_point(scenario, points, allowed) is None, scenario
    said = "I think the load factor has to stay bounded."
    assert names_a_point("Why does a bounded load factor matter?", points, [*allowed, said]) is None


class _Retrying(StubLLM):
    """A model whose second line is not its first."""

    def __init__(self, *lines: str):
        super().__init__(probe=lines[0])
        self.lines = list(lines)

    def stream(self, *, job, system, user):
        self.probe = self.lines[min(len(self.stream_calls), len(self.lines) - 1)]
        yield from super().stream(job=job, system=system, user=user)


RUNG = Move(kind="rung", depth=1, angle="mechanism", tone="credit")


def _rung(llm):
    tokens: list[str] = []
    said = Interviewer(llm).react(
        ITEM,
        RUNG,
        view=VIEW,
        name="Ananya",
        last_answer=LIVE_ANSWER,
        asked=ITEM.stem,
        answer_key=ITEM.answer_key,
        on_token=tokens.append,
    )
    return said, "".join(tokens)


def test_a_line_that_gives_the_answer_away_is_tried_once_more_before_the_template():
    """The stable-sort follow-up, live: the guard caught the model's line and
    the student heard the stock "What is actually happening underneath that
    makes it work?" — a question that ignored what they had just said."""
    llm = _Retrying(
        "Right. And what about the load factor, how does it keep lookups constant?",
        "Right. What happens to that lookup as you keep inserting into a fixed-size table?",
    )
    said, preview = _rung(llm)
    assert said.source == "model"
    assert said.text.endswith("fixed-size table?")
    assert said.retried is not None and said.call is not None, "both calls are on the ledger"
    assert "load factor" in llm.stream_calls[1]["system"], "told what it named"
    assert "load" not in preview, "the leak never reached the preview, not even its first word"
    assert preview.startswith("Right. And what about"), "what was clean was shown"


def test_twice_giving_it_away_is_the_authored_line():
    llm = _Retrying("So is it the load factor that keeps it constant?")
    said, preview = _rung(llm)
    assert said.source == "template" and said.fallback_reason.startswith("gives the answer away")
    assert len(llm.stream_calls) == 2
    assert "load factor" not in said.text and "load factor" not in preview


def test_a_line_that_gives_the_answer_away_falls_back():
    said, _ = _react(
        "Isn't it because the key is hashed to a bucket index rather than scanned?",
        Move(kind="probe_missing", other=ITEM.key_points[0].statement, tone="credit"),
    )
    assert said.source == "template"
    assert "hashed to a bucket index" not in said.text


def test_with_no_model_every_move_still_has_its_line():
    from backend_M06_Mock_Interview_Engine.llm import NullLLM

    for kind in (
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
    ):
        move = Move(kind=kind, focus="cut latency by 40%", other="it was stateless", text="Why?")
        said = Interviewer(NullLLM()).react(
            ITEM, move, view=VIEW, name="A", last_answer="x", asked="Why?", answer_key=[]
        )
        assert said.text.strip(), kind
        tone = "credit" if kind == "next_part" else move.tone
        assert screen(said.text, tone if kind != "confront" else "challenge").ok or kind in (
            "next_part",
        ), (kind, said.text)


def test_templates_never_open_the_way_the_interviewer_just_did():
    first, _ = reaction_template(
        Move(kind="give_time"), register="neutral", item=ITEM, asked="Why?", openers=[], seed="s"
    )
    second, _ = reaction_template(
        Move(kind="give_time"),
        register="neutral",
        item=ITEM,
        asked="Why?",
        openers=[opener(first)],
        seed="s",
    )
    assert opener(first) != opener(second)


# ── one question at a time ───────────────────────────────────────────────


TWO_PART = Item(
    stem=(
        "Walk me through how a hash map handles two keys landing in the same bucket, "
        "and what that costs you as the table fills up?"
    ),
    source="m05_bank",
    concept_id="concept:hashing",
    key_points=(
        KeyPoint("kp1", "Names chaining or open addressing."),
        KeyPoint("kp2", "Says lookups slow as the load factor grows."),
    ),
)
SPLIT = {
    "split": True,
    "primary": "Walk me through how a hash map handles two keys landing in the same bucket.",
    "primary_key_point_ids": ["kp1"],
    "parts": [
        {"text": "And what does that cost you as the table fills up?", "key_point_ids": ["kp2"]}
    ],
}


def test_a_comparison_is_one_question():
    assert not decompose.needs_split(
        "What is the difference between a process and a thread, and when would you use each one?"
    )


def test_a_joined_ask_is_found():
    assert decompose.needs_split(TWO_PART.stem)
    assert not decompose.needs_split("Why is lookup O(1)?")


def test_a_valid_split_is_used_and_cached(db):
    llm = StubLLM()
    llm.split = SPLIT
    split = decompose.for_item(db, TWO_PART, llm)
    assert split.stem == SPLIT["primary"]
    assert split.full_stem == TWO_PART.stem
    assert [p.text for p in split.parts] == ["And what does that cost you as the table fills up?"]
    assert split.parts[0].key_point_ids == ("kp2",)
    again = decompose.for_item(db, TWO_PART, llm)
    assert again == split
    assert len(llm.split_calls) == 1, "worked out once, then cached"


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        (
            {**SPLIT, "parts": [{"text": "And what does it cost.", "key_point_ids": []}]},
            "not a question",
        ),
        ({**SPLIT, "parts": [{"text": "Cost?", "key_point_ids": ["kp9"]}]}, "names a key point"),
        ({**SPLIT, "primary": "Hi?", "parts": [{"text": "Why?", "key_point_ids": []}]}, "lose"),
    ],
)
def test_a_split_that_fails_validation_is_not_used(db, bad, why):
    reason = decompose.valid(TWO_PART.stem, bad["primary"], bad["parts"], {"kp1", "kp2"})
    assert reason and why in reason
    llm = StubLLM()
    llm.split = bad
    assert decompose.for_item(db, TWO_PART, llm).parts == ()


def test_with_no_model_only_a_stem_of_several_questions_is_split(db):
    from backend_M06_Mock_Interview_Engine.llm import NullLLM

    several = Item(
        stem="What is a deadlock in an operating system? How would you prevent one from happening?",
        source="m05_bank",
    )
    split = decompose.for_item(db, several, NullLLM())
    assert split.stem == "What is a deadlock in an operating system?"
    assert [p.text for p in split.parts] == ["How would you prevent one from happening?"]
    joined = decompose.for_item(db, TWO_PART, NullLLM())
    assert joined.parts == (), "a joined ask needs the model to rewrite its second half"
