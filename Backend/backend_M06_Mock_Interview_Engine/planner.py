"""The interview plan, assembled from M02's — FR-6.1, spec §6.1.

**No model call happens here, and that is the point.** Revision 1 built this
with a frontier-model call, which contradicted Trap 1 (the model would decide
the structure) and cost ~2.5 s of a 4 s bootstrap budget. Everything below is
arithmetic over what four modules already said.

**M06 adds to M02's plan; it never re-allocates it** (Trap 8). M02 priced each
round — minutes, question count, which requirements it covers — against the
whole ontology and the student's coverage debt. Re-deriving any of that here
would be a second planner disagreeing with the first one, silently, and the
coverage ledger would then be keyed to allocations nobody made.

So M06 does exactly four things M02 cannot:

  * **reserves** the warm-up and the closing out of the budget BEFORE asking
    M02 to price anything, so the plan M02 returns already fits;
  * **drops** what this session cannot serve — a coding round with no M07, a
    segment no available rubric can fill — and says why, in the preview and
    to M02's ledger as `skipped`;
  * **resolves** each round's requirements to the concept ids M05 selects on;
  * **orders** the result and names each segment in the student's words.

Two vocabularies meet here and must not be confused (spec §5). M02's
`round_type` is a MODALITY — `verbal`, `coding`, `design`, priced at 3.5, 12
and 20 minutes a question. M05's and M13's `round_type` is a RUBRIC —
`dsa_verbal`, and whatever else is authored. A segment carries both: the
modality decides whether this session can run it at all, the rubric decides
what M13 scores the answers against.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from . import panel
from .contracts import InterviewPlan, Mode, PlannedSegment, SegmentKind
from .modes import ModeConfig, mode_config

#: What M06 can actually run today. `coding` needs M07 and `design` needs
#: M08's canvas; neither exists, so a round priced for one is dropped rather
#: than quietly served as conversation — a student told "talk me through your
#: solution" has not had a coding round.
SERVABLE_MODALITIES = frozenset({"verbal"})

#: Why a modality is not servable, in the student's words. Keyed by M02's
#: vocabulary so an unknown one still gets a sentence.
MODALITY_BLOCKED = {
    "coding": "The coding round isn't built yet, so this part is left out.",
    "design": "The system-design round isn't built yet, so this part is left out.",
}

#: The closing is reserved: never dropped by a re-plan or by the clock
#: (FR-6.17). §6.1 gave it five minutes flat, which was a third of a
#: 15-minute interview spent on "any questions for me?" (2026-10-07). It is
#: now 10% of the session, between two minutes and five.
CLOSING_MINUTES = 5.0
CLOSING_MIN_MINUTES = 2.0
CLOSING_SHARE = 0.10

#: `min(4, 10% of budget)` — §6.1. One question, to get the student talking.
WARMUP_MAX_MINUTES = 4.0
WARMUP_SHARE = 0.10

#: What one verbal question costs, its follow-ups included. §6.5 said 3.5
#: minutes, which made a 15-minute interview two questions and a warm-up;
#: the student asked for five to seven (2026-10-07), and a campus panel's
#: pace is nearer two. M02 prices at the same figure, so a plan built from a
#: job description holds as many questions as one built without.
MINUTES_PER_VERBAL_QUESTION = 2.0

#: A part of a mixed interview has to be long enough to be a part: fewer
#: than this many questions and it is a sampler, not a round.
MIN_QUESTIONS_PER_PART = 3

#: M02's measurement modes that make a round behavioural rather than
#: technical. The distinction is which module scores it, not how it is asked.
BEHAVIOURAL_MODES = frozenset({"behavioural", "communication"})

#: A claim is one question with its own probe ladder behind it, priced like
#: any other verbal question.
MINUTES_PER_CLAIM = MINUTES_PER_VERBAL_QUESTION

#: §6.1: the project segment's minutes come from the largest verbal segment,
#: never from the closing. It must not eat that segment either — a session
#: that was 14 minutes of SQL should not become 4 minutes of SQL because the
#: resume had three shaky lines on it.
MAX_PROJECT_SHARE = 0.5

#: M01 bands a claim. These are the ones worth defending: a claim nobody
#: doubts is a question nobody learns from.
DEFENDABLE_BANDS = frozenset({"risky", "vague"})


@dataclass(frozen=True)
class PlanInputs:
    """Everything the assembly reads. All of it already decided elsewhere."""

    session_id: uuid.UUID
    mode: Mode
    requested_minutes: int
    jd_id: uuid.UUID | None = None
    #: M02's `CoveragePlan`, exactly as returned. None when there is no JD or
    #: M02 could not be reached — the two are different and §10 says so.
    coverage: dict[str, Any] | None = None
    #: requirement_id -> M02's requirement, for `concept_ids` and `measured_by`.
    requirements: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Rubric round types M05 answered for at plan time (§6.1 step 5). Empty
    #: means M05 could not be asked; that is not the same as "nothing to ask".
    available_round_types: tuple[str, ...] = ()
    #: M01's risky or vague claims. A project segment exists only if there is
    #: at least one (day 6).
    claims: tuple[dict[str, Any], ...] = ()
    #: M13's published hint credit for the round type this session will use.
    #: Frozen here so the price quoted is the price paid (§32.5).
    hint_penalty: dict[int, float] = field(default_factory=dict)
    #: What the student asked to practise, from the skill graph's bottleneck.
    focus_concepts: tuple[str, ...] = ()
    focus_label: str | None = None
    #: The track the student picked (2026-10-07). When set, it is the only
    #: round type offered as `available_round_types`; here it names the plan.
    track: str | None = None
    #: M05's `/v1/bank/tracks`, by round type: what each is called (`title`)
    #: and who runs it (`kind`). Empty when M05 could not say.
    tracks: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Whether the student opted in to resume questions, and from which one.
    resume_included: bool = False
    resume_id: uuid.UUID | None = None
    #: Who the student met in their last few interviews (`store.recent_
    #: panelists`): they stand back, so the next panel is someone else.
    recent_personas: frozenset[str] = frozenset()


def reserved_minutes(requested_minutes: int) -> tuple[float, float]:
    """`(warmup, closing)` — taken off the top, before M02 prices anything."""
    warmup = min(WARMUP_MAX_MINUTES, round(requested_minutes * WARMUP_SHARE, 1))
    closing = min(
        CLOSING_MINUTES, max(CLOSING_MIN_MINUTES, round(requested_minutes * CLOSING_SHARE, 1))
    )
    return warmup, closing


def minutes_for_m02(requested_minutes: int) -> int:
    """What to ask M02 to price. A plan that already fits needs no trimming,
    and trimming M02's allocations afterwards is re-allocating them."""
    warmup, closing = reserved_minutes(requested_minutes)
    return max(1, int(requested_minutes - warmup - closing))


