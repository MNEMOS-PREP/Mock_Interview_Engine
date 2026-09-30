"""The persona never changes the standard — spec §6.7, and a new gate.

§6.7 says it plainly: *"A friendly interviewer and a bar-raiser score the same
answer identically (blind evaluator, same rubric). Only the experience
differs. Say this in the report so students don't think Practice mode inflates
their score."* M06 has printed that sentence in every report since day 3.

**Nothing tested it.** There is no AC for it in spec §13, and day 9 ships
personas — the one feature able to break it. A promise the product makes to a
student, with no gate behind it, is the gap this file closes; the gate exists
before the feature it guards, because afterwards is too late.

What must be identical, and what may differ:

  * **identical** — the payload M13 scores, and the input the strategist
    judges. The strategist's verdict becomes an M05 θ observation (FR-6.25),
    so a measurement that moved with the interviewer's manner would be a
    measurement of the manner.
  * **may differ** — the words said, the register, how deep the ladder goes
    (`follow_up_aggression`), whether hints exist. That is the *experience*,
    and it is the point of having modes at all.
  * **differs, and is not a standard** — Practice declares M13's
    `n1_practice` ensemble: one evaluator instead of three. M13's own comment
    is "drops the COUNT, never the tier", so Practice is measured less
    PRECISELY, never more generously, and M13 calibrates it separately or
    withholds the number. The report has to say that rather than imply the
    two are interchangeable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from backend_M06_Mock_Interview_Engine import adapters, outbox, report, store
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache
from backend_M06_Mock_Interview_Engine.llm import NullLLM
from backend_M06_Mock_Interview_Engine.models import EvaluationOutbox

from .stubs import BankQuestions, NoClaims, StubLLM, verdict

#: Every mode, now that each one is a config with its own personas (day 9):
#: the gate has to hold for the feature it was written before.
MODES = ("practice", "mock", "real_drive", "final_boss")

ANSWER = "Keys are hashed to a bucket index, so you jump straight to it instead of scanning."


def run(db, mode: str) -> tuple[Engine, uuid.UUID]:
    """One session in `mode`, one question, one answer. Same answer every time."""
    engine = Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
        llm=StubLLM([verdict()]),
        thetas=ThetaCache(),
    )
    row, _ = store.create_session(
        engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=30
    )
    engine.start(row.id)
    state = engine.state(row.id)
    engine.answer(row.id, state.open_turn_id, ANSWER)
    return engine, row.id


# ── what M13 is sent ─────────────────────────────────────────────────────


@pytest.mark.gate
def test_the_payload_m13_scores_does_not_depend_on_the_mode(db):
    """The blind half of §6.7. Everything that decides the score is the same;
    only `ensemble` differs, and that is a count of evaluators, not a bar."""
    sent = {}
    for mode in MODES:
        engine, session_id = run(db, mode)
        queued = outbox.status(engine.db, session_id)
        assert queued["evaluations"]["pending"] == 1, f"{mode} owes exactly one evaluation"
        row = engine.db.exec(
            select(EvaluationOutbox).where(EvaluationOutbox.session_id == session_id)
        ).one()
        sent[mode] = dict(row.payload)

    # Identity fields differ between sessions by construction; drop them and
    # everything left must match, byte for byte.
    identity = {"turn_id", "session_id", "candidate_id", "consent_id"}
    scoring = {m: {k: v for k, v in p.items() if k not in identity} for m, p in sent.items()}

    practice, mock, drive, boss = (scoring[m] for m in MODES)
    assert mock == boss == drive, "mock, Real drive and Final Boss send M13 the same thing"
    assert practice["answer_text"] == mock["answer_text"] == ANSWER
    assert practice["question_id"] == mock["question_id"]
    assert practice["round_type"] == mock["round_type"]
    assert practice["hint_level_used"] == mock["hint_level_used"]

    # The ONE difference, and it is declared rather than hidden.
    assert practice["ensemble"] == "n1_practice"
    assert mock["ensemble"] == boss["ensemble"] == "n3_het_v1"
    assert {k for k in practice if practice[k] != mock[k]} == {"ensemble"}


# ── what the strategist judges ───────────────────────────────────────────


@pytest.mark.gate
def test_the_strategist_judges_the_question_not_the_register(db):
    """Its verdict becomes an M05 θ observation (FR-6.25), so a verdict that
    moved with the interviewer's manner would be a measurement of the manner.

    The leak this gate was written for: the strategist used to be handed the
    RENDERED interviewer turn, which carries the register's lead — "Hello.
    Let's begin. First question." against a bar-raiser's "Let's get started.
    First." Same answer, different prompt, and on day 9 a different verdict.
    """
    prompts = {}
    for mode in MODES:
        engine, _ = run(db, mode)
        judged = engine.llm.structured_calls
        assert len(judged) == 1, f"{mode} asked the strategist exactly once"
        prompts[mode] = judged[0]

    first = prompts[MODES[0]]
    for mode in MODES[1:]:
        assert prompts[mode]["system"] == first["system"], f"{mode}: same instructions"
        assert prompts[mode]["user"] == first["user"], f"{mode}: same question and answer"

    # And no register word reached it — the phrasebook's, or any persona's
    # own greeting, which is where a name and a manner live since day 9.
    from backend_M06_Mock_Interview_Engine.personas import personas
    from backend_M06_Mock_Interview_Engine.phrasebook import LINES

    tables = [*LINES.values(), *(p.said() for p in personas().values())]
    leads = {lines.greeting for lines in tables} | {lines.first_question_lead for lines in tables}
    for lead in leads:
        assert lead not in first["user"], f"the register leaked: {lead!r}"
    assert ANSWER in first["user"], "the answer itself is still there to judge"


# ── what the student is told ─────────────────────────────────────────────


def test_the_report_says_what_is_actually_true_about_practice(db):
    """§6.7 says to tell the student, so the sentence has to be exactly right.

    "Judged the same way" on its own implies Practice and Final Boss are
    interchangeable. They share a rubric and a model tier; Practice runs one
    evaluator instead of three, so it is less precise. Saying only the first
    half would let a student read a Practice score as a mock-grade one.
    """
    engine, session_id = run(db, "practice")
    built = report.build(
        engine.state(session_id), store.events_for(engine.db, session_id), engine.clock()
    )
    note = built.persona_note
    assert "never changes the standard" in note
    # The half that was missing.
    assert "precise" in note or "precision" in note
    assert "generous" in note or "easier" in note
    # And it never promises a number that M13's display gate is withholding.
    assert "score" not in note.lower().replace("scored", "")


def test_every_mode_sends_an_ensemble_m13_actually_publishes(db):
    """A mode naming an ensemble M13 does not have would fall back to M13's
    default silently — a different standard, arrived at by typo."""
    engine, _ = run(db, "mock")
    published = {c["name"] for c in engine.upstreams.m13.ensembles()}
    assert set(outbox.ENSEMBLE_BY_MODE.values()) <= published, (
        f"M06 names {set(outbox.ENSEMBLE_BY_MODE.values()) - published}, which M13 does not serve"
    )


def test_no_mode_is_left_without_an_ensemble(db):
    """A mode missing from the table would get `n3_het_v1` by default, which is
    right for three modes and wrong for Practice. Naming them all is cheaper
    than remembering which default is safe."""
    from backend_M06_Mock_Interview_Engine.contracts import Mode

    assert set(Mode.__args__) == set(outbox.ENSEMBLE_BY_MODE)


def test_the_null_model_is_judged_the_same_way_too(db):
    """Rule 2 in this corner: with no model the rule path decides, and it must
    not consult the mode either."""
    verdicts = {}
    for mode in MODES:
        engine = Engine(
            db=db,
            upstreams=adapters.fixture_upstreams(m05=BankQuestions(), m01=NoClaims()),
            llm=NullLLM(),
            thetas=ThetaCache(),
        )
        row, _ = store.create_session(
            engine.db, candidate_id=uuid.uuid4(), kind="mock", mode=mode, minutes=30
        )
        engine.start(row.id)
        state = engine.state(row.id)
        engine.answer(row.id, state.open_turn_id, "I don't know")
        decided = next(
            e.payload for e in store.events_for(engine.db, row.id) if e.kind == "probe.decided"
        )
        verdicts[mode] = {k: v for k, v in decided.items() if k not in ("turn_id",)}
    assert (
        verdicts["practice"] == verdicts["mock"] == verdicts["real_drive"] == verdicts["final_boss"]
    )
