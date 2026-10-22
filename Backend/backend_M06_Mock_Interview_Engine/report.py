"""The session report — FR-6.18, the Phase 1 version (spec §15.7).

Built from the event log alone, so it exists for every session that has one:
ended, aborted, or crashed half-way (AC-6.1). M19 will project the same events
into the real report; this one is deleted when that ships.

What it does NOT contain yet is any score. M13's evaluations arrive on day 4,
and even then `display_numeric` is false everywhere until calibration is
fitted — so the honest Phase 1 report is the ladder: what was asked, how far
each question went, where it stopped, and why a turn was not scored.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from .contracts import (
    DRAFT_NOT_SCORED,
    JUDGED_CATEGORIES,
    M05_OWNED,
    MISCONCEIVED,
    SessionStatus,
)
from .items import expected_statements, shorten
from .models import SessionEvent
from .modes import mode_config
from .personas import persona
from .state import SessionState

#: §10 "Everything fails": what was still queued when the session failed.
VOIDED = "Not scored — the session failed on our side, so it doesn't count."
#: EC-6.1: the student moved on after a silence, so there was no answer.
MOVED_ON = "We moved on from this one after a pause, so there was nothing to score."
#: 2026-10-07: skips. The first at a question's number is replaced and costs
#: nothing; the second at the same number is left, and counts.
SKIPPED_REPLACED = "You skipped this one, so a different question was asked in its place."
SKIPPED_LEFT = (
    "You skipped this one too, so it counts as not answered in this interview. "
    "Your skill graph is unchanged: a skip isn't evidence either way."
)

#: A resume question in a mock: not a drill, so it is not called one.
RESUME_NOT_SCORED = (
    "A question about your own resume — not scored: only questions from the bank have a "
    "rubric to mark against."
)

NOT_SCORED = {
    "m01_probe": "Practice drill — drills are not scored yet.",
    "m05_fallback": (
        "Asked from the question bank's short backup list when nothing else fitted, so it was "
        "not scored."
    ),
    "local_fallback": (
        "Asked from the backup set while the question bank was offline, so it was not scored."
    ),
    "template": "Not a scored question.",
    "m05_draft": DRAFT_NOT_SCORED,
}

WARM_UP_SHARE = 0.25

#: Consent lives in M04, so when M04 is absent its own degradation sentence
#: already tells the student the session will not count. See `notes` below.
CONSENT_OWNER = "M04"


class Exchange(BaseModel):
    role: str
    text: str
    move: str | None = None
    depth: int = 0
    #: The answer's turn — where M11 keeps its audio, when the student chose
    #: to keep it (FR-11.19), so the notes can play it beside the words.
    turn_id: str | None = None
    #: §15.4: part of a Practice retry — shown, and never the scored attempt.
    retry: bool = False


class Feedback(BaseModel):
    """M13's words about an answer, per dimension — never its numbers (§2.2;
    M13's display gate holds those until they agree with human raters)."""

    dimension: str
    reasoning: str = ""
    #: Key points the answer did not reach.
    missing: list[str] = Field(default_factory=list)
    #: The student's own sentences that counted, verified against the text.
    quotes: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One thing the interview found in an answer, in the student's words."""

    said: str
    #: Why it is wrong, or what it does not fit with.
    why: str = ""