# ─────────────────────────────────────────────────────────────────────────
#  Naming and classifying one of M02's rounds
# ─────────────────────────────────────────────────────────────────────────


def _requirement_texts(inputs: PlanInputs, requirement_ids: list[str]) -> list[str]:
    texts = []
    for rid in requirement_ids:
        text = (inputs.requirements.get(rid) or {}).get("text")
        if text:
            texts.append(str(text))
    return texts


def _title(inputs: PlanInputs, requirement_ids: list[str], fallback: str) -> str:
    """The segment's name, in the posting's own words.

    Not "Technical Round 1": the student is about to be asked about SQL, and
    the plan preview is the one screen where saying so costs nothing.
    """
    texts = _requirement_texts(inputs, requirement_ids)
    if not texts:
        return fallback
    if len(texts) == 1:
        return texts[0]
    if len(texts) == 2:
        # "SQL and DBMS" reads better than a comma — but not when a
        # requirement is already called "Data structures and algorithms".
        joiner = ", " if any(" and " in text for text in texts) else " and "
        return joiner.join(texts)
    return f"{texts[0]}, {texts[1]} and {len(texts) - 2} more"


def _kind(inputs: PlanInputs, requirement_ids: list[str]) -> SegmentKind:
    """Behavioural when every requirement is measured that way, else technical.

    A round with one behavioural requirement among four technical ones is a
    technical round that happens to ask about teamwork; calling it behavioural
    would change which persona runs it.
    """
    modes: set[str] = set()
    for rid in requirement_ids:
        modes.update((inputs.requirements.get(rid) or {}).get("measured_by") or [])
    return "behavioural" if modes and modes <= BEHAVIOURAL_MODES else "technical"


