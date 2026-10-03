/**
 * Who the browser is — `@ai/core`'s session (v0.12.0), in this module's words.
 *
 * Until 2026-10-02 this file kept its own id under its own localStorage key
 * and set the page's identity headers itself, as did M01, M02 and M15. In
 * Platform_Shell the student was whoever's module loaded last. The session is
 * the platform's now: the shell's sign-in screen sets it, standalone sets the
 * seeded student when nobody is signed in, and the headers follow it. What is
 * left here is the vocabulary the rest of this module already uses — the old
 * keys are migrated by the session itself, so nobody loses the student they were.
 */

import {
  SEEDED_CANDIDATE_ID,
  candidateIdOf,
  getSession,
  sessionHeaders,
  signIn,
  subscribeSession,
} from "@ai/core";

/** The platform's shared seeded candidate. */
export const DEFAULT_CANDIDATE_ID = SEEDED_CANDIDATE_ID;

/**
 * The student these screens are about: the signed-in student, or — for staff,
 * who are nobody's candidate — the seeded one, which the backend then decides
 * whether they may see.
 */
export function getCandidateId(): string {
  return candidateIdOf(getSession()) ?? DEFAULT_CANDIDATE_ID;
}

/** The dev control's "be this student". */
export function setCandidateId(next: string): void {
  signIn({ role: "student", subject: next.trim() || DEFAULT_CANDIDATE_ID });
}

export function subscribeCandidateId(listener: () => void): () => void {
  return subscribeSession(listener);
}

/** The headers a raw `fetch` sends — the live stream's, which `api` cannot carry. */
export function identityHeaders(): Record<string, string> {
  return sessionHeaders();
}

/** Kept for callers; the session publishes the headers itself now. */
export function publishIdentity(): void {}
