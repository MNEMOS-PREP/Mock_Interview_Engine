# M06 — TODO · Mock Interview Engine

> **Completion: 0%** — 0 of 26 functional requirements met. **Build started 2026-09-16**; the spec was revised to Revision 2 the same day after [M06_REVIEW.md](M06_REVIEW.md), which added FR-6.23–6.26 — each one an obligation a shipped module already places on M06, not new scope. Of the 26, **21 can be met in full in Phase 1**, **4 only in part** (FR-6.10, 6.11 and 6.22 for text; FR-6.21 as record-only), and **FR-6.20 not at all** until M13 ships a `push_back` rubric.
>
> _Method: `(met + ½ × partial) ÷ total`, counted from the spec, 2026-09-16. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

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
| Status | **Plan revised (Revision 2); day 1 of 15 in progress.** |
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
| 1 | 🟡 | Scaffold and state: repo, ports, `module.json`, Platform_Core v0.9.1, `/health`, `/v1/deps`, adapters + fixtures, session/turn/event tables, event fold, checkpoint CAS, one live session, `may_see` |
| 2 | ⬜ | Drill slice (`POST /v1/drills`) end to end + SSE + minimal stage UI + **latency harness on the live account** |
| 3 | ⬜ | `ProbeStrategist` structured call, derived rungs, `break_depth`, `ProvisionalOutcome` → M05; decide LangGraph (§15.6) |
| 4 | ⬜ | `InterviewerView` + outbound-request gates; eval outbox → M13; ledger → M02; consent adapter |
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

---

## 3. Functional requirements

Spec §4, Revision 2. This is the authoritative list.

| FR | | Priority | Phase |
|---|---|---|---|
| FR-6.1 | ⬜ `InterviewPlan` from M02 plan + M04 profile + M05 availability + budget + mode, no model call | P0 | 1 |
| FR-6.2 | ⬜ Plan preview with drop-a-segment | P1 | 1 |
| FR-6.3 | ⬜ Segments in sequence, per-segment persona, rubric from M05's selection | P0 | 1 |
| FR-6.4 | ⬜ Re-plan at boundaries, ≤ 2, hot-path signals only | P1 | 1 |
| FR-6.5 | ⬜ Probe ladder, cap 5, graceful exit, derived rungs | P0 | 1 |
| FR-6.6 | ⬜ `break_depth` per concept per session | P0 | 1 |
| FR-6.7 | ⬜ M05 hint ladder, `hint_level_used`, M13 credit table shown | P0 | 1 |
| FR-6.8 | ⬜ Four modes as configs | P0 | 1 |
| FR-6.9 | ⬜ Final Boss: pressure via mechanics, never rudeness | P0 | 1 |
| FR-6.10 | ⬜ Voice / text / coding / canvas in one session | P0 | 1·text · voice ⛔ M11 · coding ⛔ M07 · canvas ⛔ M08 |
| FR-6.11 | ⬜ Modality switch without state loss | P0 | 1·text |
| FR-6.12 | ⬜ Pause once ≤ 5 min, resume | P1 | 1 |
| FR-6.13 | ⬜ Reconnect and resume from checkpoint | P0 | 1 |
| FR-6.14 | ⬜ Evaluation never blocks the hot path | P0 | 1 |
| FR-6.15 | ⬜ Interviewer cannot read scores, band or θ | P0 | 1 |
| FR-6.16 | ⬜ Fixed context size | P0 | 1 |
| FR-6.17 | ⬜ Pacing: 70% checkpoint, reserved closing | P0 | 1 |
| FR-6.18 | ⬜ A report for every session, partial and failed included | P0 | 1 |
| FR-6.19 | ⬜ Replayable state + model-call trace from the event log; Langfuse optional | P0 | 1 |
| FR-6.20 | ⛔ Steelman probes, dispatched against `push_back` | P1 | blocked — M13 rubric |
| FR-6.21 | ⬜ Record closing questions · ⛔ score them | P1 | 1 · scoring blocked — rubric |
| FR-6.22 | ⬜ p95 text ≤ 2.5 s to first token · voice ≤ 1.2 s | P0 | 1·text · voice ⛔ M11 |
| FR-6.23 | ⬜ Defend drill — M01's `POST /v1/drills` | P0 | 1 |
| FR-6.24 | ⬜ M02 ledger: `asked`, `answered`, `skipped` | P0 | 1 |
| FR-6.25 | ⬜ `ProvisionalOutcome` → M05 per verdict; θ never persisted | P0 | 1 |
| FR-6.26 | ⬜ `may_see` on every candidate-scoped route | P0 | 1 |

---

## 4. Acceptance gates

Spec §13. A **[GATE]** is release-blocking; the rest are tracked.

