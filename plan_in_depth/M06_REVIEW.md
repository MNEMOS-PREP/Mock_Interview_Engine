# M06 — Plan Review, Before Implementation

> Reviewed: 2026-09-16 · Target: [M06_Mock_Interview_Engine.md](M06_Mock_Interview_Engine.md) · Reviewed against the **shipped code** of every module M06 calls or is called by — M01 `resume-ingestion`, M02 `jd-parser-coverage`, M04 `Memory`, M05 `Question_Intelligence`, M13 `Evaluation_Engine` — and against `Platform_Core` v0.9.1, the three earlier reviews (M04, M05, M13), and `scripts/launch.ps1`.
>
> **Status of evidence.** Every module M06 talks to has shipped, so almost every claim below is checked against a router, a model or a test rather than against a spec. Those carry a file and line. Items marked *(judgment)* are a single reading and worth a second opinion. Items marked *(unmeasured)* are predictions that day 2's latency harness exists to settle.

---

## Verdict

§2 and §3 are the best user-side writing in the set. The graceful exit, the "no live score" rule, the pace-check sentence, and Trap 2 (evaluation never blocks the conversation) are the product. None of them changes.

The problem is timing. M06 was written on 29 July, before any of its four dependencies existed, and **all four have since shipped with contracts that M06 contradicts**. M02 already builds the plan M06 §6.1 describes. M05 already owns the in-session ability estimate that M06's checkpoint would persist. M13 scores a round type that M06's vocabulary does not contain. M04 cannot tell M06 whether a student has consented. And M01 is already calling an M06 endpoint that §7 does not list.

Five things are wrong rather than out of date:

1. **The default probe ladder asks a deliberately false question in Practice mode** (§2.4). `LADDER[current_depth + 1]` reaches `"steelman"` at depth 3 in every mode, not just Final Boss.
2. **The idempotency key includes `attempt`** (§2.8), so a retry gets a fresh key and is not idempotent. That is the one property the key exists for.
3. **§6.1 builds the plan with a frontier-model call.** Trap 1 says the model never decides the structure (§2.1).
4. **The "Struggling" re-plan trigger reads M13 scores and "distress"** (§2.2). The scores are asynchronous and uncalibrated. "Distress" is an emotion inference, which M12's charter forbids.
5. **The latency and cache gates assume models the platform does not run** (§2.5). The platform runs `gpt-oss-120b`/`20b` on Groq. Both are reasoning models, and no module has measured whether that account reports cached tokens.

None of it is deep. It is about **one day of contract alignment** folded into days 1–4, plus **a smaller Phase 1 scope**. Voice, coding, canvas and steelman are all blocked on modules that do not exist yet. Those cuts are what keep the plan at 15 days rather than growing past 14.

---

## Part 1 — The contracts, as the upstreams actually shipped them

### 1.1 M02 already builds the plan — consume it, don't rebuild it

**Verified.** `jd-parser-coverage/.../plan.py:1-5`: *"we produce a coverage plan: an allocation of interview question budget across requirements. The Mock Interview Engine consumes that plan directly."*

`POST /v1/jds/{jd_id}/plan/{candidate_id}` (`router.py:906`, body `{minutes}`) returns a `CoveragePlan` (`plan.py:195`) containing:

| field | what it already does that M06 §6.1 re-specifies |
|---|---|
| `allocations[]` | question budget per requirement, by `severity = weight × (1 − mastery)`, log-utility, cap 4 per requirement |
| `allocations[].round_type` | `verbal` / `coding` / `design`, priced 3.5 / 12 / 20 min per question — §6.1's *"coding round < 12 min is not a coding round"* |
| `rounds[]` | one per modality, ordered by cost |
| `uncovered`, `suggestion` | must-haves that did not fit, stated — EC-2.11 |
| `unmeasurable` | requirements no round can probe |
| `difficulty`, `difficulty_note` | `diagnostic` / `calibrated` / `final_boss`, derived from mastery |
| `saturated` | the plan is the same for everyone, and says so |

§6.1's *"per-round minutes ∝ coverage weight, floored at the minimum viable"* is a second allocator. Two allocators disagree, and the first symptom would be a plan preview promising a DBMS round that M02's coverage screen does not show.

