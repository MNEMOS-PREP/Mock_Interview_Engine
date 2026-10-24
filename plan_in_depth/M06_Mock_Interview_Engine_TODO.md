# M06 — TODO · Mock Interview Engine

> **Completion: 87%** — 20 of 26 functional requirements met, 5 partially. **Days 1–15 of 15 are done — the build order is complete**, plus two pieces pulled forward out of days 9 and 11 because they were shipped-today defects rather than missing features (see below). Since 2026-10-24 **the notes say how each answer went**: correct, partly correct, too vague, incorrect or not answered — decided by the interview, never by a model — and each answer is explained in the student's own words, checked before it is shown ([the report](M06_NOTES.md)). Since 2026-10-23 **the interviewer judges an answer before it speaks**: a wrong answer is challenged in the student's own words, difficulty moves per topic and only for the interview, a question that asks two things is asked one at a time, every decision says why, and the notes quote what was said ([the report](M06_OVERHAUL.md)). Since day 15 **the build order is finished and what is left is named**: what waits on another module, what waits on a person (human evaluation, round 1, prepared), and what M06 still owes itself. Since day 14 **the full chain runs live with M04's guard on** — five real services, the real model, a student's answers reaching M13 and moving M04's skill graph — and a scripted student drives twenty sessions across the four modes on every run of the suite. Since day 13 **every route has a screen** — or a named caller — and a gate fails the build the day one does not; the setup offers the four modes and honours a job description handed over, the preview says who runs each part, and §7's last three routes exist. Since day 12 **a session degrades instead of breaking**: a failing model is noticed turn by turn, the session wraps up early and then stops asking it, and if everything fails the student gets an apology and an honest record rather than a spinner. The notes now carry M13's own words about each answer — never its numbers. Since day 11 **a session survives the student leaving**: the clock stops while their stage is gone, they come back to "we were on question 2 of Data structures", silence gets a prompt rather than a stare, and the spec's five chaos scenarios pass with nothing done twice. Since day 10 **a session keeps time like an interviewer**: it narrows at 70%, hands over to the closing at 90%, holds Final Boss to its clock, re-plans at most twice from what it saw, and the closing is where the student asks. Since day 9 **a mock is a panel**: seven personas as data, four modes as one table, and a guard that reads what the student sends as well as what the interviewer says. On 2026-09-20 **the platform's core loop closed for the first time**: a student consents (M04), is asked a question from M05's bank, answers it in M06, M13 scores the answer, and M04's skill graph moves — Hashing and Time Complexity to `emerging`, with the evidence resolving to the student's own sentence. Six backends and the shell, running together, through one origin on `:5173`. Since day 5 the **mock** path runs on M02's real plan rather than a stub: rounds that are named, priced, previewed, droppable, and that end and begin out loud. The **defend drill** path runs whole.
>
> Met: plan assembly over M02 (FR-6.1) and its preview (FR-6.2), segments with a persona each (FR-6.3), the probe ladder and break depths (FR-6.5, 6.6), hints at a published price (FR-6.7), modes as configs (FR-6.8), pause (FR-6.12), reconnect and resume (FR-6.13), evaluation off the hot path (FR-6.14), the interviewer's blind view (FR-6.15), fixed context (FR-6.16), a report for every session (FR-6.18), re-planning (FR-6.4), Final Boss (FR-6.9), pacing and the reserved closing (FR-6.17), the drill (FR-6.23), the M02 ledger (FR-6.24), the M05 θ seam (FR-6.25), identity (FR-6.26).
>
> Partly: the modalities beyond text (FR-6.10, 6.11, 6.22 — voice waits on M11, the editor on M07, the canvas on M08), the trace's offline harness and Langfuse export (FR-6.19), and closing questions (FR-6.21 — recorded and shown; scoring them waits on a rubric). Blocked: steelman (FR-6.20), on M13's `push_back` rubric.
>
> _Day 6 moved no requirement across a line, and the number is right not to move: it deepened FR-6.3 (rounds now end, begin and say so) without completing it, because per-segment personas wait on day 9. The measure counts requirements, not work — which is the point of having one._
>
> _Method: `(met + ½ × partial) ÷ total`, audited against shipped code, 2026-09-17; re-checked 2026-10-04 and 2026-10-17: unchanged. One measure applied the same way to all nineteen modules so they compare; it counts requirements, not screens or gates._

Task list for taking **M6 — Mock Interview Engine** to 100% of [M06_Mock_Interview_Engine.md](M06_Mock_Interview_Engine.md) (Revision 2).

> **Read this first when starting a session on M06.** It is the running state of
> the module: what is done, what is next, and what is deliberately deferred.
> Update it as things land — a stale list is worse than no list, because the
> next session trusts it.

- **Phase:** 1–2 · **Owner:** E2 · **Ports:** API `8106`, web `5206`
- **Repo:** `Mock_Interview_Engine` — on disk at `projects\Mock_Interview_Engine` (the folder must equal the repo name, or `launch.ps1` skips it)
- **Platform_Core:** v0.40.0 on the backend (since 2026-10-24: the `writing` tier the notes are written on), v0.39.0 on the frontend (since 2026-10-21). The router guard is `ai_core.guard`'s; the two staff routes are `require_role(admin)`; M05 and M04 are asked as a module with `ai_core.service`; who the browser is comes from `@ai/core`'s session

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
| Status | **Days 1–15 of 15 done — the build order is complete.** A mock interview is planned from a real job description and the student's resume, run by a panel of personas across M02, M04, M05, M06 and M13, and reaches the skill graph; mounted in Platform_Shell on one origin. |
| Backend tests passing | **750**, no socket opened, no API key (counted 2026-10-24) |
| Frontend tests passing | **31** (`npm test`: vitest + Testing Library on jsdom, since 2026-10-24) |
| Release gates (`-m gate`) | **82** |
| Route decorators | **45** on `/v1`, plus `/health` and `/status` |
| Lint | `ruff check` and `ruff format --check` clean; frontend `tsc` clean |
| Frontend | five screens on `:5206`; **mounted in Platform_Shell** on `:5173` at `/mock`, with `interviews`/`drills`/`agents` in its proxy table |
| Live chain | **2026-10-02**: M02 → M06 → M05 → M13 → M04, M04's guard on — 4 artifacts, 4 evaluations, 3 ledger rows delivered; hashing, time complexity and hashing internals moved to `emerging`; anonymous and cross-student reads 403, theta without the service secret 401 |
| Measured | strategist p95 **1106 ms**, interviewer first token p95 **919 ms**, a rung ≈ **2.0 s** to first visible token (AC-6.4 wants ≤ 2.5 s) — `Backend/reports/latency-*.json` |
| Spec | [Revision 2](M06_Mock_Interview_Engine.md), after [the review](M06_REVIEW.md) |
| Scope | 26 functional requirements (21 of them P0), 17 acceptance metrics (8 release-blocking), 17 edge cases |
| Upstreams | M01, M02, M04, M05, M13 — all shipped, all optional at runtime, each behind an adapter with a fixture |
| Asked as a module | **2026-10-03**: M05 now serves a question's key points and follow-ups only with the platform secret, so `LiveQuestions.question()` sends it; `test_the_question_m06_probes_against_is_fetched_as_a_module` fails without it |
| From a company | **2026-10-03**: `POST /v1/interviews` takes `company_id` + `drive_id` (M15's "Practise this format"). M02 builds the drive's requirement set (`/jds/from-drive`) and the session is planned from it like any JD; a drive M02 cannot plan starts a general interview whose plan says why, in M02's words. Live: Zoho · Campus SDE → JD → plan, nothing degraded |

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
| 5 | ✅ | Plan assembly over M02 + plan-time availability; preview UI with drop-a-segment |
| 6 | ✅ | Segments, 409 as honest end, bridges, `RoundTransition`, the project segment |
| 7 | ✅ | Hint ladder (M05), M13 credit table shown before the hint is taken |
| 8 | ✅ | Context management: §6.6's rolling round summary, bounded view; AC-6.10's mechanism gated, its number a harness run |
| 9 | ✅ | Personas (7) as data, modes (4) as configs, guard on both directions (EC-6.4, 6.6), Practice's retry |
| 10 | ✅ | Pacing 70/90 and a round's own clock, the closing runs, re-plan from hot-path signals, M05 seeded from M04 |
| 11 | ✅ | Presence (a disconnect stops the clock, a return restarts it after a grace), `resume-state`, idle prompts, the five chaos scenarios |
| 12 | ✅ | The degradation ladder (L0 → panic, from what the session saw), everything-fails with the apology, M13's words in the notes, AC-6.9's number from the log |
| 13 | ✅ | UI pass: mode picker, `?jd=`, who runs each part, round name, pause confirmation, Repeat and ⚑; §7's `/repeat`, `/flag`, `/switch-modality`; the route-client contract gate |
| 14 | ✅ | The scripted student (20 sessions across the 4 modes), the manual QA script, and the full chain live with M04's guard on |
| 15 | ✅ | Every open ask raised in its owner's TODO; this TODO reconciled against shipped code; human evaluation round 1 prepared ([M06_HUMAN_EVAL_ROUND1.md](M06_HUMAN_EVAL_ROUND1.md)) |

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

### 2026-09-20 — the chain, and the three seams in it

Five modules were started together and one real answer was driven through
them. Each blocker was invisible to every module's own green suite, because
each module tests itself against fixtures by design.

1. **M06 carried no consent.** `LiveMemory.consent()` returned `None` with a
   comment saying M04 had no route — and M13 refuses to emit any observation
   without one, so *every* scored session moved nothing. M04 now has
   `GET`/`POST /v1/candidates/{id}/consent` (`5e01e8d`) and M06 asks it.
2. **The evidence had nothing to resolve against.** M13 cites
   `artifact_id = turn_id` on every span it quotes; M04 refuses evidence that
   does not resolve; nobody registered the turn. All nine observations came
   back *"evidence does not resolve"*, and the batch took the turn's technical
   observation with it. M04 grew `POST .../artifacts`, and M06 registers the
   answer **through the outbox, before the evaluation** — see FR-6.14.
3. **M13 minted a concept that exists in no ontology.** Its communication
   filter tested `cid.startswith("concept:communication")`, which matches none
   of M04's ids (`concept:thinking_aloud`, …), so the fallback wrote
   `concept:communication` and M04 rejected the batch as "unknown concept".
   M13 now asks M04's ontology which concepts are communication (`bc30601`).

**The lesson, recorded:** a table whose rule a module *enforces* usually has no
route to fill it, because the rule ships with the model and the route is left
to a repo that does not exist yet. Four instances in one afternoon.

### Day 5 — what landed

`planner.py`: M02's `CoveragePlan` becomes an `InterviewPlan`, deterministically.
M06 **adds to** M02's plan and never re-allocates it (Trap 8) — it reserves the
warm-up and closing off the top *before* asking M02 to price anything (45 min →
M02 is asked for 36), carries M02's minutes and question counts across
untouched, resolves requirement ids to the concept ids M05 selects on, and
names each segment in the posting's own words.

**Two vocabularies, kept apart** (§5). M02's `round_type` is a MODALITY —
`verbal`, `coding`, `design`, priced at 3.5, 12 and 20 minutes a question.
M05's and M13's is a RUBRIC — `dsa_verbal`. A segment carries both: the
modality decides whether this session can run it, the rubric decides what M13
scores it against. A coding round has no M07 and a design round no M08, so
both are dropped with a sentence and their requirements go to M02 as `skipped`.

**Availability is probed at plan time** (§6.1 step 5): one `select` per round
type M13 can score, and a 409 removes it from the plan instead of surprising
the student mid-interview. The probe is safe — M05 records an item as
administered when an outcome is reported, not when one is selected.

**And the plan runs.** `question_budget` is the plan's sum rather than a second
estimate of the same thing; the segment being run supplies `coverage_debt` and
`required_requirement_ids` to M05; and a segment advances once it has had the
questions M02 priced for it. Without that last piece the plan was a screen —
the session stayed on the warm-up for ever.

Verified live against M02's real plan: a 45-minute session became a 4-minute
warm-up, M02's 14-minute SQL round for requirement R-8 carrying M02's own
rationale, and a reserved 5-minute closing. On the second segment M05 returned
an SQL question — the plan steering selection, end to end.

### Day 6 — what landed

**A crossing is said out loud.** Every register gained bridge copy, authored
like every other structural move, naming what is coming in M02's words:
*"Let's move to the next part: SQL."* It **replaces** "next question" rather
than stacking on it — three transitions for one crossing reads worse than
none. The line travels with the selection (`Selected.bridge`), because the
graph step's own state was read before the crossing happened. In the
transcript a quiet rule marks where a round ended; the spoken line is not
drawn again in a box, which would be the same sentence twice on one screen.

**M05 running dry ends the round, not the interview.** A 409 is a known state
with a behaviour (M05 §6.8), so the segment closes and the next opens, and the
abandoned round's requirements go to M02 as `skipped`. Ending the session
would throw away every segment behind it — a thin corner of the bank becoming
a short interview about nothing.

**The project segment.** With a risky or vague claim from M01, the plan opens
with the student's own work before the posting's. Its minutes come out of the
largest verbal round, never the closing, and never more than half of it. Its
questions are M01's probes and are never scored, because M13 resolves a
package from M05 and a claim probe is not a bank item. The claims ride on the
plan, so the claim the preview showed is the one the student defends.

**A test that names its upstreams.** Ten tests now say `m01=NoClaims()` where
they are about M02's rounds rather than resumes — the fixture M01 always has
one shaky claim, which is right for the drill and noise everywhere else.

### Day 7 — what landed

FR-6.7's missing half. The ladder and `hint_level_used` had been there since
day 3; the **deduction was invisible**, and a hint only fired when the
strategist spotted a plea for one inside an answer.

- **The price is M13's** (`Rubric.hint_penalty`, already published on
  `/v1/rubrics`) and is read in the same call that asks which round types M13
  can score. **Frozen on the plan**: a rubric reloaded mid-session must not
  change what a hint cost a student quoted 85%. Unlisted levels credit fully
  — M13's own rule — and the lookup tries int and string keys, because a miss
  reads as "this hint is free".
