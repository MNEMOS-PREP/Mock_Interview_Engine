# M06 — TODO · Mock Interview Engine

> **Completion: 52%** — 8 of 26 functional requirements met, 11 partially. **Days 1–4 of 15 are done.** What works end to end now spans three modules: a mock interview asks **M05 bank questions**, the answers reach **M13**, and M13's status comes back into the report — verified against the three services running together, not against fixtures. The **defend drill** path also runs whole. The **mock** path still runs on a stub plan (one segment, a fixed round type) until day 5.
>
> Met: the probe ladder and break depths (FR-6.5, 6.6), evaluation off the hot path (FR-6.14), the interviewer's blind view (FR-6.15), a report for every session (FR-6.18), the drill (FR-6.23), the M05 θ seam (FR-6.25), identity (FR-6.26).
>
> Not started: plan assembly and its preview (FR-6.1, 6.2), re-planning (FR-6.4), modes as configs (FR-6.8), Final Boss (FR-6.9), closing questions (FR-6.21). Blocked: steelman (FR-6.20).
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-09-17. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Task list for taking **M6 — Mock Interview Engine** to 100% of [M06_Mock_Interview_Engine.md](M06_Mock_Interview_Engine.md) (Revision 2).

> **Read this first when starting a session on M06.** It is the running state of
> the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1–2 · **Owner:** E2 · **Ports:** API `8106`, web `5206`
- **Repo:** `Mock_Interview_Engine` — on disk at `projects\Mock_Interview_Engine` (the folder must equal the repo name, or `launch.ps1` skips it)
- **Platform_Core:** v0.9.1

Legend: ✅ done · 🟡 partly done · ⬜ not started · ⛔ blocked on another module

---

## 0. Ideas and scouting

Things worth building that did not come from the spec — usually from reading
somebody else's implementation. **New ideas go at the top of this section.**

The rule we keep arriving at: borrow a **technique**, not a **component**. The
platform's contracts — character offsets, per-fact provenance, permanent
evidence — are more demanding than general-purpose tools assume, so integration
usually costs more than reimplementing the one idea we actually wanted.

_Nothing scouted for this module yet._

---

## 1. Where the module stands

| | |
|---|---|
| Status | **Days 1–4 of 15 done.** A mock interview runs across M05, M06 and M13 with the three services live; a defend drill runs end to end on the live model through the web app. |
| Backend tests passing | **170**, no socket opened, no API key |
| Release gates (`-m gate`) | **24** |
| Route decorators | **18** on `/v1`, plus `/health` and `/status` |
| Lint | `ruff check` and `ruff format --check` clean; frontend `tsc` clean |
| Frontend | four screens on `:5206`, `m06Routes` exported for Platform_Shell |
| Measured | strategist p95 **1106 ms**, interviewer first token p95 **919 ms**, a rung ≈ **2.0 s** to first visible token (AC-6.4 wants ≤ 2.5 s) — `Backend/reports/latency-*.json` |
| Spec | [Revision 2](M06_Mock_Interview_Engine.md), after [the review](M06_REVIEW.md) |
| Scope | 26 functional requirements (21 of them P0), 16 acceptance metrics (7 release-blocking), 17 edge cases |
| Upstreams | M01, M02, M04, M05, M13 — all shipped, all optional at runtime, each behind an adapter with a fixture |

**What the review changed, in one breath.**
- **The plan:** it wraps M02's `CoveragePlan` instead of re-allocating it, and no model builds it.
- **Ownership:** M06 writes M02's `asked`/`answered`/`skipped` ledger rows, and never persists M05's provisional θ.
- **The ladder:** it no longer reaches `steelman` in Practice mode, and steelman stays off everywhere until M13 has a `push_back` rubric.
- **Re-planning:** it reads only hot-path signals.
- **New route:** the defend drill M01 already calls is specified.
- **Scope:** Phase 1 is text-only.
- **Latency:** the gate is time-to-first-token, measured on day 2 against the models this platform actually runs.

---

## 2. Build order (spec §14, Revision 2)