**Fix.** `InterviewPlan` wraps M02's plan:

- **frozen:** M02's `CoveragePlan` is stored whole with its `plan_version`, because the endpoint is not persisted and a second call can differ;
- **added:** the warm-up segment, the reserved closing segment, a persona per segment, and the mode.

No model call. The preview's rationale is M02's per-allocation `rationale` plus a templated sentence per segment.

**The coverage ledger is M06's to write, not M05's.**
- M02's docstring (`router.py:1868`) says *"When M5 selects a question, it writes `asked`"*.
- M05 has no HTTP client at all.
- A selected question is not an asked one: a session can end between selection and presentation.

M06 is the only module that knows a question was actually put to the student, so M06 writes these states to `POST /v1/sessions/{sid}/coverage/{cid}` (`router.py:1856`):
- `asked` when a question is presented;
- `answered` when an answer is received;
- `skipped` when a re-plan or the clock drops a planned requirement.

`scored` stays M13's, and M13's delivery of it is a known unbuilt transport (M13 TODO).

**`GET /v1/sessions/{sid}/coverage/{cid}`** (`router.py:1920`) is the report's coverage block. Read it; don't recompute it.

### 1.2 M05 — selection, and the θ that M06 must never write down

**Verified routes** (`Question_Intelligence/.../router.py`, prefix `/v1`):

| call | when | note |
|---|---|---|
| `POST /questions/select` (:222) | each question | `SelectionRequest` (`contracts.py:414`). **409 = the bank cannot fill this round** — a specified state, not a crash |
| `GET /questions/{id}` (:108) | after selection | `hint_ladder` (:296), `follow_ups` by depth (:294), `time_budget_s`, `key_points` |
| `GET /questions/{id}/package` (:116) | — | what M13 reads; M06 does not need to forward it |
| `POST /sessions/{sid}/theta/seed` (:240) | bootstrap | `{candidate_id, posterior, snapshot_id}` |
| `POST /sessions/{sid}/theta/observe` (:260) | after every strategist verdict | `{concept_id, outcome: ProvisionalOutcome}` |
| `POST /sessions/{sid}/close` (:273) | session end | `{posterior}` — M04's wins, silently |

**`ProvisionalOutcome` is M06's to produce** (`contracts.py:390`): `{turn_id, band: below|at|above, confidence, latency_ms}`. The M05 review made this a P0 contract: the CAT branches on M06's `ProbeStrategist`, never on M13's asynchronous score.

**The conflict.** `SelectionRequest.theta_provisional` is supplied by the caller, and `/select` does not read M05's own `_SESSIONS` (:44). So M06 has to carry the provisional θ. But M06 checkpoints `SessionState` to a table after every node (§6.8), which is exactly what `session.py:50` `ProvisionalIsNotDurable` exists to prevent: *"two stored ability numbers is two answers to 'how good is this student'"*.

**Fix, both halves:**
- **In M06:** hold θ in process memory only, keyed by session. The checkpoint schema has no θ field, and a test asserts the serialised checkpoint contains no `theta` key. On a resume after a process restart, re-seed from M04. A provisional estimate that loses a few steps has lost nothing it was entitled to keep.
- **In M05 (a small ask):** `/select` should fill `theta_provisional` from `_SESSIONS[session_id]` when the caller omits it. Then M06 need not carry θ at all.

**`coverage_debt` is keyed by concept id, not requirement id.** `selection.py:154-160` matches keys against `question.concepts[].concept_id`, whatever the field's docstring says. So M06 translates M02's `requirement_id → concept_id` before calling, and keeps the reverse map to write M02's ledger by requirement id.

**M06 is the only durable record of what a student was asked.**
- M05's `administered` list dies with the process, so `seen_item_ids` and `recent_item_ids` (90-day freshness) come from M06's turns table.
- M04 owns `forced_item_ids` and `bypass_freshness` for re-tests. M06 reads them from the profile summary's `retests` and forwards them.

**The bank today: 12 `dsa_verbal` items and an 8-item fallback playlist.** Every other round type returns 409. `/bank/health` (:165) reports counts per concept, not per round type.