class QuestionReport(BaseModel):
    question: str
    source: str
    scored: bool
    not_scored_reason: str | None = None
    #: `not_scored` · `queued` (with M13) · `scored` — never a number. M13 owns
    #: the number and the gate that decides whether anyone may see it, and
    #: today that gate is closed everywhere because no calibration is fitted.
    scoring_status: str = "not_scored"
    exchanges: list[Exchange] = Field(default_factory=list)
    depth_reached: int = 0
    #: The rung where the reasoning stopped holding. None means it never did.
    break_depth: int | None = None
    #: Two clears in a row at depth ≥ 4 — the student was stretched and held.
    ceiling: int | None = None
    hints_used: int = 0
    #: What a strong answer covers. Shown only once the session is over.
    strong_answer_covers: list[str] = Field(default_factory=list)
    #: Who asked it (FR-6.3) — a panel is several people, and the notes say
    #: which of them this was.
    asked_by: str | None = None
    #: §15.4: the student took a Practice retry on this one. The first
    #: attempt is the one scored; the retry is recorded beside it.
    retried: bool = False
    #: EC-6.1: after a silence, the interviewer offered to move on and the
    #: student took it. Not a break and not a fail — nothing was answered.
    moved_on: bool = False
    #: 2026-10-07: the student skipped it — `replaced` (another question at
    #: the same number, nothing against them), `left` (the second skip at a
    #: number: counted as not answered), or `follow_up` (moved on from a
    #: follow-up after answering).
    skipped: str | None = None
    #: What M13 said about the answer, once it has scored it and the session
    #: is over. Mid-session it would be a live verdict (§2.2).
    feedback: list[Feedback] = Field(default_factory=list)
    #: The concept the item measures, so the notes can offer "practise this
    #: topic again" as a focused interview rather than a generic one.
    concept_id: str | None = None
    #: The item's own name for its topic, when it has one.
    topic: str | None = None
    #: The first answer's turn — what M13's evidence page (`/turns/{id}`)
    #: is keyed on, so "how was this marked?" is one link.
    turn_id: str | None = None
    # ── 2026-10-22: what the interview found, question by question ──────────
    #: All of these are the interview's own reading, filled once the session
    #: is over (mid-session they would be a live verdict, §2.2). M13's words
    #: are `feedback`; these say what happened in the conversation.
    #: What the answers got right, in a few words each.
    went_well: list[str] = Field(default_factory=list)
    #: What was wrong: the student's own words, and why.
    went_wrong: list[Finding] = Field(default_factory=list)
    #: Claims with nothing behind them, in their words.
    unsupported: list[str] = Field(default_factory=list)
    #: Statements that did not fit together: (earlier, now).
    contradictions: list[Finding] = Field(default_factory=list)
    #: `self` — they caught their own mistake; `prompted` — after the
    #: interviewer pushed back, gave a hint or asked something simpler.
    corrected: str | None = None
    #: How the question was left (`ladder.Outcome.left`), and in words.
    outcome: str | None = None
    outcome_words: str | None = None
    #: The misunderstanding left standing, if one was.
    misconception: str | None = None
    #: How the interviewer decided, in order — "pushed back on an error",
    #: "went one level deeper" — so the follow-ups have their reasons.
    how_it_went: list[str] = Field(default_factory=list)
    #: One strong answer (M05's reference answer) — *a* good answer, not the
    #: only one. `reviewed` is False for a drafted question nobody has checked.
    one_strong_answer: str | None = None
    strong_answer_reviewed: bool = True
    #: What to study next, specific to what was missed.
    study: list[str] = Field(default_factory=list)
    #: The student's last attempt at this question, compared (`memory`).
    last_time: str | None = None
    #: The library's key and marks, for the notes' star.
    question_key: str | None = None
    starred: bool = False
    flagged: bool = False
    #: For a line of the student's resume: whether they backed it up — what
    #: they showed they understand, against what the line claims.
    claim_check: str | None = None


class Summary(BaseModel):
    """The whole interview in a few lines — built from the questions above and
    nothing else, so it can never say something they do not."""

    held: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    corrected: list[str] = Field(default_factory=list)
    repeated_misconceptions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    #: How each topic went, from its level (`difficulty.py`).
    topics: list[str] = Field(default_factory=list)
    #: How it was said (`delivery.py`): fillers, restarts, pace.
    communication: list[str] = Field(default_factory=list)


class SessionReport(BaseModel):
    session_id: str
    kind: str
    mode: str
    status: SessionStatus
    end_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    minutes_used: float
    minutes_planned: int
    framing: str
    questions: list[QuestionReport]
    #: FR-6.21: what the student asked the interviewer, in their words.
    #: Recorded, not scored — there is no rubric for a question yet.
    your_questions: list[str] = Field(default_factory=list)
    #: §6.4: "I changed the plan here because…" — each re-plan's reason, in
    #: full, now that the session is over and it can no longer be a tell.
    plan_changes: list[str] = Field(default_factory=list)
    notes: list[str]
    #: 2026-10-22: the interview in a few lines, from the questions above.
    summary: Summary = Field(default_factory=Summary)
    #: Spec §6.7 tells M06 to say this, "so students don't think Practice mode
    #: inflates their score" — which means it has to be exactly right, not
    #: reassuring. Two facts, and the second one was missing: the STANDARD is
    #: identical (same rubric, same blind payload, same model tier — gated by
    #: `test_fairness.py`), and the PRECISION is not, because Practice runs
    #: M13's `n1_practice`: one evaluator rather than three. Saying only the
    #: first half lets a student read a Practice result as a mock-grade one.
    persona_note: str = (
        "The interviewer's manner never changes the standard: a friendly interviewer and a "
        "bar-raiser judge the same answer against the same rubric. Practice checks each "
        "answer once rather than three times, so it is less precise — not more generous."
    )


