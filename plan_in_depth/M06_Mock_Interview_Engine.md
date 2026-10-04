# M6 — Mock Interview Engine

> **Master plan reference:** §32 + §26 · **Phase:** 1–2 · **Owner:** E2 · **Depends on:** M2 (the coverage plan), M4 (pinned profile, posterior, consent), M5 (selection, hints, the provisional θ), M13 (scoring), M1 (defend drills, project claims) — **all optional at runtime**, each behind an adapter with a fixture · `Platform_Core` v0.9.1 · **Feeds:** M13, M2, M5, M4, M16, M19 · **This is the product's front door.**
>
> **Revision 2** (2026-09-16) — reworked after [M06_REVIEW.md](M06_REVIEW.md), which was checked against the shipped code of all five modules M06 talks to. Substantive changes: the plan wraps M02's `CoveragePlan` instead of re-allocating, and no model builds it (§6.1); M06 writes the coverage ledger's `asked`/`answered`/`skipped` (§6.2, FR-6.24); the provisional θ is M05's and is never checkpointed (§6.8, FR-6.25); the round-type vocabulary splits into the student-facing segment and the rubric M13 scores against (§5); the default probe ladder no longer reaches `steelman` in every mode, and rungs are derived from each question's own follow-ups (§6.5); steelman is **off** until M13 ships a `push_back` rubric (FR-6.20); re-plan triggers read only hot-path signals, never M13 scores or "distress" (§6.4); the strategist is one structured call whose band never reaches the interviewer (§5, §6.3); the idempotency key no longer includes `attempt`, and session state is a fold over an append-only event log (§3.2, §6.8); the defend drill M01 already calls is specified (FR-6.23, §7); identity via `ai_core.identity` on every route (FR-6.26); Phase 1 is text-only and the latency gate is time-to-first-token on the models this platform runs (§11, AC-6.4); build order re-estimated at 15 days over a smaller Phase 1 scope (§14).

---

## 1. In one paragraph

The student drops in a JD and the orchestrator does what a placement coordinator, a panel lead, and three interviewers would do: reads the role, reads the candidate, plans a sequence of rounds with a time budget, runs each round with an appropriate persona, probes every answer until understanding breaks, adapts the plan when reality diverges from the plan, and hands off to evaluation and coaching. Everything else in the platform is either an input to this loop or an output of it. It has to feel like an interview — not a quiz with a chat interface — which means the engineering is mostly about **timing, memory, and knowing when to stop asking.**

---

## 2. Reverse-thinking: the user

### 2.1 The single sentence this module must earn

> *"That felt like a real interview."*

Everything below is in service of that sentence. Students will forgive a wrong score. They will not forgive an interviewer that asks a follow-up to an answer they never gave, forgets what they said two minutes ago, or ends abruptly.

### 2.2 The full journey

#### Pre-interview: the setup (must take under 60 seconds)

```
┌──────────────────────────────────────────────────────────────┐
│  Zoho · Software Engineer · 45 min                           │
│                                                              │
│  How do you want to do this?                                 │
│    ● Voice   — closest to the real thing                     │
│    ○ Text    — quieter, works on bad wifi                    │
│    □ Camera on (optional, for presence feedback)             │
│                                                              │
│  Difficulty                                                  │
│    ○ Practice — hints on, no timer, gentle                   │
│    ● Mock     — realistic                                    │
│    ○ Final Boss — no hints, hard timer, interruptions        │
│                                                              │
│  ⏱ You have about 45 minutes. You can pause once.            │
│                                                              │
│  [ Check my mic ]              [ Start interview → ]         │
└──────────────────────────────────────────────────────────────┘
```

**The mic check is not optional and must be a real check** (record 3 seconds, play it back, show the level meter). Half of all "the AI didn't hear me" complaints are a browser permission or a wrong input device, and finding out 8 minutes in ruins the session.

> **Phase 1 (Revision 2).** Text is the only modality that exists — voice needs M11, camera needs M12. The Phase 1 setup card offers Text, says in one line that voice is coming, and shows no disabled radio buttons. The difficulty rows list only mechanics that are true today (§6.7): Final Boss is "no hints, hard timer", not "interruptions".

#### The plan preview (10 seconds, skippable, high trust value)

```
  Here's what I'm planning:

  1. Warm-up                     5 min
  2. Your crop-disease project  12 min   ← from your GitHub
  3. DSA — arrays, then DP      15 min   ← DP is your weak spot
  4. DBMS quickfire              8 min   ← this JD mentions it 3×
  5. HR + your questions         5 min

  [ Looks good, start ]   [ Change something ]   [ Skip this ]
```

Two things happen here: the student understands the session is *designed*, and they get one chance to say "actually, no system design today". Both increase completion rates.

Every line of this preview comes from somewhere checkable: segment minutes and the "this JD mentions it" reasons are M02's allocations and rationales, "your weak spot" is M04's pinned summary, and "from your GitHub" becomes "from your resume" in Phase 1 — M03 is not built, so the project segment draws on M01's highest-risk claims. A segment the question bank cannot fill is not shown at all (§6.1).

#### During the interview — the screen

```
┌────────────────────────────────────────────────────────────────┐
│ ● Recording        Round 3 of 5 · DSA          22:14 remaining │
│                                                                │
│                    ┌──────────────┐                            │
│                    │              │   Priya                    │
│                    │   (avatar)   │   Senior Engineer          │
│                    │              │   ● speaking               │
│                    └──────────────┘                            │
│                                                                │
│  "Okay. Given an array of integers and a target, return the    │
│   indices of two numbers that add up to it. Talk me through    │
│   how you'd approach it before you code."                      │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ▁▃▅▇▅▃▁  Listening…                        [ ⏸ Pause ]  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  [ 💬 Switch to typing ]  [ ↻ Repeat that ]  [ ⚑ ]             │
└────────────────────────────────────────────────────────────────┘
```

**Every control here exists because of a specific failure:**
- `Repeat that` — a student who didn't catch the question will otherwise fake an answer and get a bad score for an audio problem.
- `Switch to typing` — mid-session, without losing state. Wifi dies, roommate walks in, mic fails.
- `Pause` — once per session, 5 minutes max. Real life happens. A student who can't pause abandons instead.
- `⚑` — flag a bad question (M5).
- **The remaining-time counter is always visible.** Hiding it to "increase pressure" is a cheap trick that mostly causes anxiety-driven abandonment.

**What is deliberately absent:** any live score, any correct/incorrect indicator, any progress-toward-a-grade. Feedback during a real interview doesn't exist, and showing it destroys the measurement (students start optimising for the meter).

#### The probe experience — what a break point feels like

```
Q:  "How would you make this faster?"
A:  "Use a hash map."
Q:  "Why does that help?"                                    ← L1
A:  "Because lookup is O(1)."
Q:  "What makes it O(1)?"                                    ← L2
A:  "Because... hashing puts it directly in a slot."
Q:  "And if two keys hash to the same slot?"                 ← L2 deeper
A:  "Then... um. I think it overwrites?"                     ← BREAK POINT
Q:  "Fair enough — that's the edge of it. Let's move on."    ← graceful exit
```

**The graceful exit is a hard requirement.** A student who is drilled two levels past their break point feels humiliated. The moment the ladder detects failure, the interviewer acknowledges neutrally and moves on. The *report* explains what happened; the *interview* doesn't dwell. This one behaviour is the difference between "that was tough but fair" and "that was brutal", and they produce identical data.

#### The end

```
  That's time. Thanks — you handled the DP question better than
  most people do.

  I'm scoring it now — your report will be ready in about a minute.
  I'll email you when it's done, or you can wait here.

  [ Wait for my report ]     [ I'll check later ]
```

Warm, specific (one genuine observation), honest about the delay, and gives them an exit. Never a silent redirect to a loading dashboard.

### 2.3 Abandonment: where and why

| Drop point | Rate risk | Counter |
|---|---|---|
| Setup screen | High | ≤ 60 s, sensible defaults, one-click start |
| First 2 minutes | Highest | Warm-up round is deliberately easy and conversational; nobody's first question is hard |
| Mic/audio failure | High | Real pre-check + one-tap switch to typing |
| Mid-session, feeling stupid | Medium | Graceful exits, recovery rounds after failure clusters, no live score |
| Long silence from the AI | Medium | Filler acknowledgement within 800 ms of any turn end |
| No time to finish | Medium | Visible timer + "we can wrap up early" offer at 70% if pace is slow |

