# M06 — TODO · Mock Interview Engine

Task list for taking **M6 — Mock Interview Engine** to 100% of [M06_Mock_Interview_Engine.md](M06_Mock_Interview_Engine.md).

> **This is the branch that holds the plan.** The `todo` branch carries the
> spec and this list and nothing else, so the module's own history stays
> about its code. Sync it here when something lands.

> **Read this first when starting a session on M06.** It is the running state of
> the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Repo:** `Mock_Interview_Engine`

Legend: ✅ done · 🟡 partly done · ⬜ not started

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
| Status | **Not started.** No code exists — no backend, no frontend, no tests. |
| Spec | Written, and the source of every row below. |
| Scope | 22 functional requirements (17 of them P0), 12 acceptance metrics (4 release-blocking), 17 edge cases. |

Everything below is ⬜ because nothing is built. That is the honest state and
it is worth writing down rather than leaving three sections saying
_To fill in._ — the point of this list is that the next session can start from
it instead of re-reading a six-hundred-line spec.

---

## 2. Functional requirements

Spec §4, verbatim. This is the authoritative list.

| FR | | Priority |
|---|---|---|
| FR-6.1 | ⬜ Build an `InterviewPlan` from JD + profile + time budget + modality | P0 |
| FR-6.2 | ⬜ Show the plan to the student before running, with an edit option | P1 |
| FR-6.3 | ⬜ Execute rounds in sequence with per-round persona and rubric | P0 |
| FR-6.4 | ⬜ Re-plan at round boundaries, max 2 per session, on defined triggers | P1 |
| FR-6.5 | ⬜ Probe ladder with depth cap 5 and graceful exit on break | P0 |
| FR-6.6 | ⬜ Record `break_depth` per concept per session | P0 |
| FR-6.7 | ⬜ Hint ladder with published, fixed score reduction per level | P0 |
| FR-6.8 | ⬜ Four modes (Practice / Mock / Real-drive / Final Boss) as configs of one engine | P0 |
| FR-6.9 | ⬜ Enforce the Final Boss rule: pressure via mechanics, never rudeness | P0 |
| FR-6.10 | ⬜ Support voice, text, coding, and canvas modalities within one session | P0 |
| FR-6.11 | ⬜ Mid-session modality switch without state loss | P0 |
| FR-6.12 | ⬜ Pause (once, ≤5 min) and resume | P1 |
| FR-6.13 | ⬜ Reconnect and resume after disconnect from the last checkpoint | P0 |
| FR-6.14 | ⬜ Evaluation must never block the conversational hot path | P0 |
| FR-6.15 | ⬜ Interviewer nodes cannot read current-round evaluation scores | P0 |
| FR-6.16 | ⬜ Fixed context size regardless of session length | P0 |
| FR-6.17 | ⬜ Time-aware pacing with a 70% checkpoint and a reserved closing round | P0 |
| FR-6.18 | ⬜ Always produce a report, even on partial/failed sessions | P0 |
| FR-6.19 | ⬜ Emit a full Langfuse trace and replayable state per session | P0 |
| FR-6.20 | ⬜ Deliberate-wrong-statement (steelman) probes marked in the transcript | P1 |
| FR-6.21 | ⬜ Score the student's own closing questions | P1 |
| FR-6.22 | ⬜ p95 turn latency: text ≤ 2.5 s, voice ≤ 1.2 s to first audio | P0 |

---

## 3. Acceptance gates

Spec §13. A **[GATE]** is release-blocking; the rest are tracked.

| AC | | Target |
|---|---|---|
| AC-6.1 **[GATE]** | ⬜ Every session produces a report | 100%, including aborted |
| AC-6.2 **[GATE]** | ⬜ Evaluator view cannot reach candidate identity or interviewer reasoning | unit test |
| AC-6.3 **[GATE]** | ⬜ Interviewer never receives current-round scores | unit test |
| AC-6.4 **[GATE]** | ⬜ p95 turn latency (text 2.5 s / voice 1.2 s) | met |
| AC-6.5 | ⬜ Session completion rate | ≥ 80% |
| AC-6.6 | ⬜ Break point found | ≥ 80% of sessions |
| AC-6.7 | ⬜ Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | ⬜ "Felt like a real interview" (post-session, 5-point) | ≥ 4.0 mean |
| AC-6.9 | ⬜ Reconnect success rate | ≥ 95% |
| AC-6.10 | ⬜ Context tokens per turn variance across session length | < 15% |
| AC-6.11 | ⬜ Prompt cache-hit ratio on interviewer calls | ≥ 0.7 |
| AC-6.12 | ⬜ Sessions where a student reported feeling humiliated | 0 (open-text review each phase) |

