# M06 — Mock Interview Engine

> **The product's front door.** Everything else in the platform is either an input to this loop or an output of it.
>
> Spec: [plan_in_depth/M06_Mock_Interview_Engine.md](plan_in_depth/M06_Mock_Interview_Engine.md) (Revision 2) · Review that produced it: [M06_REVIEW.md](plan_in_depth/M06_REVIEW.md) · Running state: [the TODO](plan_in_depth/M06_Mock_Interview_Engine_TODO.md) · Ports: API `8106`, web `5206` ([PORTS.txt](PORTS.txt))

The student drops in a job description, and the engine plans a sequence of rounds with a time budget. It runs each round with a persona, probes every answer until understanding breaks, then exits gracefully. The engineering is mostly about **timing, memory, and knowing when to stop asking**. The one sentence it has to earn is *"that felt like a real interview."*

```bash
git clone https://github.com/MNEMOS-PREP/Mock_Interview_Engine
cd Mock_Interview_Engine/Backend
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # no network, no API key
cd .. && start_mock.bat                 # API on :8106
```

Nothing upstream is needed to boot, test or run a session. [`/v1/deps`](dependencies.txt) says which of M01, M02, M04, M05 and M13 are up, and a session narrows its scope around the ones that are not.

---

## Where it stands

**Day 1 of the 15-day [build order](plan_in_depth/M06_Mock_Interview_Engine.md#14-build-order).** See [the TODO](plan_in_depth/M06_Mock_Interview_Engine_TODO.md) for the requirement-by-requirement state.

| Landed | |
|---|---|
| **Session state as a fold over an append-only event log** | [`state.py`](Backend/backend_M06_Mock_Interview_Engine/state.py). Pure, and strict about transitions. Checkpoint, replay and "a report even if the checkpoint write failed" are one mechanism. |
| **`record()`, the only write path** | [`store.py`](Backend/backend_M06_Mock_Interview_Engine/store.py). `(session, turn, step)` is the idempotency key. `(session, seq)` is the compare-and-swap. The checkpoint is a cache that only moves forward. |
| **One live session per student** (EC-6.13) | A unique, nullable `occupying_key` behaves the same on SQLite and Postgres. A session left at the plan preview is superseded, not blocking. |
| **Identity on every route** (FR-6.26) | [`access.py`](Backend/backend_M06_Mock_Interview_Engine/access.py) runs `ai_core.identity` at router level, and resolves a session id to its student before `may_see`. |
| **Adapters for all five upstreams** | [`adapters/`](Backend/backend_M06_Mock_Interview_Engine/adapters/): live HTTP clients against the shipped routers, plus fixtures. [`test_contracts.py`](Backend/backend_M06_Mock_Interview_Engine/tests/test_contracts.py) holds them to shapes captured from the upstreams' own models by [`tools/capture_contracts.py`](Backend/tools/capture_contracts.py). |
| **Session lifecycle API** | Create, start, pause (once, ≤ 5 min), resume, end, transcript, trace with a replay check, and the student's own history. |

## Three things worth reading the code for

**1. Where the seq comes from.** `record()` takes the next sequence number from the state it validated against, not from `max(seq)` read afterwards. Read afterwards, a tab that lost a race would commit its answer at N+1, validated against a state that is missing the winner's answer. The student would then have two answers to one question. Taking the seq from the validated state makes the loser's insert collide. It re-reads, and gets *"That question has already been answered."* A test forces the race, and reverting the line makes that test fail.

**2. The provisional θ is not in the checkpoint.** M05 owns the in-session ability estimate and forbids persisting it (its `ProvisionalIsNotDurable`). M06 checkpoints after every step, so the obvious implementation would store the estimate. Two release gates stop that. One reads the schema. The other scans a real checkpoint written after a 30-turn scripted session.

**3. Steelman is off, everywhere.** The spec's original ladder asked a deliberately false question at depth 3 in every mode, including Practice. And M13 has no `push_back` rubric to score a steelman turn against, so the trap would be scored as knowledge. Revision 2 separates rungs from moves, and keeps steelman unreachable until that rubric exists.

## Layout

```
Backend/
  backend_M06_Mock_Interview_Engine/
    app.py            FastAPI app, /health, /status
    router.py         /v1 routes (spec §7)
    access.py         identity — router-level, FR-6.26
    contracts.py      the shapes M06 owns (spec §5)
    state.py          the fold (spec §6.8)
    store.py          record(), the only write path
    models.py         tables
    adapters/         M01, M02, M04, M05, M13 — live + fixture
    fixtures/         the fallback playlist; captured upstream contracts
    tests/
  tools/capture_contracts.py
plan_in_depth/        spec, review, TODO
scripts/              launcher (services.txt is the one to edit)
```

## Before you wire another module to this one

Read [M06_REVIEW.md](plan_in_depth/M06_REVIEW.md) Part 1. It lists every route M06 calls and every route that calls M06, each checked against shipped code. Part 5 lists what M06 needs other modules to change. None of it blocks this repo, and all of it is small.