def _concepts(inputs: PlanInputs, requirement_ids: list[str]) -> list[str]:
    """The concept ids M05 selects on — M02 resolved these against the same
    ontology, so there is nothing to translate."""
    found: list[str] = []
    for rid in requirement_ids:
        for concept in (inputs.requirements.get(rid) or {}).get("concept_ids") or []:
            if concept not in found:
                found.append(str(concept))
    return found


#: A picked track the bank had nothing in for this student. The sentence the
#: plan screen shows on the part, and what to do about it.
TRACK_UNSERVED = (
    "The question bank had nothing in this track it could ask you right now, so this "
    "part is left out. Pick another track, or add a job description."
)


def _blocked(inputs: PlanInputs, modality: str) -> str | None:
    """Why this round cannot run, or None. The sentence a student reads."""
    if modality not in SERVABLE_MODALITIES:
        return MODALITY_BLOCKED.get(
            modality, f"The {modality} round isn't built yet, so this part is left out."
        )
    if not inputs.available_round_types:
        # M05 could not be asked, or answered 409 for every round type. Rule 2:
        # the session narrows, and the reason is not an empty list nobody reads.
        return "The question bank had nothing for this topic, so it was left out."
    return None


# ─────────────────────────────────────────────────────────────────────────
#  Assembly
# ─────────────────────────────────────────────────────────────────────────


def assemble(inputs: PlanInputs) -> InterviewPlan:
    """M02's plan, plus what only M06 knows. Deterministic; no model call.

    Each segment gets a panelist (FR-6.3, `panel.py`): the persona whose
    declared expertise and temperament best fit that part in this mode, from
    the persona files — so a mock is a panel (a methodical lead, a professor
    for the project, HR for the people questions) because of who those
    personas ARE, not because a table says so. The lead opens and closes,
    because a closing run by someone the student has not met is a page load.
    """
    warmup_minutes, closing_minutes = reserved_minutes(inputs.requested_minutes)
    mode = mode_config(inputs.mode)
    middle = (
        _from_coverage(inputs, mode)
        if inputs.coverage
        else _without_a_job_description(inputs, mode, warmup_minutes, closing_minutes)
    )
    claims = defendable(inputs.claims) if inputs.resume_included else []
    project = _project_segment(claims, mode, middle)
    if project is not None:
        # §6.1's order: warm-up, then the student's own work, then the
        # posting's. Defending your resume first is the gentler ramp and it
        # is also the part a student is most able to talk about cold.
        middle = [project, *middle]

    segments: list[PlannedSegment] = [
        PlannedSegment(
            index=0,
            kind="warmup",
            title="Warm-up",
            persona_id=mode.persona_for("warmup"),
            minutes=warmup_minutes,
            question_budget=1,
            rubric_round_types=list(inputs.available_round_types),
            rationale="One question to get talking before anything counts.",
        ),
        *middle,
        PlannedSegment(
            index=0,
            kind="closing",
            title="Your questions",
            persona_id=mode.persona_for("closing"),
            minutes=closing_minutes,
            question_budget=0,
            rationale="Time for you to ask, and for the report to be put together.",
            is_reserved=True,
        ),
    ]
    for index, segment in enumerate(segments):
        segment.index = index
    # FR-6.3: the panel, seated from the personas' own data for the parts
    # this plan actually has (`panel.py`) — not a table per mode. Rotated by
    # the session, and away from who the student met last time (2026-10-07).
    rotation = {"seed": str(inputs.session_id), "recent": inputs.recent_personas}
    assignment = panel.assign(
        segments, mode.temperament, inputs.requested_minutes, **rotation
    )
    for segment, persona_id in zip(segments, assignment, strict=True):
        segment.persona_id = persona_id
    # Everyone the opening introduces: the lead, whoever runs a part, and
    # anyone sitting in on what would otherwise be a panel of one.
    sitting = panel.sit_in(
        segments, assignment, mode.temperament, inputs.requested_minutes, **rotation
    )
    lead = assignment[0]  # the warm-up's: the lead opens
    seated = list(dict.fromkeys([lead, *assignment, *([sitting] if sitting else [])]))

    coverage = inputs.coverage or {}
    return InterviewPlan(
        id=uuid.uuid4(),
        session_id=inputs.session_id,
        mode=inputs.mode,
        total_minutes=inputs.requested_minutes,
        segments=segments,
        coverage_plan=inputs.coverage,
        coverage_plan_version=coverage.get("plan_version"),
        jd_id=inputs.jd_id,
        hint_penalty=dict(inputs.hint_penalty),
        claims=list(claims),
        uncovered=[str(u) for u in coverage.get("uncovered") or []],
        panel=seated,
        track=inputs.track,
        resume_included=inputs.resume_included,
        resume_id=inputs.resume_id,
    )