**Fix:** M06 checks round availability **at plan time** by calling `/select` once per candidate round type (it is side-effect free) and drops segments that return 409. This is EC-6.16's rule generalised: *a round the bank cannot fill is replaced at plan time, not discovered at runtime.*

**No channel for `difficulty_offset`.** `SelectionRequest` has no field for it, and M06 must not shift θ to fake one. Until M05 adds the field, the four modes differ in **mechanics**, not item difficulty, and the setup copy must not promise harder questions. *(M05 ask.)*

**Modality vocabulary.** M05's `Modality` enum is `verbal | coding | design | mcq | numeric | case | gd_topic`. M06's `canvas` is M05's `design`. Use M05's words on the wire.

### 1.3 M13 — synchronous, one rubric, and consent it cannot supply

**Verified.** `POST /v1/evaluations` (`router.py:187`) takes `EvaluateRequest` (`router.py:40`):

```
turn_id, candidate_id, session_id, question_id, answer_text, code?, canvas?,
hint_level_used, consent_id?, round_type?, ensemble, supersedes?
```

**It is synchronous.** It scores and stores before returning, and its docstring says *"Async in production (FR-13.19)"*, meaning the caller's job. M06 therefore never calls it from the turn loop. It writes an **evaluation outbox row** in the same transaction as the turn and a background drainer posts it. This is the pattern M04 and M13 already use, so no Redis and no worker process are needed in Phase 1.

**`round_type` must be the one M05 returned** (`SelectionResult.round_type`), because M13 resolves the rubric from it. It uses the rubric vocabulary:
- **Phase 1 set** (M13 §6.1, Revision 2): `dsa_verbal`, `dsa_coding`, `cs_core`, `communication`.
- **Shipped:** `rubrics/dsa_verbal.yaml` only.

§5's `round_type: Literal["warmup","project","dsa","cs_core",...]` is a different vocabulary for a different idea. **Split it:**
- `PlannedSegment.kind`: warm-up / technical / project / behavioural / closing. This is what the student sees.
- `Turn.rubric_round_type`: per question, from M05. This is what M13 scores against.

A turn with no rubric M13 can load is **recorded and not sent** for scoring. The report says "not scored — no rubric for this round yet", which is Rule 2 rather than a 422 retry loop.

**Ensemble choice is M06's.** `ensemble.py:93-97`: `n1_practice` for Practice mode and for the degradation ladder, `n3_het_v1` otherwise.

**The hint deduction is M13's, applied once.** `service.py:82` `apply_hint_credit` multiplies by `rubric.credit(hint_level)`, and M04 does not re-apply it. FR-6.7's *"published, fixed score reduction"* is therefore **M13's rubric table, which M06 displays** (`GET /v1/rubrics/{round_type}`). M06 records `hint_level_used` and computes nothing. The hints themselves are M05's `hint_ladder`. M06 authors neither.

**Consent cannot be resolved over HTTP today.** `emit.py:142` raises `NoConsent` when `consent_id` is None — *"Consent is resolved at session start (M6)"*. M04 rejects any observation without an active `ConsentRecord` (`store.py:287`). But M04 has **no route that reads or grants consent** (`models.py:182`); only `seed.py` and the test fixtures create rows. The instruction points at a door that does not exist.

**Fix:**
- **M06:** calls a consent lookup at bootstrap through an adapter.
- **M04 (ask):** add `GET /v1/candidates/{cid}/consent?purpose=`. The grant screen belongs to Platform_Shell's login work.
- **Until both land:** sessions run and are scored; M13's outbox holds the observations; the report says *"this session didn't update your skill graph — consent isn't recorded yet"*. That is true, and better than a silent no-op.

**Steelman needs a rubric that does not exist.** The M13 review settled that a `deliberately_false` turn is dispatched against a `push_back` rubric variant. The shipped M13 selects by `round_type` alone and has no `push_back` rubric. Scoring a steelman turn under `dsa_verbal` would **score agreement with a falsehood as knowledge**, the exact inversion FR-6.20 exists to prevent. **FR-6.20 is blocked on M13**, and until it lands no steelman is ever asked, in any mode.