| Day | | Task |
|---|---|---|
| 1 | ✅ | Scaffold and state: repo, ports, `module.json`, Platform_Core v0.9.1, `/health`, `/v1/deps`, adapters + fixtures, session/turn/event tables, event fold, compare-and-swap, one live session, `may_see` |
| 2 | ✅ | Drill slice (`POST /v1/drills`) end to end + SSE + stage UI + **latency harness on the live account** |
| 3 | ✅ | `ProbeStrategist` structured call, derived rungs, `break_depth`, `ProvisionalOutcome` → M05; LangGraph adopted (§15.6) |
| 4 | ✅ | `InterviewerView` + outbound-request gates; eval outbox → M13; ledger → M02; consent adapter; **outbox sweeper** |
| 5 | ⬜ | Plan assembly over M02 + plan-time availability; preview UI |
| 6 | ⬜ | Segments, 409 as honest end, bridges, `RoundTransition` |
| 7 | ⬜ | Hint ladder (M05), M13 credit table shown |
| 8 | ⬜ | Context management; AC-6.10 |
| 9 | ⬜ | Personas (7) as data, modes (4) as configs, guard |
| 10 | ⬜ | Pacing, re-plan from hot-path signals |
| 11 | ⬜ | Pause/resume, reconnect, idle prompts, auto-close, chaos tests |
| 12 | ⬜ | Degradation ladder, partial report, report page |
| 13 | ⬜ | UI pass, `routes.tsx`, mobile, ARIA |
| 14 | ⬜ | Scripted student 20 × 4, manual QA |
| 15 | ⬜ | Cross-module asks raised, TODO reconciled, human eval prep |

### Day 1 — what landed, and what it found

- **The seq bug.** `record()` first took the next seq from `max(seq)` read *after* loading state. A losing tab would then have committed a second answer to one question. Fixed by taking the seq from the validated state, and pinned by a test that forces the race; reverting the line fails it. Spec §6.8 now says so.
- **The compare-and-swap moved** from the checkpoint's `version` to the event log's `(session_id, seq)`. This guards the truth rather than the cache, and lets the checkpoint be written after commit, so a checkpoint failure loses nothing (§10).
- **Contracts captured from shipped code.** `Backend/tools/capture_contracts.py` runs under each upstream's own venv and dumps model shapes into `fixtures/contracts/`; `test_contracts.py` holds the adapters to them. M04 and M01 build dicts rather than models, so their shapes are hand-written with the source line.
  - M05's package is not installed in its own venv. Run the tool there with `PYTHONPATH` set to M05's `Backend/`.
- **Two new cross-module asks** (§7): M01 must forward identity on the drill hand-off, and M13 reads the wrong service-secret variable.
- **Mutation-checked.** Three gates were broken on purpose (the seq line, the occupying key, a θ field) and each was caught.

### Days 2–3 — what landed, and what they found

**Decided: LangGraph, behind our own interface** (§15.6). Master plan §26.1 names it, the long-term shape is a registry of 20+ agents with ablation flags and parallel GD panels, and `orchestration/graph.py` is the only file that imports it. It runs **without a checkpointer**: the event log stays the single record, so there is never a second answer to "what happened". `GET /v1/agents` publishes the registry and the compiled graph as mermaid — which is also the diagram for the viva.

**Built:** the drill route on M01's contract · the text turn loop · `ProbeStrategist` as one structured call with a rule fallback · the interviewer adapting rungs and presenting scored stems verbatim · `SafetyGuard`'s rule filter · the live SSE stream · four screens · the latency harness.

**Found, and fixed:**
- **The "live" stream was not live.** Built as a poll of the log, the reader sat behind the writer's SQLite lock: the first token frame arrived at **+1384 ms** against a POST that returned at **1237 ms** — a preview of an answer the student already had. Events are now pushed as they commit (`store.NOTIFY`), with a slow sweep behind them; the first token arrives at **860 ms**, before the POST returns.
- **`/v1/sessions` would have been proxied to M05.** Platform_Shell routes one origin by the first path segment, and `sessions` belongs to M05, `candidates` to M04. M06's nouns are now `interviews`, `drills`, `agents`, with a gate test against the shell's own table.
- **The strategist over-called "failed".** A thin-but-not-wrong first answer ended a drill at depth 0 — the graceful exit firing on someone who had not been asked anything yet. `strategist-2` says failed means *wrong*, and to choose `partial` when unsure. Re-checked on four answers: thin → partial, wrong → failed, "can't remember" → the rule path, solid → held.
- **The interviewer invented bridges.** `interviewer-1` forced a link to whatever the student last said ("Given your web scraper project, why would a stack need LIFO?"). `interviewer-2` uses their words only when they bear on the probe.