- **The offer is on every read of the session**, not behind a call a client
  might skip: `available`, `level`, `credit`, `hints_left`, and
  `unavailable_reason` when there is none. The button says why rather than
  vanishing; a control that disappears reads as a bug, and "Final Boss runs
  without hints" is a rule a student should know they are under.
- **`POST /hint`** takes one, by a button. The strategist path still works for
  somebody who types "can I have a hint", but a student should not have to
  phrase a request to use a feature.
- **The hint is said.** One recorded and not shown is a deduction paid for and
  not received. It re-opens the same question, so the answer after it still
  belongs to the question the hint was about.

Verified live against M13's real table (0.95 / 0.85 / 0.70 / 0.50 / 0.30):
two hints taken, price shown before each, the ladder running out with a
reason, and `hint_level_used: 2` in the request queued for M13.

### Inserted before day 9 — the promise the report was already making

**The decision.** Day 8 was next on the list. It was the wrong thing to do
first, and the reason is an ordering one: spec §6.7 tells M06 to print *"the
persona never changes the standard"* in the report, M06 has printed it since
day 3, and **there was no acceptance metric behind it** — §13 had sixteen and
none of them was this. Day 9 ships personas, which is the single feature able
to falsify it. A gate written after the feature it guards is a gate that
ratifies whatever shipped.

**Writing it found the leak it was written for.** The strategist was handed
the *rendered* interviewer turn, and a rendered turn carries the register's
lead — "Hello. Let's begin. First question." against a bar-raiser's "Let's get
started. First." Its verdict becomes an M05 `ProvisionalOutcome` (FR-6.25), so
on day 9 the same answer would have been **measured** differently depending on
the interviewer's manner. It now gets the question without the words that
introduced it. Day 4 already separated those two things on the turn
(`question_text`); nothing had connected it here.

**And the sentence was overstated.** M13's `n1_practice` is one evaluator
where `n3_het_v1` is three — its own comment is "drops the COUNT, never the
tier". So the standard is identical and the precision is not. The report now
says both, because §6.7's whole reason for saying anything is that a student
should not read a Practice result as a mock-grade one.

**One more contract check, from the same thread.** M13 falls back to its
DEFAULT for an ensemble name it does not know, and that default is
`n1_practice` — so a typo in a mock-mode name would have scored that session
with one evaluator instead of three, quieter than an error. `Evaluator.
ensembles()` is new, and two tests hold M06's names to what M13 publishes and
to the full set of modes.

Spec §13 gains **AC-6.17** and §6.7 records why. Both gates are
mutation-checked: restoring the rendered turn fails one, misspelling
`n1_practice` fails two.

### Also inserted — a pause you never come back from locked the student out

Same question as AC-6.17, asked again: **what does the product promise that
nothing enforces?** The UI says the pause is five minutes. FR-6.12's cap is
applied by `/resume` — by the student coming *back*. Nothing applied it when
nobody did.

A session holds its candidate's one slot while it is live or paused
(EC-6.13's `occupying_key`). Nothing released it when they left. So: pause,
close the tab, and **every future interview is refused, permanently** — with
"candidate already has a live session", about a session the student paused.
Proved before fixing.

EC-6.14 already specified the answer — "auto-close after 30 min; partial
report generated" — and had it scheduled for **day 11**. That is eleven days
of a door that locks behind you, and day 4's sweeper already runs every 30
seconds, so the fix is a query and a function. Two ways a session is
abandoned: paused past 30 minutes, or live and past its own planned length by
30 minutes (its clock already said the interview was over; the turn loop
never got a turn to notice on). The refusal now also names the status it
found.

Two of my own mistakes, both caught by the tests meant to catch them:
`time_remaining_s` clamps at zero, so the first live check was dead code; and
the first gate called `close_abandoned` directly, so deleting the call from
`sweep_once` left every gate green. The wiring is gated now.

**The pattern, worth keeping.** Both of today's findings came from reading
what the product *says* and asking what holds it up. The report's fairness
sentence had no AC; the pause's "five minutes" had no enforcement. Neither
was in the build order as a task, and both were shipped-today defects. It is
worth one pass per module.

### Day 8 — what landed

`agents/summariser.py`. The interviewer saw six turns and nothing else, so a
long round lost everything before turn fourteen — it asks about hashing again
because it cannot remember asking. §6.6's note is written every four turns
and **replaces** the dropped turns rather than joining them; joined, it would
be a context that grows with the session, which is what AC-6.10 measures.

- **Off the hot path, and before delivery in that task.** Delivery blocks for
  seconds on M13's ensemble, which measurably made the note land a turn late.
  Delivery also has a retry behind it (`sweeper.py`); the note has only the
  next answer.
- **Counted per round.** A segment transition clears it — carrying the last
  round's note across would have the interviewer open by referring to a topic
  it has just left.
- **Screened by the same guard as every interviewer line.** The prompt forbids
  judgement, `guard.screen` enforces it, and a note that telegraphs is
  dropped rather than repaired: a note with the verdict edited out was still
  written by something thinking about the verdict. No model → no note, never
  a stitched-up one.
- **AC-6.10**: the measured number is a harness run; what the suite holds is
  the mechanism that makes it true — the view is bounded by construction.

Two test mistakes of my own, both found by mutating rather than by reading:
the telegraph gate passed with the guard disabled, because `summarise_if_due`
returned False for not being *due* rather than for the note being bad — a
False from the schedule looks exactly like a False from the guard. There is a
`force_due` helper now and the gate asserts dueness first.

Verified live on a five-answer session: one note at turn 10, factual, naming
chaining, tree buckets, O(n) worst case and resizing, with no judgement in it.

### Day 9 — what landed

**Personas are data** (`personas/*.yaml`, `personas.py`) and **modes are one
table** (`modes.py`). The table used to be read from three places that each
knew one column — `planner.DEFAULT_PERSONA`, `outbox.ENSEMBLE_BY_MODE`, a
`final_boss` string inside `hint_offer` — which is how a fourth mode ships
with a hint button and no hints. Now everything asks `mode_config()`.

- **Seven personas, each a parameter vector with a mechanic behind every
  parameter** (Trap 7): `follow_up_aggression` is the ladder's depth (Meera
  stops at two follow-ups, Arjun goes to five), `patience` the idle timer
  (EC-6.1, day 11 reads it), `interruption_threshold` the once-a-round "let's
  keep it moving", `verbosity_target` the model's word budget, `hints_available`
  the button. `warmth`/`formality` live in the register and the authored lines,
  not in numbers a model would interpret differently each call.
- **Refused at boot, not at minute twenty.** A missing parameter, an unknown
  register, an unknown line name, or a line the guard refuses fails
  `load_personas()`, which the lifespan calls before serving.
- **A mock is a panel** (FR-6.3). Priya opens and closes, Dr. Raghavan takes
  the project, Sunita takes the people questions; **a new voice introduces
  itself** with its own greeting instead of a bridge, the way a real panel
  hands over. Final Boss is bar-raisers; Practice is gentle throughout.
- **Two voices meet at a crossing, and each says its own line.** The leaving
  interviewer closes the question, the arriving one asks the next. Getting
  that right found a real edge: a crash replayed after the crossing was
  committed handed the leaving exit line to the arriving persona. `speaker()`
  now reads the segment of the QUESTION being answered, which does not move.
- **Final Boss (FR-6.9):** no hints, the deepest ladder with two generic
  rungs, the shortest patience — and never rudeness: a `RUDE` list joins the
  telegraph list in `guard.screen`, checked on every persona line at load and
  every model line before it is said. Its hard clock (0% overrun) is day 10,
  so FR-6.9 is 🟡.
- **The guard reads the student too.** EC-6.6: recognised instructions are
  stripped before the strategist reads the answer (the student's text is kept
  as written — it is evidence, and M13 neutralises before scoring), and a
  flagged answer **moves no θ**, because an answer asking to be marked "above"
  must not be able to become an M05 observation. The guard tier (Llama Prompt
  Guard 2, 86M) runs **as a parallel LangGraph branch beside the strategist**
  and joins at `decide`, so it costs a turn nothing, and it **fails open**.
  EC-6.4: `abusive` joins the strategist's verdict (a model reads prose; a
  lexicon is the fallback) — one neutral redirect, then a polite end.
- **Practice's retry** (§6.1's table, §15.4): after a graceful exit the
  interviewer offers another go and waits; two buttons, not a typed "yes".
  The retry is recorded beside the first attempt and never scored, never an
  M05 observation, never ledger coverage.

**Measured live** (the real model and the real guard, 2026-09-30): the guard
scored technical answers 0.0004 and an injection 0.9995, in 247–366 ms against
a strategist at 732–941 ms — no added latency; turns 0.97–1.9 s.

**Found live, fixed:**
- **"Alright. Next. Next."** The bar-raiser register's exits said "next" and
  so did its lead — composed for the first time because Final Boss spoke the
  neutral register until today. A test now composes every exit with every
  lead and bridge, for every persona; it found a second one on its first run
  (Sunita: "Thanks. Let's move on. Thanks. Now I'd like to talk about…").