**The artifact id is the turn id.** `service.py` freezes `answer_text` as the transcript artifact with `artifact_id = turn_id`. M06 stores the identical bytes with a checksum, so the report can highlight M13's evidence spans on M06's own transcript and refuse to when the checksums disagree.

### 1.4 M04 — the pinned summary, and a slot M06 has no way to fill

**Verified.**
- `GET /v1/candidates/{cid}/profile-summary?session_id=` (`router.py:274`), service-authenticated (`X-Service-Secret`), is byte-identical for the life of a session (AC-4.13). It is the prefix M06 caches.
- `GET /v1/skill-graph/theta?candidate=&concepts=` (`router.py:163`) gives the posterior that seeds M05.

`service.py:729`: *"`recent_sessions` … M6 fills these. Present-and-empty, not absent."* There is no write path. **Contract to agree, not a blocker:** M06 exposes `GET /v1/candidates/{cid}/sessions/recent`, and M04 reads it when it builds a summary. The empty list stays the honest shape until then.

**`break_depth` stays in M06.** It is an M06 fact about a session, read by M16 and M19. It is not an observation, and pushing it into M04 as one would put a probe-ladder position inside θ.

### 1.5 M01 is a dependency the spec never lists

**Verified.** `resume-ingestion/.../router.py:1372` already calls **`POST {M06}/v1/drills`** with:

```json
{ "candidate_id": "…", "source_module": "M01", "claim_id": "…", "claim_text": "…",
  "probes": [{ "depth": 0, "question": "…", "expects": "…" }] }
```

It expects `{session_id | id, url | session_url}` back, and it already degrades cleanly when M06 is down. It is M01's stated KPI (AC-1.8), and §7 has no such route.

**Add FR-6.23, the defend drill.** It is a single-claim session of about two minutes. M01's probe ladder is the question source, and the flow is graceful exit, then a report. **It is the smallest complete session the engine can run, which makes it the first vertical slice** (Part 4, day 2).

- **Drill turns are not scored in Phase 1.** M13 needs an M05 question package (`router.py:193-201` returns 404 without one), and M01 probes are not bank items. The drill's product is the ladder and the break point. The report says so. Minting grounded M05 items from claims is Phase 2 (M05 §6.12 already has the consent and scoping rules).
- **The project segment** (§2.2, *"your crop-disease project ← from your GitHub"*) needs M03, which is not built. In Phase 1 it sources from M01's highest-risk claims, via `GET /v1/resumes/candidate/{cid}` and `/claims`.

**Launcher bug, verified.** M01's `module.json:39` names the repo `mock-interview-engine`. The real repo is `Mock_Interview_Engine`, and `scripts/launch.ps1:323` finds siblings by the last segment of that URL, so M01's `start.bat` would silently skip a running M06. **One-line fix in M01.**

### 1.6 Platform_Core v0.9.1

- **`ai_core.identity`** (v0.9.0). M06 is born calling `may_see` on every candidate-scoped route. PLATFORM_TODO §1: *"every module that ships before [login] is another call site to change afterwards"*. So M06 ships as one that doesn't need changing.
- **`ai_core.models`.** Tiers are `generation` (gpt-oss-120b), `extraction` / `classification` (gpt-oss-20b), and `guard` (prompt-guard-86m). §6's frontier/mid/cheap tiers don't exist here. The mapping:
  - interviewer utterance → `generation`
  - `ProbeStrategist` → `classification`
  - round summary → `extraction`
  - EC-6.6 injection check → `guard`
- **`ai_core.dependencies`** for `/v1/deps`, with a human `on_missing` sentence per upstream, as every shipped module does.
- **`ai_core.versions.VersionStamp`** on every turn and plan.

---

## Part 2 — Wrong, not just out of date

### 2.1 §6.1 step 3 hands the structure to a model

Trap 1: *"the LLM fills utterances, it does not decide the structure."* §6.1 step 3: *"OrchestratorSupervisor → InterviewPlan (frontier tier, ~2.5 s)"*. With 1.1 in place, plan assembly is deterministic over M02's plan, M05's availability and the mode config. That removes about 2.5 s from a 4 s bootstrap budget and one model call that could invent a round.

