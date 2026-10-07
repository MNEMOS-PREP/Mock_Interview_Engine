"""Modes as configs of one engine — FR-6.8, spec §6.1's mode table.

Until day 9 the table was read from three places that each knew one column:
`planner.DEFAULT_PERSONA`, `outbox.ENSEMBLE_BY_MODE`, and a `final_boss`
check inside `hint_offer`. Three copies of one table is how a fourth mode
ships with hints in the button and none in the engine. This is the table,
once; everything else asks it.

**Modes are configs, not offsets on θ.** M05's `SelectionRequest` has no
difficulty field and M06 must not shift the provisional θ to fake one, so the
four modes differ in MECHANICS: who asks, whether hints exist, how the clock is
enforced, how many evaluators score the answer. `difficulty_offset` is carried
so the day M05 accepts it is one line, and is sent nowhere until then.

**What a mode may never change** is the standard (AC-6.17): the payload M13
scores and the prompt the strategist judges. The one difference that reaches
M13 is `ensemble`, which is a COUNT of evaluators — M13's own note is "drops
the count, never the tier" — and the report says so.

**The summaries are shown to a student choosing a mode**, so each one names
only mechanics this engine enforces today. A mode that promises
"interruptions" and cannot interrupt is a promise the session breaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import Mode, SegmentKind
from .panel import Temperament, lead_for


@dataclass(frozen=True)
class ModeConfig:
    id: Mode
    label: str
    #: One sentence for the setup card. Mechanics only, and only true ones.
    summary: str
    #: FR-6.7. Whether any hint is offered in this mode.
    hints: bool
    #: What the student is told when they reach for one and there is none.
    no_hints_reason: str | None
    #: M13's ensemble configuration, by name (M13 `ensemble.py`). A COUNT of
    #: evaluators, never a different bar — see `test_fairness.py`.
    ensemble: str
    #: EC-6.9 / §6.4's time-overrun trigger: how far past its budget a round
    #: may run before the clock forces the move. 25%, and 0% in Final Boss.
    overrun_allowance: float
    #: §2.2's pace check at 70%: Practice OFFERS to narrow and changes
    #: nothing; the other modes narrow.
    pacing_enforced: bool
    #: §15.4's proposal: a retry is allowed in Practice only, and only the
    #: first attempt is scored.
    retry_allowed: bool
    #: What kind of panel this mode is, as numbers (FR-6.3; `panel.py`).
    #: Who sits on it is decided from the personas' own data — a table of
    #: names here was one posting behind the day it was written.
    temperament: Temperament = field(
        default_factory=lambda: Temperament(target={"warmth": 0.5}, bounds={})
    )
    #: A sentence the plan preview shows about who is asking, when it is not
    #: what the mode's name suggests (Real-drive until M15 can match).
    persona_note: str | None = None
    #: FR-6.20 — off everywhere until M13 serves a `push_back` rubric.
    steelman_enabled: bool = False
    steelman_rate: float = 0.0
    #: §6.1: sent only once M05 accepts `difficulty_offset`. Carried so that
    #: day is one line, and read by nothing until then.
    difficulty_offset: float = 0.0

    def persona_for(self, kind: SegmentKind | str = "default") -> str:
        """The panel's lead — who opens, closes, and speaks when a plan names
        nobody. Each part's own interviewer is `panel.assign`'s to choose."""
        return lead_for(self.temperament)


MODES: dict[str, ModeConfig] = {
    "practice": ModeConfig(
        id="practice",
        label="Practice",
        summary=(
            "A gentle interviewer, hints on, and a retry if you want another go. Each answer is "
            "checked once rather than three times — less precise, never more generous."
        ),
        hints=True,
        no_hints_reason=None,
        ensemble="n1_practice",
        overrun_allowance=0.25,
        pacing_enforced=False,
        retry_allowed=True,
        # Warm and patient, never pushy: whoever sits on this panel.
        temperament=Temperament(
            target={"warmth": 0.9, "patience": 0.9, "follow_up_aggression": 0.4},
            bounds={
                "warmth": (0.7, 1.0),
                "patience": (0.75, 1.0),
                "follow_up_aggression": (0.0, 0.6),
            },
        ),
        difficulty_offset=-0.3,
    ),
    "mock": ModeConfig(
        id="mock",
        label="Mock",
        summary=(
            "A realistic panel: a lead who opens and closes, someone who knows each part, a "
            "professor if you include your projects, HR for the people questions. Hints cost "
            "what the evaluator publishes."
        ),
        hints=True,
        no_hints_reason=None,
        ensemble="n3_het_v1",
        overrun_allowance=0.25,
        pacing_enforced=True,
        retry_allowed=False,
        # A methodical lead; experts join for the parts they know.
        temperament=Temperament(
            target={"warmth": 0.55, "patience": 0.65, "follow_up_aggression": 0.85},
            bounds={"follow_up_aggression": (0.3, 1.0)},
        ),
    ),
    "real_drive": ModeConfig(
        id="real_drive",
        label="Real drive",
        summary=(
            "As Mock, with a brisker technical interviewer. Matching the panel to a company's own "
            "style arrives with the company guide."
        ),
        hints=True,
        no_hints_reason=None,
        ensemble="n3_het_v1",
        overrun_allowance=0.25,
        pacing_enforced=True,
        retry_allowed=False,
        # As Mock, and brisker: a brisk lead and nobody coddling — but a real
        # drive's HR round has its HR partner, so the bounds admit one.
        temperament=Temperament(
            target={"warmth": 0.45, "patience": 0.5, "follow_up_aggression": 0.85},
            bounds={"follow_up_aggression": (0.25, 1.0), "warmth": (0.0, 0.85)},
        ),
        persona_note=(
            "Company-matched interviewers need the company guide (M15), which does not cover "
            "this posting yet — this is the standard drive panel."
        ),
    ),
    "final_boss": ModeConfig(
        id="final_boss",
        label="Final Boss",
        summary=(
            "No hints, a hard clock with no overrun, and an interviewer who keeps going until your "
            "reasoning runs out. Harder, never ruder."
        ),
        hints=False,
        no_hints_reason="Final Boss runs without hints.",
        ensemble="n3_het_v1",
        overrun_allowance=0.0,
        pacing_enforced=True,
        retry_allowed=False,
        # Never warm, never gentle — harder by mechanics, never by manner.
        temperament=Temperament(
            target={"warmth": 0.3, "patience": 0.4, "follow_up_aggression": 1.0},
            bounds={"warmth": (0.0, 0.5), "follow_up_aggression": (0.6, 1.0)},
            weight=0.6,
        ),
        difficulty_offset=0.8,
    ),
}

#: M13's ensemble per mode. Derived, so it cannot disagree with the table.
ENSEMBLE_BY_MODE: dict[str, str] = {mode: config.ensemble for mode, config in MODES.items()}


def mode_config(mode: str | None) -> ModeConfig:
    """The config for `mode`. An unknown mode runs as Mock, never as an error."""
    return MODES.get(mode or "", MODES["mock"])


__all__ = ["ENSEMBLE_BY_MODE", "MODES", "ModeConfig", "mode_config"]