**The pace-check rule:** at 70% of the time budget, if coverage debt is high, the interviewer says *"We've got about 12 minutes — I'll focus on the DBMS side, is that okay?"* Real interviewers do this. It converts a rushed ending into a managed one.

---

## 3. Reverse-thinking: the developer

### 3.1 The seven traps

**Trap 1 — Building it as a chat loop.** A chat loop has no plan, no rounds, no coverage, no time budget, and no memory of intent. It's easy to build and it will feel exactly like ChatGPT with a system prompt. *Counter: the session is a state machine over `InterviewPlan`; the LLM fills utterances, it does not decide the structure.*

**Trap 2 — Letting evaluation block the conversation.** A 12-second frontier-model evaluation between turns is a dead interview — and M13's `POST /v1/evaluations` is synchronous, so calling it inline is the easy mistake. *Counter: `ProbeStrategist` (the `classification` tier, one structured call) decides the next move on the hot path; the turn's evaluation request is written to an outbox in the same transaction as the turn and drained afterwards (§6.2). This is the single most important architectural decision in the module.*

**Trap 3 — Unbounded context growth.** By turn 30 you're sending 40k tokens per turn, latency doubles and cost quadruples. *Counter: rolling window of the last 6 turns verbatim + a maintained round summary + the working-tier profile. Fixed context size regardless of session length (§6.6).*

**Trap 4 — Re-planning too eagerly.** A supervisor that re-plans after every turn produces an interview that wanders. *Counter: re-plan only at round boundaries, max 2 per session, on explicit triggers (§6.4).*

**Trap 5 — Losing the session on a refresh.** Student's browser crashes at minute 30 and everything is gone. This will happen, and it will happen to your demo. *Counter: `SessionState` is checkpointed to Postgres after every node; reconnect resumes from the last checkpoint with a "welcome back, we were on question 4" (§6.8).*

**Trap 6 — The interviewer knowing the score.** If the interviewer node can read `TurnEvaluation`, it will telegraph ("Good!" / "Hmm, not quite") and the whole blind-scoring property is dead — plus students read the tell and optimise for it. *Counter: state projections, enforced at the node level (§6.3), not by asking the prompt nicely.*

**Trap 7 — Personas that are just adjectives in a prompt.** "Be a strict interviewer" produces a rude one on some turns and a friendly one on others. *Counter: personas are parameter vectors that drive concrete mechanics — silence duration, interruption threshold, hint availability, verbosity target (§6.7).*

Three more, added in Revision 2 because the upstreams now exist and each one is easy to fall into:

**Trap 8 — A second planner.** M02 already allocates the question budget across requirements, prices rounds by modality and names the must-haves that did not fit. Re-deriving minutes per round here produces a preview that disagrees with M02's coverage screen. *Counter: `InterviewPlan` wraps M02's `CoveragePlan`, frozen at bootstrap, and adds only what M02 does not know — warm-up, closing, personas, mode (§6.1).*

**Trap 9 — Writing down the provisional θ.** M05 steers selection by a session-scoped estimate that must never be persisted (M05 §6.10, `ProvisionalIsNotDurable`). M06 checkpoints after every step; the obvious implementation puts θ in the checkpoint. *Counter: θ lives in process memory only; the checkpoint schema has no field for it and a gate test proves it (FR-6.25, AC-6.13).*

**Trap 10 — Scoring a trap as knowledge.** A steelman turn scored under the ordinary rubric rewards agreeing with a falsehood. *Counter: no steelman is asked in any mode until M13 serves a `push_back` rubric to dispatch it against (FR-6.20, AC-6.14).*

### 3.2 The non-obvious hard parts

1. **Time budgeting is a scheduling problem.** Rounds overrun; students ramble; a coding problem takes 18 minutes instead of 12. The supervisor must continuously re-allocate remaining time, and must always reserve the closing round.
2. **"Answer complete" is genuinely hard.** In text, it's a submit button. In voice, it's M11's semantic endpointing. In coding, it's neither — a student who stops typing may be thinking. The engine needs a per-modality completion contract.
3. **The transition between rounds is where immersion breaks.** A hard cut from DSA to HR feels like a page load. Scripted, persona-appropriate bridges ("Alright, let's switch gears — I'd like to hear about a time you disagreed with a teammate") cost nothing and matter a lot.
4. **Idempotency under retry.** A worker crash mid-turn must not double-charge, double-ask, or double-score. Every step is keyed by `(session_id, turn_index, step)` — **not** including `attempt`, which would give every retry a fresh key and de-duplicate nothing. `attempt` is a counter on the row.
5. **The report must exist even if everything failed.** A session that crashed at turn 12 still produces a report for the 11 turns that worked. Never a dead end. Session state is a fold over an append-only event log (§6.8), so the report, the checkpoint and the replay are one mechanism rather than three.
6. **"Selected" is not "asked".** A question M05 selected may never be presented — the session can end in between. Only M06 knows a question reached the student, so only M06 writes `asked` to M02's coverage ledger.

---

## 4. Functional requirements

**Phase** says when the requirement can be met, not when it matters. `1` is buildable now; `1·text` is the text half of a requirement whose other half waits on a module; `3` waits on Phase 3; **blocked** names the upstream that has to ship first.

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-6.1 | Build an `InterviewPlan` from M02's `CoveragePlan` + M04's profile + M05's round availability + time budget + mode — deterministically, no model call | P0 | 1 |
| FR-6.2 | Show the plan to the student before running, with an edit option (drop a segment) | P1 | 1 |
| FR-6.3 | Execute segments in sequence with a per-segment persona; each turn scored against the rubric M05's selection names | P0 | 1 |
| FR-6.4 | Re-plan at segment boundaries, max 2 per session, on triggers computed from M06's own hot-path signals only | P1 | 1 |
| FR-6.5 | Probe ladder with depth cap 5 and graceful exit on break; rung wording derived from the question's own follow-ups | P0 | 1 |
| FR-6.6 | Record `break_depth` per concept per session | P0 | 1 |
| FR-6.7 | Serve M05's hint ladder in order, record `hint_level_used`, and show M13's published credit table — M06 computes no score reduction | P0 | 1 |
| FR-6.8 | Four modes (Practice / Mock / Real-drive / Final Boss) as configs of one engine | P0 | 1 |
| FR-6.9 | Enforce the Final Boss rule: pressure via mechanics, never rudeness | P0 | 1 |
| FR-6.10 | Support voice, text, coding, and canvas modalities within one session — the turn contract carries `modality` from day 1 | P0 | 1·text; voice 3 (M11), coding blocked (M07), canvas 2 (M08) |
| FR-6.11 | Mid-session modality switch without state loss | P0 | 1·text |
| FR-6.12 | Pause (once, ≤5 min) and resume | P1 | 1 |
| FR-6.13 | Reconnect and resume after disconnect from the last checkpoint | P0 | 1 |
| FR-6.14 | Evaluation must never block the conversational hot path | P0 | 1 |
| FR-6.15 | Interviewer nodes cannot read current-round evaluation scores **or the strategist's band** | P0 | 1 |
| FR-6.16 | Fixed context size regardless of session length | P0 | 1 |
| FR-6.17 | Time-aware pacing with a 70% checkpoint and a reserved closing round | P0 | 1 |
| FR-6.18 | Always produce a report, even on partial/failed sessions | P0 | 1 |
| FR-6.19 | Replayable state and a full model-call trace per session, from an append-only event log; Langfuse is an optional export when keys exist | P0 | 1 |
| FR-6.20 | Deliberate-wrong-statement (steelman) probes marked in the transcript and dispatched against M13's `push_back` rubric | P1 | **blocked** (M13 `push_back` rubric) |
| FR-6.21 | Record the student's own closing questions; score them once a rubric exists | P1 | 1 record · scoring blocked (rubric) |
| FR-6.22 | p95 turn latency: text ≤ 2.5 s to first visible token, voice ≤ 1.2 s to first audio | P0 | 1·text; voice 3 |
| FR-6.23 | **Defend drill** — accept M01's `POST /v1/drills` hand-off and run a ≤ 2-minute single-claim session on M01's probe ladder | P0 | 1 |
| FR-6.24 | Write M02's coverage ledger: `asked` on presentation, `answered` on receipt, `skipped` when a planned requirement is dropped | P0 | 1 |
| FR-6.25 | Post a `ProvisionalOutcome` to M05 after every strategist verdict; never persist the provisional θ | P0 | 1 |
| FR-6.26 | Every candidate-scoped route resolves a principal and calls `ai_core.identity.may_see` | P0 | 1 |