### 2.2 The "Struggling" trigger reads things it must not

§6.4: *"Mean score < 0.3 across the round AND delivery signals show distress."*
- **M13 scores are asynchronous** (p95 ≤ 15 s, AC-13.13), so at a round boundary the last turns' scores usually do not exist.
- **They are uncalibrated.** `GET /v1/calibration` is `display_numeric: false` everywhere, and a number nobody may show should not steer the session either.
- **"Distress" is an emotion inference.** M12's charter (Module_Overview): *"it does not infer emotion, personality or hireability."*

**Fix.** Re-plan triggers read only M06's own hot-path signals:
- strategist bands;
- break depths (≥ 3 breaks at depth ≤ 1 in a round → recovery posture);
- silence timeouts;
- the clock.

M13 scores are read by exactly one component, the post-session report assembler.

### 2.3 M12 on the hot path

§6.2 calls `multimodal.extract(answer)` inside the turn loop. M12 is Phase 3 and `required: false` everywhere. It comes out of the Phase 1 loop, and when it arrives it goes off-path like evaluation.

### 2.4 The ladder asks a steelman in Practice mode

```python
LADDER = ["clarify","deepen","mechanism","counterfactual","steelman","transfer"]
...
return LADDER[L.current_depth + 1]
```

**Verified by tracing.** At `current_depth == 3`, the fallthrough returns `LADDER[4] == "steelman"`, in **every** mode. The `final_boss` branch above it is not the only way in. Every Practice session that reaches depth 3 on a good answer would be told something false on purpose.

**Also:**
- `LADDER[0] == "clarify"` is unreachable by depth, since the fallthrough starts at index 1.
- `L.ceiling = …` assigns a field `ProbeLadderState` does not declare.

**Fix.**
- **Rungs and moves become separate things.** Rungs are depths 1–5. Moves are `clarify`, `silence`, `steelman`, `hint` and `move_on`, and they are never rungs.
- **The wording of rung *d* is derived, not hardcoded** (the platform rule): from the question's own `follow_ups[depth=d]` (M05) or `probes[depth=d]` (M01). The generic rung names (deepen → mechanism → counterfactual → transfer) are the fallback when a question has no template at that depth.
- **`steelman` is reachable only through a mode flag** that is off in every mode until the `push_back` rubric exists.
- **`ceiling` becomes a declared field.**

### 2.5 The budgets assume models this platform does not run *(unmeasured)*

- `gpt-oss-120b` and `-20b` are **reasoning** models. `ai_core/models.py` warns that hidden reasoning tokens are billed and count against `max_tokens`. M01's roster note puts 120b at about 2.3 s for three grounded questions.
- A text turn is `ProbeStrategist` then an interviewer utterance, two reasoning calls in series. §11's p95 of 2.5 s from submit to rendered is **unlikely as written** *(judgment)*.

**Fix, before anything is built on top of it:**
1. **Gate on time-to-first-visible-token.** The utterance streams over SSE, and "the interviewer started talking" is what a student perceives. Record the full-render time beside it.
2. **Structural moves use templated copy.** Graceful exit, round bridge, hint delivery, time warning and the closing are already written in §6.5 and §2. The model is called only to phrase a question or a probe.
3. **The strategist runs on `classification` at the lowest reasoning setting the provider accepts**, with a hard timeout and §10's fallback (`deepen` once, then `move_on`).
4. **Day 2 builds a latency harness against the live account.** It reports p50 and p95 per call before day 3 builds on those numbers.

**AC-6.11 (cache-hit ≥ 0.7)** stays a *discipline*: byte-stable prefix, pinned M04 summary. It becomes a *gate* only if the provider's usage block reports cached tokens. No module has checked that. Until someone does, it is reported as "not measured", not as passing.

**§11's rupee figures** price a different provider. On the platform's account the binding constraint is **rate limits**, not rupees. Re-express the budget as calls and tokens per session and measure them on day 2.

### 2.6 Phase 1 cannot deliver four modalities

FR-6.10 and FR-6.11 are P0 for voice, text, coding and canvas. Voice is M11 (Phase 3), the editor and judge are M07 (not built), and the canvas is M08 (Phase 2).

