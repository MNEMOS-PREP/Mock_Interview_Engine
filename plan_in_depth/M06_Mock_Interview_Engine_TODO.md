# M06 — TODO · Mock Interview Engine

> **Completion: 75%** — 16 of 26 functional requirements met, 7 partially. **Days 1–9 of 15 are done**, plus two pieces pulled forward out of days 9 and 11 because they were shipped-today defects rather than missing features (see below). Since day 9 **a mock is a panel**: seven personas as data, four modes as one table, and a guard that reads what the student sends as well as what the interviewer says. On 2026-09-20 **the platform's core loop closed for the first time**: a student consents (M04), is asked a question from M05's bank, answers it in M06, M13 scores the answer, and M04's skill graph moves — Hashing and Time Complexity to `emerging`, with the evidence resolving to the student's own sentence. Six backends and the shell, running together, through one origin on `:5173`. Since day 5 the **mock** path runs on M02's real plan rather than a stub: rounds that are named, priced, previewed, droppable, and that end and begin out loud. The **defend drill** path runs whole.
>
> Met: plan assembly over M02 (FR-6.1) and its preview (FR-6.2), segments with a persona each (FR-6.3), the probe ladder and break depths (FR-6.5, 6.6), hints at a published price (FR-6.7), modes as configs (FR-6.8), pause (FR-6.12), evaluation off the hot path (FR-6.14), the interviewer's blind view (FR-6.15), fixed context (FR-6.16), a report for every session (FR-6.18), the drill (FR-6.23), the M02 ledger (FR-6.24), the M05 θ seam (FR-6.25), identity (FR-6.26).
>
> Partly: Final Boss (FR-6.9 — its hard clock is day 10). Not started: re-planning (FR-6.4), closing questions (FR-6.21). Blocked: steelman (FR-6.20).
>
> _Day 6 moved no requirement across a line, and the number is right not to move: it deepened FR-6.3 (rounds now end, begin and say so) without completing it, because per-segment personas wait on day 9. The measure counts requirements, not work — which is the point of having one._
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
| Status | **Days 1–9 of 15 done.** A mock interview is planned from a real job description and the student's resume, run by a panel of personas across M02, M04, M05, M06 and M13, and reaches the skill graph; mounted in Platform_Shell on one origin. |
| Backend tests passing | **283**, no socket opened, no API key |
| Release gates (`-m gate`) | **45** |
| Route decorators | **25** on `/v1`, plus `/health` and `/status` |
| Lint | `ruff check` and `ruff format --check` clean; frontend `tsc` clean |
| Frontend | five screens on `:5206`; **mounted in Platform_Shell** on `:5173` at `/mock`, with `interviews`/`drills`/`agents` in its proxy table |
| Measured | strategist p95 **1106 ms**, interviewer first token p95 **919 ms**, a rung ≈ **2.0 s** to first visible token (AC-6.4 wants ≤ 2.5 s) — `Backend/reports/latency-*.json` |
| Spec | [Revision 2](M06_Mock_Interview_Engine.md), after [the review](M06_REVIEW.md) |
| Scope | 26 functional requirements (21 of them P0), 17 acceptance metrics (8 release-blocking), 17 edge cases |
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
| 5 | ✅ | Plan assembly over M02 + plan-time availability; preview UI with drop-a-segment |
| 6 | ✅ | Segments, 409 as honest end, bridges, `RoundTransition`, the project segment |
| 7 | ✅ | Hint ladder (M05), M13 credit table shown before the hint is taken |
| 8 | ✅ | Context management: §6.6's rolling round summary, bounded view; AC-6.10's mechanism gated, its number a harness run |
| 9 | ✅ | Personas (7) as data, modes (4) as configs, guard on both directions (EC-6.4, 6.6), Practice's retry |
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

### Next: day 10

1. **Pacing 70/90/100** (FR-6.17): the 70% focus offer when coverage debt is
   high, the forced move to the closing at 90%, the wrap-up at 100% — and
   Final Boss's 0% overrun (EC-6.9), which completes FR-6.9.
2. **The closing runs** (FR-6.21): it has had `question_budget = 0` since day
   5, so "Anything you'd like to ask me?" was said and the session ended. The
   student's questions are recorded; scoring them waits on a rubric.
3. **Re-planning** (FR-6.4) from hot-path signals only, ≤ 2, `plan.changed`.
4. M04's posterior is never fetched at bootstrap, so M05 is always seeded
   cold (§6.1 steps 3–4) — fix with the plan's concept ids.

