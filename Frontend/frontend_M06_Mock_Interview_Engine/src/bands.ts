/**
 * One question's band and topic, read off M06's notes — in one place.
 *
 * The notes and the shell's "My answers" page both show a band per answer,
 * and two copies of "which key points did it miss" is exactly how the same
 * answer ends up Strong on one screen and Partly there on the next.
 */
import { answerBand, type AnswerBand } from "@ai/core";

import type { QuestionReport } from "./types";

/**
 * `kp_3`, `[kp_3] Says the worst case degrades…` → the statement, once.
 * Key points are numbered in the order "what a strong answer covers" lists
 * them, so `kp_N` is entry N-1 when the item carries no text of its own.
 */
export function missingStatements(missing: string[], covers: string[]): string[] {
  const out = new Map<string, string>();
  for (const raw of missing) {
    const match = /^\[?(kp_\d+)\]?\s*(.*)$/i.exec(raw.trim());
    const id = match?.[1]?.toLowerCase() ?? raw;
    const text = match?.[2]?.trim() || covers[Number(id.replace(/\D/g, "")) - 1] || "";
    if (text && !out.has(id)) out.set(id, text);
  }
  return [...out.values()];
}

/** The band for one question, or null before it is marked. */
export function bandOf(question: QuestionReport): AnswerBand | null {
  const total = question.strong_answer_covers.length;
  if (!total || question.feedback.length === 0) return null;
  const missed = new Set(
    question.feedback.flatMap((f) => missingStatements(f.missing, question.strong_answer_covers)),
  );
  return answerBand(Math.max(0, total - missed.size), total);
}

/** The topic's name for "practise this again", from the item or its id. */
export function topicName(question: QuestionReport): string | null {
  if (!question.concept_id) return null;
  return question.topic || question.concept_id.split(":").pop()!.replace(/_/g, " ");
}