FR-6.23–6.26 are new in Revision 2. None is new scope: each is an obligation a shipped module already placed on M06 — M01 calls the drill route today, M02's ledger has no other writer, M05's CAT has no other signal, and PLATFORM_TODO §1 names every module that ships without identity as a call site to fix later.

---

## 5. Data contracts

**Two vocabularies, deliberately.** A *segment* is what the student sits and sees ("DSA · 15 min"). A *rubric round type* is what M13 scores a turn against, and it is chosen per question by M05's selection (`SelectionResult.round_type`) from the rubric set — Phase 1: `dsa_verbal`, `dsa_coding`, `cs_core`, `communication`; Phase 2 adds `project_defence`, `behavioural_star`, `system_design`, `ml_viva`. Revision 1 used one `round_type` for both, and the two do not map one to one: a "technical" segment can hold `dsa_verbal` and `cs_core` turns.

Modality words are M05's `Modality` enum on the wire (`verbal`, `coding`, `design`, …) — Revision 1's `canvas` is `design`.

```python
from ai_core.versions import VersionStamp

Mode = Literal["practice", "mock", "real_drive", "final_boss"]
SegmentKind = Literal["warmup", "technical", "project", "behavioural", "closing"]

class PlannedSegment(BaseModel):
    index: int
    kind: SegmentKind
    title: str                          # "DSA — arrays, then DP"
    persona_id: str
    minutes: float
    question_budget: int
    requirement_ids: list[str]          # M02's ids — the ledger is keyed by these
    concept_ids: list[str]              # the same requirements, as M05 matches them
    rubric_round_types: list[str]       # what M05 can fill for this segment, probed at plan time
    modality: str                       # M05 Modality
    source: Literal["m05_bank", "m01_claims", "template"]
    rationale: str                      # one sentence, shown in the preview
    is_reserved: bool = False           # closing: never dropped
    dropped_reason: str | None = None   # set by a re-plan or a student edit, never deleted

class Replan(BaseModel):
    at_segment: int
    trigger: Literal["gap_discovered", "ceiling_hit", "struggling", "time_overrun", "modality_lost"]
    signals: dict[str, float]           # the hot-path numbers that fired it — never an M13 score
    before: list[PlannedSegment]
    after: list[PlannedSegment]
    student_sentence: str               # "I changed the plan here because…"

class InterviewPlan(BaseModel):
    id: UUID
    session_id: UUID
    mode: Mode
    total_minutes: int
    segments: list[PlannedSegment]
    #: M02's plan exactly as returned, frozen — the endpoint is not persisted and
    #: a second call can differ. None when M02 was unavailable (§10).
    coverage_plan: dict | None
    coverage_plan_version: str | None   # M02 `plan_version`
    jd_id: UUID | None
    replans: list[Replan] = []          # len ≤ 2 (FR-6.4)
    uncovered: list[str] = []           # carried from M02, shown in the preview
    versions: VersionStamp

class ProbeLadderState(BaseModel):
    concept_id: str
    depth: int = 0                      # rung reached, 0..5 (FR-6.5 cap)
    #: Rungs and moves are different things. A rung consumes depth; a move does not.
    moves: list[Literal["rung", "clarify", "silence", "hint", "steelman", "move_on"]] = []
    break_depth: int | None = None      # set when justification fails at `depth`
    ceiling: int | None = None          # set when two successes at depth ≥ 4 end the ladder
    consecutive_successes: int = 0

class StrategistVerdict(BaseModel):
    """ProbeStrategist's one structured output. The band is a provisional
    judgement of the answer — it goes to M05 and to the ladder, and never into
    InterviewerView (FR-6.15)."""
    band: Literal["below", "at", "above"]     # → M05 ProvisionalOutcome
    confidence: float                          # 0..1
    justification: Literal["held", "partial", "failed"]
    ambiguous: bool                            # → clarify, no depth consumed
    off_question: bool                         # EC-6.2
    asks_interviewer: bool                     # EC-6.3
    asks_for_answer: bool                      # EC-6.5
    key_points_missing: list[str]              # M05 KeyPoint ids
    latency_ms: int

class Turn(BaseModel):
    id: UUID                            # == M13's transcript artifact_id
    session_id: UUID
    segment_index: int
    turn_index: int
    role: Literal["interviewer", "candidate", "system"]
    text: str
    text_sha256: str                    # the bytes M13 scored — highlights are refused on mismatch
    modality: str                       # M05 Modality
    audio_uri: str | None               # Phase 3
    started_at: datetime
    ended_at: datetime | None
    question_id: UUID | None            # M05 item; None for drill probes and templates
    question_source: Literal["m05_bank", "m05_fallback", "m01_probe",
                             "local_fallback",   # M06's own playlist, M05 unreachable (§10)
                             "template"]
    rubric_round_type: str | None       # None → recorded, not sent for scoring
    probe_depth: int
    probe_move: str | None
    hint_level_used: int
    deliberately_false: bool = False    # steelman marker — always False until FR-6.20 unblocks
    asr_confidence: float | None        # Phase 3
    completion_reason: Literal["submit", "timeout", "interrupted", "endpoint", "barge_in"]
    versions: VersionStamp

class SessionEvent(BaseModel):
    """Append-only. Session state is a fold over these (§6.8)."""
    session_id: UUID
    seq: int
    turn_index: int
    step: str                           # idempotency key is (session_id, turn_index, step)
    kind: str                           # question.asked, answer.received, probe.decided, …
    payload: dict
    attempt: int = 1                    # a counter, NOT part of the key
    at: datetime

class SessionFlags(BaseModel):
    status: Literal["planned", "live", "paused", "ended", "aborted"]
    degradation_level: Literal["L0", "L1", "L2", "L3", "panic"] = "L0"
    modalities_available: set[str]
    camera_on: bool = False
    paused_at: datetime | None = None
    pause_used: bool = False
    reconnect_count: int = 0
    evaluation_pending: int = 0         # outbox rows not yet accepted by M13
    consent_id: UUID | None = None      # resolved at bootstrap; None is stated in the report
    #: DELIBERATELY ABSENT: any theta, provisional or otherwise (FR-6.25).
```

**Tables** (SQLite in dev, Postgres in prod, as every platform module):

| Table | What it holds |
|---|---|
| `m06_event` | **The truth.** Append-only. Unique on `(session_id, turn_index, step)` (idempotency) and on `(session_id, seq)` (the compare-and-swap, §6.8). The plan lives here as a `plan.set` payload rather than in a table of its own. |
| `m06_session` | One row per session. `occupying_key` is the candidate id while live or paused and NULL otherwise; a plain UNIQUE on it enforces EC-6.13 identically on SQLite and Postgres, which both allow many NULLs. |
| `m06_checkpoint` | The fold, cached: `version`, `last_seq`, `state_json`. Only ever moved forward. |
| `m06_turn` | A projection of the log for queries a fold is bad at (the 90-day `seen_item_ids`); rebuildable. Carries `text_sha256`. |
| `m06_eval_outbox`, `m06_ledger_outbox` | What M06 owes M13 and M02, written with the turn. `state` is `pending` → `sending` (claimed, with `claimed_at`) → `sent`, or `held` after `MAX_ATTEMPTS`. |
| `m06_llm_call` | Model id, tier, prompt version, tokens in/out/reasoning, cached tokens if the provider reports them, latency, time to first token. |

---

## 6. The pipeline in minute detail

### 6.1 Session bootstrap (target: < 4 s from click to first question)

```
1. Resolve principal (ai_core.identity); refuse unless may_see → full          (FR-6.26)
2. Refuse if the candidate already has a live session                          (EC-6.13)
3. In parallel, each through its adapter, each optional:
     M04  GET  /v1/candidates/{cid}/profile-summary?session_id=   pinned prefix
     M04  GET  /v1/skill-graph/theta?candidate=&concepts=          posterior
     M04  consent lookup                                           consent_id | None
     M02  POST /v1/jds/{jd}/plan/{cid}  {minutes}                  CoveragePlan (if a JD)
     M01  GET  /v1/resumes/candidate/{cid} → /claims               project claims
4. M05  POST /v1/sessions/{sid}/theta/seed {candidate_id, posterior}
5. Round availability: one side-effect-free POST /v1/questions/select per
   candidate rubric round type; a 409 removes it                               (EC-6.16)
6. Assemble InterviewPlan deterministically (rules below) — NO model call
7. Warm the prefix while the preview is on screen (a no-op if the provider
   does not cache; §6.6)
8. Pre-select the warm-up question
9. Open the SSE channel, greet
```