**Re-scope.**
- The turn contract carries `modality`, and the per-modality completion contract (§3.2.2) is defined.
- **Text is the only implementation in Phase 1.** A switch between modalities keeps state (FR-6.11), which is testable with text ↔ "text with code block".
- The voice half of FR-6.22 moves to Phase 3.
- The setup card offers Text and says voice is coming. A disabled radio button that does nothing is not an option.

### 2.7 The closing questions have no rubric

FR-6.21 says to score the student's own closing questions. No rubric for it exists in M13's Phase 1 or Phase 2 set. **Record them; don't score them.** Promote the requirement when a rubric exists.

### 2.8 The idempotency key defeats itself

§3.2.4: *"Every node keyed by `(session_id, node, turn_idx, attempt)`."* A retry increments `attempt`, so the retry has a different key from the original and nothing is de-duplicated.

**Fix.**
- The key is `(session_id, turn_index, step)`, with `attempt` as a counter on the row.
- **The event log is append-only with that unique key**, and the session state is a fold over it. Checkpoint, replay and "report even if the checkpoint write failed" (§10) then become the same mechanism, not three.

### 2.9 M06 does not build the evaluator's view

§6.3's `project_for_evaluator` is M13's, and it is shipped (`projection.py`, with a type-graph walk in CI as AC-13.2). M06 builds only the `EvaluateRequest`.

**AC-6.2 therefore becomes a test on M06's outbound payload.** It carries this answer's text and nothing else from the session: no interviewer reasoning, no probe intent, no `deliberately_false`, no other turns. It is checked against the same forbidden-name idea M13 uses, except `candidate_id`, which M13 needs for the observation and strips before projection.

### 2.10 The strategist's verdict is a score — keep it out of the interviewer's view

The strategist's `band` is a provisional judgement of the answer. AC-6.3 (*"the interviewer never receives current-round scores"*) has to cover it, or the utterance model sees "below" and telegraphs it.

**`InterviewerView` receives the chosen *move*, never the band.** The boundary test walks `InterviewerView`'s type graph for `ProvisionalOutcome`, `band`, `TurnEvaluation` and any score-named field.

### 2.11 One structured call, not four vague attributes

§6.5 reads `answer.is_ambiguous`, `answer.failed_justification` and `answer.trailing_off` as if the answer carried them. They are the strategist's output, so define it once:

```python
class StrategistVerdict(BaseModel):
    band: Literal["below", "at", "above"]          # → M05 ProvisionalOutcome
    confidence: float
    justification: Literal["held", "partial", "failed"]
    ambiguous: bool                                  # → clarify (no depth)
    off_question: bool                               # EC-6.2
    asks_interviewer: bool                           # EC-6.3
    asks_for_answer: bool                            # EC-6.5
    key_points_missing: list[str]                    # M05 key-point ids
```

One `json_schema` call, which gpt-oss honours per `ai_core.models`. EC-6.2, EC-6.3 and EC-6.5 are handled by the same call rather than three more.

### 2.12 Final Boss, once steelman is out

The Phase 1 Final Boss is: no hints, a hard timer, `bar_raiser`, shorter patience, and the ensemble at full size. Interruptions need voice. That is still "pressure via mechanics, never rudeness" (FR-6.9). The setup copy lists only what is true.

### 2.13 One active session per student needs a mechanism

EC-6.13 blocks parallel sessions. It needs a unique constraint over `(candidate_id)` for sessions in a live state, plus a compare-and-swap so two tabs on **one** session cannot both advance it.

*Built on day 1, two refinements:*
- **One live session per student.** This is a unique nullable `occupying_key` rather than a partial index, because the partial index is spelled differently on SQLite and Postgres.
- **The compare-and-swap sits on the event log's `(session_id, seq)`, not on the checkpoint.** Building it exposed a real bug: taking `seq` from `max(seq)` after reading state lets the losing tab commit a second answer to one question. Spec §6.8 now says where the seq must come from.

---

## Part 3 — What Phase 1 M06 is

