"""Shared scaffolding for the pacing, closing and re-planning tests (day 10).

A session's clock is the engine's `clock`, so a test moves time by moving an
offset — the event log keeps real timestamps, and the fold's arithmetic is
done against whatever "now" the engine is handed, exactly as in production.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from ai_core.timeutil import utcnow

from backend_M06_Mock_Interview_Engine import adapters, store
from backend_M06_Mock_Interview_Engine.adapters.fixtures import (
    FixtureCoveragePlanner,
    fallback_playlist,
)
from backend_M06_Mock_Interview_Engine.engine import Engine, ThetaCache

from .stubs import BankQuestions, NoClaims, StubLLM, answer, verdict

FAIL = verdict(band="below", justification="failed")


class Clock:
    """utcnow(), plus however many seconds a test says have passed."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self):
        return utcnow() + timedelta(seconds=self.offset)

    def at(self, seconds: float) -> None:
        self.offset = seconds


def rounds_plan(*rounds: tuple[str, int, float]) -> dict:
    """An M02 `CoveragePlan` with the given `(requirement, questions, minutes)`
    rounds, one requirement each, priorities falling in order."""
    return {
        "rounds": [
            {"round_type": "verbal", "minutes": m, "question_count": q, "requirement_ids": [r]}
            for r, q, m in rounds
        ],
        "allocations": [
            {"requirement_id": r, "priority": round(0.9 - i * 0.2, 2), "rationale": f"{r} matters"}
            for i, (r, _q, _m) in enumerate(rounds)
        ],
        "uncovered": [],
        "plan_version": "greedy-log-v1",
    }


REQUIREMENTS = [
    {
        "id": "r1",
        "text": "Data structures",
        "measured_by": ["technical"],
        "concept_ids": ["concept:stacks"],
    },
    {
        "id": "r2",
        "text": "Recursion",
        "measured_by": ["technical"],
        "concept_ids": ["concept:recursion"],
    },
    {
        "id": "r3",
        "text": "Hashing",
        "measured_by": ["technical"],
        "concept_ids": ["concept:hashing"],
    },
]


def deep_bank(copies: int = 5) -> BankQuestions:
    """M05 with `copies` of the fallback playlist, each item its own id.

    The playlist alone runs dry after four questions, and a round M05 has
    nothing left for ends early (§6.1's 409) — right for the product, and
    wrong for a test that needs a session to get through twelve.
    """
    items = fallback_playlist()["items"]
    return BankQuestions(
        [{**item, "id": str(uuid.uuid4())} for _ in range(copies) for item in items]
    )


def make(db, *, plan=None, verdicts=None, m05=None, clock=None, memory=None, llm=None) -> Engine:
    overrides = {
        "m05": m05 or BankQuestions(),
        "m01": NoClaims(),
        "m02": FixtureCoveragePlanner(plan=plan, requirements=REQUIREMENTS)
        if plan
        else FixtureCoveragePlanner(),
    }
    if memory is not None:
        overrides["m04"] = memory
    return Engine(
        db=db,
        upstreams=adapters.fixture_upstreams(**overrides),
        llm=llm or StubLLM(verdicts or [FAIL]),
        thetas=ThetaCache(),
        clock=clock or Clock(),
    )


def session(engine: Engine, *, mode="mock", minutes=30, jd=True):
    row, _ = store.create_session(
        engine.db,
        candidate_id=uuid.uuid4(),
        kind="mock",
        mode=mode,
        minutes=minutes,
        jd_id=uuid.uuid4() if jd else None,
    )
    engine.start(row.id)
    return row


def say(engine: Engine, row, text: str):
    state = engine.state(row.id)
    assert state.open_turn_id is not None, "nothing is open to answer"
    return answer(engine, row, text)


def events(engine: Engine, row, kind: str) -> list[dict]:
    return [e.payload for e in store.events_for(engine.db, row.id) if e.kind == kind]


def last_line(state) -> str:
    return next(t.text for t in reversed(state.transcript) if t.role == "interviewer")
