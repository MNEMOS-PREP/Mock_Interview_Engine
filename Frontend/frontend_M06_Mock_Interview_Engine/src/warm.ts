/**
 * Lines made before they are said (2026-10-09).
 *
 * The user, after a mock: gaps in speech and awkward pauses, worst on long
 * lines. On a laptop M11 makes speech barely faster than it is spoken, so a
 * line made only when it is needed keeps the student waiting. Most of what
 * comes next is known before it is said — the next question is one of the
 * few M05 would choose now, and every transition is one of the panel's own
 * phrases — so while the student reads the plan, and again while they answer
 * each question, the room has M11 make them (`/upcoming`, then `prepareLine`
 * as a line made ahead: only while nothing is being said). When the line
 * comes, its sentences are already there and it plays without a pause.
 *
 * M11 makes them in the order asked, the likely next line (`"next"`) before
 * the stock phrases (`"warm"`); so the questions go first, and each new batch
 * drops what is left of the last batch's guesses that it no longer makes —
 * the question about to be asked, not the one just answered.
 */
import { api, dropOnServer, prepareLine, prepareLines } from "@ai/core";

import type { PersonaCard } from "./types";

interface UpcomingLine {
  kind: "question" | "phrase";
  parts: { speaker_id: string; text: string }[];
}

type Parts = readonly { speaker_id: string; text: string }[];

/** Lines already handed to M11 on this page: each is asked for once. */
const asked = new Set<string>();
/** The last batch's question guesses, by line id: those a newer batch does
 *  not guess again are dropped, and their unmade sentences are not made. */
let guessed = new Map<string, string>();
let lines = 0;

function keyOf(parts: Parts): string {
  return parts.map((part) => `${part.speaker_id}:${part.text}`).join("|");
}

function spoken(parts: Parts, cards: readonly PersonaCard[]) {
  const voiceOf = new Map(cards.map((card) => [card.id, card.voice_id ?? null]));
  return parts.map((part) => ({
    text: part.text,
    personaId: part.speaker_id,
    voiceId: voiceOf.get(part.speaker_id) ?? null,
  }));
}

/** Have M11 make, while nothing is being said, what the room may say next. */
export async function warmUpcoming(sessionId: string, cards: readonly PersonaCard[]): Promise<void> {
  let batch: UpcomingLine[];
  try {
    batch = (await api.get<{ lines: UpcomingLine[] }>(`/v1/interviews/${sessionId}/upcoming`)).lines ?? [];
  } catch {
    return; // ahead of time only: every line is still made when it is said
  }
  const questions = batch.filter((line) => line.kind === "question");
  const phrases = batch.filter((line) => line.kind !== "question");
  const now = new Map<string, string>();
  const fresh: { id: string; parts: ReturnType<typeof spoken> }[] = [];
  for (const line of questions) {
    const key = keyOf(line.parts);
    const kept = guessed.get(key);
    if (kept) {
      now.set(key, kept); // guessed last time too: still being made, or made
      continue;
    }
    const id = `next-${++lines}-${sessionId.slice(0, 8)}`;
    now.set(key, id);
    fresh.push({ id, parts: spoken(line.parts, cards) });
  }
  // A piece of each in turn: whichever is asked has its first piece ready.
  await prepareLines(fresh, "next");
  dropOnServer([...guessed].filter(([key]) => !now.has(key)).map(([, id]) => id));
  guessed = now;
  for (const line of phrases) {
    const key = keyOf(line.parts);
    if (asked.has(key)) continue;
    asked.add(key);
    await prepareLine(`warm-${++lines}-${sessionId.slice(0, 8)}`, spoken(line.parts, cards), "warm");
  }
}

/**
 * The line the interviewer would say if the student's answer stopped where
 * they paused (M06's prefill, FR-11.6): made while they are still talking,
 * as the likely next line. Said only if it is the line the real answer gets —
 * when the student says nothing more, it is, and it plays at once.
 */
export function warmThought(sessionId: string, parts: Parts, cards: readonly PersonaCard[]): void {
  if (parts.length === 0) return;
  const key = keyOf(parts);
  if (asked.has(key)) return;
  asked.add(key);
  void prepareLine(`thought-${++lines}-${sessionId.slice(0, 8)}`, spoken(parts, cards), "next");
}