Revision 1 built the plan with a frontier-model call at step 6. That contradicted Trap 1 — the model would decide the structure — and cost ~2.5 s of a 4 s budget.

**Plan assembly rules** — M06 adds to M02's plan; it never re-allocates it (Trap 8):
```
reserve  = closing(5 min, is_reserved) + warmup(min(4, 10% of budget))
M02 call = POST /plan {minutes: requested - reserve}

technical / behavioural segments ← M02.rounds, one per modality, in M02's order,
    each allocation's requirement_ids carried over, concept_ids resolved from the
    JD's requirements, minutes and question budget exactly as M02 priced them
    - a segment whose modality this session cannot serve is dropped and its
      requirements written to the ledger as `skipped` (coding until M07 exists)
    - a segment whose concept set no available rubric round type can fill is
      dropped the same way, and the preview says why
project segment ← only when M01 has ≥ 1 confirmed risky or vague claim;
    minutes taken from the largest verbal segment, never from the closing
no JD      → segments from what M05 can fill, split evenly, labelled
             "not tailored to a job description" (§10)
order      = warmup → project → technical → behavioural → closing
uncovered  = M02.uncovered, shown in the preview with M02's suggestion
```

**Modes are configs, not offsets on θ.** M05's `SelectionRequest` has no difficulty field and M06 must not shift the provisional θ to fake one, so until M05 adds `difficulty_offset` the four modes differ in *mechanics* (§6.7). M02's `difficulty` band describes the student and is shown; it is not added to anything.

| | Practice | Mock | Real-drive | Final Boss |
|---|---|---|---|---|
| hints | yes | yes (M13 credits them) | as Mock | no |
| timer | always shown (§2.2); pacing offers only, nothing forced | shown; §6.9 pacing | as Mock | shown; §6.9 pacing with no overrun allowance — EC-6.9's 25% becomes 0% |
| pause | 1 × 5 min (FR-6.12, every mode) | 1 × 5 min | 1 × 5 min | 1 × 5 min |
| default persona | `friendly_recruiter` | `methodical_engineer` | company-matched | `bar_raiser` |
| M13 ensemble | `n1_practice` | `n3_het_v1` | `n3_het_v1` | `n3_het_v1` |
| retry a question | yes, first attempt scored (§15.4) | no | no | no |
| steelman | off | off | off | off until FR-6.20 unblocks |
| difficulty_offset | −0.3 | 0 | company band | +0.8 — **sent only once M05 accepts it** |

### 6.2 The turn loop

Text mode is request-driven: presenting a question ends one request, and `POST /answer` starts the next. Each step below appends an event keyed `(session_id, turn_index, step)`, so a retried request replays nothing it already did.

```python
async def present_next(s: Session) -> None:
    pick = await questions.select(s.selection_request())      # M5 /questions/select; 409 → end segment honestly
    item = await questions.get(pick.question_id)              # hint_ladder, follow_ups, key_points
    text = await interviewer.phrase(project_for_interviewer(s), item)   # generation tier; streams
    text = guard.screen(text)                                  # rule filter; fail-open (§10)
    append(s, "question.asked", ...)                           # the moment it reached the student
    ledger.write(s, requirement_ids, state="asked", turn_id)    # M2 ledger, via outbox (FR-6.24)

async def on_answer(s: Session, answer: str) -> None:
    turn = append(s, "answer.received", text=answer, sha256=...)
    ledger.write(s, requirement_ids, state="answered", turn_id)

    # HOT PATH — one structured call, narrow context
    v = await strategist.decide(item, answer, s.ladder)        # classification tier → StrategistVerdict
    await theta.observe(s.id, item.primary_concept, v)         # M5 ProvisionalOutcome (FR-6.25)
    move = ladder.decide(s, v)                                 # pure function, §6.5

    # OFF PATH — written in the same transaction as the turn
    if turn.rubric_round_type and not turn.deliberately_false:
        eval_outbox.add(turn, ensemble=s.mode_config.ensemble) # drained to M13 /v1/evaluations

    append(s, "probe.decided", move=move)
    await (present_probe(s, move) if move.is_rung else present_next(s))
```

**The outbox has three senders, and needs all three** (`outbox.py`, `sweeper.py`
— added after the day-4 live run). The request that created the work delivers it
in a background task; a student or an operator can force an explicit drain; and
a per-process **sweeper** works through every session that still owes something,
every 30 s. The first two are not enough on their own: a send that fails puts
its row back to `pending`, and if the student has closed the tab nothing ever
asks again.

Because more than one of them can run at once, **a row is claimed before it is
sent** — a conditional `UPDATE … WHERE state = <what we read>` that commits
before the network call, with a claim that expires (`STALE_CLAIM_S`, 180 s) so a
process that dies mid-send strands nothing. Without the claim, the first live
run had a background task and an explicit drain both post the same answer, and
M13 scored one turn three times concurrently until the third call timed out.
Delivery stays at-least-once by design — M13 keys on `turn_id`, M02's ledger is
append-only — but at-least-once is a safety net, not a plan.

**`ProbeStrategist` gets a deliberately narrow context** — the question, the answer, the item's key points, and the current ladder depth. Not the full transcript. This keeps the call small and forces the decision to be about *this answer*, which is the right scope. It never sees the candidate's identity or profile either: a strategist that knows the student is "weak on DP" judges the answer by the student.

**Structural moves use templated copy, not a model call** — graceful exit (§6.5), round bridge (§3.2.3), hint delivery, time warnings, the closing. The model is called only to phrase a question or a probe from the item's own template. This is the latency plan (§11) and it is also safer: the copy that must never say "wrong" is copy nobody generates.

**M12 is not on this path.** Revision 1 called `multimodal.extract(answer)` inside the loop. M12 is Phase 3 and optional everywhere; when it arrives it runs off-path, like evaluation.

### 6.3 State projections (enforcing the information boundaries)

```python
def project_for_interviewer(s: SessionState) -> InterviewerView:
    return InterviewerView(
        recent_turns=s.transcript[-6:],       # text only
        segment_summary=s.segments[s.current].summary,
        profile_prefix=s.pinned_profile,      # M04's pinned summary, byte-stable
        segment=s.plan.segments[s.current],
        move=s.pending_move,                  # WHAT to do next — never why
        ladder_depth=s.ladder.depth,
        time_remaining_s=s.time_remaining_s,
        # ABSENT: any TurnEvaluation, any M13 score, the StrategistVerdict and
        #         its band, the provisional θ, consent, identity
    )

def evaluation_request(turn: Turn, s: SessionState) -> dict:
    """What M06 sends M13 — M13's EvaluateRequest, exactly. M13 builds the
    blind evaluator view itself (its projection.py, gated as AC-13.2)."""
    return {
        "turn_id": turn.id, "session_id": s.id, "candidate_id": s.candidate_id,
        "question_id": turn.question_id, "answer_text": turn.text,
        "hint_level_used": turn.hint_level_used, "consent_id": s.flags.consent_id,
        "round_type": turn.rubric_round_type, "ensemble": s.mode_config.ensemble,
        # ABSENT: interviewer text, probe move/intent, deliberately_false,
        #         other turns, the verdict, the plan
    }
```

These are functions with tests, not conventions:

- **AC-6.3** walks `InterviewerView`'s type graph and fails on any path reaching `TurnEvaluation`, `StrategistVerdict`, `ProvisionalOutcome`, or a field named like a score, band or θ.
- **AC-6.2** asserts the outbound request's keys are exactly the set above. `candidate_id` is the one identity field present, because M13 needs it to address the observation and strips it before its own projection; everything that would tell the evaluator what the interviewer was thinking is absent.

Revision 1 had M06 build an `EvaluatorView`. That projection is M13's and it has shipped; a second copy here would be two definitions of "blind" that drift.

### 6.4 Re-planning

Triggers (evaluated only at segment boundaries). **Every input is one M06 produced on its own hot path** — strategist bands, break depths, silence timeouts, the clock. M13's scores are never read here: they are asynchronous (p95 ≤ 15 s), so at a boundary the last turns' scores usually do not exist, and they are uncalibrated (`display_numeric: false`), so a number nobody may show should not steer the session either.

