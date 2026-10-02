/**
 * M06 — shapes the API returns (Backend/.../router.py, report.py, public.py).
 *
 * Declared field by field against the backend models, because a field the
 * frontend reads and the backend never sends is a screen that renders
 * `undefined` as if it were an answer.
 */

export type SessionStatus = "planned" | "live" | "paused" | "ended" | "aborted";
export type Mode = "practice" | "mock" | "real_drive" | "final_boss";

export interface TurnView {
  turn_id: string;
  turn_index: number;
  segment_index: number;
  role: "interviewer" | "candidate" | "system";
  text: string;
  modality: string;
  question_id: string | null;
  question_source: string | null;
  rubric_round_type: string | null;
  probe_depth: number;
  probe_move: string | null;
  hint_level_used: number;
  deliberately_false: boolean;
  /** Practice retry (§15.4): recorded beside the first attempt, never scored. */
  retry: boolean;
  at: string;
}

/** Who is asking (FR-6.3). A card — never the parameters behind the ladder. */
export interface InterviewerCard {
  id: string;
  name: string;
  title: string;
  /** EC-6.1: seconds of silence before a gentle prompt. */
  idle_after_s: number;
  long_answer_words: number;
}

export interface ModeOption {
  id: Mode;
  label: string;
  /** Mechanics only, and only ones the engine enforces today. */
  summary: string;
  hints: boolean;
  retry_allowed: boolean;
  overrun_allowance: number;
}

export interface PersonaCard {
  id: string;
  name: string;
  title: string;
  style: string;
}

export interface SessionFlags {
  degradation_level: string;
  modalities_available: string[];
  camera_on: boolean;
  paused_at: string | null;
  pause_used: boolean;
  reconnect_count: number;
  evaluation_pending: number;
  consent_id: string | null;
  /** module id → the sentence the student is owed. */
  degraded: Record<string, string>;
  /** EC-6.4: neutral redirects given; the second ends the session. */
  conduct_warnings: number;
  /** EC-6.6: answers the guard found instructions in. */
  inputs_flagged: number;
  /** §8 "Disconnected — timer paused": when the stage went away, or null. */
  away_since: string | null;
}

export interface PlannedSegment {
  index: number;
  kind: string;
  title: string;
  minutes: number;
  question_budget: number;
  rationale: string;
  requirement_ids: string[];
  /** Set when this part will not run. The segment stays, so the report can
   *  say what was planned as well as what happened. */
  dropped_reason: string | null;
  /** The closing. It is where the student asks, so it cannot be dropped. */
  is_reserved: boolean;
  /** Who runs this part (FR-6.3) — `/v1/interviews/personas` names them. */
  persona_id: string;
}

export type ReplanTrigger =
  | "gap_discovered"
  | "ceiling_hit"
  | "struggling"
  | "time_overrun"
  | "modality_lost";

/** §6.4: one change to the plan at a segment boundary, at most two a session.
 *  Mid-session the backend sends none of these — only `Session.plan_notes` —
 *  because the trigger and its reason are a live score by another name. */
export interface Replan {
  at_segment: number;
  trigger: ReplanTrigger;
  signals: Record<string, number>;
  before: PlannedSegment[];
  after: PlannedSegment[];
  student_sentence: string;
  live_note: string;
}

export interface InterviewPlan {
  id: string;
  mode: Mode;
  total_minutes: number;
  segments: PlannedSegment[];
  /** Empty while the session is live; filled once it is over. */
  replans: Replan[];
  /** Requirements in the posting that this session will not reach. M02's
   *  list, shown rather than hidden — a plan that quietly covers 3 of 8 is
   *  the one a student would want to know about. */
  uncovered: string[];
  jd_id: string | null;
}

export interface HintOffer {
  available: boolean;
  level: number;
  /** M13's factor: 0.85 means an answer after this hint credits at 85%. */
  credit: number;
  hints_left: number;
  unavailable_reason: string | null;
}

export interface Session {
  id: string;
  candidate_id: string;
  kind: "mock" | "drill";
  mode: Mode;
  status: SessionStatus;
  requested_minutes: number;
  time_used_s: number;
  time_remaining_s: number;
  jd_id: string | null;
  plan: InterviewPlan | null;
  hint: HintOffer;
  interviewer: InterviewerCard | null;
  /** §15.4: a retry is on offer; nothing is open until the student chooses. */
  retry_offered: boolean;
  /** A sentence about the panel when it isn't what the mode's name suggests. */
  mode_note: string | null;
  /** §6.4's live notes: what changed in the plan, said neutrally. */
  plan_notes: string[];
  /** FR-6.21: the open turn is the closing, where the student asks. */
  in_closing: boolean;
  /** §6.9's checkpoints passed — 70 and 90 (percent of the session). */
  time_warnings: number[];
  /** EC-6.1 for the open line: silence prompts given (0–3), the last one,
   *  and whether the interviewer has offered to move on. */
  idle_prompts: number;
  idle_line: string | null;
  idle_offered: boolean;
  /** §6.8: after more than two reconnects, what the student can do. */
  connection_note: string | null;
  current_segment: number;
  questions_asked: number;
  /** The interviewer turn the answer box posts to. Null when nothing is open. */
  open_turn_id: string | null;
  transcript: TurnView[];
  flags: SessionFlags;
  drill_claim: string | null;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
}

export interface SessionSummary {
  id: string;
  kind: "mock" | "drill";
  mode: Mode;
  status: SessionStatus;
  requested_minutes: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
}

export interface Exchange {
  role: "interviewer" | "candidate";
  text: string;
  move: string | null;
  depth: number;
}

export interface QuestionReport {
  question: string;
  source: string;
  scored: boolean;
  not_scored_reason: string | null;
  exchanges: Exchange[];
  depth_reached: number;
  break_depth: number | null;
  ceiling: number | null;
  hints_used: number;
  strong_answer_covers: string[];
  /** EC-6.1: moved on after a silence — nothing was answered, nothing scored. */
  moved_on: boolean;
}

export interface SessionReport {
  session_id: string;
  kind: "mock" | "drill";
  mode: Mode;
  status: SessionStatus;
  end_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  minutes_used: number;
  minutes_planned: number;
  framing: string;
  questions: QuestionReport[];
  /** FR-6.21: what the student asked at the closing. Recorded, not scored. */
  your_questions: string[];
  /** §6.4: why the plan changed, in full. Only once the session is over. */
  plan_changes: string[];
  notes: string[];
  persona_note: string;
}

/** §6.8: what a returning page needs (`GET /resume-state`). A read only —
 *  the return itself is recorded by the stream re-attaching. */
export interface ResumeState {
  session_id: string;
  status: SessionStatus;
  away: boolean;
  /** "Welcome back — we were on question 4 of Data structures." */
  welcome: string | null;
  open_question: TurnView | null;
  transcript_tail: TurnView[];
  time_remaining_s: number;
  grace_s: number;
  reconnect_count: number;
  connection_note: string | null;
}

/** One frame of the live stream (public.py). */
export interface StreamEvent {
  seq: number;
  kind: string;
  at: string;
  data: Record<string, unknown>;
}

export interface DependencyRow {
  module_id: string;
  name: string;
  available: boolean;
  required: boolean;
  reason: string;
  on_missing: string;
  base_url: string;
  checked_at: string;
  detail: string;
}

export interface AgentRow {
  name: string;
  side: string;
  tier: string | null;
  enabled: boolean;
  switch: string;
  purpose: string;
}

export interface AgentsResponse {
  agents: AgentRow[];
  model_on: boolean;
  step_graph: string;
}

export interface Health {
  status: string;
  module: string;
  prompt_version: string;
}