def _framing(state: SessionState, now: datetime) -> str:
    used = state.time_used_s(now)
    planned = state.requested_minutes * 60
    if state.end_reason == "system_failure":
        # §10 "Everything fails": the honest version, said once.
        return (
            "This one's on us — something on our side stopped working, so this session "
            "doesn't count. Here's what we got through before it did."
        )
    if state.status is SessionStatus.aborted:
        return "This session didn't get going, so there is nothing to review yet."
    if state.end_reason == "conduct":
        # EC-6.4. Neutral: it says what happened, not what the student is.
        return "This session ended early. Here's what was covered before it did."
    if state.kind == "drill":
        return "A two-minute drill on one line from your resume. Not scored — it's practice."
    if state.end_reason == "ended_by_student" and planned and used < WARM_UP_SHARE * planned:
        # EC-6.10: framed as a warm-up, not a failure.
        return "A short warm-up. Nothing here counts against you — come back for a full session."
    if not state.is_final:
        return "This interview is still in progress."
    return "Here's how each question went."


def _asked_by(state: SessionState, segment_index: int | None) -> str | None:
    if state.plan is None or segment_index is None:
        return None
    segment = next((s for s in state.plan.segments if s.index == segment_index), None)
    if segment is None:
        return None
    who = persona(segment.persona_id)
    return f"{who.name}, {who.title}"


#: The verbs in front of a point ("uses chaining", "mentions chaining"): the
#: same point, worded by two decisions, listed twice in a live run's notes.
_REPORTING = frozenset(
    "use uses used mention mentions mentioned name names named state states stated "
    "describe describes described explain explains explained note notes noted".split()
)


def _gist(point: str) -> frozenset[str]:
    """A point's content words, for telling one point said twice."""
    return frozenset(
        w for w in re.findall(r"[a-z0-9]+", point.lower()) if len(w) > 2 and w not in _REPORTING
    )


def _label(question: QuestionReport) -> str:
    if question.topic and not question.topic.startswith(("fb_", "hashing_", "claim:")):
        # A resume line can be long: cut at a word, for a summary to read —
        # and its own full stop dropped, or "…in pytest.: the basics held".
        label = shorten(question.topic.replace("_", " "), 60)
        return label if label.endswith("…") else label.rstrip(" .;:,")
    if question.concept_id and not question.concept_id.startswith("claim:"):
        return question.concept_id.split(":", 1)[-1].replace("_", " ")
    words = question.question.split()
    return " ".join(words[:9]) + ("…" if len(words) > 9 else "")


def _study(question: QuestionReport, missing: list[str], key_points: dict[str, str]) -> list[str]:
    """What to practise next — specific to what this question showed."""
    out: list[str] = []
    if question.misconception:
        out.append(f"Revisit the idea behind this: {question.misconception}.")
    for kp in missing[:2]:
        statement = key_points.get(kp)
        if statement:
            out.append(f"Be ready to cover: {statement.rstrip('.')}.")
    if question.unsupported and question.source == "m01_probe":
        out.append("For each claim, prepare the number, the baseline and how you measured it.")
    elif question.unsupported:
        # Not a resume line: a statement made without the reason it holds.
        out.append(
            "Say why each statement holds — the mechanism or the evidence, not only the conclusion."
        )
    if question.outcome == "gap:surface":
        out.append("Practise explaining the mechanism step by step, not just naming it.")
    return out


def _claim_check(question: QuestionReport) -> str | None:
    """A resume line, judged on what the student showed about it: the claim
    is theirs; whether they could stand behind it is what the room heard."""
    if question.contradictions:
        return "Your answers about this line did not fit together — settle the story first."
    if question.unsupported or question.outcome == "unsupported":
        return "This line stayed unsupported: you claimed it, but did not show how you know."
    if question.outcome in ("held", "ceiling"):
        return "You backed this line up: what you said showed you did and understood the work."
    if question.outcome and question.outcome.startswith("gap:"):
        return "You could not yet defend this line in depth — expect it to be pushed on."
    return None