**Measured** (16 rounds, real prompts, `reports/latency-2026-09-16.json`): `reasoning_effort: "low"` is accepted; verdicts matched the intended label on 16 of 16; **cached tokens are reported on 2 of 16** structured calls and never on a streamed one, so AC-6.11's 0.7 target is not reachable on this provider as things stand — it caches opportunistically.

**Two new asks** (§7): M13 has **no live M05 client at all** (`get_questions()` is always the fixture bank), so it 404s on every real question id — which blocks the Phase-1 exit gate, not just day 4. And M05's `Bank.get()` cannot find its own fallback-playlist items.

### Day 4 — what landed, and what it found

**Built:** `outbox.py` — one mechanism for two obligations (an answered turn owes
M13 an evaluation, a requirement behind a question owes M02 a ledger row), each
row written **in the same transaction as the turn**. `EVALUATION_KEYS` is the
gate on what leaves: the blind-scoring property is what is *absent* — no
interviewer text, no probe intent, no verdict, no other turn. Scores come back
as a **status** (`queued` → `complete`), never as a number, because M13 owns
the number and the gate that says whether anybody may see it.

**Then the three services were started together** — M05 on 8105, M13 on 8113,
M06 on 8106 — and a real interview was driven through the HTTP API. It found
four things 166 passing tests had not:

- **One answer reached M13 three times, concurrently.** A background task and
  an explicit drain both took the same row, because `_pending` read rows
  without claiming them; the third call timed out at 60 s. A row is now claimed
  by a conditional UPDATE that commits *before* the network call, and the claim
  expires (`STALE_CLAIM_S`) so a process that dies mid-send strands nothing.
  Without the claim the regression test recurses for ever.
- **A send that failed had nobody left to retry it.** It went back to `pending`
  and sat there — the student had stopped answering. `sweeper.py` is the worker
  the outbox docstring already promised: one task per process, every 30 s,
  working through every session that still owes something. On the live database
  it picked the stranded row up on its first pass and the report moved
  `queued` → `complete`.
- **Repeating a question repeated the turn it arrived in:** *"That's a different
  question. Here's mine again. Okay, let's leave that there. Next question. Two
  keys hash to the same bucket."* A turn now carries `question_text` — the
  question without the words that introduced it.
- **Pressing End said nothing at all.** `session.ended` has carried a closing
  line since day 1; the student-initiated path never filled it in.

**Evidence.** M13 scored two live M05 bank questions with verified quote spans
(correctness 0, reasoning "does not address hashing", on an answer that
deliberately did not), `composite` withheld by its display gate, and
`key_point_coverage` against the bank item's own key points. M06's report shows
those key points as *"a strong answer covers"*. Turn latency 0.6–1.7 s.

**Also:** the report tells a student a consequence **once** — M04 owns consent,
so when M04 is absent its own sentence is the whole story. And
`fixture_upstreams` now serves `module.json`'s real `on_missing` copy, so a
test about what a student is told asserts on the words that ship.

### Next: day 5

1. **Plan assembly over M02's `CoveragePlan`** (FR-6.1) — no model call, and
   `skipped` ledger rows become writable once the plan says what was planned.
2. **Plan-time availability from M05** and the segment sequence (FR-6.3).
3. **The plan preview with drop-a-segment** (FR-6.2).

---

## 3. Functional requirements

Spec §4, Revision 2. This is the authoritative list.

