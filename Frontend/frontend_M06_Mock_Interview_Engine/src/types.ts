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
  at: string;
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
}

export interface PlannedSegment {
  index: number;
  kind: string;
  title: string;
  minutes: number;
  question_budget: number;
  rationale: string;
}

export interface InterviewPlan {
  id: string;
  mode: Mode;
  total_minutes: number;
  segments: PlannedSegment[];
  uncovered: string[];
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
  notes: string[];
  persona_note: string;
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