---

## 4. Edge cases

Spec §12. Listed in full, because several are one afternoon each and are the
difference between a demo and a product.

| EC | | Expected behaviour |
|---|---|---|
| EC-6.1 | ⬜ Student says nothing for 45 s | One gentle prompt, then a second, then offer to move on. Never loop forever |
| EC-6.2 | ⬜ Student answers a different question | Interviewer notes it and redirects once; if repeated, moves on and the report flags "answered a different question" |
| EC-6.3 | ⬜ Student asks the interviewer a question mid-round | Persona-appropriate brief answer, then back. Never derail |
| EC-6.4 | ⬜ Student is abusive / tests the AI | One neutral redirect, then end the session politely. Logged |
| EC-6.5 | ⬜ Student asks for the answer | Hint ladder if available; otherwise "I'll walk you through it in the report" |
| EC-6.6 | ⬜ Answer contains prompt injection | Stripped; scored on the rest; logged |
| EC-6.7 | ⬜ Mic dies mid-answer | Auto-switch to text with the partial transcript preserved |
| EC-6.8 | ⬜ Browser refresh | Resume from checkpoint |
| EC-6.9 | ⬜ Session exceeds budget by 25% | Force closing round |
| EC-6.10 | ⬜ Student ends at minute 3 | Report is generated for what exists, framed as a warm-up not a failure |
| EC-6.11 | ⬜ All modalities fail | Session ends cleanly with an apology and no score recorded |
| EC-6.12 | ⬜ LLM provider outage mid-session | Panic degradation: local model for interviewer, evaluation deferred, session completes |
| EC-6.13 | ⬜ Two sessions in parallel by one student | Blocked with an explanation (state would collide) |
| EC-6.14 | ⬜ Student pauses and never returns | Auto-close after 30 min; partial report generated |
| EC-6.15 | ⬜ Steelman probe accepted by a *correct* student | Push-back scored positively; if they don't push back, it's a note, not a penalty |
| EC-6.16 | ⬜ Coding round with no editor support on device | Round replaced at plan time, not at runtime |
| EC-6.17 | ⬜ Camera denied after opting in | Presence dimension omitted, no penalty, one-line note |

---

## 5. Data model

Spec §5 declares 5 types. None exist.

| Type | | |
|---|---|---|
| `PlannedRound` | ⬜ | Not written |
| `InterviewPlan` | ⬜ | Not written |
| `ProbeLadderState` | ⬜ | Not written |
| `Turn` | ⬜ | Not written |
| `SessionFlags` | ⬜ | Not written |

---

## 6. Deferred — inter-module

Not gaps in this module. Each needs a module that is not built or not wired
yet, and each is listed so it is not mistaken for an oversight.

The spec names **M11, M12, M13, M16, M19**. Until those are wired, anything
depending on them is blocked rather than unstarted, and the distinction
matters: one is work waiting to be done and the other is work that cannot
begin.

---

## 7. First moves

When work begins, the order that has worked on M01 and M02:

1. **The manifest and the ports.** `module.json` with `depends_on` declaring
   every upstream as OPTIONAL, each with an `on_missing` sentence a student
   can act on. Rule 2: a missing dependency narrows scope, never quality, and
   never silently.
2. **Identity before endpoints.** Router-level `enforce_access` on
   `ai_core.identity`, so no route can be written without it. A per-route
   check is the one somebody omits on the sixteenth endpoint, and the
   sixteenth endpoint is the one that leaks.
3. **The P0 that carries the module's name**, not the easiest one.
4. **Contract gates from the first commit** — every route has a client, every
   hook has a screen, every response field is declared on the frontend. M01
   shipped ten routes nobody could reach before these existed.
5. **A golden corpus before the third extraction fix**, not after. On M02 it
   found four real bugs within an hour of existing.