| FR | | Priority | Phase |
|---|---|---|---|
| FR-6.1 | ⬜ `InterviewPlan` from M02 plan + M04 profile + M05 availability + budget + mode, no model call | P0 | 1 |
| FR-6.2 | ⬜ Plan preview with drop-a-segment | P1 | 1 |
| FR-6.3 | 🟡 Segments in sequence, per-segment persona, rubric from M05's selection — one segment and one register today; sequencing lands with the plan (day 5–6) | P0 | 1 |
| FR-6.4 | ⬜ Re-plan at boundaries, ≤ 2, hot-path signals only | P1 | 1 |
| FR-6.5 | ✅ Probe ladder, cap 5, graceful exit, derived rungs — pure function, 14 tests, steelman unreachable | P0 | 1 |
| FR-6.6 | ✅ `break_depth` per concept per session — recorded by the fold, kept at the shallowest break | P0 | 1 |
| FR-6.7 | 🟡 M05 hint ladder served and `hint_level_used` recorded; M13's credit table is not shown yet (day 7) | P0 | 1 |
| FR-6.8 | ⬜ Four modes as configs | P0 | 1 |
| FR-6.9 | ⬜ Final Boss: pressure via mechanics, never rudeness | P0 | 1 |
| FR-6.10 | 🟡 Text runs; the turn contract carries `modality` | P0 | 1·text · voice ⛔ M11 · coding ⛔ M07 · canvas ⛔ M08 |
| FR-6.11 | 🟡 Contract fixed and carried; nothing to switch to yet | P0 | 1·text |
| FR-6.12 | 🟡 Pause once ≤ 5 min, resume — once-only and the 5-min cap on resume are built and tested; the clock does not restart on its own if the student never resumes (day 11) | P1 | 1 |
| FR-6.13 | 🟡 Reconnect and resume from checkpoint — checkpoint recovery (stale, unreadable, failed write) is built and tested; `resume-state` and the "welcome back" flow are not (day 11) | P0 | 1 |
| FR-6.14 | ✅ Evaluation never blocks the hot path — outbox written with the turn, delivered by a background task, an explicit drain, or the sweeper; claimed before sending; a status returns, never a number | P0 | 1 |
| FR-6.15 | ✅ Interviewer cannot read scores, band or θ — `InterviewerView` + the type-graph gate | P0 | 1 |
| FR-6.16 | 🟡 Last six turns only reach the model; no round summary, no constancy test (day 8) | P0 | 1 |
| FR-6.17 | 🟡 A question is not asked without time for an answer, and the clock can end a session; the 70% checkpoint and the reserved closing are day 10 | P0 | 1 |
| FR-6.18 | ✅ A report for every session — ended, aborted, or crashed half-way; built from the log | P0 | 1 |
| FR-6.19 | 🟡 `/trace` serves the log, every model call, and a replay equality check; an offline re-run harness and the Langfuse export are not built | P0 | 1 |
| FR-6.20 | ⛔ Steelman probes, dispatched against `push_back` | P1 | blocked — M13 rubric |
| FR-6.21 | ⬜ Record closing questions · ⛔ score them | P1 | 1 · scoring blocked — rubric |
| FR-6.22 | 🟡 Text measured at ≈ 2.0 s p95 to first visible token, inside the gate | P0 | 1·text · voice ⛔ M11 |
| FR-6.23 | ✅ Defend drill — M01's contract, end to end, on the live model | P0 | 1 |
| FR-6.24 | 🟡 M02 ledger: `asked` and `answered` are written with the turn and delivered; `skipped` needs the real plan to know what was never reached (day 5) | P0 | 1 |
| FR-6.25 | ✅ `ProvisionalOutcome` → M05 per model verdict; θ in memory only, gated twice | P0 | 1 |
| FR-6.26 | ✅ `may_see` on every route, including the body-scoped `/drills` | P0 | 1 |

---

## 4. Acceptance gates

Spec §13. A **[GATE]** is release-blocking; the rest are tracked.