| Trigger | Condition | Action |
|---|---|---|
| Gap discovered | ≥ 2 turns in this segment broke at depth ≤ 1 on concepts sharing a prerequisite in M04's graph | Re-target the next segment to that prerequisite |
| Ceiling hit | The segment's stretch item (M05 `reason = stretch`) got band `above` | Allow one extra question per remaining segment (§6.9's ahead-of-schedule rule); raise `difficulty_offset` by 0.4 once M05 accepts the field (§6.1) |
| Struggling | ≥ 3 turns in the segment with band `below` **and** justification `failed` at depth ≤ 1, or ≥ 2 silence timeouts | Drop one non-reserved segment, extend the closing, `recovery` posture: warm-up-band items, friendly register |
| Time overrun | > 25% over the segment's budget (0% in Final Boss) | Compress the next segment, protect the closing |
| Modality lost | Phase 3: mic died, no reconnect | Convert remaining segments to text |

Revision 1's "Struggling" read *"mean score < 0.3 AND delivery signals show distress"*. Both halves were wrong: the score is M13's (above), and "distress" is an emotion inference that M12's charter forbids — it measures observable behaviour only.

Each re-plan writes `Replan{trigger, signals, before, after, student_sentence}`, and every requirement a re-plan drops goes to M02's ledger as `skipped`.

Cap: 2 re-plans. Every re-plan writes `{trigger, before, after}` to the trace and appears in the report ("I changed the plan here because…") — transparency turns adaptivity from spooky into impressive.

### 6.5 The probe ladder in code

```python
#: The generic rung names, used only when the question has no template of its own
#: at that depth. Moves (clarify, silence, hint, steelman, move_on) are NOT rungs.
GENERIC_RUNGS = {1: "deepen", 2: "mechanism", 3: "counterfactual", 4: "transfer", 5: "transfer"}
DEPTH_CAP = 5

def rung_text(item, depth: int) -> str | None:
    """Derived, not hardcoded: the question's own follow-up at this depth —
    M05 `follow_ups[depth]` or M01 `probes[depth]` — else None (use the generic)."""

def decide(s, v: StrategistVerdict) -> Move:
    L = s.ladder
    if v.asks_interviewer:              return Move("answer_briefly")   # EC-6.3, no depth
    if v.asks_for_answer:               return Move("hint") if s.hints_left() else Move("defer_to_report")
    if v.ambiguous:                     return Move("clarify")          # no depth consumed
    if v.off_question:                  return Move("redirect_once")    # EC-6.2
    if v.justification == "failed":
        L.break_depth = L.depth;        return Move("move_on", graceful=True)   # GRACEFUL EXIT
    if v.band != "below":               L.consecutive_successes += 1
    else:                               L.consecutive_successes = 0
    if L.consecutive_successes >= 2 and L.depth >= 4:
        L.ceiling = L.depth;            return Move("move_on")          # don't punish success
    if L.depth >= DEPTH_CAP:            return Move("move_on")
    if s.mode_config.steelman_enabled and s.rng() < s.mode_config.steelman_rate:
        return Move("steelman")                                         # unreachable today (FR-6.20)
    L.depth += 1
    return Move("rung", depth=L.depth, text=rung_text(s.item, L.depth))
```

**What Revision 1's version did wrong.** `LADDER[current_depth + 1]` reached index 4, `"steelman"`, on the ordinary fall-through at depth 3 — in every mode, not just Final Boss. A Practice session going well would have been told something false on purpose at its fourth probe. `LADDER[0]` (`clarify`) was unreachable by depth, and `L.ceiling` was assigned but never declared. Rungs and moves are now separate, and a gate test drives the ladder 10,000 times in every mode and asserts no `steelman` move while `steelman_enabled` is false (AC-6.14).

`key_points_missing` does not force a `deepen` any more. Revision 1's `if rubric_gaps: return "deepen"` kept probing a point the student had not reached, which is exactly the "drilled past the break" experience the graceful exit exists to prevent. Missing key points are the report's business, via M13.

**Graceful exit copy**, per persona register:
- Friendly: *"That's fair — it's a detail people usually look up. Let's move on."*
- Neutral: *"Okay, let's leave that there."*
- Bar-raiser: *"Alright. Next."*

None of them say "wrong", "incorrect", or "you should know this".

**Steelman probes:** the interviewer asserts something subtly false (*"Hash maps guarantee O(1) worst case, right?"*). The turn is stored with `deliberately_false=True` so the evaluator scores **push-back**, not agreement — and so the report can show the student the moment: *"I said something wrong at 14:20. You agreed. Here's what was wrong with it."* That is a genuinely memorable teaching moment.

> **Blocked (Revision 2).** A steelman turn must be dispatched to M13 against a `push_back` rubric variant (M13 EC-13.10, settled in the M13 review). M13 has shipped only `dsa_verbal`, and scoring a steelman under it would reward agreeing with the falsehood (Trap 10). `steelman_enabled` is false in every mode until that rubric exists; the text above is the target behaviour, not Phase 1's.

### 6.6 Context management (fixed size)

```
System prompt (persona + round rubric + rules)   ~1,400 tok   [CACHED, byte-stable]
Profile working summary                            ~900 tok   [CACHED per session]
Round summary (rolling, regenerated every 4 turns) ~300 tok
Last 6 turns verbatim                            ~1,800 tok
Current question package                           ~400 tok
Ladder + time state                                 ~80 tok
                                          TOTAL  ~4,900 tok, constant
```
The round summary is regenerated by an `extraction`-tier call every 4 turns and replaces the dropped turns. The profile prefix is M04's **pinned** summary (`profile-summary?session_id=`), byte-identical for the whole session by M04's own gate (AC-4.13) — do not rebuild it from live mastery mid-session.

**Cache-hit ratio target: ≥ 0.7** on interviewer calls — *if it can be read*. The byte-stable prefix is kept regardless, because it costs nothing. But no module on this platform has yet confirmed that the provider's usage block reports cached tokens for the models in `ai_core.models`; `m06_llm_call` records the field when present, and AC-6.11 reports "not measured" rather than passing when it is not.

The token numbers above are for budgeting, not a promise about the tokenizer: gpt-oss models also spend hidden reasoning tokens that count against `max_tokens` (`ai_core.models`), so every call's budget is set well above its visible output.

### 6.7 Personas as parameters

```python
class Persona(BaseModel):
    id: str; name: str; title: str
    warmth: float              # 0–1 → greeting length, acknowledgement frequency
    patience: float            # → silence duration before prompting
    formality: float           # → register, contractions, slang tolerance
    interruption_threshold: float   # ×time_budget before a soft interrupt
    follow_up_aggression: float     # → probability of deepening vs moving on
    verbosity_target: int      # words per utterance
    domain_bias: list[str]     # what they keep circling back to
    voice_id: str
    note_taking_cadence: int   # turns between "let me note that down"
    hints_available: bool
```

Ship set: `friendly_recruiter` · `methodical_engineer` · `impatient_senior` · `professor` (viva cadence, derivation-heavy) · `bar_raiser` · `startup_founder` · `hr_generalist`.

Personas are data (`personas/*.yaml`), validated at load: a persona file missing a parameter fails the boot, not the session. In Phase 1 the parameters that need audio — `voice_id`, `interruption_threshold` as a spoken interrupt — are carried and unused; in text mode `patience` drives the idle prompt timer (EC-6.1) and `interruption_threshold` drives the "let's keep it moving" nudge on an over-long typed answer. Each persona carries its own graceful-exit, bridge and closing copy, so the register that must never say "wrong" is authored once and reviewed, not generated.

**The persona never changes the standard.** A friendly interviewer and a bar-raiser score the same answer identically (blind evaluator, same rubric). Only the *experience* differs. Say this in the report so students don't think Practice mode inflates their score.

Revision 2 added **AC-6.17** to hold that promise, because Revision 1 made it in the report and nowhere else. Two things must be identical for one answer across every mode: the payload M13 scores, and the prompt the strategist judges. The strategist's verdict becomes an M05 `ProvisionalOutcome` (FR-6.25), so a verdict that moved with the interviewer's manner would be a *measurement* of the manner — and the leak was real: the strategist was handed the rendered interviewer turn, which carries the register's lead ("Hello. Let's begin. First question." against a bar-raiser's "Let's get started. First."). It is handed the question without the words that introduced it.