- **A follow-up judged against the original question.** "Each iteration is
  constant time" was judged `held` against "what if each iteration also loops
  over the array?" — the key points describe depth 0. `strategist-3` says a
  follow-up is judged as a follow-up; re-checked live, it is now a redirect.
- **"Set the band pass filter" read as an injection.** The day's own
  false-positive probe caught the rule pattern; it now needs a strategist
  field AND one of its values.

Thirteen mutations at the call sites, each caught.

### Day 10 — what landed

**Pacing is a scheduler, not an alarm** (`pacing.py`). One reading of the
clock — used, budget, the closing's reserve, what is still owed — and three
places that act on it, each at a question boundary, never mid-ladder.

- **70%** (§2.3): announced once. In the enforced modes, if more is planned
  than fits, the rounds are kept by M02's priority and the rest dropped —
  owed to M02 as `skipped` — and the interviewer says so with the next
  question: *"We have about 9 minutes left, so I'll focus on Stacks."* Practice
  says how long is left and changes nothing. Ahead of schedule, the ladder
  goes one rung deeper **from then on** (§6.9) — not for one round, because
  the check runs before the step's crossing and a per-round grant went to
  the round being left.
- **90%**: the closing takes over whatever is left of the plan (FR-6.17's
  "must always reserve the closing round"), and the rounds it skipped are
  owed to M02.
- **A round's own clock** (EC-6.9): 25% over in a mock, **0% in Final Boss**,
  which completes FR-6.9. The warm-up and the closing are exempt — one is a
  single question by construction, the other is the student's.

**The closing runs** (FR-6.21). It had `question_budget = 0` since day 5, so
"Anything you'd like to ask me?" was said and the session ended on it. Now
the student asks, the interviewer acknowledges and offers one more (two at
most), and "no, that's all" ends it. The questions are `closing.question`
events and the report's `your_questions`; they are never sent to M13 (there is
no rubric for a question — scoring stays ⛔) and never registered with M04.

**Re-planning** (FR-6.4, `replan.py`): at a segment boundary only, at most
twice, from `question.asked`, `probe.decided` and `idle.moved_on` — never an
M13 field, and a gate feeds it an evaluation saying the opposite to prove it.
Four triggers, in order:
- `time_overrun` — the next round is compressed; the closing is never touched.
- `struggling` — three failures at depth ≤ 1 in one round: the last round is
  dropped, the closing extended, and the rest handed to the gentlest persona.
- `gap_discovered` — two shallow breaks on ideas that share a prerequisite in
  **M04's graph** (`GET /v1/concepts/{id}`): the next round checks it first.
  No M04, no trigger: it never guesses a prerequisite.
- `ceiling_hit` — a stretch item answered above: one more question in each
  part that is left.

While the student is in the room they see only **what** changed, neutrally —
*"Adjusting — I want to check Arrays first."* The reason describes the
student, so it waits for the report (`plan_changes`); `GET /session` strips
the re-plans while live, and a gate pins it.

**M05 is seeded from M04's posterior** (§6.1 steps 3–4) at plan time, before
the availability probe — the posting's concepts only, and absent rather than
0.0 where M04 has measured nothing. Every CAT used to start at the prior.

**Found by the day's own tests, fixed:**
- **The boundary decided on a log one answer short.** The step selects the
  next question before its own decision is written, so three failures read as
  two and `struggling` fired as `gap`. The step's pending decision now goes
  to the selector with the state.
- **"I don't know" recorded as the student's question for the panel**, and
  "No, that's all." too. The nothing-to-ask matcher is a sequence of phrases
  now, not one.
- **Narrowing dropped every round** when no whole round fitted; it trims the
  top-priority round to one question instead.
- **The 70% focus line said in the same breath as the jump to the closing.**
- **The warm-up's own overrun fired a re-plan.**
- **Two plan changes in one step** (the 70% narrowing, then the boundary).
- **A docstring the code did not keep.** `enqueue_artifact` said "queued on
  the same condition as the evaluation" from day 4 and never checked it:
  every drill and retry answer was registered with M04 for nothing to cite.

**The mutation sweep missed six of sixteen on its first pass** — every miss
a test that could not fail, not a defect in the code:
- the drill and backup-set tests checked the evaluation queue and never the
  artifact queue, so the `enqueue_artifact` fix above was untested;
- the extra-depth test used a mock's interviewer, already at the cap of five,
  so "+1, capped" equalled the base;
- the 90% test checked the 70% line was not *said*, and not that the 70%
  narrowing did not *happen* — it would still have reached the report;
- nothing crossed 70% and a boundary in the same step, so the
  one-change-per-step guard was never exercised;
- the closing's own `scoreable` reason sat behind the backup-set check, and
  the warm-up's clock exemption behind its one-question budget.

Each is pinned, with a seventeenth for the extra depth's new semantics:
**seventeen of seventeen caught**. A fixture finding on the way: the
fallback playlist runs dry after four questions, so `day10.deep_bank()`
clones it with fresh ids for any test that needs a session to get through
twelve.

**Frontend.** Types for everything above; the notes render *How the plan
changed* and *Your questions for the interviewer* — the report's own note
promises both are there. The stage shows the newest plan note, and at the
closing an "Ask" button, its own placeholder, and no hint button.

### Day 11 — what landed

**Presence** (`presence.py`). In text mode a student is in the room while
their stage's event stream is attached, so the stream is the signal:

- **Gone.** The last stream detaching is noted in memory. Under five seconds
  it is a refresh or a blip and nothing is written — the student never left.
  Longer, and it becomes `connection.lost`, **dated when the stream went**,
  written by whichever comes first: the student's return or the sweeper's
  next pass. No timers anywhere — plain functions of `now`, so a test drives
  it without sleeping. The clock stops (§8, "Disconnected — timer paused")
  and the student's one pause is not spent on it.
- **Back.** The stream re-attaching writes `connection.resumed`, counts the
  reconnect, and restarts the clock after §6.8's 30-second grace. Any action
  — an answer, a hint, a pause, End — is a return with no grace.
- **Never back.** Away as long as an abandoned pause (30 min) and the sweeper
  ends it. A stopped clock never runs out, so without this the session
  would hold the candidate's one slot for ever — the lockout fixed before
  day 9, back through a side door. Gated.
- **`GET /resume-state`** (FR-6.13) is a pure read: the welcome line in the
  interviewer's own register (*"Welcome back — we were on question 2 of
  Data structures. Ready to keep going?"*, the number being the student's
  count of new questions in the round), the open question, the tail, time
  left, reconnects. A prefetch or a second fetch never counts a reconnect.