| AC | | Target |
|---|---|---|
| AC-6.1 **[GATE]** | ⬜ Every session produces a report | 100%, including aborted |
| AC-6.2 **[GATE]** | ⬜ M13 request carries no interviewer text, intent, steelman flag, verdict or other turn | unit test |
| AC-6.3 **[GATE]** | ⬜ Interviewer never receives scores, band or θ | type-graph walk |
| AC-6.4 **[GATE]** | ⬜ p95 text 2.5 s to first token (voice 1.2 s, Phase 3) | harness |
| AC-6.13 **[GATE]** | ⬜ No provisional θ in persisted state | unit test |
| AC-6.14 **[GATE]** | ⬜ No steelman while disabled, any mode | 0 / 10,000 per mode |
| AC-6.15 **[GATE]** | ⬜ `asked` / `answered` ledger rows for every turn | 100% |
| AC-6.5 | ⬜ Session completion rate | ≥ 80% |
| AC-6.6 | ⬜ Break point found | ≥ 80% of sessions |
| AC-6.7 | ⬜ Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | ⬜ "Felt like a real interview" | ≥ 4.0 mean |
| AC-6.9 | ⬜ Reconnect success rate | ≥ 95% |
| AC-6.10 | ⬜ Context tokens per turn variance | < 15% |
| AC-6.11 | ⬜ Prompt cache-hit ratio | ≥ 0.7, or "not measured" |
| AC-6.12 | ⬜ Sessions where a student felt humiliated | 0 |
| AC-6.16 | ⬜ Retries never double-ask, double-write or double-enqueue | chaos test |

---

## 5. Edge cases

Spec §9. Listed in full, because several are one afternoon each and are the
difference between a demo and a product.

| EC | | Expected behaviour |
|---|---|---|
| EC-6.1 | ⬜ Student says nothing for 45 s | One gentle prompt, then a second, then offer to move on. In text: idle timer from persona `patience` |
| EC-6.2 | ⬜ Student answers a different question | Redirect once (`off_question`); if repeated, move on and flag it |
| EC-6.3 | ⬜ Student asks the interviewer a question | Brief persona answer, then back (`asks_interviewer`) |
| EC-6.4 | ⬜ Student is abusive / tests the AI | One neutral redirect, then end politely. Logged |
| EC-6.5 | ⬜ Student asks for the answer | Hint ladder if the mode allows; else "I'll walk you through it in the report" |
| EC-6.6 | ⬜ Answer contains prompt injection | Guard + rule filter; scored on the rest by M13 (which neutralises in place); logged |
| EC-6.7 | ⛔ Mic dies mid-answer | Phase 3 (M11) |
| EC-6.8 | ⬜ Browser refresh | Resume from checkpoint |
| EC-6.9 | ⬜ Session exceeds budget by 25% | Force closing (0% in Final Boss) |
| EC-6.10 | ⬜ Student ends at minute 3 | Report for what exists, framed as a warm-up |
| EC-6.11 | ⬜ All modalities fail | Clean end, apology, no score |
| EC-6.12 | ⬜ LLM provider outage | Item stems and templates verbatim, rule strategist, eval stays queued, session completes |
| EC-6.13 | ⬜ Two sessions in parallel | Blocked with an explanation (partial unique index) |
| EC-6.14 | ⬜ Pauses and never returns | Auto-close after 30 min; partial report |
| EC-6.15 | ⛔ Steelman accepted by a correct student | Blocked with FR-6.20 |
| EC-6.16 | ⬜ Coding round with no editor | Dropped at plan time — which is every coding round until M07 exists |
| EC-6.17 | ⛔ Camera denied after opting in | Phase 3 (M12) |

---

## 6. Data model

Spec §5 (Revision 2).

| Type / table | | |
|---|---|---|
| `PlannedSegment`, `Replan`, `InterviewPlan` | ⬜ | |
| `ProbeLadderState`, `StrategistVerdict` | ⬜ | |
| `Turn`, `SessionEvent`, `SessionFlags` | ⬜ | |
| `m06_session` (partial unique: one live per candidate) | ⬜ | |
| `m06_event` (unique `(session_id, turn_index, step)`) | ⬜ | |
| `m06_checkpoint` (CAS on `version`, no θ) | ⬜ | |
| `m06_eval_outbox`, `m06_ledger_outbox`, `m06_llm_call` | ⬜ | |

---

## 7. Asks of other modules

From [M06_REVIEW.md](M06_REVIEW.md) Part 5. None blocks day 1. Each belongs in
the other module's TODO once raised; tick it here when it has been.

| Module | Ask | Raised |
|---|---|---|
| M01 | `module.json` repo URL `mock-interview-engine` → `Mock_Interview_Engine` (launcher skips M06 otherwise) | ⬜ |
| M05 | `/questions/select` reads its own `_SESSIONS` θ when the caller omits it | ⬜ |
| M05 | `difficulty_offset` on `SelectionRequest` | ⬜ |
| M05 | per-round-type counts on `/bank/health` | ⬜ |
| M04 | consent lookup route | ⬜ |
| M04 | source `recent_sessions` from M06 | ⬜ |
| M13 | `push_back` rubric variant (unblocks FR-6.20) | ⬜ |
| M13 | `cs_core` and `communication` rubrics | ⬜ |
| M02 | docstring: M06 writes `asked`/`answered` | ⬜ |
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

- **6. LangGraph or an explicit state machine** — recommendation: explicit for Phase 1; settle on day 3.
- **7. Report home until M19** — recommendation: M06 serves it, deleted when M19 ships.
- **8. Drill scoring** — recommendation: unscored in Phase 1, and the report says so.
