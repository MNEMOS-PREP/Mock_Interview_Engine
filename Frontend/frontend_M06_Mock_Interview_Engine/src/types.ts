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
  /** Interviewer turns: the question alone, without the words that led into
   *  it — what a repeat says, and the recogniser's prompt (M11 day 4). */
  question_text?: string | null;
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
  /** Question turns the student skipped (2026-10-07): `replaced` when a
   *  different question was asked at the same number, else left — counted
   *  as not answered — or a follow-up moved on from. */
  skipped?: boolean;
  replaced?: boolean;
  follow_up_skip?: boolean;
  /** Interviewer turns: the persona who asks — the line's last voice. */
  speaker_id?: string | null;
  /** Interviewer turns said by more than one panelist (FR-6.3), part by
   *  part: a hand-over, the opening's hellos. Empty when one person said it. */
  parts?: TurnPart[];
  /** M11's FR-11.9: the student started speaking over this line — the part
   *  being heard and how far through it, 0–1. Null when heard to the end. */
  heard_part?: number | null;
  heard?: number | null;
  /** Spoken answers (M11's recogniser): how sure it was, 0–1, and the
   *  character ranges of `text` it was unsure of — never quoted back. */
  asr_confidence?: number | null;
  unsure?: [number, number][];
  /** The language the recogniser heard (M11's FR-11.22), lower case. */
  language?: string | null;
  /** M11's FR-11.6: prefills this answer's question had, and whether one was
   *  used (its words were exactly these). */
  prefill?: { tried: number; used: boolean } | null;
  at: string;
}

/** One panelist's words within an interviewer line. */
export interface TurnPart {
  speaker_id: string;
  text: string;
  /** Quiet after this part, ms — the note-taking pause (M11's FR-11.12). */
  pause_after_ms?: number;
}

/** Who is asking (FR-6.3). A card — never the parameters behind the ladder. */
export interface InterviewerCard {
  id: string;
  name: string;
  title: string;
  /** EC-6.1: seconds of silence before a gentle prompt. */
  idle_after_s: number;
  long_answer_words: number;
  /** `locale-kind-manner` from the persona file — `en-IN-female-warm`. M11
   *  casts a voice for this interviewer by `id`; when M11 is down the browser
   *  speaks in the closest voice to this (`@ai/core`). */
  voice_id?: string;
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
  /** `locale-kind-manner`, e.g. `en-IN-female-warm` — what M11 speaks in. */
  voice_id: string;
  /** The line this interviewer opens with — M11's voice check plays it. */
  greeting: string;
  /** M11's FR-11.10: 0–1. How long they wait before answering is read from it. */
  patience?: number;
  /** M11's FR-11.11: what they say, softly, while the student talks — and the
   *  least time between two of them, in seconds. */
  backchannels?: string[];
  backchannel_every_s?: number;
  /** M11's EC-11.9: their own "didn't catch that", for an answer nobody
   *  could write down. */
  didnt_catch?: string;
  /** M11's EC-11.1: said aside as they yield to a student who started
   *  speaking over the start of a line. */
  go_ahead?: string;
}

export interface SessionFlags {
  degradation_level: string;
  modalities_available: string[];
  camera_on: boolean;
  paused_at: string | null;
  /** True once no pause is left. */
  pause_used: boolean;
  /** FR-6.12, revised: one pause per 15 planned minutes. */
  pauses_used: number;
  pauses_allowed: number;
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
  /** §10's ladder: model turns failed running, and when it was last tried. */
  model_failures: number;
  model_tried_at: string | null;
  /** §10 "Everything fails": steps that crashed running. */
  step_failures: number;
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
  /** The round types (tracks) this part asks from, M05's and M13's ids. */
  rubric_round_types?: string[];
}

export type ReplanTrigger =
  | "gap_discovered"
  | "ceiling_hit"
  | "struggling"
  | "time_overrun"
  | "modality_lost"
  | "degraded";

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
  /** FR-6.3: who sits on the panel, the lead first — including anyone
   *  sitting in without a part of their own. Absent on older plans. */
  panel?: string[];
  /** The track the student picked (a round type), or null for a mixed one. */
  track?: string | null;
  /** Whether the student asked for questions from their resume, and which. */
  resume_included?: boolean;
  resume_id?: string | null;
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
  /** An answer's turn: where M11 keeps its audio, when the student chose to
   *  keep it (FR-11.19). */
  turn_id?: string | null;
}

/** M13's words about an answer, per dimension. Never its numbers. */
export interface Feedback {
  dimension: string;
  reasoning: string;
  /** Key points the answer did not reach. */
  missing: string[];
  /** The student's own sentences that counted, verified against the text. */
  quotes: string[];
}

