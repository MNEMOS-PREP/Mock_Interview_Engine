# M6 — Mock Interview Engine

> **Master plan reference:** §32 + §26 · **Phase:** 1–2 · **Owner:** E2 · **Depends on:** M2, M4, M5, M13 · **Feeds:** M13, M16, M19 · **This is the product's front door.**

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

**Trap 2 — Letting evaluation block the conversation.** A 12-second frontier-model evaluation between turns is a dead interview. *Counter: `ProbeStrategist` (cheap, ~1.2 s) decides the next move on the hot path; the full evaluation ensemble runs async in workers (§6.5). This is the single most important architectural decision in the module.*

**Trap 3 — Unbounded context growth.** By turn 30 you're sending 40k tokens per turn, latency doubles and cost quadruples. *Counter: rolling window of the last 6 turns verbatim + a maintained round summary + the working-tier profile. Fixed context size regardless of session length (§6.6).*

**Trap 4 — Re-planning too eagerly.** A supervisor that re-plans after every turn produces an interview that wanders. *Counter: re-plan only at round boundaries, max 2 per session, on explicit triggers (§6.4).*

**Trap 5 — Losing the session on a refresh.** Student's browser crashes at minute 30 and everything is gone. This will happen, and it will happen to your demo. *Counter: `SessionState` is checkpointed to Postgres after every node; reconnect resumes from the last checkpoint with a "welcome back, we were on question 4" (§6.8).*

**Trap 6 — The interviewer knowing the score.** If the interviewer node can read `TurnEvaluation`, it will telegraph ("Good!" / "Hmm, not quite") and the whole blind-scoring property is dead — plus students read the tell and optimise for it. *Counter: state projections, enforced at the node level (§6.3), not by asking the prompt nicely.*

**Trap 7 — Personas that are just adjectives in a prompt.** "Be a strict interviewer" produces a rude one on some turns and a friendly one on others. *Counter: personas are parameter vectors that drive concrete mechanics — silence duration, interruption threshold, hint availability, verbosity target (§6.7).*

### 3.2 The non-obvious hard parts

1. **Time budgeting is a scheduling problem.** Rounds overrun; students ramble; a coding problem takes 18 minutes instead of 12. The supervisor must continuously re-allocate remaining time, and must always reserve the closing round.
2. **"Answer complete" is genuinely hard.** In text, it's a submit button. In voice, it's M11's semantic endpointing. In coding, it's neither — a student who stops typing may be thinking. The engine needs a per-modality completion contract.
3. **The transition between rounds is where immersion breaks.** A hard cut from DSA to HR feels like a page load. Scripted, persona-appropriate bridges ("Alright, let's switch gears — I'd like to hear about a time you disagreed with a teammate") cost nothing and matter a lot.
4. **Idempotency under retry.** A worker crash mid-turn must not double-charge, double-ask, or double-score. Every node keyed by `(session_id, node, turn_idx, attempt)`.
5. **The report must exist even if everything failed.** A session that crashed at turn 12 still produces a report for the 11 turns that worked. Never a dead end.

---

## 4. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-6.1 | Build an `InterviewPlan` from JD + profile + time budget + modality | P0 |
| FR-6.2 | Show the plan to the student before running, with an edit option | P1 |
| FR-6.3 | Execute rounds in sequence with per-round persona and rubric | P0 |
| FR-6.4 | Re-plan at round boundaries, max 2 per session, on defined triggers | P1 |
| FR-6.5 | Probe ladder with depth cap 5 and graceful exit on break | P0 |
| FR-6.6 | Record `break_depth` per concept per session | P0 |
| FR-6.7 | Hint ladder with published, fixed score reduction per level | P0 |
| FR-6.8 | Four modes (Practice / Mock / Real-drive / Final Boss) as configs of one engine | P0 |
| FR-6.9 | Enforce the Final Boss rule: pressure via mechanics, never rudeness | P0 |
| FR-6.10 | Support voice, text, coding, and canvas modalities within one session | P0 |
| FR-6.11 | Mid-session modality switch without state loss | P0 |
| FR-6.12 | Pause (once, ≤5 min) and resume | P1 |
| FR-6.13 | Reconnect and resume after disconnect from the last checkpoint | P0 |
| FR-6.14 | Evaluation must never block the conversational hot path | P0 |
| FR-6.15 | Interviewer nodes cannot read current-round evaluation scores | P0 |
| FR-6.16 | Fixed context size regardless of session length | P0 |
| FR-6.17 | Time-aware pacing with a 70% checkpoint and a reserved closing round | P0 |
| FR-6.18 | Always produce a report, even on partial/failed sessions | P0 |
| FR-6.19 | Emit a full Langfuse trace and replayable state per session | P0 |
| FR-6.20 | Deliberate-wrong-statement (steelman) probes marked in the transcript | P1 |
| FR-6.21 | Score the student's own closing questions | P1 |
| FR-6.22 | p95 turn latency: text ≤ 2.5 s, voice ≤ 1.2 s to first audio | P0 |