---

## 3. Functional requirements

Spec §4, Revision 2. This is the authoritative list.

| FR | | Priority | Phase |
|---|---|---|---|
| FR-6.1 | ✅ `InterviewPlan` from M02's plan + M05 availability + budget + mode, assembled by `planner.py` with no model call; M04's profile is the pinned prefix, not a plan input | P0 | 1 |
| FR-6.2 | ✅ `POST /plan` previews without starting; `DELETE /plan/segments/{i}` drops one, only while `planned`; `PlanPreview` shows minutes, questions, M02's rationale, what was dropped and M02's `uncovered` | P1 | 1 |
| FR-6.3 | ✅ Segments run in sequence, advance on their budget, and say so crossing over (§3.2.3); each has the persona its mode assigns its kind, and a new voice introduces itself; the rubric comes from M05's selection | P0 | 1 |
| FR-6.4 | ⬜ Re-plan at boundaries, ≤ 2, hot-path signals only | P1 | 1 |
| FR-6.5 | ✅ Probe ladder, cap 5, graceful exit, derived rungs — pure function, 14 tests, steelman unreachable | P0 | 1 |
| FR-6.6 | ✅ `break_depth` per concept per session — recorded by the fold, kept at the shallowest break | P0 | 1 |
| FR-6.7 | ✅ M05's ladder served, `POST /hint` takes one, M13's published factor shown BEFORE it is taken and frozen at plan time, `hint_level_used` carried to M13 | P0 | 1 |
| FR-6.8 | ✅ Four modes as one table (`modes.py`): personas per segment kind, hints, ensemble, overrun allowance, retry, steelman flag; `GET /v1/interviews/modes` serves only true mechanics | P0 | 1 |
| FR-6.9 | 🟡 No hints, the deepest ladder, the shortest patience, and a `RUDE` screen on every line; the hard clock (0% overrun) is day 10 | P0 | 1 |
| FR-6.10 | 🟡 Text runs; the turn contract carries `modality` | P0 | 1·text · voice ⛔ M11 · coding ⛔ M07 · canvas ⛔ M08 |
| FR-6.11 | 🟡 Contract fixed and carried; nothing to switch to yet | P0 | 1·text |
| FR-6.12 | ✅ Pause once ≤ 5 min, resume. The cap is applied on `/resume` for a student who comes back, and by the sweeper (EC-6.14) for one who does not — which used to lock them out of every future interview | P1 | 1 |
| FR-6.13 | 🟡 Reconnect and resume from checkpoint — checkpoint recovery (stale, unreadable, failed write) is built and tested; `resume-state` and the "welcome back" flow are not (day 11) | P0 | 1 |
| FR-6.14 | ✅ Evaluation never blocks the hot path — outbox written with the turn, delivered by a background task, an explicit drain, or the sweeper; claimed before sending; a status returns, never a number. Three obligations now: the answer text to M04 (so evidence resolves), the evaluation to M13, the coverage row to M02 — and the artifact goes first | P0 | 1 |
| FR-6.15 | ✅ Interviewer cannot read scores, band or θ — `InterviewerView` + the type-graph gate | P0 | 1 |
| FR-6.16 | ✅ Last six turns plus §6.6's rolling note, regenerated every four turns and REPLACING the dropped turns; bounded by construction, so a six-times-longer session is not a six-times-larger context | P0 | 1 |
| FR-6.17 | 🟡 A question is not asked without time for an answer, and the clock can end a session; the 70% checkpoint and the reserved closing are day 10 | P0 | 1 |
| FR-6.18 | ✅ A report for every session — ended, aborted, or crashed half-way; built from the log | P0 | 1 |
| FR-6.19 | 🟡 `/trace` serves the log, every model call, and a replay equality check; an offline re-run harness and the Langfuse export are not built | P0 | 1 |
| FR-6.20 | ⛔ Steelman probes, dispatched against `push_back` | P1 | blocked — M13 rubric |
| FR-6.21 | ⬜ Record closing questions · ⛔ score them | P1 | 1 · scoring blocked — rubric |
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
| AC-6.5 | ⬜ Session completion rate | ≥ 80% |
| AC-6.6 | ⬜ Break point found | ≥ 80% of sessions |
| AC-6.7 | ⬜ Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | ⬜ "Felt like a real interview" | ≥ 4.0 mean |
| AC-6.9 | ⬜ Reconnect success rate | ≥ 95% |
| AC-6.10 | ⬜ Context tokens per turn variance | < 15% |
| AC-6.11 | 🟡 Prompt cache-hit ratio — measured: reported on 2 of 16 structured calls, never on a streamed one | ≥ 0.7, or "not measured" |
| AC-6.12 | ⬜ Sessions where a student felt humiliated | 0 |
| AC-6.17 **[GATE]** | ✅ The persona never changes the standard — for one answer, M13's payload and the strategist's prompt are identical across every mode, save the declared `ensemble`. **New in Revision 2**: §6.7 made the promise and the report printed it; nothing tested it | ✅ |
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
| EC-6.4 | ✅ Student is abusive / tests the AI | One neutral redirect, then end politely. Logged — `abusive` in the verdict (model) or the lexicon (fallback) |
| EC-6.5 | 🟡 Student asks for the answer | A hint while hints last, else a graceful exit; M13's credit table is day 7 |
| EC-6.6 | ✅ Answer contains prompt injection | Recognised spans stripped before the strategist; the guard model beside it; a flagged answer moves no θ; M13 neutralises before scoring; the report says a passage was set aside |
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
| `m06_artifact_outbox`, `m06_eval_outbox`, `m06_ledger_outbox` (`claimed_at`, states `pending`/`sending`/`sent`/`held`) | ✅ | written with the turn, claimed before sending, retried by `sweeper.py`; the artifact is delivered before the evaluation that cites it |