What may differ is the experience: the words, the register, how deep the ladder goes, whether hints exist. And one thing differs that is **not** a standard — Practice declares M13's `n1_practice`, one evaluator rather than three. M13's own note is "drops the COUNT, never the tier", so Practice is measured less *precisely*, never more generously. The report says both halves, because saying only the first lets a student read a Practice result as a mock-grade one. M13 falls back to its default (`n1_practice`) for an ensemble name it does not know, so M06 checks its names against `GET /v1/ensembles`: a typo would silently score a mock with one evaluator.

### 6.8 Checkpointing & resume
Session state is a **fold over `m06_event`**. The checkpoint is a cache of that fold, not the truth:

```
read       state at seq N-1: the checkpoint, plus any events after its last_seq
validate   apply(state, event) — an impossible transition never reaches disk
append     INSERT event at seq N (= state.last_seq + 1), in one transaction with
           the projections (session status, turn row)
           · unique (session_id, turn_index, step) → a retried request finds its
             own event and returns it instead of acting twice
           · unique (session_id, seq) → THE compare-and-swap: two tabs that both
             read N-1 cannot both write N; the loser re-reads and re-validates
             ("That question has already been answered." → 409)
checkpoint after commit, best effort: UPDATE … WHERE last_seq < :new
resume     checkpoint if usable, re-fold the tail; unreadable → re-fold everything
report     built from events alone, so a failed checkpoint write loses nothing (§10)
```

The sequence number must come from the state that was validated, never from `max(seq)` read afterwards. Read afterwards, a writer that lost the race takes N+1 and commits an event validated against a state missing the winner's — the second answer to an already-answered question. This was found while building day 1, and a test forces the race.

*Revision 2 originally put the compare-and-swap on the checkpoint's `version`. Putting it on the event's `seq` is strictly stronger — it guards the truth rather than the cache — and it lets the checkpoint be written after the commit, which is what makes §10's "checkpoint write fails → nothing lost" true by construction.*

**Never in `state_json`: the provisional θ** (Trap 9, FR-6.25). It lives in process memory keyed by session. After a process restart the session re-seeds M05 from M04's posterior — a provisional estimate that loses a few steps has lost nothing it was entitled to keep. AC-6.13 serialises a checkpoint after a 30-turn scripted session and fails on any key matching `theta`.

On reconnect:
```
GET /v1/sessions/{id}/resume →
  { last_turn, transcript_tail, time_remaining, "we were on question 4 of the DSA round" }
```
Copy: *"Welcome back — we were on question 4. Ready to keep going?"* with a 30-second grace before the timer restarts. Reconnects are logged; > 2 reconnects triggers a modality-degradation suggestion.

### 6.9 Pacing
```
at 70% of budget:
    if coverage_debt_high:  interviewer offers a focus narrowing
    if ahead_of_schedule:   allow one extra depth level or an extra question
at 90%:
    force transition to the closing round (is_reserved, never dropped)
at 100%:
    wrap-up utterance, no hard cut
```

### 6.10 Ambient realism (opt-in)
Separate Web Audio bus, never routed into the ASR input. Layers: `room_tone` (-38 dB), `distant_keyboard` (-42 dB, sporadic), `corridor` (-45 dB, occasional), `paper_shuffle` (on note-taking pauses). Default **off**; "Calm mode" in settings disables permanently. One evening of work; ship it late in Phase 3.

---

## 7. API surface

Port **8106** (API), **5206** (web). Every route below except `/health`, `/v1/deps` and `/v1/agents` is candidate-scoped and goes through `may_see` (FR-6.26).

**The noun is `interviews`, not `sessions`.** Platform_Shell serves one origin by proxying `/v1/<noun>` to a single backend, chosen by the first path segment — and `sessions` already belongs to M05 (its provisional-θ routes) while `candidates` belongs to M04. Revision 2 originally specified `/v1/sessions/…`, which would have been proxied to M05 the day M06 was mounted in the shell, silently. A per-module noun is the cheap fix; a test holds M06 to it against the shell's own table (`fixtures/contracts/shell_nouns.json`).

```
GET  /health
GET  /v1/deps                          each upstream, its state, and the on_missing sentence
GET  /v1/agents                        which agents run, which are ablated, the step graph

POST /v1/interviews                    {jd_id?, mode, minutes} → plan (status: planned)
GET  /v1/interviews/{id}               the session, its transcript and what is open
GET  /v1/interviews/{id}/plan
PATCH /v1/interviews/{id}/plan         student edits before start (drop a segment)
POST /v1/interviews/{id}/start         starts a planned session; on a live one, carries on
SSE  /v1/interviews/{id}/events        text mode: token stream + state events
POST /v1/interviews/{id}/answer        text answer submit (code blocks allowed)
POST /v1/interviews/{id}/hint          next rung of M05's hint ladder, if the mode allows
POST /v1/interviews/{id}/repeat        "say that again" — re-sends the last question verbatim
POST /v1/interviews/{id}/flag          ⚑ — forwarded to M05 /questions/{qid}/flag
POST /v1/interviews/{id}/switch-modality {to}   Phase 1: text only; the contract is fixed now
POST /v1/interviews/{id}/pause | /resume
GET  /v1/interviews/{id}/resume-state  after disconnect
POST /v1/interviews/{id}/end           early end, still produces a report
GET  /v1/interviews/{id}/transcript
GET  /v1/interviews/{id}/report        served by M06 until M19 exists (§15.7)
GET  /v1/interviews/{id}/trace         the event log and model calls — replay input (FR-6.19)

POST /v1/drills                        M01's hand-off (FR-6.23) — contract below
GET  /v1/interviews/by-candidate/{cid}         the student's own history
GET  /v1/interviews/by-candidate/{cid}/recent  what M04's `recent_sessions` slot is for

WS   /v1/interviews/{id}/live          Phase 3, with M11: audio in, audio + events out
```

**The stream is push-driven.** Every event this process writes is published to the open streams as it commits (`store.NOTIFY`), with a slow sweep of the log behind it for another process's writes. Built as a poll, the reader competed with the writer for SQLite's lock and the "live" tokens arrived *after* the answer they were previewing — measured at +1384 ms against a POST that returned at 1237 ms. Pushed, the first token lands before the POST returns.

**`POST /v1/drills`** — shaped by the caller that already exists (`resume-ingestion/.../router.py:1372`), not by this spec:

```json
request   { "candidate_id": "…", "source_module": "M01", "claim_id": "…",
            "claim_text": "…",
            "probes": [ { "depth": 0, "question": "…", "expects": "…" } ] }
response  { "session_id": "…", "url": "/mock/sessions/…" }
```

A drill is a `practice`-mode session with one `project` segment, a 2-minute budget, the probes as its rungs (`question_source = m01_probe`), and no warm-up. `expects` is given to the strategist as the rung's key point. Drill turns are **not sent to M13** in Phase 1 — M13 needs an M05 question package and a claim probe is not a bank item — and the drill's report says so plainly (§15.8).

Live event types: `question.asked` · `interviewer.token` · `interviewer.done` · `answer.received` · `probe.decided` · `hint.given` · `segment.transition` · `plan.changed` · `time.warning` · `session.paused` · `session.resumed` · `session.degraded` · `session.ended` · `report.ready`.

---

## 8. UI specification

**Components:** `SetupCard` · `MicCheck` · `PlanPreview` · `InterviewStage` (avatar + utterance + state) · `AudioMeter` · `TranscriptDrawer` (collapsible, live) · `ModalitySwitcher` · `PauseDialog` · `RoundTransition` (a 2-second card, prevents jarring cuts) · `TimeRemaining` · `EndCard` · `ReconnectBanner`

**Phase 1** builds all of these except `MicCheck` and `AudioMeter` (M11), with `InterviewStage`'s answer area as a text box and `ModalitySwitcher` absent until a second modality exists. Added: `HintButton` (shows M13's credit for the next hint before it is taken), `DrillStage` (the 2-minute defend layout, one claim pinned above the conversation), and `SessionReport`. The module exports `src/routes.tsx` so Platform_Shell mounts the same tree, as every built module does.

**States that must be designed, not defaulted:**

| State | Visual | Copy |
|---|---|---|
| Interviewer thinking (0–800 ms) | avatar subtle pulse | — (no text; text implies a stall) |
| Interviewer thinking (> 800 ms) | pulse + typing dots | — |
| Listening | live waveform | "Listening…" |
| Processing your answer | waveform freezes, spinner on avatar | "One sec…" |
| Silence held (deliberate) | nothing changes | — (this is the point) |
| Barge-in accepted | interviewer audio ducks visibly | — |
| Round transition | full-width card, 2 s | "Next: DSA · 15 min" |
| Plan changed | inline toast | "Adjusting — I want to check recursion first" |
| Degraded (L2/L3) | subtle badge | "Wrapping up a little early" |
| Disconnected | banner, timer paused | "Lost connection — reconnecting…" |
| Reconnected | banner | "Back. We were on question 4." |

