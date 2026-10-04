"""Personas as data — spec §6.7, Trap 7.

Trap 7 is "personas that are just adjectives in a prompt": "be strict" gives a
rude interviewer on one turn and a friendly one on the next. So every test here
is about a persona being a parameter vector with a mechanic behind each
parameter, and about the file being refused at load — at boot, not at minute
twenty — when it is wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend_M06_Mock_Interview_Engine import personas as personas_module
from backend_M06_Mock_Interview_Engine.agents.guard import screen
from backend_M06_Mock_Interview_Engine.contracts import DEPTH_CAP
from backend_M06_Mock_Interview_Engine.personas import (
    FALLBACK_PERSONA,
    PersonaError,
    load_personas,
    persona,
    personas,
)

#: §6.7's ship set, by name.
SHIP_SET = {
    "friendly_recruiter",
    "methodical_engineer",
    "impatient_senior",
    "professor",
    "bar_raiser",
    "startup_founder",
    "hr_generalist",
}


def _write(directory: Path, persona_id: str, **overrides) -> Path:
    """A valid persona file, with some fields replaced (or removed with None)."""
    base = dict(personas()[FALLBACK_PERSONA].model_dump(by_alias=True))
    base["id"] = persona_id
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    path = directory / f"{persona_id}.yaml"
    path.write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    return path


def _dir_with(tmp_path: Path, **overrides) -> Path:
    """A persona directory holding the fallback and one file under test."""
    _write(tmp_path, FALLBACK_PERSONA)
    _write(tmp_path, "under_test", **overrides)
    return tmp_path


# ── the ship set ──────────────────────────────────────────────────────────


def test_the_seven_personas_of_the_spec_all_load():
    assert set(personas()) == SHIP_SET


@pytest.mark.gate
def test_every_line_every_persona_can_say_passes_the_guard():
    """FR-6.9 as well as Trap 6: no persona line telegraphs a verdict, and no
    persona — Final Boss's included — says anything rude. Checked on the
    RESOLVED table, so a register line a persona inherits is checked too."""
    for p in personas().values():
        said = p.said()
        for name in personas_module.LINE_NAMES:
            text = getattr(said, name).replace("{topic}", "SQL")
            verdict = screen(text)
            assert verdict.ok, f"{p.id}.{name}: {verdict.reason} — {text!r}"


def _sentences(text: str) -> list[str]:
    return [s.strip().lower() for s in text.replace("?", ".").split(".") if s.strip()]


def test_no_transition_says_the_same_thing_twice():
    """The first live Final Boss said "Alright. Next. Next." — an exit line and
    a lead that both said "next", composed for the first time the day the
    bar-raiser register was actually spoken. Every exit, before every lead
    and every bridge, for every persona."""
    for p in personas().values():
        said = p.said()
        for exit_name in ("graceful_exit", "ceiling_exit", "moving_on", "keep_moving"):
            exit_line = getattr(said, exit_name)
            for follow in (
                said.next_question_lead,
                said.bridge_to.format(topic="SQL"),
                said.bridge,
                said.bridge_to_closing,
            ):
                parts = _sentences(f"{exit_line} {follow}")
                assert len(parts) == len(set(parts)), f"{p.id}: {exit_line!r} + {follow!r}"


def test_a_persona_introduces_itself_by_name():
    """A panel is people. Every persona but the terse ones says who it is."""
    for p in personas().values():
        assert p.name.split()[-1] in p.said().greeting, f"{p.id} greets without its name"


# ── refused at load, not at minute twenty ─────────────────────────────────


def test_a_missing_parameter_fails_the_load(tmp_path):
    """§6.7: "a persona file missing a parameter fails the boot, not the
    session". No defaults on the vector, so a missing one is not a silent 0.5."""
    with pytest.raises(PersonaError, match="patience"):
        load_personas(_dir_with(tmp_path, patience=None))


def test_a_line_that_telegraphs_fails_the_load(tmp_path):
    with pytest.raises(PersonaError, match="telegraphs"):
        load_personas(_dir_with(tmp_path, lines={"graceful_exit": "Exactly. Next."}))


