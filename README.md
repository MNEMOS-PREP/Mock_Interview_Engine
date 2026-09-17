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

**Days 1–3 of the 15-day [build order](plan_in_depth/M06_Mock_Interview_Engine.md#14-build-order).** A **defend drill runs end to end on the live model**: M01 hands over a claim, the ladder climbs the claim's own probes, it exits gracefully when the reasoning stops holding, and it produces notes. The full mock runs on a stub plan until day 5. See [the TODO](plan_in_depth/M06_Mock_Interview_Engine_TODO.md) for the requirement-by-requirement state.

| Landed | |
|---|---|
| **Session state as a fold over an append-only event log** | [`state.py`](Backend/backend_M06_Mock_Interview_Engine/state.py). Pure, and strict about transitions. Checkpoint, replay and "a report even if the checkpoint write failed" are one mechanism. |
| **`record()`, the only write path** | [`store.py`](Backend/backend_M06_Mock_Interview_Engine/store.py). `(session, turn, step)` is the idempotency key. `(session, seq)` is the compare-and-swap. The checkpoint is a cache that only moves forward. |
| **The step, as a graph** | [`orchestration/`](Backend/backend_M06_Mock_Interview_Engine/orchestration/): LangGraph behind our own interface (master plan §26.1), with no checkpointer of its own — the event log stays the only record. `GET /v1/agents` publishes the registry, the ablation switches and the compiled graph. |
| **The probe ladder** | [`ladder.py`](Backend/backend_M06_Mock_Interview_Engine/ladder.py). A pure function: rungs derived from each question's own follow-ups, graceful exit on a break, ceiling on success, and steelman unreachable until M13 can score it. |
| **The two agents** | `ProbeStrategist` — one structured call, narrow context, with a rule fallback for when the model is off. `TechnicalInterviewer` — adapts a rung to the student's words, presents a scored stem verbatim, and is screened for telegraphed verdicts as it streams. |
| **The live surface** | SSE that is pushed as events commit, four screens on `:5206`, and `m06Routes` exported for Platform_Shell. |
| **Identity on every route** | [`access.py`](Backend/backend_M06_Mock_Interview_Engine/access.py) runs `ai_core.identity` at router level and resolves a session id to its student before `may_see`. |
| **Adapters for all five upstreams** | Live HTTP clients against the shipped routers, plus fixtures. [`test_contracts.py`](Backend/backend_M06_Mock_Interview_Engine/tests/test_contracts.py) holds them to shapes captured from the upstreams' own models. |

**147 tests, 19 release gates, ruff clean, a clean `tsc`, and not one test opens a socket.**

Measured against the live account ([`reports/`](Backend/reports)): strategist p95 **1106 ms**, interviewer first visible token p95 **919 ms** — a rung reaches the screen in about **2.0 s at p95**, inside AC-6.4's 2.5 s.

## Five things worth reading the code for

**1. Where the seq comes from.** `record()` takes the next sequence number from the state it validated against, not from `max(seq)` read afterwards. Read afterwards, a tab that lost a race would commit its answer at N+1, validated against a state that is missing the winner's answer — two answers to one question. A test forces the race, and reverting the line makes it fail.

**2. The provisional θ is not in the checkpoint.** M05 owns the in-session ability estimate and forbids persisting it. M06 checkpoints after every step, so the obvious implementation would store it. Two release gates stop that: one reads the schema, the other scans a real checkpoint from a 30-turn session.

**3. Steelman is off, everywhere.** The spec's original ladder asked a deliberately false question at depth 3 in *every* mode, including Practice — and M13 has no `push_back` rubric, so agreeing with the falsehood would be scored as knowledge. Rungs and moves are separate now, and a gate drives the ladder 10,000 times per mode to prove it cannot happen.

**4. The stream is pushed, not polled.** Polling the log for the interviewer's tokens put the reader behind the writer's SQLite lock: the first "live" token arrived 150 ms *after* the answer it was previewing. Events are published as they commit, with a slow sweep behind them for another process's writes.

**5. `/v1/interviews`, not `/v1/sessions`.** Platform_Shell proxies one origin by the first path segment, and `sessions` already belongs to M05. A gate test holds M06's nouns against the shell's own table, because the failure mode is a request answered by the wrong module rather than an error.

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