**Accessibility:** full text mode is not a fallback, it is a first-class equivalent; live captions in voice mode (always on, not optional); all controls keyboard-reachable; the timer is announced at 10/5/1 minutes via ARIA live; reduced-motion honoured on the avatar.

**Mobile:** avatar shrinks to a header strip; transcript takes the screen; push-to-talk button is thumb-sized and at the bottom; the app must survive a phone call interrupting the session (auto-pause + resume).

---

## 9. Edge cases

| ID | Case | Behaviour |
|---|---|---|
| EC-6.1 | Student says nothing for 45 s | One gentle prompt, then a second, then offer to move on. Never loop forever |
| EC-6.2 | Student answers a different question | Interviewer notes it and redirects once; if repeated, moves on and the report flags "answered a different question" |
| EC-6.3 | Student asks the interviewer a question mid-round | Persona-appropriate brief answer, then back. Never derail |
| EC-6.4 | Student is abusive / tests the AI | One neutral redirect, then end the session politely. Logged |
| EC-6.5 | Student asks for the answer | Hint ladder if available; otherwise "I'll walk you through it in the report" |
| EC-6.6 | Answer contains prompt injection | Stripped; scored on the rest; logged |
| EC-6.7 | Mic dies mid-answer | Auto-switch to text with the partial transcript preserved |
| EC-6.8 | Browser refresh | Resume from checkpoint |
| EC-6.9 | Session exceeds budget by 25% | Force closing round |
| EC-6.10 | Student ends at minute 3 | Report is generated for what exists, framed as a warm-up not a failure |
| EC-6.11 | All modalities fail | Session ends cleanly with an apology and no score recorded |
| EC-6.12 | LLM provider outage mid-session | Panic degradation: questions and probes are served from the items' own stems and follow-up templates verbatim (no phrasing call), the strategist falls back to §10's rule, evaluation stays in the outbox, session completes. *(Revision 1 said "local model"; the platform has none.)* |
| EC-6.13 | Two sessions in parallel by one student | Blocked with an explanation (state would collide) |
| EC-6.14 | Student pauses and never returns | Auto-close after 30 min; partial report generated |
| EC-6.15 | Steelman probe accepted by a *correct* student | Push-back scored positively; if they don't push back, it's a note, not a penalty |
| EC-6.16 | Coding round with no editor support on device | Round replaced at plan time, not at runtime |
| EC-6.17 | Camera denied after opting in | Presence dimension omitted, no penalty, one-line note |

---

## 10. Failure modes & fallbacks

| Failure | Fallback | User sees |
|---|---|---|
| Interviewer LLM timeout | Retry once → templated bridging utterance → next question | A slightly generic transition |
| Safety guard timeout | Fail-open with a rule-based filter (never block the interview on a guard) | Nothing |
| Question selection fails | Fixed fallback playlist (M5 §10) | Nothing |
| Probe strategist fails | Default to `deepen` once, then `move_on` | Nothing |
| TTS fails | Text render + a one-line "audio's having trouble — reading it out here" | Text |
| ASR fails repeatedly | Auto-switch to text after 2 failures | Modality switch toast |
| Checkpoint write fails | In-memory continue + alert; report still generated from the event log | Nothing |
| Everything fails | Session marked `aborted`; partial report; **no score recorded** | Honest apology + "this one's on us, it doesn't count" |

**Upstreams** — each is optional (Rule 2). The sentence in the right column is the module's `on_missing`, and `/v1/deps` serves it.

| Upstream down | Fallback | User sees |
|---|---|---|
| M02 | Segments from what M05 can fill, split evenly; no ledger writes | "This session isn't tailored to a job description — the planner is offline." |
| M05 | M06's own fixture playlist (a handful of warm-up-band verbal items); turns not sent to M13, because M13 cannot find the package | "Questions are from a short fixed set today, and this session won't be scored." |
| M05 answers 409 for a segment | End the segment and move on (§6.1 should have caught it at plan time) | "That's all I have on this topic for now — let's move on." |
| M13 | Outbox holds evaluation requests; drained when M13 returns | The report says scoring is pending, never shows zeros |
| M04 | No profile prefix, cold θ seed, no consent lookup | "I don't have your history this time, so I'll start from the beginning." |
| No consent recorded | Session runs and is scored; M13's outbox holds the observations M04 would refuse | Report: "This session didn't update your skill graph — consent isn't recorded yet." |
| M01 | No project segment; drills are not reachable (M01 is their only door) | Nothing in a mock; the preview simply has no project segment |

---

## 11. Performance & cost budget

| Path | p50 | p95 |
|---|---|---|
| Setup → first question | 3.0 s | 4.5 s |
| Text turn (answer submit → next question rendered) | 1.4 s | 2.5 s |
| Voice turn (end of speech → first audio) | 0.8 s | 1.2 s |
| Round transition | 1.5 s | 2.5 s |
| Session end → report ready | 25 s | 60 s |

**Cost per 45-minute Mock (voice, camera on):** see master plan §47.2 — ≈ ₹134. Interviewer turns are ≈ ₹19 of that; the bulk (≈ ₹81) is the evaluation ensemble, which is M13's budget.

> **Revision 2 — measured on the models this platform runs, not assumed.** The figures above price the master plan's provider. The platform calls Groq's `gpt-oss-120b` (generation) and `gpt-oss-20b` (extraction, classification) through `ai_core.models`; both are reasoning models whose hidden tokens count against `max_tokens`. On that account the binding constraint is **rate limits, not rupees**, so the budget is also stated as calls and tokens:
>
> | Per text turn | Calls | Tier |
> |---|---|---|
> | Question or probe phrasing | 1 (0 for templated moves) | generation |
> | ProbeStrategist | 1 | classification |
> | Segment summary | 1 per 4 turns | extraction |
> | Evaluation | M13's, off-path | M13's |
>
> **Measured on 2026-09-16 and 2026-09-17** (`Backend/reports/latency-*.json`, 16 rounds, the real prompts): ProbeStrategist p50 **775 ms** / p95 **1106 ms**; the interviewer's first visible token p50 **745 ms** / p95 **919 ms**; a rung's first visible token therefore **≈ 2.0 s at p95**, inside AC-6.4's 2.5 s. `reasoning_effort: "low"` is accepted by both models. Cached tokens are reported on **2 of 16** structured calls (512-token blocks) and never on a streamed one — so AC-6.11's 0.7 target is far off, and the honest reading is that this provider caches opportunistically rather than on demand.
>
> **The text latency gate is time-to-first-visible-token** — the utterance streams, and "the interviewer started talking" is what a student perceives. Full render time is recorded beside it. Two reasoning calls in series will probably not fit 2.5 s to a *full* render *(unmeasured)*, which is why structural moves are templated (§6.2) and why **day 2 builds a latency harness against the live account** before anything is stacked on these numbers. If the harness shows the strategist alone exceeds ~1.2 s p95, the fallback is to stream the templated acknowledgement first ("Okay —") and phrase the probe after it, not to drop the strategist.

---

## 12. Test plan

**Runs alone.** Every upstream sits behind an adapter with a fixture implementation, as in M13 §6.11, so the whole suite passes with nothing else running and without an API key. The strategist and interviewer have deterministic fixture implementations; the live-model path is exercised by the latency harness and the scripted-student run, not by CI.