**In:**
- **Text-mode sessions:** the defend drill (FR-6.23) and the full mock.
- **Planning and pacing:** plan assembly over M02, preview with drop-a-segment, round execution and bridges.
- **The ladder:** derived rungs, graceful exit and `break_depth`, plus M05's hint ladder.
- **The session contracts:**
  - four modes as configs, with no steelman;
  - seven personas as parameter vectors;
  - fixed-size context;
  - pacing at 70/90/100 and at most two re-plans from hot-path signals;
  - pause and resume, reconnect, one live session per student;
  - the degradation ladder.
- **Outputs:**
  - an evaluation outbox to M13;
  - the M02 ledger (`asked`, `answered`, `skipped`);
  - the M05 θ seam;
  - the M04 pinned summary.
- **Reporting:** an event-sourced trace with replay, and a session report served by M06 until M19 exists.
- **Identity:** `may_see` on every route.

**Out, each with the thing it waits on:**

| Deferred | Waits on |
|---|---|
| Voice, barge-in, mic check, voice latency | M11 (Phase 3) |
| Coding rounds | M07 |
| Canvas rounds | M08 (Phase 2) |
| Camera, presence | M12 (Phase 3) |
| Steelman probes (FR-6.20) | M13 `push_back` rubric |
| Closing-question scoring (FR-6.21) | a rubric |
| Mode-dependent item difficulty | M05 `difficulty_offset` |
| Skill-graph updates from sessions | M04 consent route |
| Scored drill turns | M05 grounded items from M01 claims |
| Ambient bed (§6.10) | Phase 3, as already stated |
| Langfuse export | keys; the event log is the trace of record (port 3001 is reserved) |

---

## Part 4 — Build order, re-estimated

The spec's 14 days hand-rolled a state machine on day 1 and replaced it with LangGraph on day 3. That is double work whichever way decision 1 below goes. Days 1–2 here are needed under either choice.