| AC | | Target |
|---|---|---|
| AC-6.1 **[GATE]** | ✅ Every session produces a report | 100%, including aborted |
| AC-6.2 **[GATE]** | ✅ M13 request carries no interviewer text, intent, steelman flag, verdict or other turn — `EVALUATION_KEYS` asserted against M13's own `EvaluateRequest` | unit test |
| AC-6.3 **[GATE]** | ✅ Interviewer never receives scores, band or θ | type-graph walk |
| AC-6.4 **[GATE]** | 🟡 p95 text 2.5 s to first token — measured ≈ 2.0 s on 16 rounds; voice is Phase 3 | harness |
| AC-6.13 **[GATE]** | ✅ No provisional θ in persisted state — schema test + a real 30-turn checkpoint scanned | unit test |
| AC-6.14 **[GATE]** | ✅ No steelman while disabled, any mode | 0 / 10,000 per mode |
| AC-6.15 **[GATE]** | 🟡 `asked` / `answered` ledger rows for every turn — written and delivered whenever a JD is behind the session; `skipped` waits on the real plan (day 5) | 100% |
| AC-6.5 | ⬜ Session completion rate | ≥ 80% |
| AC-6.6 | ⬜ Break point found | ≥ 80% of sessions |
| AC-6.7 | ⬜ Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | ⬜ "Felt like a real interview" | ≥ 4.0 mean |
| AC-6.9 | ⬜ Reconnect success rate | ≥ 95% |
| AC-6.10 | ⬜ Context tokens per turn variance | < 15% |
| AC-6.11 | 🟡 Prompt cache-hit ratio — measured: reported on 2 of 16 structured calls, never on a streamed one | ≥ 0.7, or "not measured" |
| AC-6.12 | ⬜ Sessions where a student felt humiliated | 0 |
| AC-6.16 | 🟡 Retries never double-ask or double-write — proven for the event key, a crashed step, and now two senders racing over one outbox row; the full chaos suite is day 11 | chaos test |

---

## 5. Edge cases

Spec §9. Listed in full, because several are one afternoon each and are the
difference between a demo and a product.

| EC | | Expected behaviour |
|---|---|---|
| EC-6.1 | ⬜ Student says nothing for 45 s | One gentle prompt, then a second, then offer to move on. In text: idle timer from persona `patience` |
| EC-6.2 | ✅ Student answers a different question | Redirected once, then judged as given |
| EC-6.3 | ✅ Student asks the interviewer a question | Brief answer, then the question again |
| EC-6.4 | ⬜ Student is abusive / tests the AI | One neutral redirect, then end politely. Logged |
| EC-6.5 | 🟡 Student asks for the answer | A hint while hints last, else a graceful exit; M13's credit table is day 7 |
| EC-6.6 | 🟡 Answer contains prompt injection | Fenced as data in every prompt and judged as part of the answer; the guard model is day 9 |
| EC-6.7 | ⛔ Mic dies mid-answer | Phase 3 (M11) |
| EC-6.8 | 🟡 Browser refresh | Resume from checkpoint — state survives; the stage UI that re-attaches does not exist yet |
| EC-6.9 | ⬜ Session exceeds budget by 25% | Force closing (0% in Final Boss) |
| EC-6.10 | ✅ Student ends at minute 3 | A report framed as a warm-up, not a failure |
| EC-6.11 | ⬜ All modalities fail | Clean end, apology, no score |
| EC-6.12 | ⬜ LLM provider outage | Item stems and templates verbatim, rule strategist, eval stays queued, session completes |
| EC-6.13 | ✅ Two sessions in parallel | Blocked with an explanation and the id to resume; a unique nullable `occupying_key` enforces it at the database |
| EC-6.14 | ⬜ Pauses and never returns | Auto-close after 30 min; partial report |
| EC-6.15 | ⛔ Steelman accepted by a correct student | Blocked with FR-6.20 |
| EC-6.16 | ⬜ Coding round with no editor | Dropped at plan time — which is every coding round until M07 exists |
| EC-6.17 | ⛔ Camera denied after opting in | Phase 3 (M12) |

---

## 6. Data model

Spec §5 (Revision 2).

| Type / table | | |
|---|---|---|
| `PlannedSegment`, `Replan`, `InterviewPlan` | ✅ | `contracts.py` — declared; assembled on day 5 |
| `ProbeLadderState`, `StrategistVerdict`, `Move` | ✅ | driven by `ladder.decide`, a pure function |
| `TurnView`, `SessionFlags`, `SessionState` | ✅ | `contracts.py`, `state.py` — no θ field, gated |
| `m06_session` (unique nullable `occupying_key`) | ✅ | EC-6.13 at the database |
| `m06_event` (unique `(session, turn, step)` and `(session, seq)`) | ✅ | the idempotency key and the compare-and-swap |
| `m06_checkpoint` (monotonic `last_seq`, no θ) | ✅ | a cache; stale or unreadable → re-fold |
| `m06_turn` (projection, `text_sha256`) | ✅ | feeds `seen_item_ids` |
| `m06_llm_call` | ✅ | every model call, with reasoning and cached tokens when reported |
| `m06_eval_outbox`, `m06_ledger_outbox` (`claimed_at`, states `pending`/`sending`/`sent`/`held`) | ✅ | written with the turn, claimed before sending, retried by `sweeper.py` |