def _summary(
    state: SessionState, questions: list[QuestionReport], deliveries: list | None = None
) -> Summary:
    """From the questions above, the topics' own levels and how the answers
    were said — nothing else."""
    from . import delivery, difficulty  # noqa: PLC0415 — report is imported early by the router

    out = Summary(communication=delivery.summarise(deliveries or []))
    for q in questions:
        label = _label(q)
        if q.outcome in ("held", "ceiling") or (q.went_well and not q.went_wrong and not q.outcome):
            out.held.append(label)
        elif q.outcome in memory_difficult():
            gap = f"{label}: {(q.outcome_words or q.outcome or '').lower()}"
            out.gaps.append(f"{gap} — {q.misconception}" if q.misconception else gap)
        if q.corrected:
            how = "yourself" if q.corrected == "self" else "after the interviewer pushed back"
            out.corrected.append(f"{label}: corrected {how}")
        out.unsupported_claims.extend(q.unsupported)
    # A topic is named as its questions are: a resume line's topic is its
    # claim's id, and a live summary read "0ac8493e-…: a real gap" (2026-10-23).
    names = {q.concept_id: _label(q) for q in questions if q.concept_id}
    for topic in state.topics.values():
        out.repeated_misconceptions.extend(topic.repeated)
        if topic.level:
            name = names.get(topic.concept_id) or (
                topic.concept_id.split(":", 1)[-1].replace("_", " ")
            )
            out.topics.append(f"{name}: {difficulty.explain(topic)}")
    return out


def memory_difficult() -> frozenset[str]:
    from .memory import DIFFICULT  # noqa: PLC0415

    return DIFFICULT