---

## 5. Data contracts

```python
class PlannedRound(BaseModel):
    index: int
    round_type: Literal["warmup","project","dsa","cs_core","system_design",
                        "ml_viva","behavioural","closing"]
    persona_id: str
    minutes: int
    question_budget: int
    coverage_targets: list[str]         # requirement_ids from M2
    difficulty_offset: float            # relative to θ̂
    rubric_id: UUID
    modality: Literal["verbal","coding","canvas","mixed"]
    is_reserved: bool = False           # closing round: never dropped

class InterviewPlan(BaseModel):
    id: UUID
    session_id: UUID
    rounds: list[PlannedRound]
    total_minutes: int
    mode: Literal["practice","mock","real_drive","final_boss"]
    replan_count: int = 0
    generated_by: str                   # prompt_version
    rationale: str                      # shown in the plan preview

class ProbeLadderState(BaseModel):
    concept_id: str
    current_depth: int                  # 0..5
    history: list[Literal["clarify","deepen","mechanism","counterfactual",
                          "steelman","transfer","silence","move_on"]]
    break_depth: int | None             # set when justification fails
    consecutive_successes: int

class Turn(BaseModel):
    id: UUID
    session_id: UUID
    round_index: int
    turn_index: int
    role: Literal["interviewer","candidate","system"]
    text: str
    audio_uri: str | None
    started_at: datetime
    ended_at: datetime | None
    question_id: UUID | None
    probe_depth: int
    probe_action: str | None
    hint_level_used: int
    deliberately_false: bool = False    # steelman marker
    asr_confidence: float | None
    completion_reason: Literal["endpoint","submit","timeout","interrupted","barge_in"]

class SessionFlags(BaseModel):
    degradation_level: Literal["L0","L1","L2","L3","panic"] = "L0"
    modalities_available: set[str]
    camera_on: bool
    paused_at: datetime | None
    pause_used: bool = False
    reconnect_count: int = 0
    evaluation_pending: bool = False
```

---

## 6. The pipeline in minute detail

### 6.1 Session bootstrap (target: < 4 s from click to first question)

```
1. Load working-tier profile from M4 (cached, 40 ms)
2. Load RequirementSet + gap from M2 (cached if JD seen before)
3. OrchestratorSupervisor → InterviewPlan          (frontier tier, ~2.5 s)
4. Warm the model cache: send the stable prefix for round 1's persona+rubric
5. Pre-select the warm-up question (M5, from the fixed playlist — instant)
6. Open the WS/SSE channel, start the recorder, greet
```

Step 4 matters: warming the prompt cache during the plan preview means the first real turn is already a cache hit.

**Plan construction rules:**
```
minutes_available = requested - closing_reserve(5) - warmup(4)
round set from:  archetype template
                 ∩ modalities available (no coding round if no editor support)
                 ∩ JD coverage needs
                 ordered: warmup → project → technical → core → behavioural → closing
per-round minutes ∝ coverage weight, floored at the minimum viable for that round type
                    (coding round < 12 min is not a coding round — drop it instead)
difficulty_offset = 0 (mock) | -0.3 (practice) | +0.8 (final boss) | company band (real drive)
```

### 6.2 The turn loop

```python
async def run_turn(state: SessionState) -> SessionState:
    q = await questions.next(state)                     # M5, pre-computed, ~20ms
    utterance = await interviewer.speak(state, q)       # mid tier, ~900ms
    utterance = await safety.check(utterance)           # cheap tier, ~500ms, concurrent w/ TTS warmup
    await surface.present(utterance)                    # TTS stream / text render

    answer = await surface.collect_answer(state)        # blocks on the human
    features = await multimodal.extract(answer)         # M12, local, ~200ms

    # HOT PATH — cheap and fast
    action = await probe_strategist.decide(state, answer)   # cheap tier, ~1.1s

    # OFF PATH — expensive and slow
    enqueue(evaluate_turn, turn_id, priority="normal")      # M13 ensemble, async

    state = apply(state, action)
    return state
```