export interface QuestionReport {
  question: string;
  source: string;
  scored: boolean;
  not_scored_reason: string | null;
  /** `queued` while M13 marks the answer; `scored` once it has. Never a number. */
  scoring_status: "not_scored" | "queued" | "scored";
  exchanges: Exchange[];
  depth_reached: number;
  break_depth: number | null;
  ceiling: number | null;
  hints_used: number;
  strong_answer_covers: string[];
  /** EC-6.1: moved on after a silence — nothing was answered, nothing scored. */
  moved_on: boolean;
  /** 2026-10-07: skipped — `replaced` by another question at the same number
   *  (nothing against it), `left` (a second skip there: counted as not
   *  answered), or `follow_up` (moved on from a follow-up). */
  skipped?: "replaced" | "left" | "follow_up" | null;
  /** Once M13 has scored the answer and the session is over. */
  feedback: Feedback[];
  /** The concept the item measures — "practise this topic again". */
  concept_id: string | null;
  /** The item's own name for that topic, when it has one. */
  topic: string | null;
  /** The first answer's turn: M13's evidence page is `/turns/{turn_id}`. */
  turn_id: string | null;
  asked_by: string | null;
  // ── 2026-10-22: what the interview found, filled once it is over ────────
  went_well?: string[];
  went_wrong?: Finding[];
  unsupported?: string[];
  contradictions?: Finding[];
  /** `self` — they caught it; `prompted` — after a push, a hint, a simpler question. */
  corrected?: "self" | "prompted" | null;
  outcome?: string | null;
  outcome_words?: string | null;
  misconception?: string | null;
  how_it_went?: string[];
  /** One strong answer — *a* good answer, not the only one. */
  one_strong_answer?: string | null;
  strong_answer_reviewed?: boolean;
  study?: string[];
  /** This attempt against their last one at the same question. */
  last_time?: string | null;
  question_key?: string | null;
  starred?: boolean;
  flagged?: boolean;
  /** For a resume line: whether they backed it up. */
  claim_check?: string | null;
  /** 2026-10-24: the one status the page is built around — the interview's
   *  own judgement of the whole thread (`report._status`). Null mid-session. */
  status?: AnswerStatus | null;
  status_label?: string | null;
  status_detail?: string | null;
  /** "after a push", "with 1 hint", "corrected yourself". */
  status_qualifier?: string | null;
  /** The strong answer's points, each reached or not (null: unknown). */
  key_points?: KeyPointCheck[];
  /** The explanation written after the session, once checked. */
  writeup?: Writeup | null;
}

export type AnswerStatus =
  | "correct"
  | "partial"
  | "vague"
  | "incorrect"
  | "unanswered"
  | "unsupported"
  | "not_judged"
  | "not_reached";

export interface KeyPointCheck {
  statement: string;
  covered: boolean | null;
}

export interface WriteupPoint {
  point: string;
  /** The student's own words, verbatim — checked server-side. */
  evidence: string;
  fix: string;
}

/** One answer explained (`notes_writer`): never shown unless it passed its
 *  checks — the student's own quotes, no praise for a wrong answer. */
export interface Writeup {
  headline: string;
  strengths: WriteupPoint[];
  gaps: WriteupPoint[];
  misconception: string;
  correction: string;
  model_answer: string;
  next_steps: string[];
  model: string;
}

/** One thing the interview found in an answer, in the student's words. */
export interface Finding {
  said: string;
  why: string;
}

/** The interview in a few lines — built from the questions, never beside them. */
export interface ReportSummary {
  held: string[];
  gaps: string[];
  corrected: string[];
  repeated_misconceptions: string[];
  unsupported_claims: string[];
  topics: string[];
  communication: string[];
  /** 2026-10-24: questions per status, and the topics to work on, worst first. */
  status_counts?: Partial<Record<AnswerStatus, number>>;
  focus?: string[];
}

/** One past attempt at a library question. */
export interface LibraryAttempt {
  session_id: string;
  at: string;
  outcome: string | null;
  outcome_words: string | null;
  corrected: string | null;
  misconception: string | null;
  answers: string[];
}

/** A question in the student's library (`GET /v1/interviews/library`). */
export interface LibraryEntry {
  id: string;
  question_key: string;
  question_id: string | null;
  stem: string;
  concept_id: string;
  topic: string;
  source: string;
  claim_text: string | null;
  /** The student's own mark, and the interview's — independent of each other. */
  starred: boolean;
  flagged: boolean;
  flagged_reason: string | null;
  difficulty_band: string | null;
  attempts: LibraryAttempt[];
  last_time: string | null;
  updated_at: string;
}

export interface StarResult {
  question_turn_id: string;
  starred: boolean;
  flagged: boolean;
  entry_id: string | null;
}

/** One track on the setup page (`GET /v1/interviews/tracks`). */
export interface TrackOption {
  round_type: string;
  title: string;
  group: string;
  blurb: string;
  /** Who runs it: an HR interviewer for `behavioural`. */
  kind: "technical" | "behavioural" | string;
  /** Questions a person has approved for scoring, and drafts awaiting one. */
  approved: number;
  drafts: number;
  /** Whether answers here can be scored yet (a rubric and an approved item). */
  scored: boolean;
}

export interface TracksResponse {
  groups: string[];
  tracks: TrackOption[];
  /** Why the list is short, when the bank could not be asked. */
  note: string | null;
}

/** One of the student's resumes, for the picker (`GET /v1/interviews/resumes`). */
export interface ResumeOption {
  id: string;
  filename: string | null;
  created_at: string | null;
  is_active: boolean;
  /** Lines an interviewer would push on. None means no project round. */
  defendable: number;
}

export interface ResumesResponse {
  resumes: ResumeOption[];
  note: string | null;
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
  /** 2026-10-22: the interview in a few lines, built from the questions. */
  summary?: ReportSummary;
  /** 2026-10-24: where the written explanations are — `pending` means ask again. */
  writeups?: "none" | "pending" | "ready" | "partial";
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

/** AC-6.9 and §10, counted off the event log. Staff only. */
export interface Reliability {
  sessions: number;
  disconnects: number;
  returns: number;
  /** Returns over disconnects; null until anyone has disconnected. */
  reconnect_rate: number | null;
  reconnect_target: number;
  wrapped_early: number;
  reached_panic: number;
  crashed_steps: number;
  ended_by_failure: number;
}

/** `GET /v1/interviews/stats`: counts across everyone, never anyone. */
export interface CohortStats {
  interviews_this_week: number;
  students_this_week: number;
  since: string;
}

export interface Health {
  status: string;
  module: string;
  prompt_version: string;
}