def test_a_rude_line_fails_the_load(tmp_path):
    """FR-6.9: Final Boss is harder, never ruder — and the file is where a
    rude line would be written."""
    with pytest.raises(PersonaError, match="rude"):
        load_personas(_dir_with(tmp_path, lines={"moving_on": "Come on, that's basic. Next."}))


def test_an_unknown_line_name_fails_the_load(tmp_path):
    """A typo'd override is a line that silently never ships."""
    with pytest.raises(PersonaError, match="unknown line"):
        load_personas(_dir_with(tmp_path, lines={"greting": "Hello."}))


def test_a_bridge_that_does_not_name_the_topic_fails_the_load(tmp_path):
    with pytest.raises(PersonaError, match="topic"):
        load_personas(_dir_with(tmp_path, lines={"bridge_to": "Moving on."}))


def test_the_id_must_be_the_file_name(tmp_path):
    _write(tmp_path, FALLBACK_PERSONA)
    path = _write(tmp_path, "one_name")
    path.rename(tmp_path / "another_name.yaml")
    with pytest.raises(PersonaError, match="must equal the file name"):
        load_personas(tmp_path)


def test_an_out_of_range_parameter_fails_the_load(tmp_path):
    with pytest.raises(PersonaError, match="follow_up_aggression"):
        load_personas(_dir_with(tmp_path, follow_up_aggression=1.7))


# ── every parameter drives a mechanic ─────────────────────────────────────


def test_aggression_is_how_deep_the_ladder_goes():
    """§6.7: the ladder's depth is the persona's — and the experience, which
    may differ, never the standard, which may not (AC-6.17)."""
    depths = {p.id: p.max_depth for p in personas().values()}
    assert depths["bar_raiser"] == DEPTH_CAP
    assert depths["friendly_recruiter"] == 2
    assert depths["hr_generalist"] == 2
    assert all(2 <= d <= DEPTH_CAP for d in depths.values())
    ordered = sorted(personas().values(), key=lambda p: p.follow_up_aggression)
    assert [p.max_depth for p in ordered] == sorted(p.max_depth for p in ordered)


def test_patience_is_how_long_the_silence_is():
    """EC-6.1's 45 seconds is a persona with patience 0.4."""
    assert persona("bar_raiser").idle_after_s == 46
    assert persona("friendly_recruiter").idle_after_s > persona("impatient_senior").idle_after_s


def test_a_bar_raiser_gives_no_hints_and_a_recruiter_does():
    assert persona("bar_raiser").hints_available is False
    assert persona("friendly_recruiter").hints_available is True


def test_an_unknown_persona_falls_back_rather_than_crashing_a_live_session():
    """A plan names personas by id; a renamed file must not end an interview."""
    assert persona("no_such_persona").id == FALLBACK_PERSONA
    assert persona(None).id == FALLBACK_PERSONA


def test_the_card_a_browser_sees_carries_no_ladder_parameters():
    """The stage needs a name and a patience. It must not learn how deep this
    interviewer goes — that would tell a student when to stop trying."""
    card = persona("bar_raiser").card()
    assert "max_depth" not in card and "follow_up_aggression" not in card


def test_the_card_names_the_voice_the_browser_speaks_in():
    """Until M11 exists the browser reads each line aloud in the voice the
    persona file names, so the card carries it — authored, never guessed from
    a name — and every one of the seven is an Indian-English voice."""
    for p in personas().values():
        card = p.card()
        assert card["voice_id"] == p.voice_id
        locale, _, rest = card["voice_id"].partition("-IN-")
        assert locale == "en" and rest, card["voice_id"]


def test_a_voice_id_the_browser_cannot_read_fails_the_load(tmp_path):
    """`locale-voice-manner` or the boot refuses — not a session that falls
    silent at minute one because "a nice voice" names no voice."""
    with pytest.raises(PersonaError, match="voice_id"):
        load_personas(_dir_with(tmp_path, voice_id="a nice voice"))