**`ProbeStrategist` gets a deliberately narrow context** — the question, the answer, the rubric's key points, and the current ladder depth. Not the full transcript. This keeps it at ~1.1 s and forces the decision to be about *this answer*, which is the right scope.

### 6.3 State projections (enforcing the information boundaries)

```python
def project_for_interviewer(s: SessionState) -> InterviewerView:
    return InterviewerView(
        recent_turns=s.transcript[-6:],
        round_summary=s.rounds[s.current].summary,
        profile=s.profile_snapshot,           # mastery, story bank, prior break points
        plan_context=s.plan.rounds[s.current],
        ladder=s.ladder,
        time_remaining=s.time_remaining,
        # ABSENT: any TurnEvaluation from this round, any composite score
    )

def project_for_evaluator(s: SessionState, turn_id: UUID) -> EvaluatorView:
    return EvaluatorView(
        question=..., reference_answer=..., rubric=..., answer=...,
        # ABSENT: interviewer reasoning, candidate identity, prior scores,
        #         profile, other turns
    )
```
These are functions with tests, not conventions. A test asserts that `EvaluatorView` has no field transitively reaching `candidate_id`.

### 6.4 Re-planning

Triggers (evaluated only at round boundaries):
| Trigger | Condition | Action |
|---|---|---|
| Gap discovered | ≥2 turns in this round broke at L1 on a prerequisite concept | Re-target the next round to that prerequisite |
| Ceiling hit | Student cleared the stretch item | Raise `difficulty_offset` by 0.4 for remaining rounds |
| Struggling | Mean score < 0.3 across the round AND delivery signals show distress | Drop one round, extend the closing, shift to a recovery posture |
| Time overrun | > 25% over the round's budget | Compress the next round, protect the closing |
| Modality lost | Mic died, no reconnect | Convert remaining rounds to text |

Cap: 2 re-plans. Every re-plan writes `{trigger, before, after}` to the trace and appears in the report ("I changed the plan here because…") — transparency turns adaptivity from spooky into impressive.

### 6.5 The probe ladder in code

```python
LADDER = ["clarify","deepen","mechanism","counterfactual","steelman","transfer"]

def decide(state, answer, rubric_gaps) -> ProbeAction:
    L = state.ladder
    if answer.is_ambiguous:            return "clarify"          # doesn't consume depth
    if L.current_depth >= 5:           return "move_on"
    if L.consecutive_successes >= 2 and L.current_depth >= 4:
        L.ceiling = L.current_depth;   return "move_on"          # don't punish success
    if answer.failed_justification:
        L.break_depth = L.current_depth; return "move_on"        # GRACEFUL EXIT
    if rubric_gaps:                    return "deepen"           # cover the rubric first
    if state.mode == "final_boss" and random() < 0.25:
        return "steelman"
    if answer.trailing_off:            return "silence"
    return LADDER[L.current_depth + 1]
```

**Graceful exit copy**, per persona register:
- Friendly: *"That's fair — it's a detail people usually look up. Let's move on."*
- Neutral: *"Okay, let's leave that there."*
- Bar-raiser: *"Alright. Next."*

None of them say "wrong", "incorrect", or "you should know this".

**Steelman probes:** the interviewer asserts something subtly false (*"Hash maps guarantee O(1) worst case, right?"*). The turn is stored with `deliberately_false=True` so the evaluator scores **push-back**, not agreement — and so the report can show the student the moment: *"I said something wrong at 14:20. You agreed. Here's what was wrong with it."* That is a genuinely memorable teaching moment.

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
The round summary is regenerated by a cheap-tier call every 4 turns (~₹0.02) and replaces the dropped turns. **Cache-hit ratio target: ≥ 0.7** on interviewer calls; it's a tracked metric and a drop means something volatile crept into the prefix.

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

**The persona never changes the standard.** A friendly interviewer and a bar-raiser score the same answer identically (blind evaluator, same rubric). Only the *experience* differs. Say this in the report so students don't think Practice mode inflates their score.

### 6.8 Checkpointing & resume
After every node: `UPSERT session_state (session_id, state_json, version)`. On reconnect:
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

