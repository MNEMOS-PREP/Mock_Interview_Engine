"""How an answer was said (2026-10-22, the user's §7) — against realistic
answers, the thresholds, the cooldown, and the honesty about what text can
and cannot measure."""

from __future__ import annotations

from backend_M06_Mock_Interview_Engine import delivery

HABIT = (
    "So basically a hash map, basically, takes the key and basically runs it through a hash "
    "function, and basically that gives you an index into an array, and then you basically "
    "go straight to that slot instead of searching the whole thing, which is why it is fast "
    "on average."
)
NATURAL = (
    "A hash map runs the key through a hash function, which gives an index into an array of "
    "buckets. You go straight to that bucket instead of scanning, so lookup is constant time "
    "on average. Actually, that only holds while the keys spread evenly and the table is "
    "resized before it fills up."
)
LIKE_AS_VERB = (
    "I would like to use a hash map here, because it looks like the natural fit: the lookup "
    "is constant on average, and things like duplicate detection become a single pass over "
    "the data with a set, which I like for its simplicity and its predictable cost."
)
LIKE_AS_FILLER = (
    "So it's, like, you take the key, like, and you hash it, and, like, you get an index, "
    "and like, um, you go to that bucket and, like, check it, and that's like the whole "
    "thing really, it's constant time on average if the keys spread out nicely."
)
RESTARTS = (
    "The the lookup is, sorry, let me rephrase, the key is hashed to a bucket, no wait, the "
    "the hash gives an index, and I mean the index picks the bucket, sorry, the bucket then "
    "holds the entry, and you read it directly without scanning the rest of the table."
)


def test_a_habitual_filler_is_named_once():
    found = delivery.analyse(HABIT)
    assert found.fillers["basically"] == 5
    line = delivery.note(found)
    assert line is not None and "“basically”" in line and "5 times" in line


def test_a_natural_answer_with_a_filler_or_two_gets_nothing():
    found = delivery.analyse(NATURAL)
    assert found.filler_count <= 1
    assert delivery.note(found) is None


def test_like_as_a_verb_or_a_comparison_is_not_a_filler():
    assert delivery.analyse(LIKE_AS_VERB).fillers.get("like", 0) == 0
    assert delivery.analyse(LIKE_AS_FILLER).fillers["like"] >= 5


def test_a_short_answer_is_never_flagged():
    assert delivery.note(delivery.analyse("Basically, basically, basically linear.")) is None


def test_restarts_and_repeated_words_are_noted():
    found = delivery.analyse(RESTARTS)
    assert found.repeats >= 2 and found.restarts >= 3
    assert "restarts" in (delivery.note(found) or "")


def test_a_repeat_inside_a_garbled_stretch_is_the_recogniser_not_the_student():
    text = "The the key is hashed to a bucket and read directly from that bucket every time."
    clean = delivery.analyse(text, spoken=True, unsure=[(0, 7)])
    assert clean.repeats == 0


def test_pace_is_only_measured_when_the_room_says_how_long():
    assert delivery.analyse(NATURAL).wpm is None
    fast = delivery.analyse(NATURAL, spoken=True, duration_s=12)
    assert fast.wpm and fast.wpm > delivery.FAST_WPM
    assert "fast" in (delivery.note(fast) or "")


def test_the_note_waits_its_turn_and_only_live_modes_say_it():
    found = delivery.analyse(HABIT)
    assert delivery.live_note(found, mode="practice", answers_since_last=None)
    assert delivery.live_note(found, mode="practice", answers_since_last=1) is None
    assert delivery.live_note(found, mode="practice", answers_since_last=2)
    assert delivery.live_note(found, mode="final_boss", answers_since_last=None) is None


def test_the_summary_says_what_it_cannot_measure():
    lines = delivery.summarise([delivery.analyse(HABIT, spoken=True), delivery.analyse(NATURAL)])
    assert any("basically" in line for line in lines)
    assert any("under-counted" in line and "not measured" in line for line in lines)


def test_the_room_hears_the_note_and_the_cooldown_holds(db):
    """Through the engine: a habit noted once, then not on the very next answer."""
    import uuid

    from backend_M06_Mock_Interview_Engine import adapters, store
    from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
    from backend_M06_Mock_Interview_Engine.public import public_event

    from .stubs import BankQuestions, NoClaims, StubLLM, verdict

    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=StubLLM([verdict(category="correct")]),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        db, candidate_id=uuid.uuid4(), kind="mock", mode="practice", minutes=15
    )
    engine.start(row.id)
    engine.answer(row.id, engine.state(row.id).open_turn_id, HABIT)
    engine.answer(row.id, engine.state(row.id).open_turn_id, HABIT)
    noted = [e for e in store.events_for(db, row.id) if e.kind == "delivery.noted"]
    assert [bool(e.payload["note"]) for e in noted] == [True, False]
    shown = public_event(noted[0])
    assert set(shown["data"]) == {"for", "note"}, "the counts stay in the log"


#: A spoken answer as M11 writes it down since 2026-10-23, its fillers kept.
VOCAL = (
    "Um, so a hash map, uh, takes the key and, um, runs it through a hash function, uh, "
    "which gives an index into an array, and, um, you go straight to that bucket instead "
    "of, uh, searching the whole thing, so lookup is, um, constant time on average."
)


def test_um_and_uh_said_often_are_named_now_the_recogniser_keeps_them():
    """Whisper wrote none of them down, so they were never named; M11's prompt
    now keeps about two in three, inventing none (Voice_Engine research/fillers)."""
    said = delivery.analyse(VOCAL, spoken=True)
    assert said.fillers["um/uh"] == 7
    line = delivery.note(said)
    assert line and "7 “um”s and “uh”s" in line
    lines = delivery.summarise([said, delivery.analyse(VOCAL, spoken=True)])
    assert any("“um”/“uh” ×14" in line for line in lines)
    assert any("two in three" in line for line in lines)