---

## 7. Asks of other modules

From [M06_REVIEW.md](M06_REVIEW.md) Part 5. None blocks day 1. Each belongs in
the other module's TODO once raised; tick it here when it has been.

| Module | Ask | State |
|---|---|---|
| M01 | `module.json` repo URL `mock-interview-engine` → `Mock_Interview_Engine` (launcher skips M06 otherwise) | ✅ landed (`d785b9f`, branch `m01-claim-pipeline`) |
| M01 | forward `X-Role` / `X-Candidate-Id` on the drill hand-off (M06 refuses anonymous callers) | ✅ landed (`d785b9f`) |
| M05 | `/questions/select` reads its own `_SESSIONS` θ when the caller omits it | ✅ landed (`d30915d`) |
| M05 | `Bank.get()` cannot find its own fallback-playlist items | ✅ landed (`d30915d`) |
| M13 | **a live M05 question source** — `get_questions()` was always the fixture bank, so it 404d on every real question id (blocked the Phase-1 gate) | ✅ landed (`efb5a5a`); confirmed live: M13 resolves `/v1/questions/{id}/package?round_type=` from M05 |
| M13 | **a worker that drains its own outbox** — `emit.py` promises one ("a row is written in the same transaction and a worker drains it") but only `POST /outbox/drain` exists, so a failed send to M04/M02/M19 is never retried. M06's `sweeper.py` is the pattern | ⬜ new |
| M05 | `difficulty_offset` on `SelectionRequest` | ⬜ |
| M05 | per-round-type counts on `/bank/health` | ⬜ |
| M04 | consent lookup route — until it exists, M13 emits **no observations at all** (it requires `consent_id` on every one), so a scored session still moves no mastery | ⬜ |
| M04 | source `recent_sessions` from M06 | ⬜ |
| M13 | `push_back` rubric variant (unblocks FR-6.20) | ⬜ |
| M13 | `cs_core` and `communication` rubrics | ⬜ |
| M13 | read `M04_SERVICE_SECRET`, as M04 and M15 do, not `SERVICE_SECRET` | ⬜ |
| M02 | docstring: M06 writes `asked`/`answered` | ⬜ |
| Platform_Shell | add `interviews`/`drills`/`agents` to the proxy table and mount `m06Routes` | ⬜ |
| Platform | `modules_meta` M06 → built; `Platform_Shell` journey card | ⬜ (on ship) |

---

## 8. Deferred — inter-module

Not gaps in this module. Each waits on a module that is not built or not
wired, and is listed so it is not mistaken for an oversight.

| Deferred | Waits on |
|---|---|
| Voice, mic check, barge-in, voice latency | M11 (Phase 3) |
| Coding segments | M07 |
| Canvas segments | M08 (Phase 2) |
| Camera / presence | M12 (Phase 3) |
| Steelman (FR-6.20, EC-6.15) | M13 `push_back` rubric |
| Scoring closing questions (FR-6.21) | a rubric |
| Mode-dependent item difficulty | M05 `difficulty_offset` |
| Sessions updating the skill graph | M04 consent route |
| Scored drill turns | M05 grounded items from M01 claims (Phase 2) |
| The report, long-term | M19 |
| Project segment from repositories | M03 |

---

## 9. Open decisions

Spec §15. 1–5 stand as written; 6–8 are new.

- **6. LangGraph or an explicit state machine** — **settled 2026-09-17: LangGraph**, behind `orchestration/` and with no checkpointer of its own. Master plan §26.1 names it, the long-term shape (an agent registry with ablation flags, parallel GD panels) is what it is for, and keeping the event log as the only record avoids the dual-truth problem. `graph.py` is the only file that imports it.
- **7. Report home until M19** — recommendation: M06 serves it, deleted when M19 ships.
- **8. Drill scoring** — recommendation: unscored in Phase 1, and the report says so.