---

## 7. Asks of other modules

From [M06_REVIEW.md](M06_REVIEW.md) Part 5. None blocks day 1. Each belongs in
the other module's TODO once raised; tick it here when it has been.

| Module | Ask | State |
|---|---|---|
| M01 | `module.json` repo URL `mock-interview-engine` → `Mock_Interview_Engine` (launcher skips M06 otherwise) | ✅ landed (`d785b9f`), on M01's `main` since 2026-09-23 |
| M01 | forward `X-Role` / `X-Candidate-Id` on the drill hand-off (M06 refuses anonymous callers) | ✅ landed (`d785b9f`) |
| M05 | `/questions/select` reads its own `_SESSIONS` θ when the caller omits it | ✅ landed (`d30915d`) |
| M05 | `Bank.get()` cannot find its own fallback-playlist items | ✅ landed (`d30915d`) |
| M13 | **a live M05 question source** — `get_questions()` was always the fixture bank, so it 404d on every real question id (blocked the Phase-1 gate) | ✅ landed (`efb5a5a`); confirmed live: M13 resolves `/v1/questions/{id}/package?round_type=` from M05 |
| M13 | **a worker that drains its own outbox** — `emit.py` promised one and only `POST /outbox/drain` existed | ✅ landed (`bdf31bb`), on Platform_Core v0.10.0's shared `ai_core.outbox` — which M06's own outbox should move to |
| M13 | a rejected outbox row disappeared from `/v1/outbox` | ✅ landed (`bdf31bb`): stuck rows listed per destination, with requeue |
| M13 | code and canvas artifacts get a fresh `uuid4()` every evaluation (`service.py`), so they can never resolve in M04 the way a transcript now does. Blocks scored evidence for M07/M08 | ⬜ new |
| M13 | `authenticated: false` on `/v1/outbox` — the observation write was unauthenticated | ✅ landed (`bdf31bb`, `ecb3548`): reads `M04_SERVICE_SECRET` and forwards the student |
| M05 | `difficulty_offset` on `SelectionRequest` | ⬜ |
| M05 | per-round-type counts on `/bank/health` | ⬜ |
| M04 | consent lookup route — until it existed, M13 emitted **no observations at all** | ✅ landed (`5e01e8d`): `GET`/`POST /v1/candidates/{id}/consent` |
| M04 | a route to register an artifact, so evidence can resolve | ✅ landed (`5e01e8d`): `POST /v1/candidates/{id}/artifacts` |
| M04 | source `recent_sessions` from M06 | ⬜ |
| M13 | `push_back` rubric variant (unblocks FR-6.20) | ⬜ |
| M13 | `cs_core` and `communication` rubrics | ⬜ |
| M13 | read `M04_SERVICE_SECRET`, as M04 and M15 do, not `SERVICE_SECRET` | ✅ landed (`bdf31bb`) |
| M04 | guard every candidate route — it failed OPEN with no secret configured | ✅ landed (`97daa17`); M06 forwards the student on profile-summary and artifacts (`284634e`) |
| M02 | docstring: M06 writes `asked`/`answered` | ⬜ |
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