def defendable(claims: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The claims worth a project segment: risky or vague, with probes —
    spread across the resume rather than taken in M01's order.

    A claim M01 could not write probes for is one M06 has no question for,
    and inventing one here would be the model deciding what to ask about
    somebody's resume — which is M01's job and it already did it.

    The order matters because the segment asks the first few. M01 lists
    claims as they appear, so a resume whose first project has four shaky
    lines was questioned on that project alone (2026-10-07: "only from 1
    particular project"). Now each pick prefers a section, then a subject,
    not yet asked about; riskier first within that.
    """
    shaky = [
        claim
        for claim in claims
        if str(claim.get("risk_band")) in DEFENDABLE_BANDS and claim.get("probes")
    ]
    shaky.sort(key=lambda c: -float(c.get("risk_score") or 0.0))
    ordered: list[dict[str, Any]] = []
    sections: set[str] = set()
    subjects: set[str] = set()

    def staleness(claim: dict[str, Any]) -> tuple[bool, bool]:
        section = str(claim.get("section_id") or "")
        topics = {str(c) for c in claim.get("subject_concepts") or []}
        return (section in sections, bool(topics) and topics <= subjects)

    while shaky:
        pick = min(shaky, key=staleness)  # stable: the riskiest of the freshest
        shaky.remove(pick)
        ordered.append(pick)
        sections.add(str(pick.get("section_id") or ""))
        subjects.update(str(c) for c in pick.get("subject_concepts") or [])
        if all(str(c.get("section_id") or "") in sections for c in shaky):
            sections.clear()  # every section has had a turn; go round again
    return ordered


def _project_segment(
    claims: list[dict[str, Any]], mode: ModeConfig, middle: list[PlannedSegment]
) -> PlannedSegment | None:
    """§6.1 — only when M01 has something worth defending, and it is paid for
    out of the largest verbal segment rather than out of the closing."""
    if not claims:
        return None
    payer = max(
        (s for s in middle if s.dropped_reason is None and s.question_budget > 0),
        key=lambda s: s.minutes,
        default=None,
    )
    wanted = len(claims) * MINUTES_PER_CLAIM
    if payer is None:
        # No verbal segment to take it from. The project segment is then the
        # interview, which is what a session with no JD and a shaky resume
        # should be.
        minutes = wanted
    else:
        minutes = min(wanted, round(payer.minutes * MAX_PROJECT_SHARE, 1))
        payer.minutes = round(payer.minutes - minutes, 1)
        if not payer.requirement_ids:
            # A round M06 priced itself (no job description) is re-priced for
            # the minutes it has left, or it promises questions its clock
            # cannot hold. M02's rounds keep M02's count (Trap 8).
            payer.question_budget = max(1, int(payer.minutes // MINUTES_PER_VERBAL_QUESTION))
    budget = max(1, int(minutes // MINUTES_PER_CLAIM))
    return PlannedSegment(
        index=0,
        kind="project",
        title="Your projects",
        persona_id=mode.persona_for("project"),
        minutes=minutes,
        question_budget=min(budget, len(claims)),
        source="m01_claims",
        rationale=(
            "Lines from the resume you chose that an interviewer would push on. "
            "Not scored — M13 scores questions from the bank."
        ),
    )


def _from_coverage(inputs: PlanInputs, mode: ModeConfig) -> list[PlannedSegment]:
    """One segment per M02 round, in M02's order, at M02's prices."""
    segments: list[PlannedSegment] = []
    for planned in (inputs.coverage or {}).get("rounds") or []:
        requirement_ids = [str(r) for r in planned.get("requirement_ids") or []]
        modality = str(planned.get("round_type") or "verbal")
        kind = _kind(inputs, requirement_ids)
        segments.append(
            PlannedSegment(
                index=0,
                kind=kind,
                title=_title(inputs, requirement_ids, fallback=modality.title()),
                persona_id=mode.persona_for(kind),
                # M02's arithmetic, carried over rather than recomputed.
                minutes=float(planned.get("minutes") or 0.0),
                question_budget=int(planned.get("question_count") or 0),
                requirement_ids=requirement_ids,
                concept_ids=_concepts(inputs, requirement_ids),
                rubric_round_types=list(inputs.available_round_types),
                rationale=_rationale(inputs, requirement_ids),
                dropped_reason=_blocked(inputs, modality),
            )
        )
    return segments


def _rationale(inputs: PlanInputs, requirement_ids: list[str]) -> str:
    """M02 wrote one per requirement; the segment shows the first it has."""
    wanted = set(requirement_ids)
    for allocation in (inputs.coverage or {}).get("allocations") or []:
        if str(allocation.get("requirement_id")) in wanted and allocation.get("rationale"):
            return str(allocation["rationale"])
    return ""


def _without_a_job_description(
    inputs: PlanInputs, mode: ModeConfig, warmup: float, closing: float
) -> list[PlannedSegment]:
    """§10: no JD, so the session is what M05 can fill — split evenly, and
    labelled, because a student must not think this was tailored to a job."""
    available = inputs.available_round_types
    usable = max(0.0, inputs.requested_minutes - warmup - closing)
    if not available:
        if inputs.track is None:
            return []
        # The track the student picked, and the bank could not serve them in
        # it (M05's 409 on the probe): the part stays on the plan, left out,
        # with the reason — not a fifteen-minute interview that is quietly a
        # warm-up and a goodbye (2026-10-08).
        return [
            PlannedSegment(
                index=0,
                kind=_track_kind(inputs, inputs.track),
                title=round_type_title(inputs.track, inputs.tracks),
                persona_id=mode.persona_for("technical"),
                minutes=round(usable, 1),
                question_budget=0,
                rubric_round_types=[inputs.track],
                rationale="The track you picked.",
                dropped_reason=TRACK_UNSERVED,
            )
        ]
    if inputs.focus_concepts:
        # "Practise Recursion" means recursion: the segment's concepts become
        # M05's coverage debt, which is what steers selection toward items
        # that measure them. One segment, all the usable time.
        label = inputs.focus_label or ", ".join(
            c.split(":")[-1].replace("_", " ") for c in inputs.focus_concepts
        )
        return [
            PlannedSegment(
                index=0,
                kind="technical",
                title=f"Focus: {label}",
                persona_id=mode.persona_for("technical"),
                minutes=round(usable, 1),
                question_budget=max(1, int(usable // MINUTES_PER_VERBAL_QUESTION)),
                concept_ids=list(inputs.focus_concepts),
                rubric_round_types=list(available),
                rationale=(
                    # Neutral about WHERE the choice came from: Today's
                    # bottleneck, the skill graph's Learn panel and the notes'
                    # "practise again" all send a focus, and only one of them
                    # is a bottleneck.
                    f"You chose to practise {label}, so every question in this part is on it."
                ),
            )
        ]
    # A mixed interview (no track picked): as many parts as the time holds
    # at MIN_QUESTIONS_PER_PART each — splitting fifteen minutes nine ways
    # is nine one-question samplers. WHICH parts is seeded by the session,
    # so two mixed interviews in a row are not the same two rounds.
    room = max(1, int(usable // (MIN_QUESTIONS_PER_PART * MINUTES_PER_VERBAL_QUESTION)))
    chosen = (
        list(available)
        if len(available) <= room
        else sorted(available, key=lambda rt: uuid.uuid5(inputs.session_id, rt).hex)[:room]
    )
    each = usable / len(chosen)
    return [
        PlannedSegment(
            index=0,
            kind=_track_kind(inputs, round_type),
            title=round_type_title(round_type, inputs.tracks),
            persona_id=mode.persona_for("technical"),
            minutes=round(each, 1),
            question_budget=max(1, int(each // MINUTES_PER_VERBAL_QUESTION)),
            rubric_round_types=[round_type],
            rationale=(
                "The track you picked. Not tailored to a job description — add one and the "
                "plan follows it."
                if inputs.track is not None
                else "Not tailored to a job description — add one and the plan follows it."
            ),
        )
        for round_type in chosen
    ]


def _track_kind(inputs: PlanInputs, round_type: str) -> SegmentKind:
    """Who runs a track's part: M05's `kind` for it. Behavioural brings the
    HR side of the panel (`panel.py`); anything else is technical."""
    kind = (inputs.tracks.get(round_type) or {}).get("kind")
    return "behavioural" if kind == "behavioural" else "technical"


def round_type_title(round_type: str, tracks: dict[str, dict[str, Any]] | None = None) -> str:
    """`dsa_verbal` is an id, not a title. M05 names its tracks
    (`/v1/bank/tracks`); without that, the honest guess: the id split on its
    separators, short parts left upper-case because they are acronyms."""
    title = ((tracks or {}).get(round_type) or {}).get("title")
    if title:
        return str(title)
    parts = round_type.replace("-", "_").split("_")
    return " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in parts)


def live_segments(plan: InterviewPlan) -> list[PlannedSegment]:
    """The segments that will actually run. A dropped one keeps its place in
    the plan, with its reason — "I changed the plan here because…" needs the
    before as much as the after."""
    return [s for s in plan.segments if s.dropped_reason is None]


def skipped_requirements(plan: InterviewPlan) -> list[str]:
    """Requirement ids owed to M02's ledger as `skipped` (FR-6.24): planned,
    then dropped, so no turn will ever reach them."""
    out: list[str] = []
    for segment in plan.segments:
        if segment.dropped_reason is not None:
            out.extend(r for r in segment.requirement_ids if r not in out)
    return out


__all__ = [
    "BEHAVIOURAL_MODES",
    "DEFENDABLE_BANDS",
    "MAX_PROJECT_SHARE",
    "MINUTES_PER_CLAIM",
    "defendable",
    "CLOSING_MINUTES",
    "MINUTES_PER_VERBAL_QUESTION",
    "MIN_QUESTIONS_PER_PART",
    "MODALITY_BLOCKED",
    "SERVABLE_MODALITIES",
    "WARMUP_MAX_MINUTES",
    "PlanInputs",
    "assemble",
    "live_segments",
    "minutes_for_m02",
    "reserved_minutes",
    "round_type_title",
    "skipped_requirements",
]