```
POST /v1/sessions                      {jd_id?, archetype?, mode, minutes, modalities} → plan
GET  /v1/sessions/{id}/plan
PATCH /v1/sessions/{id}/plan           student edits before start
POST /v1/sessions/{id}/start
WS   /v1/sessions/{id}/live            bidirectional: audio in, audio+events out
SSE  /v1/sessions/{id}/events          text mode: token stream + state events
POST /v1/sessions/{id}/answer          text/code answer submit
POST /v1/sessions/{id}/repeat          "say that again"
POST /v1/sessions/{id}/switch-modality {to: "text"}
POST /v1/sessions/{id}/pause | /resume
GET  /v1/sessions/{id}/resume-state    after disconnect
POST /v1/sessions/{id}/end             early end, still produces a report
GET  /v1/sessions/{id}/transcript
GET  /v1/sessions/{id}/report          (M19)
```

Live event types: `question.asked` · `interviewer.speaking` · `listening.started` · `answer.received` · `probe.deepening` · `round.transition` · `plan.changed` · `time.warning` · `session.degraded` · `session.ended`.

---

## 8. UI specification

**Components:** `SetupCard` · `MicCheck` · `PlanPreview` · `InterviewStage` (avatar + utterance + state) · `AudioMeter` · `TranscriptDrawer` (collapsible, live) · `ModalitySwitcher` · `PauseDialog` · `RoundTransition` (a 2-second card, prevents jarring cuts) · `TimeRemaining` · `EndCard` · `ReconnectBanner`

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
| EC-6.12 | LLM provider outage mid-session | Panic degradation: local model for interviewer, evaluation deferred, session completes |
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

---

## 12. Test plan

**Unit** — plan construction under 12 time budgets and 6 archetypes (closing round always survives) · ladder transitions incl. graceful exit · state projections (evaluator view cannot reach identity) · context size stays constant across 60 simulated turns · pacing triggers.

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
| AC-6.2 **[GATE]** | Evaluator view cannot reach candidate identity or interviewer reasoning | unit test |
| AC-6.3 **[GATE]** | Interviewer never receives current-round scores | unit test |
| AC-6.4 **[GATE]** | p95 turn latency (text 2.5 s / voice 1.2 s) | met |
| AC-6.5 | Session completion rate | ≥ 80% |
| AC-6.6 | Break point found | ≥ 80% of sessions |
| AC-6.7 | Coverage of must-have requirements | ≥ 90% |
| AC-6.8 | "Felt like a real interview" (post-session, 5-point) | ≥ 4.0 mean |
| AC-6.9 | Reconnect success rate | ≥ 95% |
| AC-6.10 | Context tokens per turn variance across session length | < 15% |
| AC-6.11 | Prompt cache-hit ratio on interviewer calls | ≥ 0.7 |
| AC-6.12 | Sessions where a student reported feeling humiliated | 0 (open-text review each phase) |

---

## 14. Build order

| Day | Task |
|---|---|
| 1 | Session tables, state machine skeleton, checkpointing |
| 2 | Turn loop (text only), SSE streaming, transcript |
| 3 | LangGraph orchestrator + agent registry wiring (§26) |
| 4 | State projections + boundary tests |
| 5 | Plan construction + plan preview UI |
| 6 | Round execution + transitions + bridging utterances |
| 7 | Probe ladder + graceful exit + break-point recording |
| 8 | Hint ladder + score reduction + coachability signal |
| 9 | Context management (rolling window + round summary) + cache warming |
| 10 | Personas as parameters + the 7 ship personas |
| 11 | Modes (4 configs) + Final Boss mechanics + safety register enforcement |
| 12 | Pacing, time warnings, reserved closing round |
| 13 | Pause/resume, reconnect, checkpoint recovery, chaos tests |
| 14 | Degradation ladder, partial-report path, human eval round 1 |
| *(Phase 3)* | Voice integration (M11), camera (M12), ambient bed |

---

## 15. Open decisions

1. **Avatar: static image, animated, or none?** Recommendation: **a simple animated presence indicator, not a face.** An uncanny 3D face is worse than no face, and a real photo raises questions about whose face it is. Revisit if a student panel disagrees.
2. **Should the timer be hideable?** Some students say it stresses them. Proposal: a "focus mode" that dims but never removes it — hiding elapsed time entirely creates worse anxiety at the end.
3. **How many pauses?** Currently one × 5 min. If completion data shows abandonment at pause exhaustion, raise it — completion beats realism.
4. **Do we let students retry a question?** Real interviews don't. But a "let me try that again" in Practice mode is genuinely valuable for learning. Proposal: allow in Practice only, mark the retry in the data, score the first attempt.
5. **Steelman frequency in Final Boss** — currently 25% of turns. Needs tuning with real students; too high and it feels like a trap rather than a test.