- **More than two reconnects** (§6.8's "modality-degradation suggestion"):
  text is already the floor in Phase 1, so the suggestion is the pause (if
  unused) or the end, with the notes keeping everything answered.

**Silence** (EC-6.1). The browser says *when* — it can see typing, the server
cannot — and the interviewer decides *what*: a gentle prompt, a second, then
the offer to move on, and never a fourth. Prompt *n* needs *n* times the
persona's patience since the line was asked, a floor so a page cannot talk
the interviewer into skipping a question early. The prompts are lines beside
the question, never turns: the answer box still answers what was asked.
Taking the offer records `idle.moved_on`; M02 hears `asked` and no
`answered`, M13 hears nothing, and the notes say *"we moved on from this one
after a pause"*, never a fail. Day 10's `struggling` trigger counts these as
silences, and that leg could not fire until today — a test now proves it does.

**The chaos suite** (AC-6.16, spec §12's five, in text mode):
- A worker killed at three points mid-turn: the decision is not re-made, and
  a fresh process carries on.
- The stream dropped at turn 15: the clock and the welcome are right.
- The provider down for 30 seconds: templates and the rule strategist carry
  it, the model is used again once it is back, and the session completes.
- Five refreshes: five clean resumes. Five quick refreshes count nothing.
- A pause at turn 20, resumed four minutes later.
- A retried answer is one answer.

`nothing_twice()` reads AC-6.16's three straight off the tables: no question
asked twice, no ledger row written twice, no evaluation queued twice.

**Smarter on the way.** Persona line placeholders are now read off the
register's own templates. A new templated line needs no validator rule, and
an override naming a field nothing fills — a `KeyError` mid-session — fails
the boot.

**Found on the way.** The test of the stream's presence wiring hung: a live
session's stream never ends, and the test client waits for it. The test now
drives the endpoint's generator directly.

Seventeen mutations at the call sites, all caught on the first pass — one of them in nine minutes, because the stream test waited on heartbeats. It is bounded by frame order now, and catches the same mutation in twenty seconds.

**Frontend.**
- The countdown stops while the feed is down.
- "Lost connection — reconnecting…" shows after 1.5 s, so a blip the server
  does not count never flashes a banner.
- The welcome appears only on a reload into a session under way, or on a
  return after a drop — never at a first start.
- The idle timer counts from the last keystroke.
- The idle line sits beside the question, and the offer brings *Move on* /
  *Keep thinking*.
- A moved-on question reads as one in the notes.

### Day 12 — what landed

**The degradation ladder** (`degrade.py`). §10 names the rungs and the
fallback for each failure; it does not say what moves a session between
them. Now it is what the session saw — model turns failing in a row:

- **L0**: nothing is degraded.
- **L1**: an upstream is down, covered by its fallback.
- **L2**: one failed turn, carried by a template or the rule strategist.
- **L3**: two running. The session **wraps up a little early**: the rounds
  after this one give way, M02 hears `skipped`, and §8's badge says so. This
  is one-way.
- **Panic** (EC-6.12): three running, and the model is not asked again. The
  circuit is a `NullLLM` the agents already fall back from, so a panic turn
  makes no call and writes no fake failure to the trace. Once a minute one
  turn goes through to the real model; when it answers, the session climbs
  back down. The cut plan stays cut, so the badge stays true.

Three properties hold whatever the rung:
- The levels are folded from `model.health` events, so they replay like
  everything else.
- The guard's outages are not the interview's: it fails open by design
  (EC-6.6), and it is excluded from the count.
- **The standard does not move.** An outage's answers go to M13 with the
  mode's own ensemble (AC-6.17). `n1_practice` stays Practice's and is not a
  degradation tool, because a templated question is still the same question.

**Everything fails** (§10, EC-6.11). The first crashed step is retried by the
next request, since the answer is already on the log. The second crash in a
row ends the session:
- it is `aborted`, with reason `system_failure`;
- the apology is said in the transcript: *"This one's on us: it doesn't
  count"*;
- evaluations still queued are voided;
- the notes are framed honestly.

Rows M13 had already scored stand. Those answers were given before anything
failed, and were scored like any other.

**M13's words in the notes** (its display gate): per dimension, once the
session is over:
- the evaluator's reasoning;
- the key points the answer did not reach;
- the student's own sentences that counted — verified spans only.

No number is ever copied: M13 owns them and the gate on them. A test fails if
`raw_score` or `calibrated_score` appears anywhere in the report.

**AC-6.9's number, from the log.** `GET /v1/interviews/reliability`
(staff only) reports, on the System page:
- disconnects, returns, and the rate against the 95% target;
- wrap-ups and panics;
- crashed steps, and sessions ended by failure.

**Found on the way.** Day 11's outage chaos test asserted "the model is used
again". With the ladder, three failed turns open the circuit, and a short
session ends before the one-minute probe — the ladder working, not a defect.
The test now asserts what §12 asks (the ladder engages, the session
completes), and the probe has a test of its own.

Sixteen mutations at the call sites, all caught on the first pass.

**Frontend.**
- §8's badge at L3 and panic.
- *"That one's on us."* on the end card.
- *What the evaluator noticed* under each question in the notes.
- The reliability card on the System page.

### Day 13 — what landed

**The route-client contract gate** (`test_client_contract.py`). `api.ts` has
said "one hook per endpoint, and no hook without one" since day 2, and
nothing checked it. The gate reads both sides — the frontend's source and the
backend's own OpenAPI document — and fails on either break:
- a route with no screen and no named caller;
- a hook calling a path the backend does not serve.

Routes that other modules call are listed with their caller (M01's drills,
M04's recent sessions, the trace harness, operations), and a third test
fails if that list names a route that no longer exists. Its first run found
its own blind spot: `@ai/core` spells DELETE `api.del`.

**§7's last three routes**, each named in the spec and absent until now:
- `POST /repeat` gives the open question **verbatim**. A rephrasing could
  change what is being asked, so it is never one, and it is never a turn,
  so the answer box keeps answering the question. It is recorded once per
  question for the trace.
- `POST /flag` is ⚑, forwarded to M05, which owns the item and stops
  selecting it (FR-5.19). The flag is recorded here either way, and
  `forwarded: false` tells the student the item has not been excluded yet
  rather than "thanks, done". Only an item M05 owns can be flagged. The
  test caught the first version letting M06's own backup set through:
  backup items carry ids too, so the check is the source, not the id.
  `M05_OWNED` is now one constant, shared with the report's scoring rule,
  which had kept its own copy of the same pair.
- `POST /switch-modality` fixes the contract now (FR-6.11). Text is a no-op;
  anything else is a 409 that names the module it waits on (M07, M08).

**The UI pass.**
- **Setup** offers the four modes from `/v1/interviews/modes`, which since
  day 9 are real and serve only mechanics the engine enforces. A job
  description handed over as `?jd=` (M02, M15) tailors the session and
  says so.
- **The plan preview** says who runs each part: *"with Priya, Senior
  Engineer · 8 min"*. A mock is a panel (FR-6.3), and the preview never
  said so.
- **The stage**:
  - the round by M02's name beside the question count;
  - a pause that asks before spending the student's one pause;
  - *Repeat the question*, with the words shown nearest the box;
  - *⚑ Flag*, with three reasons and an honest answer.

Already true and kept: banners are `role="status"`, the timer is announced at
10/5/1 minutes, every control is a labelled button, and layouts wrap at
phone width.

Four mutations at the new call sites, all caught.

### Day 14 — what landed

**The scripted student** (`test_scripted_student.py`, spec §12). Twenty full
sessions across the four modes, driven by recorded answers and a seeded
strategist, so every path is taken somewhere:
- holds and breaks;
- Practice retries taken and declined;
- hints;
- an injection attempt the guard flags;
- the closing asked and then declined.

Per session it asserts:
- the session ends on its own (AC-6.5);
- a report is built (AC-6.1);
- the trace replays to the same state (FR-6.19);
- nothing is done twice (AC-6.16);
- model calls per answer stay inside §11's budget.

Across the twenty it asserts AC-6.6 (a break found in ≥ 80% of sessions)
and AC-6.7 (≥ 90% of the plan's requirements asked about). It passed on the
first run, so it was probed before it was believed: 11–29 answers per
session, 3–4 round crossings, up to two re-plans — not a vacuous pass.

**The manual QA script** (`plan_in_depth/M06_QA_SCRIPT.md`): §12's 15-minute
release check, in text-mode form, with the exact copy each step must show.
It is written; nobody has run it yet.

**The full chain, live** (2026-10-02). M02, M04, M05, M06 and M13 ran as
five services with a shared service secret, so M04's guard was on, and the
real model asked the questions. The session:
1. Consent was recorded in M04, and a real posting was parsed by M02.
2. The session was planned on that posting.
3. Four answers were given: probes, a redirect, a graceful exit and a
   bridge, all from the live model.

Then, by module:
- **Delivery.** The outbox delivered 4 artifacts to M04, 4 evaluations to
  M13 and 3 ledger rows to M02.
- **M13** scored every answer, with `calibrated_score` still `None` — the gate
  closed, as it should be.
- **M04's skill graph moved**: hashing (4 direct), time complexity (3),
  hashing internals (1), and propagation to arrays and control flow. θ was
  low, correctly — the scripted answers were off the question.
- **M02's ledger** holds `asked` with M13's scores beside it.
- **The guard held**: an anonymous read and another student's read were both
  403, and theta without the service secret was 401.
- **The notes** carried M13's own words — *"The answer is unrelated to the
  prompt…"* — and no number.

**Found live, fixed:** M02's first plan for a posting took 4.7 s, and M06
waited the 3 s a turn's call is allowed. So every session fell back to the
even split and told the student *"the planner is offline"* while it was
up. No module's own suite could see it, because each tests against fixtures.
The plan is built once, behind a spinner, so plan-time M02 calls now get
20 s (`PLAN_TIMEOUT_S`), pinned by a test.

**Observed, not a defect:** the live strategist judged an explanation of
hash tables as off-question for *"elaborate on why O(1) given those
conditions"*. It is a judgment call, logged for the first human-evaluation
round (§12), which is where a judgment like that gets measured.

### Day 15 — what landed

**The asks, raised where their owners will read them.** Every open row in §7
went into its owner's `main` TODO and the umbrella copy, as a dated
*"asks from M06"* note in the style M05 and M13 already used for M06's
earlier seams:
- **M02** (`cde74e6`): the 4.7 s first plan; the `?jd=` link; the ledger
  docstring.
- **M05** (`7b0bbf4`, `e9d3161`): the unguarded ⚑; EC-5.9's retraction;
  `difficulty_offset`; per-round-type counts.
- **M13** (`9e4c6c7`, `40c1846`): its words are student-visible now; the
  artifact ids; `push_back`; `cs_core` and communication.
- **M04** (`265774f`): `recent_sessions`, and the live confirmation of its
  guard.
- **M15**: the `?jd=` link — in its local plan copy, which its repo does not
  track.

The owners' `todo` branches were last synced on 2026-08-27, and rebuilding
them is theirs to do.

**This TODO, reconciled against shipped code.**
- EC-6.5 was ✅ since day 7 and still said "day 7".
- EC-6.16 has been enforced and tested since day 5, and was marked ⬜.
- FR-6.11 and FR-6.19 now say what day 13 and day 14 added to them.
- The completion figure was recounted from the table rather than carried
  forward: **87%**, 20 met and 5 partial of 26.

**Human evaluation, round 1, prepared**
([M06_HUMAN_EVAL_ROUND1.md](M06_HUMAN_EVAL_ROUND1.md)):
- ten students, split six Mock / two Practice / two Final Boss — Final Boss
  because AC-6.12 is most at risk there;
- the verbatim briefing, and seven questions in a fixed order;
- consent twice: on paper, and in M04 with purpose `research`, which the
  product's `practice` does not cover;
- what to export on the day, and how a reported moment is found in the trace.

### 2026-10-04 — the interview room, for a student

- ✅ **The room is a conversation**: the interviewer's lines sit beside their
  face, the student's words in their own bubble; the header holds persona,
  status and clock; the answer box stays in reach. Still no score, no marker,
  no bar (§2.2). The notes open with "Session complete".
- ✅ **Answers can be spoken** — the browser's speech recognition (Web Speech
  API) puts words into the same answer box, edited before sending; filler
  words are counted, not judged. **Input only**: the interviewer does not
  speak, and the spec's voice (FR-6.10, FR-6.22) is still M11's. A code mode
  too: monospace, Tab indents, sent fenced.
- ✅ **A focused interview focuses**: `POST /v1/interviews` takes
  `focus_concepts` (up to three) and a label. With no job description the plan
  is one segment on them; they become M05's coverage debt and M04's posterior
  is seeded for them.
- ✅ **Pauses: one per 15 planned minutes**, each ≤ 5 min — a deliberate change
  from FR-6.12's "once"; the spec row has not been revised. Each pause and
  resume has its own event key (the second pause returned the first's
  idempotent event).
- ✅ `GET /v1/interviews/stats` counts this week's interviews and students,
  never anyone. The report carries each question's concept, topic and first
  turn, so the notes offer "practise this topic again".
- ✅ The notes give each answer Strong / Partly there / Not yet from the key
  points it reached; M13's "not reached" ids are read back to their statements.
- ✅ A first interview defaults to 15 minutes of Practice; `?minutes=` and
  `?mode=` are honoured. A screen reader hears each new interviewer line, and
  the room has a heading. The personas have drawn faces.
- No requirement moves; FR-6.10 gains an interim input half.

### 2026-10-05 — the interviewer speaks

- ✅ **Each line of record is read aloud** in the voice its persona file names
  (`voice_id`, `en-IN-female-warm`): the browser's own speech synthesis, which
  in Edge includes neural Indian-English voices. `voice-core.ts` chooses the
  voice — exact locale, then neural over robotic, then the persona's kind
  before its accent — and makes text speakable (code and links are on screen;
  O(n log n) is "O of n log n"); `voice.ts` speaks it a sentence at a time
  (Chrome cuts a long utterance off), queues lines so an acknowledgement is
  not cut off by the question behind it, and stops when the mic opens, the
  answer is sent, the session pauses or the student ends it. One button turns
  it off, remembered for the browser; a browser that blocks sound until a
  click gets a "Hear Meera" button. `npm test` pins the logic (11 tests).
- ✅ **The face talks**: a ring while the interviewer speaks, and the mouth
  opens on each word the voice reports (a gentle loop for voices that report
  none), drawn per frame without re-rendering the room. Reduced motion keeps
  the ring and stills the mouth.
- ✅ **The persona card carries `voice_id`**, and its shape is checked at load
  (`locale-kind-manner`) — two tests. The seven personas' ids were authored in
  August and read by nothing until now.
- ✅ **Speech recognition is Indian English** whatever the laptop reports —
  most report en-US even in India.
- ✅ **Fixed: a first start was greeted "Welcome back" and its opening went
  unspoken.** The plan screen's redirect (session went live) raced Start's own
  navigation and dropped `justStarted` when it landed second; 2026-10-04's fix
  covered only the other order. Both navigations now carry it when the start
  was this page's.
- Verified in a headless Edge: Meera → "Microsoft Neerja Online (Natural) -
  English (India)" at 0.97; first audio ~1.1 s after the line lands (the online
  voice's fetch); word boundaries reported; the mic, End and the off switch
  silence it.
- **A caveat recorded for M12:** recognisers delete filler words, the browser's
  included, so the live filler count (2026-10-04) is a floor. It is said as a
  count, never a judgement, which keeps it honest; the measure is M12's.
- What stays M11's: streaming the first clause, a VAD-driven barge-in within
  350 ms, server ASR with word timestamps, Kokoro for browsers without a neural
  voice, lip-sync from the audio itself. See M11's Revision 2.

### 2026-10-06 — the panel: seated from data, and talking

The user's words: *"intro from all the panelists at once, then one of them
starts, hands control to another, hands back to the previous if needed, else
continues with the flow as planned — a multi-interview experience, not
hardcoded, smartly managed"*, and *"sometimes another interviewer interrupts
while you're answering — realism is the key to victory"*.

- ✅ **The panel is seated from the personas' own data, not a table per mode**
  (`panel.py`). Each mode says what kind of panel it is as numbers — a target
  warmth / patience / follow-up aggression, with bounds nobody outside may
  cross (Practice never pushy, Final Boss never warm); each persona says what
  it knows (`domain_bias`, title, style); each part says what it is about (its
  kind, title, rubric, concepts). The lead — closest to the mode's temperament
  — opens and closes; an expert the panel lacks joins for the part they know;
  the panel grows with the interview (2 at 15 minutes, up to 4 for an hour);
  two or more parts always seat at least two people. Authoring a persona
  changes the panel; a test authors one (a database engineer) and watches her
  take the SQL round.
- ✅ **A panel of one gets someone sitting in** (`panel.sit_in`). A plan with
  one round of its own — no job description, a focus session — seated one
  interviewer for half an hour, which reads as one bot. A real round is often
  two at the table: the second persona that fits the mode is introduced and
  comes in with a follow-up on about every other question. The plan records
  its `panel`; the preview names anyone sitting in.
- ✅ **The panel talks.** The opening introduces everyone before the first
  question (the lead greets and names the others; each says hello and what
  they will ask about, in their own voice). A round's end is a hand-over in two
  voices ("Dr. Raghavan, over to you." / "Thanks, Priya. Let's turn to the
  next part: your projects."). A panelist who knows a question's topic clearly
  better than the asker comes in with one follow-up at the second rung, once a
  round, and the asker takes it back ("Thanks, Dr. Raghavan."). A long answer
  is cut short by whoever on the panel ran out of patience first — not always
  the asker. The panel closes as "we", and the lead says goodbye whoever was
  asking. Seven new lines per register (`panel_greeting`, `panel_hello`,
  `panel_sitting_in`, `hand_over`, `take_over`, `interject`,
  `panel_to_closing[_early]`), screened by the same guard at boot.
- ✅ **Every interviewer line records who said it** — `speaker_id`, and `parts`
  when more than one voice said it; events from before read the speaker off
  the segment. The room shows each part under its own name and face, the
  header shows the panel with the speaker lit, and each part is said in its
  speaker's voice (`@ai/core` v0.17.0–v0.17.1: M11's cast voice, or the
  browser's by `voice_id`).
- ✅ **Fixed: an arriving interviewer's first question went out under the
  previous one's name** — since day 9. The selector named who asked the LAST
  question as the asker of the next, so the arriving interviewer's own lead-in
  was never said. `arriving_speaker()` reads the segment now running.
- ✅ **Fixed: every line was labelled with the CURRENT interviewer's name**, so
  a hand-over relabelled the whole transcript. Found by the first headless walk
  of a panel; no test read the labels.
- ✅ **§6.4's recovery posture stays on the panel**: the rest of a hard session
  goes to the warmest person the student has met, or to the gentlest persona
  the mode admits — not always to one hardcoded persona nobody had introduced.
- ✅ **Faces follow the persona file's declared voice kind** — Arjun's male
  voice was under a face with long hair.
- Verified in headless Edge with M11 running: a Mock's and a Final Boss's
  opening, three parts in two cast voices (Priya `chatterbox-default`, Arjun
  `indictts-022743`, Vikram `indictts-063175`), the strip lighting whoever
  spoke. 442 pass (+17).
- **Found on the way, fixed in Core:** "Dr. Raghavan, over to you." was split
  after "Dr." — a voice said "Dr." alone and paused, and M11 made two clips.
  And a line's sentences were all asked of M11 at once; M11 makes one at a
  time, so the last could be made first (the opening waited five seconds for
  its first sentence). Now asked in speaking order (v0.17.1).
- **Next, M11's:** an interviewer cutting in while the student is SPEAKING
  needs streaming speech (M11 day 3 on: VAD, then ASR). The text-mode cut-in
  above is its stand-in. Long term (the user): question sources per expert.

### 2026-10-06/07 — the panel, heard live end to end, and what it found

A whole mock in headless Edge with every service running (M01, M02, M04, M05,
M11, M13): a model-written student answering the question actually asked,
typed until the round came back to the lead, then SPOKEN into a microphone
stream the script controls.

- ✅ **Heard live, as the user asked for it:** the panel introduced first,
  each part on screen only as its speaker began (Priya at +0.6 s, Dr. Raghavan
  at +5.3 s, Priya's question at +8.8 s); the hand-over ("Dr. Raghavan, over
  to you." / "Thanks, Priya…") and the hand-back ("Priya, over to you." /
  "Thanks, Dr. Raghavan…"), each in the speaker's own cast voice
  (`chatterbox-default`, `indictts-103607`); follow-ups on the student's own
  resume claims; spoken answers heard, judged finished (Smart Turn 0.96) and
  sent; "okay" / "I see" said softly while the student spoke (five times);
  and the lead closing. No page errors.
- ✅ **Fixed: the same question three times in one interview** (M06 `26f987e`,
  M05 `897748d`). M06 sent the student's whole history as M05's hard "never"
  filter as well as its freshness filter, so M05 could not relax freshness and
  fell to a playlist that ignored what the session had asked. Now
  `seen_item_ids` is this interview's questions and `recent_item_ids` adds the
  history (M05 §6.6); a repeat offered anyway is refused; M05's disclosure for
  a deliberate re-ask ("You've seen this one before…") is said with the
  question — it had been dropped since it was written.
- ✅ **Fixed: "Take your time." the moment a spoken answer ended** (`779146c`).
  The idle count ran through the question's synthesis and the whole answer —
  only keystrokes reset it. It now starts when the interviewer stops and the
  student is quiet; any speech starts it again.
- ✅ **Fixed in Core v0.24.0: a student explaining in three sentences was
  answered after the first** — a ~700 ms pause after a complete sentence. A
  long answer now gets a full second before the turn model is asked, and a
  turn taken too soon (the student carries on within 1.5 s) is learned from.
- ✅ **The room on M11 days 11–12** (`870f184`, `spokenRoom.ts`): the
  interviewer answers no sooner than a person would (the speaker's own gap,
  from patience; Final Boss sometimes holds a silence); a fresh line appears
  as it is said; backchannels by warmth, never in Final Boss; the note-taking
  line then 1.5 s of quiet (`fda446f`); the interviewer's own voice coming
  back through the mic is not sent (twice → hold-to-talk); Talk freely off
  mid-answer keeps what was said; hold-to-talk by choice, on a poor connection
  or after two drops; two answers nobody could write down → typing; an answer
  heard but not written is asked for again aloud by the asker; spoken answers
  kept with consent and played back in the notes.
- Earlier the same day, all from live walks: "Sorry, I didn't catch that" on
  a low-confidence answer and unsure words never quoted (`3eeb88d`); the
  project round reads the CURRENT resume (`eb88907`); recovery hands the
  session to someone gentle, or keeps the panel (`80fbf2d`); nobody closes a
  question the same way twice running (`364719e`); joining midway is a
  joining line, not an opening (`fbc0fa4`); what the student heard of a line
  they cut in on (`7b67a60`).

- ✅ **"No, that's all from me. Thank you." is nothing to ask** (`2b6fec0`).
  Two live runs filed it as the student's question for the panel ("That's
  one to ask the real panel"): the closing matched a phrase list and "from
  me" was not on it. Now an answer with no question mark made only of closing
  talk, in any order, says nothing to ask.
- ✅ **"Did you say quick sort or quick select?"** (M11's FR-11.16, `28fdc2e`,
  `clarify.py`). A word the recogniser was unsure of, near a term that decides
  the answer, is asked about before anything is judged — once a question,
  three a session. The decisive terms are the question's own (key points,
  each rung's expected points, label, stem); never asked when what was heard
  is one of them, or the same word with an ending. The reply is judged with
  the answer it clarifies, and M13 and M04 get both together, the unsure
  words still unquotable.
- ✅ **A question spoken over from its start is put again** (M11's EC-11.1,
  `28fdc2e`): an answer given before most of the question was heard is not
  judged against it. The room yields aside ("Sorry — go ahead.").
- ✅ **Thinking while the student pauses, strictly** (M11's FR-11.6,
  `8152191`, `prefill.py`). The user's rule: *"the reply should be based on
  what the answer is, not assume what he/she is gonna say"*. A prefill runs
  the step in memory on what has been said so far and keeps each model answer
  by its exact request; the real step uses one only for a byte-identical
  request — exact words, same state. Pinned: no second model call, and the
  same line as without a prefill; one word more and the model is asked.
- ✅ **A phone call takes the microphone** (M11's EC-11.12, `7846920`): the
  clock stops as for a lost connection; no pause spent, no reconnect counted;
  the room counts five seconds back in and asks the question again.
- ✅ **The room on Core v0.25.0** (`364bef9`): prefill at pauses, captions
  from M11 where the browser has none, offline answers kept and sent when the
  network is back, a Bluetooth note.

### 2026-10-07/08 — the user's feedback round: tracks, skips, 39 interviewers, faces

The user sat interviews and listed what felt wrong. Each item, as fixed:

- ✅ **"An ML interview asks DSA and my resume"** (`b4ba15c`, `cac1b10`). The
  track the student picks on the setup page is the only round type the
  session asks about; questions from the resume come only when they opt in,
  from the resume they pick. Every track is offered to every student — the
  profile no longer decides what can be practised. A track the bank holds
  only drafted items for (M05 FR-5.6) is practised and never scored or moved
  θ for, and the notes say so (`m05_draft`).
- ✅ **"Fifteen minutes should be five to seven questions"** (`b4ba15c`): two
  minutes a verbal question; the closing is 10% of the session, two to five
  minutes; a mixed interview is a few real rounds, not one-question samplers.
- ✅ **Skips** (`cac1b10`, `141d15c`): a skipped question is replaced; skipped
  twice at one number it is left, and costs that question's points in this
  interview only. **The user's call (2026-10-08), from the student's side:**
  a skip never lowers the saved skill graph (not answering is not evidence),
  and a skipped question stays out of that student's interviews for 180 days.
- ✅ **"Interviews feel repetitive"** (`908798e`, M05 `e62ddee`): M06 tells
  M05 what this interview has asked (`asked_this_session`); M05 avoids the
  same concept twice running, halves a concept's weight per repeat, and
  pushes away a stem much like one already asked.
- ✅ **"Only Priya and Raghavan, every time"** (`9b836a5`, `4f72e17`,
  `f2c0a33`): 39 interviewers, three or four per domain, seated from their
  data, rotated by the session and away from whoever the student met
  recently, never two of one voice at a table; exits read per speaker.
- ✅ **Voices: 37 of 39 Indian** (`5008437`, M11 `62c4a0b`) — a foreign accent
  only for Priya and Kabir, as the team cast them. All nine new voices passed
  a read-back probe (WER ≤ 0.18).
- ✅ **Rephrase when asked; the closing explains** instead of "ask the real
  panel" (`a19218e`).
- ✅ **"The voice starts 5–6 s after the text"** (`30e4418`): the opening is
  made while the plan is read (`GET /interviews/{id}/opening`, Core
  v0.27.1 `prepareLine`).
- ✅ **Faces** (`f5d487b`, `e38e6ef`; Core v0.27.0 → v0.28.0; M11 `a339fb6`,
  `b2f8cc3`): each interviewer is a 3D head — an AI-generated portrait
  (FLUX.1-schnell) lifted by LAM — labelled AI, lip-synced from the voice's own
  audio (wav2arkit, 52 ARKit blendshapes at 30 fps); the drawn face stands in
  until a head loads, or where WebGL is missing. Measured in the room: the
  mouth each head is given is the frame for its audio's own time, exactly,
  once playback starts; a listener's mouth stays shut; a mouth closes within
  0.4 s of the speech ending; heads blink and nod. Offline, over eight voices,
  the mouth opens a median 83 ms before the sound, as natural speech does.
  Heads are built on the machine (M11 `scripts/make_faces.py`, ~8 min each),
  not committed.
- ✅ **A track the bank cannot serve says so** (`7605840`): it stays on the
  plan, left out, with the reason — it had quietly become a warm-up and a
  goodbye. An unknown track id is refused with a 422.
- ✅ The notes call a resume question and a backup question what they are
  (`e8b02aa`).

### 2026-10-24 — notes a student can trust: the user's 8-section brief

A correct, a vague and a wrong answer looked alike in the notes. The full
report — root causes, the model comparison, twelve bugs with their tests, the
security review — is [M06_NOTES.md](M06_NOTES.md). Platform_Core `5682d0d`
(v0.40.0); this repo; Platform_Shell.

- ✅ **One status per question** (`report._status`): correct, partial,
  vague, incorrect, unanswered, unsupported, not judged, not reached — from
  how the interview left the question and every judged answer in the thread.
  Code decides it; no model can change it.
- ✅ **Each answer explained** (`notes_writer.py`): what held (quoted), what was
  missing or wrong (with a fix), the misconception and the right reasoning,
  a model answer, next steps. Checked before it is shown (quotes are the
  student's, no praise for a wrong answer, a correction for an incorrect one,
  no generic advice), stored per question by brief hash, written after the
  session, polled by the page.
- ✅ **The writing tier on NVIDIA NIM**, chosen by measurement
  (`Backend/research/notes_models/RESULTS.md`): minimax-m3.1-flash, Groq
  gpt-oss-120b as the fallback; after one failure a run skips NIM. Live: 4
  write-ups in 45–50 s; a refused key and a 429 both fell back at once.
- ✅ **The page rebuilt around the status**: colour + shape + word per
  status, the student's answer first, the rubric marked ✓ / ✕ / – in a neutral
  frame, a distribution (never a score), what to work on first, filters. The
  shell's My answers and Today show the same badge.
- ✅ **Found by the audit and live runs, fixed with tests**: the rubric
  un-covering what an earlier answer reached (last answer's list won); a
  missed key point listed twice; "Writing…" kept after polling stopped; a
  hanging NIM costing 90 s per question; an ai_core without the tier taking
  every model job down; a `not_judged` answer sent to the writer; background
  calls on the hot-path pool; fenced JSON refused; one quote under every gap.
- ✅ **Frontend tests exist**: vitest 4.1.12 (3.2.x carried critical
  advisories), Testing Library, jsdom — 31 tests of the states and rules.
- ✅ **"Incorrect in a follow-up"** — the user's call, 2026-10-24. A story
  that covered every point, then a wrong idea that stood in a follow-up, read
  "Incorrect" beside a full ✓ rubric. When the opening answer held, the label
  and detail now say the follow-up is where it went wrong; the status, the
  colour, the counts and "work on first" stay incorrect (`report._incorrect`).
  Live: session C, Q1.
- ⬜ **Rotate the NVIDIA key** — pasted in a chat; the user's to do.
- ⬜ **NIM's free tier throttles** at about ten calls in two minutes, so a
  cohort's notes would mostly come from Groq: pace a queue or pay for NIM.
- ⬜ **Notes rated by people** — the checks are necessary, not sufficient.

### 2026-10-22/23 — the realism overhaul: the user's 19-section brief

The interviewer judges an answer before it speaks, and says what it decided.
The full report — root causes, fixes, the evidence behind each design choice,
and the brief's acceptance criteria one by one — is
[M06_OVERHAUL.md](M06_OVERHAUL.md). M06 `8108fa9`; M13 `f673f90`; M05 `bb4b3fe`;
M01 `f8ad4e8`.

- ✅ **A wrong answer is challenged, not followed deeper.** The strategist
  (`strategist-5`) says what an answer is — eleven categories, a severity,
  and the student's own words as evidence — and `ladder.decide` picks the move
  from that in an explicit order, with a reason on every decision
  (`probe.decided`, the trace). The interviewer only phrases it (`react()`),
  in the move's tone: a challenge may doubt and may not praise.
- ✅ **Difficulty per topic, for this interview only** (`difficulty.py`): a
  level per concept from its last two answers, drifting back to 0. It sets
  how deep, from which angle, and where M05 pitches the next question on that
  topic — never θ, never kept.
- ✅ **One thing at a time** (`decompose.py`): a stem that asks several things
  is split once, cached, and asked as a question and its follow-ups.
- ✅ **One evaluation per question**, of the student's words only, the pushes
  it needed priced like hints (M13 `prompts_used`), against the key points
  actually asked (`key_point_ids`).
- ✅ **Notes from what was said**: quotes and why, corrections, the claim
  check, a study list, the last attempt compared. The summary is built from
  the questions, so the two cannot disagree.
- ✅ **A question library** (`/mock/library`): starred and flagged, kept
  apart; every attempt kept; chosen questions practised again.
- ✅ **A resume interview** (track `resume`), **filler notes** (`delivery.py`),
  and **a drill that ends** (`/end` twice is fine, a live drill gives way to a
  new session, M01 explains M06's 409).
- ✅ **Found by running it live, and fixed** — each with a regression test:
  - "Focus: Hashing" asked "tell me about a time…", then drifted: the round
    was planned under every track and asked under the first alphabetically,
    and M05 treated the focus as a preference. Now: the tracks that hold it,
    and M05's `only_concepts`, never relaxed.
  - A redirect after a clarify repeated the clarify.
  - The notes gave an answer to another question a misconception, and a
    non-resume line "the number, the baseline and how you measured it".
    Findings now come only from judged answers; the resume wording only from
    resume lines.
  - With the model down, every question read "Answered well". Now "Not
    judged". The rule fallback hears "I'm not sure, I don't know this one" and
    leaves "I don't know the figure, but…" to the model.
  - "Walk me through this project" was asked about two resume lines with
    nothing to say which. A question that does not name its line now reads
    the line out.
  - Second round, with the model and the pages: a correction after a
    pushback relabelled "corrected yourself" by the next right answer, and a
    settled contradiction counted the same way; a vague answer given a
    "misconception"; the last answer of every part never reaching its topic
    (the new part was recorded before the decision); a claim's id as a topic
    name in the summary; "practise <resume line> again" planning an empty
    interview; the same point listed twice. All fixed, each with a test.
- ✅ **"Um" and "uh" are counted** (`11ec08c`; M11 `7043463`): Whisper had
  dropped every one, and now keeps about two in three because M11's prompt
  is written the way people talk. Nothing is invented. The delivery note
  names them when they dominate an answer, and the summary says how much is
  measured.
- ✅ **The library is in the shell's menu** under Progress (Platform_Shell
  `main` 00b5f15, `feat/gd-entry` 389f7c5). The menu lights the most specific
  item, so "Mock interview" no longer lights on the library.
- ⬜ **Still thin, and not M06's to fix:** no bank item has authored
  follow-ups, and 12 items are reviewed, all DSA (§7).
- ⬜ **The 429 policy** (2026-10-17 below) is still the user's call; the live
  runs used one key.

### 2026-10-22 — what the demo can claim: follow-ups, adaptivity, scoring

An audit for the demo reference (`Final_Year_Project/demo_interview.md`,
untracked), against M06 `9769401`, M05 `7634858` and M13 `77ead37`. No code
changed. The engine does what it was designed to; what it has to work with is
thinner than the pitch.

- 🟡 **Follow-ups on bank questions are generic.** No M05 item has
  `follow_ups` (12 reviewed, 292 drafts), so every rung is
  `phrasebook.GENERIC_RUNGS` reworded around the student's words, and
  `Persona.max_generic_rungs` caps them: 1 interviewer asks none, 33 ask one,
  6 ask two. The "probe until it breaks, up to depth 5" ladder runs only on
  M01's drills and resume probes. The fix is M05's data (§7). _2026-10-23:
  the interviewer now decides what to ask from what the answer was — a
  challenge, a simpler question, a request for specifics, the next part —
  and angles a deeper one by the topic's level; the content of a deeper
  question is still generic until M05 authors follow-ups._
- 🟡 **The next question adapts to the answer on DSA only.** θ is observed only
  for `m05_bank` items (`_record_decision`), and only 12 items are reviewed —
  11 `dsa_verbal`, 1 shared with `dbms_verbal`. On every other track the next
  question follows coverage, history and position in the round, not how the
  last answer went. It is per concept too: M05 penalises repeating a concept,
  so one answer mostly moves later questions on the same concept. The fix is
  reviewing drafts (M05's FR-5.6 queue). _2026-10-23: on every track, the
  next question on a topic is pitched by that topic's level in this
  interview (M05 `difficulty_offset`); θ still moves on reviewed items only._
- ✅ **Notes show unreviewed key points as the answer.** For a drafted item,
  "what a strong answer covers" (`report.py`) lists key points nobody has
  checked. Label them as unreviewed, or hide them for `m05_draft` — the user's
  call. _2026-10-23 (`8108fa9`): labelled — "a newly written practice question
  nobody has reviewed yet", its strong answer "not yet reviewed by a person"._
- ✅ **The checklist under a strong answer can be wrong** — M13's, not M06's
  (§7). When the evaluators list nothing missing, M13 fills the list from its
  word-overlap measure, which marked a correct paraphrase of the hashing item
  as missing all three key points. _Fixed in M13, 2026-10-23 (`f673f90`)._
- ⬜ **The README is stale.** It says "days 1–3" and 147 tests; today it is
  570 tests, 81 gates and 42 routes.

### 2026-10-17 — a decision: two keys, two organizations?

- ⬜ **Key rotation and Groq's policy — the user's call.** M06's `KeyRing`
  cycles the two `GROQ_API_KEYS` and retries a 429 on the next key. Measured
  on 2026-10-17 from the rate-limit headers, the two keys have **separate
  quotas** (8,000 tokens/min and 1,000 requests/day each, per model), and Groq
  applies limits per organization — so they are almost certainly two
  organizations. Groq's Acceptable Use Policy (effective 2025-10-15) forbids
  use "beyond published parameters, rate limits, or use limitations, including
  by registering multiple accounts or orchestrating usage between multiple
  organizations." If they are two organizations: one key per running platform,
  and headroom from spreading jobs across models (each has its own bucket) and
  pacing. Switching keys because one is revoked or down is fine; retrying a
  429 on another organization's key is the forbidden part. Same decision in
  M13 and in Platform_Core's `ai_core.models`.

### 2026-10-13/16 — interviews drawn from the student's courses; each interviewer in an office

- ✅ **A mixed interview is drawn from the student's courses** (`135b584`):
  with no posting, track or focus, the planner reads M04's `/coursework` and
  keeps only the tracks those courses fill — a track counts when the courses
  cover at least a part's worth (three) of its concepts, so first-year
  maths' linear algebra does not make a machine-learning round. Each part's
  concepts become M05's coverage debt (a preference, never a filter), and
  M05 is seeded with M04's estimate on them before the first question. Live:
  a CSE-AI third-semester student who has sat OS, DSA and networks gets
  those, not machine learning. With a posting, a track or a focus the plan is
  exactly what it was.
- ✅ **A course's practice is up to eight concepts** (`focus_concepts`, was
  three): Today's course card sends its syllabus's concepts, and eight is the
  most the ontology's sizing rule says one session can test. `?focus=` takes
  a comma-separated list, and the choice is named "Course: <title>".
- ✅ **The setup page** (`47d1d87`): six interviewers and "Show all 39"
  instead of five screens of them; titles and explanations wrap; a row of
  cards is top-aligned; unreviewed tracks say "not scored" (the "practice"
  chip read as the Practice mode).
- ✅ **Each interviewer in their own office** (`ed1924b`): `@ai/core` v0.37.0,
  abhinav's office backdrop. The photo tiles pass `backdrop`, so the room is
  the same before and after a head loads, and captions keep the name whole.
  Checked with WebGL in two fresh sessions.
- ✅ **One underline slides between Conversation and Notes** (`840b863`).
- No requirement moves. Counted 2026-10-17 by running the suite: **564
  passed**, **81** gates.

### 2026-10-12 — abhinav's room and second interviewer, merged

- ✅ **The room as a call** (`2bbcba5`, abhinav): the student's own tile
  (camera off unless turned on, never sent), the current question large,
  the conversation and private notes in tabs, the question's details,
  progress dots. At 1440×900 the faces, the question and the answer box are
  all on one screen. Then fixed (`b1fb81c`), measured at 1280×680: the
  header one row (106 → 62 px) with its height published (`--room-head`),
  the tiles and the conversation pinned under it, 16:9 tiles under 800 px
  high — the faces stay while the answer box is in view; the conversation
  at reading size (the question large once, in its card); the camera an
  icon in the tile's corner.
- ✅ **The second interviewer takes the first follow-up of about every other
  question** (abhinav).
- ✅ Persona voices from the listening-test cast; os_karan and professor
  were still on the voice it removed. With eight voices for 39 an engineer
  took a behavioural part over the seated expert: a newcomer who knows a
  part less than the panel is now marked down (`panel.assign`).
- ✅ Pins `@ai/core` v0.34.0 (identifiers and notation said as people say
  them).

### 2026-10-11 — replies no longer held by a slow model; candidate questions made in turns

- ✅ **Wall-clock deadlines on the strategist and the guard** (`cdceaff`): a
  live run's replies took 8+ s in M06 because those two calls took 6.7 s and
  6.3 s against 4 s and 1.5 s timeouts (`urlopen` bounds each read, not the
  call). Past the deadline the guard fails open and the move comes from the
  rules. Every step of a turn logs its time. Now 0.76–0.95 s.
- ✅ **The questions the room may ask next are made a piece of each in turn**
  (`eaa4779`, Core v0.31.0 `prepareLines`).
- ✅ Pins `@ai/core` v0.31.0 (no voice lost while M11 is still loading).

### 2026-10-10 — the room on a wide screen: the panel beside the conversation

The user: *"when we scroll down to see the question we lose the interviewer's
face; there is a lot of space"* — and *"forget phone first, we need desktop"*.

- ✅ **Two columns on a wide screen** (`c6055df`): the panel sticks beside the
  conversation; the one speaking (or whose turn it is) large, as a call
  shows the speaker, the others small beneath. Tiles change size, never
  place, so no 3D head is made again at a hand-over. A short window gives
  up the large tile's height first. Checked at 1440×900 and 1280×680.
- ✅ **The status strip** is opaque and flush under the app's bar (lines read
  through it before); its small faces only where the tiles are not beside it.
- ✅ Pins `@ai/core` v0.30.0 (`1322cd6`).
- ⬜ A head's first frame can be blank for a moment after "ready" (seen once
  on a small tile): fade in on the first drawn frame.
- ⬜ The opening still stalls in a live run (M11's TODO, 2026-10-10): check that
  what the plan page makes ahead is exactly what the room asks for.

### 2026-10-09 — lines made before they are said; real photos; the panel thinks

The user, after a mock: gaps and awkward pauses, worst on long lines (M11's
`research/listening/gaps.md` has why: this laptop makes speech barely faster
than it is spoken); and *"we don't want dummy faces in the interview"*.

- ✅ **`GET /interviews/{id}/upcoming`** (`49e7e7c`): the questions M05 would
  choose now — its choice and two alternatives, after the lead-in they will
  follow, asked with the same request the real selection makes
  (`_bank_request`) — the next round's too when this question ends the
  round, and the panel's stock phrases with names and topics in place. The
  plan page has M11 make the opening and these while the student reads; the
  room, again after each question, while they answer (`warm.ts`); a newer
  batch drops the guesses it no longer makes. Tested: the question asked is
  one of those named.
- ✅ **The prefill says what would be said** (FR-11.6): the line the
  interviewer would say if the answer stopped where the student paused, made
  while they talk; said only if it is the line the real answer gets.
- ✅ **`GET /interviews/phrases`**: every interviewer's stock phrases, for
  M11's `warm_phrases.ts` to make once for every interview after.
- ✅ **No drawn faces**: `Face` is each interviewer's own photo (Core
  `InterviewerPhoto`) on the setup page, the plan, the transcript and in the
  room's tile until the 3D head is ready; initials when there is no photo
  yet. While the reply is worked out, the asker's head glances down and aside
  (`replying`).
- ✅ Earlier the same day (`7605840`): a picked track the bank cannot serve
  stays on the plan with the reason; an unknown track is refused (422).
- Pins `@ai/core` v0.29.0 (one gapless voice track).

### What is left — and whose it is

**Waiting on another module:**
- FR-6.20 (steelman) waits on M13's `push_back` rubric.
- FR-6.21's scoring waits on a rubric for questions.
- Voice (FR-6.10 and FR-6.22's voice half) waits on M11 — the browser mic
  (2026-10-04) and the browser voice (2026-10-05) are interims; the editor on M07;
  the canvas on M08; the camera on M12.
- FR-6.11 has nothing to switch to until one of those lands.

**Waiting on a person:**
- AC-6.8 and AC-6.12 — human evaluation round 1, prepared above.
- AC-6.5, AC-6.6, AC-6.7 and AC-6.9 on real sessions; each is met or
  measured by the scripted student or the reliability page today.
- The manual QA script has never been run by a person.

**M06's own:**
- FR-6.19's offline re-run harness and the Langfuse export.
- AC-6.11 (prompt cache hits) measured on a streamed call.
- ~~Moving M06's outbox onto `ai_core.outbox`~~ — **done 2026-10-02**. M06's
  three tables are `OutboxRow`s and its three destinations are `Channel`s.
  It is the library's second consumer, after M13. What changed for a student
  and for an operator:
  - an M13 outage no longer holds a row;
  - a 4xx is `rejected` after one try, not five;
  - stuck rows are listed with their reasons, and staff can requeue them
    (`POST /outbox/requeue`).
- The live drill path with M01 running: the full chain on 2026-10-02 ran
  without M01, so the project segment was not exercised live.
- Unreviewed key points in the notes for drafted items, and the stale README
  (2026-10-22 above).

Still open: FR-6.20 blocked, and FR-6.10, FR-6.11, FR-6.19, FR-6.21, FR-6.22 partial —
each row below says what it waits on.

---

## 3. Functional requirements

Spec §4, Revision 2. This is the authoritative list.

| FR | | Priority | Phase |
|---|---|---|---|
| FR-6.1 | ✅ `InterviewPlan` from M02's plan + M05 availability + budget + mode, assembled by `planner.py` with no model call; M04's profile is the pinned prefix, not a plan input | P0 | 1 |
| FR-6.2 | ✅ `POST /plan` previews without starting; `DELETE /plan/segments/{i}` drops one, only while `planned`; `PlanPreview` shows minutes, questions, M02's rationale, what was dropped and M02's `uncovered` | P1 | 1 |
| FR-6.3 | ✅ Segments run in sequence, advance on their budget, and say so crossing over (§3.2.3). The panel is seated from the personas' data (`panel.py`, 2026-10-06): the lead opens and closes, experts take the parts they know, a panel of one gets someone sitting in; the opening introduces everyone, rounds end in a two-voice hand-over, an expert comes in with a follow-up and hands back, and every line records who said it; the rubric comes from M05's selection | P0 | 1 |
| FR-6.4 | ✅ Re-plan at segment boundaries, ≤ 2, from `question.asked`/`probe.decided`/`idle.moved_on` only — four triggers, a neutral live note, the reason in the report, `skipped` owed to M02 | P1 | 1 |
| FR-6.5 | ✅ Probe ladder, cap 5, graceful exit, derived rungs — pure function, 14 tests, steelman unreachable | P0 | 1 |
| FR-6.6 | ✅ `break_depth` per concept per session — recorded by the fold, kept at the shallowest break | P0 | 1 |
| FR-6.7 | ✅ M05's ladder served, `POST /hint` takes one, M13's published factor shown BEFORE it is taken and frozen at plan time, `hint_level_used` carried to M13 | P0 | 1 |
| FR-6.8 | ✅ Four modes as one table (`modes.py`): personas per segment kind, hints, ensemble, overrun allowance, retry, steelman flag; `GET /v1/interviews/modes` serves only true mechanics | P0 | 1 |
| FR-6.9 | ✅ No hints, the deepest ladder, the shortest patience, a `RUDE` screen on every line, and the hard clock — 0% overrun, enforced at the next question boundary | P0 | 1 |
| FR-6.10 | 🟡 Text runs; the turn contract carries `modality`. **Voice runs, on M11** (2026-10-06): spoken answers heard, endpointed, written down by M11's recogniser and sent; each line said in its speaker's cast voice; barge-in, what was heard, calibrated silence, backchannels, hold-to-talk. Still partial for coding (M07) and canvas (M08) | P0 | 1·text · voice ⛔ M11 · coding ⛔ M07 · canvas ⛔ M08 |
| FR-6.11 | 🟡 Contract fixed and carried, and `POST /switch-modality` exists (day 13): text is a no-op, anything else names the module it waits on — nothing to switch to yet | P0 | 1·text |
| FR-6.12 | ✅ Pauses of ≤ 5 min, one per 15 planned minutes (2026-10-04; the spec's row still says once), and resume. The cap is applied on `/resume` for a student who comes back, and by the sweeper (EC-6.14) for one who does not — which used to lock them out of every future interview | P1 | 1 |
| FR-6.13 | ✅ Reconnect and resume: checkpoint recovery (stale, unreadable, failed write); presence — a disconnect stops the clock, a return restarts it after a 30 s grace; `GET /resume-state` with "welcome back, we were on question N"; the stage re-attaches | P0 | 1 |
| FR-6.14 | ✅ Evaluation never blocks the hot path — outbox written with the turn, delivered by a background task, an explicit drain, or the sweeper; claimed before sending; a status returns, never a number. Three obligations now: the answer text to M04 (so evidence resolves), the evaluation to M13, the coverage row to M02 — and the artifact goes first | P0 | 1 |
| FR-6.15 | ✅ Interviewer cannot read scores, band or θ — `InterviewerView` + the type-graph gate | P0 | 1 |
| FR-6.16 | ✅ Last six turns plus §6.6's rolling note, regenerated every four turns and REPLACING the dropped turns; bounded by construction, so a six-times-longer session is not a six-times-larger context | P0 | 1 |
| FR-6.17 | ✅ 70%: announced, and in the enforced modes the plan narrows by M02 priority and says so; 90%: the closing takes over; a question is never asked without time to answer it; ahead of schedule, one rung deeper | P0 | 1 |
| FR-6.18 | ✅ A report for every session — ended, aborted, or crashed half-way; built from the log | P0 | 1 |
| FR-6.19 | 🟡 `/trace` serves the log, every model call, and a replay equality check, asserted over twenty scripted sessions on every run (day 14); an offline re-run harness and the Langfuse export are not built | P0 | 1 |
| FR-6.20 | ⛔ Steelman probes, dispatched against `push_back` | P1 | blocked — M13 rubric |
| FR-6.21 | 🟡 ✅ The closing runs and records the student's questions (two at most), shown in the notes · ⛔ scoring them | P1 | 1 · scoring blocked — rubric |
| FR-6.22 | 🟡 Text measured at ≈ 2.0 s p95 to first visible token, inside the gate | P0 | 1·text · voice ⛔ M11 |
| FR-6.23 | ✅ Defend drill — M01's contract, end to end, on the live model | P0 | 1 |
| FR-6.24 | ✅ M02 ledger: `asked` and `answered` with the turn, and `skipped` for every requirement behind a segment the plan dropped or the student removed | P0 | 1 |
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
| AC-6.15 **[GATE]** | ✅ `asked` / `answered` ledger rows for every turn, `skipped` for every dropped requirement — all three written with the work that caused them | 100% |
| AC-6.5 | 🟡 Session completion rate — 20/20 for the scripted student (`test_scripted_student`); real students pending | ≥ 80% |
| AC-6.6 | 🟡 Break point found — asserted ≥ 80% over the scripted twenty; real students pending | ≥ 80% of sessions |
| AC-6.7 | 🟡 Coverage of must-have requirements — asserted ≥ 90% over the scripted twenty; real postings pending | ≥ 90% |
| AC-6.8 | ⬜ "Felt like a real interview" | ≥ 4.0 mean |
| AC-6.9 | 🟡 Reconnect success rate — counted off the log (`GET /v1/interviews/reliability`); no real sessions measured yet | ≥ 95% |
| AC-6.10 | ⬜ Context tokens per turn variance | < 15% |
| AC-6.11 | 🟡 Prompt cache-hit ratio — measured: reported on 2 of 16 structured calls, never on a streamed one | ≥ 0.7, or "not measured" |
| AC-6.12 | ⬜ Sessions where a student felt humiliated | 0 |
| AC-6.17 **[GATE]** | ✅ The persona never changes the standard — for one answer, M13's payload and the strategist's prompt are identical across every mode, save the declared `ensemble`. **New in Revision 2**: §6.7 made the promise and the report printed it; nothing tested it | ✅ |
| AC-6.16 | ✅ Retries never double-ask or double-write — the event key, a crashed step, two senders over one outbox row, and the spec's five chaos scenarios (`test_chaos.py`), each checked by `nothing_twice()` | chaos test |

---

## 5. Edge cases

Spec §9. Listed in full, because several are one afternoon each and are the
difference between a demo and a product.

| EC | | Expected behaviour |
|---|---|---|
| EC-6.1 | ✅ Student says nothing for 45 s | One gentle prompt, then a second, then offer to move on — never a fourth. In text: the browser's idle timer from persona `patience`, the server's floor of n × patience |
| EC-6.2 | ✅ Student answers a different question | Redirected once, then judged as given |
| EC-6.3 | ✅ Student asks the interviewer a question | Brief answer, then the question again |
| EC-6.4 | ✅ Student is abusive / tests the AI | One neutral redirect, then end politely. Logged — `abusive` in the verdict (model) or the lexicon (fallback) |
| EC-6.5 | ✅ Student asks for the answer | A hint while hints last, else a graceful exit — the credit table landed on day 7 and is shown before the hint is taken |
| EC-6.6 | ✅ Answer contains prompt injection | Recognised spans stripped before the strategist; the guard model beside it; a flagged answer moves no θ; M13 neutralises before scoring; the report says a passage was set aside |
| EC-6.7 | ⛔ Mic dies mid-answer | Phase 3 (M11) |
| EC-6.8 | ✅ Browser refresh | Resume from checkpoint; a refresh under 5 s is not a disconnect; a longer one is welcomed back to the same question with the clock right |
| EC-6.9 | ✅ Session exceeds budget by 25% | Force closing (0% in Final Boss) — a round's own clock, and the closing at 90% of the session's |
| EC-6.10 | ✅ Student ends at minute 3 | A report framed as a warm-up, not a failure |
| EC-6.11 | ✅ All modalities fail | Clean end, apology, no score — text is the only modality in Phase 1, so this is §10's "everything fails": two crashed steps running end the session `aborted`, the apology said, queued evaluations voided |
| EC-6.12 | ✅ LLM provider outage | Item stems and templates verbatim, rule strategist, eval stays queued, session completes — the ladder's panic rung, with a one-minute probe back |
| EC-6.13 | ✅ Two sessions in parallel | Blocked with an explanation and the id to resume; a unique nullable `occupying_key` enforces it at the database |
| EC-6.14 | ✅ Pauses and never returns | Auto-close after 30 min; partial report — the sweeper, since the fix inserted before day 9 |
| EC-6.15 | ⛔ Steelman accepted by a correct student | Blocked with FR-6.20 |
| EC-6.16 | ✅ Coding round with no editor | Dropped at plan time, with the reason on the preview and `skipped` owed to M02 (`test_a_coding_round_is_dropped_and_owed_to_m02_as_skipped`) — every coding round until M07 exists |
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
| `m06_artifact_outbox`, `m06_eval_outbox`, `m06_ledger_outbox` (`claimed_at`, states `pending`/`sending`/`sent`/`held`) | ✅ | written with the turn, claimed before sending, retried by `sweeper.py`; the artifact is delivered before the evaluation that cites it |

---

## 7. Asks of other modules

From [M06_REVIEW.md](M06_REVIEW.md) Part 5. None blocks day 1. Each belongs in
the other module's TODO once raised; tick it here when it has been. **Day 15 (2026-10-02) raised every open one** in its owner's `main` TODO and the umbrella copy — the owners' `todo` branches are stale since 2026-08-27 and are theirs to rebuild.

| Module | Ask | State |
|---|---|---|
| M01 | `module.json` repo URL `mock-interview-engine` → `Mock_Interview_Engine` (launcher skips M06 otherwise) | ✅ landed (`d785b9f`), on M01's `main` since 2026-09-23 |
| M01 | forward `X-Role` / `X-Candidate-Id` on the drill hand-off (M06 refuses anonymous callers) | ✅ landed (`d785b9f`) |
| M05 | `/questions/select` reads its own `_SESSIONS` θ when the caller omits it | ✅ landed (`d30915d`) |
| M05 | `Bank.get()` cannot find its own fallback-playlist items | ✅ landed (`d30915d`) |
| M13 | **a live M05 question source** — `get_questions()` was always the fixture bank, so it 404d on every real question id (blocked the Phase-1 gate) | ✅ landed (`efb5a5a`); confirmed live: M13 resolves `/v1/questions/{id}/package?round_type=` from M05 |
| M13 | **a worker that drains its own outbox** — `emit.py` promised one and only `POST /outbox/drain` existed | ✅ landed (`bdf31bb`), on Platform_Core v0.10.0's shared `ai_core.outbox` — which M06's own outbox should move to |
| M13 | a rejected outbox row disappeared from `/v1/outbox` | ✅ landed (`bdf31bb`): stuck rows listed per destination, with requeue |
| M13 | code and canvas artifacts get a fresh `uuid4()` every evaluation (`service.py`), so they can never resolve in M04 the way a transcript now does. Blocks scored evidence for M07/M08 | ⬜ raised (`Evaluation_Engine` `9e4c6c7`) |
| M13 | `authenticated: false` on `/v1/outbox` — the observation write was unauthenticated | ✅ landed (`bdf31bb`, `ecb3548`): reads `M04_SERVICE_SECRET` and forwards the student |
| M05 | `difficulty_offset` on `SelectionRequest` | ⬜ raised (`e9d3161`) |
| M05 | per-round-type counts on `/bank/health` | ⬜ raised (`e9d3161`) |
| M04 | consent lookup route — until it existed, M13 emitted **no observations at all** | ✅ landed (`5e01e8d`): `GET`/`POST /v1/candidates/{id}/consent` |
| M04 | a route to register an artifact, so evidence can resolve | ✅ landed (`5e01e8d`): `POST /v1/candidates/{id}/artifacts` |
| M04 | source `recent_sessions` from M06 | ⬜ raised (`Memory` `265774f`) |
| M13 | `push_back` rubric variant (unblocks FR-6.20) | ⬜ raised (`40c1846`) |
| M13 | `cs_core` and `communication` rubrics | ⬜ raised (`40c1846`) |
| M13 | read `M04_SERVICE_SECRET`, as M04 and M15 do, not `SERVICE_SECRET` | ✅ landed (`bdf31bb`) |
| M04 | guard every candidate route — it failed OPEN with no secret configured | ✅ landed (`97daa17`); M06 forwards the student on profile-summary and artifacts (`284634e`) |
| M02 | docstring: M06 writes `asked`/`answered` | ⬜ raised (`cde74e6`) |
| M02 | the first plan for a posting took 4.7 s live (2026-10-02); M06 waits 20 s at plan time now, but a student watches that spinner — precompute on parse, or publish the expected latency | ⬜ raised (`jd-parser-coverage` `cde74e6`) |
| M02, M15 | link "practise for this role" to `/mock?jd={id}` — M06's setup honours `?jd=` since day 13 | ⬜ raised (`cde74e6`; M15's local plan copy, which its repo does not track) |
| M05 | `/questions/{id}/flag` takes any caller — no identity guard; and EC-5.9's retraction of observations already sent is still not wired (M06's ⚑ says "won't be picked again", not "undone") | ⬜ raised (`Question_Intelligence` `7b0bbf4`) |
| M13 | M06's notes show `reasoning`, `missing_key_points` and verified quotes to the student (day 12); state in M13's contract that these are student-visible, so their wording is held to that | ⬜ raised (`Evaluation_Engine` `9e4c6c7`) |
| M05 | author `follow_ups` (depth 1–3) for bank items, the 12 reviewed first, and have the drafter write them — none has any, so every probe on a bank question is generic and most interviewers stop after one | ⬜ raised in M05's TODO, 2026-10-22 |
| M05 | review about ten drafted items per track — only DSA has reviewed items, so only DSA answers are scored or move θ | ⬜ raised in M05's TODO, 2026-10-22 |
| M05 | `hint_ladder`s for the reviewed items — 1 of 12 has one, so Hint is empty on 11 DSA questions | ⬜ raised in M05's TODO, 2026-10-22 |
| M13 | don't refill an empty `missing_key_points` from the word-overlap measure (`service.py` ~L209): a correct paraphrase was told it missed every key point | ✅ landed (`f673f90`) |
| M13 | take `prompts_used` (pushes priced like hints) and `key_point_ids` (only what was asked) | ✅ landed (`f673f90`) |
| M05 | pitch by topic (`difficulty_offset`, `difficulty_shift`) and hold a focus (`only_concepts`, never relaxed) | ✅ landed (`bb4b3fe`) |
| M01 | say a drill is "in progress" when M06 refuses it, and link it | ✅ landed (`f8ad4e8`) |
| Platform_Shell | add `interviews`/`drills`/`agents` to the proxy table and mount `m06Routes` | ✅ landed (`bbd4f69`); on GitHub (MNEMOS-PREP/Platform_Shell, private) since 2026-09-23 |
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
| Scored drill turns | M05 grounded items from M01 claims (Phase 2) |
| The report, long-term | M19 |
| Project segment from repositories | M03 |

---

## 9. Open decisions

Spec §15. 1–5 stand as written; 6–8 are new.

- **6. LangGraph or an explicit state machine** — **settled 2026-09-17: LangGraph**, behind `orchestration/` and with no checkpointer of its own. Master plan §26.1 names it, the long-term shape (an agent registry with ablation flags, parallel GD panels) is what it is for, and keeping the event log as the only record avoids the dual-truth problem. `graph.py` is the only file that imports it.
- **7. Report home until M19** — recommendation: M06 serves it, deleted when M19 ships.
- **8. Drill scoring** — recommendation: unscored in Phase 1, and the report says so.