def build(
    state: SessionState,
    events: list[SessionEvent],
    now: datetime,
    *,
    history: dict[str, list] | None = None,
    marks: dict[str, tuple[bool, bool]] | None = None,
) -> SessionReport:
    """`history`: the student's attempts at each question, by library key
    (`memory.attempts_for`); `marks`: (starred, flagged) by the same key."""
    from .memory import OUTCOME_WORDS, compare, question_key  # noqa: PLC0415

    questions: list[QuestionReport] = []
    current: QuestionReport | None = None
    final = state.is_final
    # Per question: its item, and the key points its last judged answer missed.
    items: dict[int, dict] = {}
    missing: dict[int, list[str]] = {}

    by_turn: dict[str, QuestionReport] = {}
    deliveries: list = []
    for event in sorted(events, key=lambda e: e.seq):
        p = event.payload
        if event.kind == "delivery.noted":
            deliveries.append(_delivery_of(p))
            continue
        if event.kind == "evaluation.completed":
            entry = by_turn.get(str(p.get("turn_id")))
            if entry is not None and final:
                entry.feedback.extend(Feedback.model_validate(f) for f in p.get("feedback") or [])
            continue
        if event.kind == "question.asked" and p.get("question_source") == "closing":
            # FR-6.21: the closing is not one of our questions. Its answers
            # are the student's own, and are listed on their own below.
            current = None
            continue
        if event.kind == "question.asked" and p.get("retry") and current is not None:
            # §15.4: the same question again, on the same entry — the notes
            # show both attempts together, and the first stays the scored one.
            current.retried = True
            current.exchanges.append(
                Exchange(role="interviewer", text=p.get("text", ""), retry=True)
            )
            continue
        if event.kind == "question.asked":
            if p.get("new_question", p.get("probe_move") is None) or current is None:
                item = p.get("item") or {}
                source = p.get("question_source") or "template"
                scored = bool(p.get("rubric_round_type")) and source in M05_OWNED
                current = QuestionReport(
                    question=item.get("stem") or p.get("text", ""),
                    source=source,
                    scored=scored,
                    not_scored_reason=None
                    if scored
                    else (
                        RESUME_NOT_SCORED
                        if source == "m01_probe" and state.kind != "drill"
                        else NOT_SCORED.get(source, NOT_SCORED["template"])
                    ),
                    strong_answer_covers=(
                        [kp["statement"] for kp in item.get("key_points", [])]
                        or expected_statements(item.get("expects"))
                    )
                    if final
                    else [],
                    asked_by=_asked_by(state, p.get("segment_index")),
                    concept_id=item.get("concept_id"),
                    topic=item.get("label"),
                    question_key=question_key(
                        item.get("question_id") or p.get("question_id"),
                        item.get("full_stem") or item.get("stem") or p.get("text", ""),
                    ),
                )
                questions.append(current)
                items[id(current)] = item
            current.exchanges.append(
                Exchange(
                    role="interviewer",
                    text=p.get("text", ""),
                    move=p.get("probe_move"),
                    depth=int(p.get("probe_depth") or 0),
                )
            )
            current.depth_reached = max(current.depth_reached, int(p.get("probe_depth") or 0))
        elif event.kind == "answer.received" and current is not None:
            by_turn[str(p.get("turn_id"))] = current
            retry_turn = state.turn_retry(p.get("turn_id"))
            if current.turn_id is None and not retry_turn and p.get("turn_id"):
                current.turn_id = str(p["turn_id"])
            current.exchanges.append(
                Exchange(
                    role="candidate",
                    text=p.get("text", ""),
                    retry=retry_turn,
                    turn_id=str(p["turn_id"]) if p.get("turn_id") else None,
                )
            )
            if current.scored and not retry_turn:
                # One evaluation per question since 2026-10-22, keyed by its
                # first answer: `queued` until M13 has it, then its status.
                # Either way, no number appears here.
                current.scoring_status = state.evaluation_status.get(
                    str(current.turn_id), "queued"
                )
        elif event.kind == "probe.decided" and current is not None:
            if p.get("break_depth") is not None:
                current.break_depth = int(p["break_depth"])
            if p.get("ceiling") is not None:
                current.ceiling = int(p["ceiling"])
            # 2026-10-22: what each answer was, and why the move followed.
            if p.get("reason"):
                current.how_it_went.append(str(p["reason"]))
            # Only an answer that was judged says anything about what they
            # know here. An answer to another question, a request or a remark
            # is not one — whatever the model wrote beside it: a live run's
            # notes told a student their "thinking aloud" story showed an
            # algorithmic complexity misunderstanding (2026-10-23).
            judged = p.get("category") is None or p["category"] in JUDGED_CATEGORIES
            for point in (p.get("correct_points") or []) if judged else []:
                if _gist(point) not in {_gist(said) for said in current.went_well}:
                    current.went_well.append(point)
            if p.get("error_quote") and p.get("category") in ("incorrect", "partial", "vague"):
                current.went_wrong.append(
                    Finding(said=str(p["error_quote"]), why=str(p.get("error_note") or ""))
                )
            unsupported = p.get("unsupported_quote") if judged else None
            if unsupported and unsupported not in current.unsupported:
                current.unsupported.append(str(unsupported))
            if judged and p.get("contradiction_quote"):
                current.contradictions.append(
                    Finding(
                        said=str(p.get("error_quote") or ""), why=str(p["contradiction_quote"])
                    )
                )
            if p.get("corrected"):
                # Help once needed stays needed — and a session recorded
                # before 2026-10-23 may carry a later "self" that undid it.
                if current.corrected != "prompted":
                    current.corrected = str(p["corrected"])
                current.misconception = None
            if p.get("misconception") and (
                p.get("category") is None or p["category"] in MISCONCEIVED
            ):
                current.misconception = str(p["misconception"])
            if p.get("left"):
                current.outcome = str(p["left"])
            if p.get("missing") is not None:
                missing[id(current)] = [str(k) for k in p["missing"]]
        elif event.kind == "hint.given" and current is not None:
            current.hints_used = int(p.get("level", current.hints_used))
        elif event.kind == "question.skipped" and current is not None:
            if p.get("follow_up"):
                current.skipped = "follow_up"
                continue
            current.skipped = "replaced" if p.get("replaced") else "left"
            if not any(e.role == "candidate" for e in current.exchanges):
                current.scored = False
                current.scoring_status = "not_scored"
                current.not_scored_reason = (
                    SKIPPED_REPLACED if p.get("replaced") else SKIPPED_LEFT
                )
        elif event.kind == "idle.moved_on" and current is not None and not p.get("closing"):
            current.moved_on = True
            if not any(e.role == "candidate" for e in current.exchanges):
                current.scored = False
                current.scoring_status = "not_scored"
                current.not_scored_reason = MOVED_ON

    if state.end_reason == "system_failure":
        for question in questions:
            if question.scoring_status != "scored":
                question.scored = False
                question.scoring_status = "not_scored"
                question.not_scored_reason = VOIDED
    for question in questions:
        item = items.get(id(question)) or {}
        if question.skipped and not question.outcome:
            question.outcome = "skipped"
        elif question.moved_on and not question.outcome:
            question.outcome = "silence"
        if not final:
            # Mid-session every one of these is a live verdict or the answer
            # key (§2.2): they wait for the end, like `strong_answer_covers`.
            question.went_well, question.went_wrong, question.unsupported = [], [], []
            question.contradictions, question.how_it_went = [], []
            question.corrected = question.misconception = question.outcome = None
            continue
        question.outcome_words = OUTCOME_WORDS.get(question.outcome or "")
        if item.get("reference_answer"):
            question.one_strong_answer = str(item["reference_answer"])
            question.strong_answer_reviewed = question.source != "m05_draft"
        key_points = {kp["id"]: kp["statement"] for kp in item.get("key_points") or []}
        question.study = _study(question, missing.get(id(question), []), key_points)
        if question.source == "m01_probe":
            question.claim_check = _claim_check(question)
        if history and question.question_key in history:
            question.last_time = compare(history[question.question_key])
        if marks and question.question_key in marks:
            question.starred, question.flagged = marks[question.question_key]
    notes = list(dict.fromkeys(state.flags.degraded.values()))
    # A student is told a consequence once. M04 owns consent, so when M04 is
    # absent its degradation sentence is already the whole story; adding this
    # one underneath reads like a second, separate problem.
    if (
        state.kind != "drill"
        and state.flags.consent_id is None
        and state.started_at is not None
        and CONSENT_OWNER not in state.flags.degraded
    ):
        notes.append("This session didn't update your skill graph — consent isn't recorded yet.")
    if any(q.scoring_status == "queued" for q in questions):
        notes.append("Some answers are still with the evaluator — check back in a minute.")
    if any(q.scored for q in questions):
        notes.append(
            "Each answer's band is the share of a strong answer's key points it covered. "
            "Numerical scores appear once they are calibrated against human raters."
        )
    replaced = sum(1 for q in questions if q.skipped == "replaced")
    left = sum(1 for q in questions if q.skipped == "left")
    if replaced or left:
        said = [f"{replaced} {'was' if replaced == 1 else 'were'} replaced with another question"]
        if left:
            said.append(
                f"{left} {'was' if left == 1 else 'were'} skipped a second time and "
                f"{'counts' if left == 1 else 'count'} as not answered"
            )
        total = replaced + left
        notes.append(f"You skipped {total} question{'s' if total != 1 else ''}: {'; '.join(said)}.")
    if any(q.retried for q in questions):
        notes.append("Where you took another go, the first attempt is the one that was scored.")
    spoken_in = sorted(
        {
            t.language
            for t in state.transcript
            if t.role == "candidate" and t.language and t.language != "english"
        }
    )
    if spoken_in:
        # M11's EC-11.10: noted, never penalised.
        names = " and ".join(language.capitalize() for language in spoken_in)
        notes.append(
            f"You answered partly in {names}. It was written down as you said it and "
            "scored on what you said — never on the language."
        )
    if state.flags.inputs_flagged:
        # EC-6.6. Said once, plainly: part of an answer read as instructions
        # to the system, so it was set aside rather than judged.
        notes.append(
            "Part of one of your answers read as instructions to the system rather than an "
            "answer, so that part was set aside and the rest was judged as usual."
        )
    mode_note = mode_config(state.mode).persona_note
    if mode_note and state.kind != "drill":
        notes.append(mode_note)
    if state.closing_questions:
        notes.append(
            "Your questions for the interviewer are in these notes but not scored — there is "
            "no rubric for a question yet, and the real panel is who can answer them."
        )
    plan_changes = (
        [r.student_sentence for r in state.plan.replans] if state.plan is not None and final else []
    )

    return SessionReport(
        session_id=str(state.session_id),
        kind=state.kind,
        mode=state.mode,
        status=state.status,
        end_reason=state.end_reason,
        started_at=state.started_at,
        ended_at=state.ended_at,
        minutes_used=round(state.time_used_s(now) / 60, 1),
        minutes_planned=state.requested_minutes,
        framing=_framing(state, now),
        questions=questions,
        your_questions=list(state.closing_questions),
        plan_changes=plan_changes,
        notes=notes,
        summary=_summary(state, questions, deliveries) if final else Summary(),
    )


def _delivery_of(p: dict):
    from .delivery import Delivery  # noqa: PLC0415

    return Delivery(
        words=int(p.get("words") or 0),
        fillers={str(k): int(v) for k, v in (p.get("fillers") or {}).items()},
        repeats=int(p.get("repeats") or 0),
        restarts=int(p.get("restarts") or 0),
        wpm=p.get("wpm"),
        spoken=bool(p.get("spoken")),
    )


__all__ = ["Exchange", "Finding", "QuestionReport", "SessionReport", "Summary", "build"]