**Unit** — plan assembly under 12 time budgets and 6 archetypes, over fixture M02 plans (closing segment always survives; M02's minutes are never re-allocated) · ladder transitions incl. graceful exit, ceiling, cap · **no `steelman` move in 10,000 driven decisions per mode while disabled** · rung text taken from the item's own follow-ups when present · event fold is deterministic (same events → same state) · duplicate `(session, turn, step)` is a no-op · checkpoint CAS rejects a stale writer · **serialised checkpoint contains no θ** · `InterviewerView` type graph reaches no score, band or verdict · outbound M13 request has exactly the contracted keys · context size stays constant across 60 simulated turns · pacing and re-plan triggers read no M13 field · one live session per candidate.

**Contract** — each adapter's request and response shapes are asserted against the upstream's *shipped* model (M02 `CoveragePlan`, M05 `SelectionRequest`/`ProvisionalOutcome`, M13 `EvaluateRequest`, M04 profile summary, M01's drill payload), so an upstream change breaks a test here rather than a session.

**Integration** — a scripted "student" (recorded answers) drives 20 full sessions across all 4 modes; assert: no crashes, coverage honoured, break points recorded, report generated, cost within budget, trace complete and replayable.

**Chaos tests [do these, they find real bugs]**
- Kill the worker mid-turn → session resumes, no double-charge
- Drop the WS at turn 15 → resume works, timer correct
- Provider 500s for 30 s → degradation ladder engages, session completes
- Refresh the browser 5 times → 5 clean resumes
- Pause at turn 20, resume 4 minutes later → correct state

**Human evaluation [the real test]** — 10 students do a session, then a 5-minute structured interview: *"Where did it feel most/least like a real interview?"* Run this every phase. It will tell you more than any metric.

**Manual QA** (15 min, before every release): full voice session with camera → mid-session switch to text → pause and resume → force a break point → verify graceful exit copy → check the report matches the transcript → check the trace replays.

---

## 13. Metrics & acceptance gates

| ID | Metric | Target |
|---|---|---|
| AC-6.1 **[GATE]** | Every session produces a report | 100%, including aborted |
| AC-6.2 **[GATE]** | The request M06 sends M13 carries no interviewer text, probe intent, `deliberately_false`, verdict or other turn | unit test |
| AC-6.3 **[GATE]** | Interviewer never receives current-round scores, the strategist's band, or θ | unit test (type-graph walk) |
| AC-6.4 **[GATE]** | p95 turn latency — text: 2.5 s to first visible token (Phase 1); voice: 1.2 s to first audio (Phase 3) | measured by the harness |
| AC-6.13 **[GATE]** | No provisional θ in any persisted state | unit test on a serialised 30-turn checkpoint |
| AC-6.14 **[GATE]** | No steelman move while `steelman_enabled` is false, in any mode | 0 in 10,000 driven decisions per mode |
| AC-6.15 **[GATE]** | Every presented M05 question has an `asked` ledger row, and every received answer an `answered` row | 100% in the scripted-student run (when M02 is up) |
| AC-6.16 | A retried request never double-asks, double-writes the ledger, or double-enqueues an evaluation | chaos test |
| AC-6.17 **[GATE]** | The persona never changes the standard: for one answer, the payload M13 scores and the strategist's prompt are identical across every mode, save the declared `ensemble` | unit test, per mode |
| AC-6.5 | Session completion rate | ≥ 80% |
| AC-6.6 | Break point found | ≥ 80% of sessions |
| AC-6.7 | Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | "Felt like a real interview" (post-session, 5-point) | ≥ 4.0 mean |
| AC-6.9 | Reconnect success rate | ≥ 95% |
| AC-6.10 | Context tokens per turn variance across session length | < 15% |
| AC-6.11 | Prompt cache-hit ratio on interviewer calls | ≥ 0.7 — reported "not measured" unless the provider's usage reports cached tokens |
| AC-6.12 | Sessions where a student reported feeling humiliated | 0 (open-text review each phase) |

---

## 14. Build order

Revision 2, **15 days** over a smaller scope than Revision 1's 14 (no voice, coding, canvas or steelman). Revision 1 hand-rolled a state machine on day 1 and replaced it with LangGraph on day 3 — double work either way §15.6 goes. Days 1–2 are needed under both.

| Day | Task | Exit |
|---|---|---|
| 1 | **Scaffold and state.** Repo per platform convention (ports 8106/5206, `module.json`, Platform_Core v0.9.1, `/health`, `/v1/deps`); one adapter per upstream, each with a fixture; session / turn / event tables; state as a fold over events; checkpoint with CAS; one live session per candidate; `may_see` | Suite green with no upstream running |
| 2 | **The drill slice.** `POST /v1/drills`; present → answer → fixture strategist → ladder → graceful exit → end → minimal report; SSE; minimal stage UI. **Latency harness on the live account** | First end-to-end session; p50/p95 per call written down |
| 3 | `ProbeStrategist` as one structured call; derived rungs; `break_depth`; `ProvisionalOutcome` → M05; §15.6 settled against day-2 code | Ladder gates incl. AC-6.14 |
| 4 | Boundaries and outbound: `InterviewerView` and M13-request gates; evaluation outbox → M13; ledger → M02; consent adapter | AC-6.2, 6.3, 6.13 |
| 5 | Plan assembly over M02 + plan-time availability from M05; warm-up and reserved closing; preview UI with drop-a-segment | Plan tests, 12 budgets × 6 archetypes |
| 6 | Segments: per-segment selection, 409 as an honest end, templated bridges, `RoundTransition` | A full mock on fixtures |
| 7 | Hint ladder from M05, `hint_level_used`, M13's credit table displayed; EC-6.5 | |
| 8 | Context: rolling six turns, summary every four, pinned M04 prefix | AC-6.10 |
| 9 | Personas as data (7), modes as configs (4), guard + rule filter failing open (EC-6.4, 6.6) | |
| 10 | Pacing 70/90/100, time warnings, reserved closing; re-plan from hot-path signals, ≤ 2, `plan.changed` | |
| 11 | Pause/resume, `resume-state`, idle prompts (EC-6.1), auto-close (EC-6.14); **chaos tests** | The five chaos scenarios, AC-6.16 |
| 12 | Degradation ladder (templated interviewer on outage, `n1_practice`, deferred evaluation); partial-report path; report page honouring M13's display gate | AC-6.1 |
| 13 | UI pass: setup, preview, stage, transcript drawer, timer (ARIA 10/5/1), pause, reconnect, end card; `routes.tsx` for Platform_Shell; mobile | |
| 14 | Scripted student: 20 sessions × 4 modes; manual QA script | AC-6.15, integration green |
| 15 | Cross-module asks raised in their repos (M06_REVIEW Part 5); TODO reconciled; human eval round 1 prepared | |
| *(blocked)* | Steelman (M13 `push_back`), closing-question scoring (rubric), coding segments (M07), mode difficulty (M05 `difficulty_offset`) | |
| *(Phase 2–3)* | Canvas (M08), voice (M11), camera (M12), ambient bed | |

---

## 15. Open decisions

1. **Avatar: static image, animated, or none?** Recommendation: **a simple animated presence indicator, not a face.** An uncanny 3D face is worse than no face, and a real photo raises questions about whose face it is. Revisit if a student panel disagrees.
   **Update 2026-10-05:** the drawn faces now talk while the interviewer's voice speaks (a ring, and the mouth on each word) — the animated presence recommended here. The user asked on 2026-10-04 for realistic faces; free options, including a realistic 3D head from one photo that runs in the browser, are in M11's spec §15.6. The decision stays open, and the condition above stands: a student panel.
2. **Should the timer be hideable?** Some students say it stresses them. Proposal: a "focus mode" that dims but never removes it — hiding elapsed time entirely creates worse anxiety at the end.
3. **How many pauses?** Currently one × 5 min. If completion data shows abandonment at pause exhaustion, raise it — completion beats realism.
4. **Do we let students retry a question?** Real interviews don't. But a "let me try that again" in Practice mode is genuinely valuable for learning. Proposal: allow in Practice only, mark the retry in the data, score the first attempt.
5. **Steelman frequency in Final Boss** — currently 25% of turns. Needs tuning with real students; too high and it feels like a trap rather than a test. *Moot until M13's `push_back` rubric exists (FR-6.20).*
6. **LangGraph, or an explicit event-sourced state machine?** The master plan (§26) and the M04 review point at LangGraph. Recommendation for Phase 1: **the explicit machine** — the loop is linear (segments in order; ask → answer → decide within each), its checkpoint contract (CAS, a de-duplicating event key, a report rebuildable from the log alone) is stricter than a generic checkpointer's, and no platform module uses the LangChain stack. Node functions are pure either way, so wiring them into a graph later is one file. Revisit when the loop stops being linear (hybrid GD, multi-agent panels) — or now, if the architecture as presented at evaluation needs to name LangGraph. Settled on day 3.
7. **Where the session report lives until M19 exists.** Recommendation: M06 serves it; M19 later projects the same events, and M06's page is deleted when M19's ships — two report implementations must never coexist.
8. **Are defend drills scored?** Recommendation: not in Phase 1 — M13 needs an M05 package, and minting grounded items from M01 claims is M05's Phase 2 path (§6.12 there already specifies its consent and scoping rules). The drill's product is the ladder and the break point, and its report says it was not scored.