| Day | Task | Exit |
|---|---|---|
| 1 | **Scaffold and state.** Repo per platform convention (ports 8106/5206, `module.json`, Platform_Core v0.9.1, `/health`, `/v1/deps`). One adapter per upstream, each with a fixture implementation, so M06 runs alone. Session, turn and event tables; state as a fold over the event log; checkpoint with version CAS; one live session per student; `may_see`. | Tests green with no upstream running |
| 2 | **The drill slice.** `POST /v1/drills` (M01's contract); present, answer, fixture strategist, ladder, graceful exit, end, minimal report; SSE events; minimal stage UI. **Latency harness on the live account.** | The first end-to-end session; p50/p95 per call written down |
| 3 | **`ProbeStrategist`** as one structured call; derived rungs; `break_depth`; `ProvisionalOutcome` to M05. Decision 1 settled against the day-2 code. | Ladder tests, including "no steelman at any depth in any mode" |
| 4 | **Boundaries and outbound.** `InterviewerView` and outbound-payload tests (AC-6.2, AC-6.3); evaluation outbox to M13; ledger writes to M02; consent adapter. | Gates green |
| 5 | **Plan assembly** over M02 plus plan-time round availability from M05; warm-up and reserved closing; preview UI with drop-a-segment. | Plan tests across 12 budgets × 6 archetypes; closing always survives |
| 6 | **Rounds.** Per-segment selection, 409 as an honest round end, templated bridges, `RoundTransition`. | A full mock on fixtures |
| 7 | **Hints.** M05's hint ladder, `hint_level_used`, M13's credit table displayed; EC-6.5. | — |
| 8 | **Context.** Rolling six turns, a round summary every four turns, the pinned M04 prefix. | AC-6.10: token variance < 15% over 60 simulated turns |
| 9 | **Personas and modes.** Seven personas as parameters, four modes as configs, guard model plus rule filter failing open (EC-6.4, EC-6.6). | — |
| 10 | **Pacing and re-planning.** 70/90/100 pacing, time warnings, reserved closing; re-plan from hot-path signals only, at most two, `plan.changed`. | Pacing and re-plan tests |
| 11 | **Pause and reconnect.** Pause/resume, `resume-state`, silence prompts (EC-6.1), auto-close (EC-6.14). **Chaos tests.** | The five chaos scenarios pass |
| 12 | **Degradation and report.** Degradation ladder (templated interviewer on outage, `n1` ensemble, deferred evaluation); partial-report path; report page honouring M13's display gate. | AC-6.1: a report for 100% of sessions, aborted included |
| 13 | **UI pass.** Setup, preview, stage, transcript drawer, timer (ARIA 10/5/1), pause, reconnect, end card; `routes.tsx` for Platform_Shell; mobile. | — |
| 14 | **Scripted student.** 20 sessions × 4 modes; manual QA script. | Integration green |
| 15 | **Close-out.** Cross-module asks raised, TODO reconciled, human-evaluation round 1 prepared. | — |

**15 days, over less scope than the original 14 covered.** The extra day is the contract work in 1.1–1.5, which the original plan could not have known about.

---

## Part 5 — Asks of other modules

None of these blocks day 1. Each is small and belongs in its own repo's TODO.

| Module | Ask | Why | Size |
|---|---|---|---|
| M01 | `module.json` repo URL → `Mock_Interview_Engine` | `launch.ps1:323` silently skips M06 otherwise | 1 line |
| M01 | Forward `X-Role` / `X-Candidate-Id` on the drill hand-off, as M02 does to M01 (`router.py:982`) | M06 enforces identity (FR-6.26). M01's call sends only `Content-Type`, so it is anonymous and gets refused | 2 lines |
| M13 | Read `M04_SERVICE_SECRET`, not `SERVICE_SECRET` (`emit.py:318`) | M04 checks `M04_SERVICE_SECRET` (`keys.py:33`), so once a secret is set, M13's observation emit is refused | 1 line |
| M05 | `/questions/select` reads `_SESSIONS[session_id]` when `theta_provisional` is omitted | M06 must not carry, and so checkpoint, the provisional θ | ~5 lines |
| M05 | `difficulty_offset` on `SelectionRequest` | Modes can't change item difficulty without it | small |
| M05 | per-round-type counts on `/bank/health` | Plan-time availability without probing `/select` | small |
| M04 | `GET /v1/candidates/{cid}/consent?purpose=` | M13 requires `consent_id` and nothing can look one up | small |
| M04 | read M06's recent sessions into `recent_sessions` | The slot is promised and has no source | small |
| M13 | `push_back` rubric variant, dispatched by caller | Unblocks FR-6.20 | rubric authoring |
| M13 | `cs_core`, `communication` rubrics (the Phase 1 set) | Only `dsa_verbal` is scoreable today | rubric authoring |
| M02 | docstring: M06 writes `asked` and `answered`, not M05 | The docstring names a writer that has no client | 1 line |
| Platform | `modules_meta` M06 → built; `Platform_Shell/journey.ts` "Not built — Q2" | When M06 ships | 2 lines |

---

## Open decisions

1. **LangGraph, or an explicit event-sourced state machine?** The master plan (§26) and the M04 review ("the honest home is M06's interview loop") point at LangGraph.

   *(judgment)* Recommendation: **an explicit state machine for Phase 1.**
   - The Phase 1 loop is linear: segments in order, and inside each one ask → answer → decide → ask or move on.
   - Its checkpoint contract is stricter than a generic checkpointer: version CAS, a de-duplicated event key, and a report that can be rebuilt from the log alone.
   - No module on the platform uses the LangChain stack. `ai_core.models` is a direct client.
   - Node functions are pure either way, so wiring them into a graph later is one file, not a rewrite. Revisit when the loop stops being linear (hybrid GD, multi-agent panels).
   - If the viva needs "LangGraph" on the architecture slide to match the master plan, that is a reason to choose it, and it is your call.

2. **Where the session report lives until M19 exists.** Recommendation: M06 serves it at `/sessions/:id/report`, and M19 later projects the same data. Two report implementations should never coexist, so M06's is deleted when M19's ships.

3. **Drill scoring.** Leave drills unscored in Phase 1 (recommended), or have M05 mint grounded items from M01 claims now? The second makes the drill count toward mastery, and costs M05's grounded-generation path, which is Phase 2 work.

4. **The spec's own five decisions** (§15) stand. Decision 5 (steelman frequency) is moot until the `push_back` rubric exists.
