/**
 * Reports for the page tests (2026-10-24): a question as the backend sends
 * it, with only what a test is about written out.
 */
import type { AnswerStatus, Exchange, QuestionReport, SessionReport } from "./types";

/** One line of the exchange, as the report sends it. */
export function line(role: Exchange["role"], text: string): Exchange {
  return { role, text, move: role === "interviewer" ? "ask" : null, depth: 0, turn_id: null };
}

const LABELS: Record<AnswerStatus, string> = {
  correct: "Correct",
  partial: "Mostly correct",
  vague: "Too vague",
  incorrect: "Incorrect",
  unanswered: "Not answered",
  unsupported: "Not backed up",
  not_judged: "Not judged",
  not_reached: "Not reached",
};

export function question(status: AnswerStatus | null, extra: Partial<QuestionReport> = {}): QuestionReport {
  return {
    question: `A question that was ${status ?? "asked"}`,
    source: "m05_bank",
    scored: true,
    not_scored_reason: null,
    scoring_status: "scored",
    exchanges: [
      line("interviewer", "Why is a hash map lookup O(1) on average?"),
      line("candidate", `My ${status ?? "first"} answer about buckets.`),
    ],
    depth_reached: 0,
    break_depth: null,
    ceiling: null,
    hints_used: 0,
    strong_answer_covers: ["Hashes the key to a bucket index", "Names a bounded load factor"],
    moved_on: false,
    feedback: [],
    concept_id: null,
    topic: null,
    turn_id: null,
    asked_by: null,
    status,
    status_label: status ? LABELS[status] : null,
    status_detail: status ? `Detail for ${status}.` : null,
    key_points: [],
    ...extra,
  } as QuestionReport;
}

export function report(questions: QuestionReport[], extra: Partial<SessionReport> = {}): SessionReport {
  const counts: Partial<Record<AnswerStatus, number>> = {};
  for (const q of questions) if (q.status) counts[q.status] = (counts[q.status] ?? 0) + 1;
  return {
    session_id: "s-1",
    kind: "mock",
    mode: "practice",
    status: "completed",
    end_reason: "time_up",
    started_at: null,
    ended_at: null,
    minutes_used: 12,
    minutes_planned: 15,
    framing: "That was a fair interview.",
    questions,
    your_questions: [],
    plan_changes: [],
    notes: [],
    persona_note: "Asked by the panel.",
    summary: {
      held: [],
      gaps: [],
      corrected: [],
      repeated_misconceptions: [],
      unsupported_claims: [],
      topics: [],
      communication: [],
      status_counts: counts,
      focus: [],
    },
    writeups: "ready",
    ...extra,
  } as SessionReport;
}
