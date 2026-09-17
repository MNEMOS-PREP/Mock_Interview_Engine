/**
 * Who the browser is, while the platform has no login (PLATFORM_TODO §1).
 *
 * M01's `candidate.ts` is the reference shape and this follows it: a persisted
 * id with a visible control, published to `@ai/core`'s fetch wrapper as the dev
 * headers the backend honours only under `AI_AUTH_MODE=dev`. It reads M01's
 * key first, so the two modules present the same student when Platform_Shell
 * mounts them side by side. When the shell grows a login, this file is the one
 * that changes.
 */

import { setIdentityHeaders } from "@ai/core";

const KEY = "m06.candidateId";
const SHARED_KEY = "m01.candidateId";

/** The platform's shared seeded candidate (M01's DEFAULT_CANDIDATE_ID). */
export const DEFAULT_CANDIDATE_ID = "4d0aa1c0-0000-4000-8000-000000000004";

const listeners = new Set<() => void>();
let current = read();

function read(): string {
  if (typeof window === "undefined") return DEFAULT_CANDIDATE_ID;
  const fromUrl = new URLSearchParams(window.location.search).get("candidate");
  if (fromUrl) return fromUrl;
  return (
    window.localStorage.getItem(KEY) ??
    window.localStorage.getItem(SHARED_KEY) ??
    DEFAULT_CANDIDATE_ID
  );
}

export function getCandidateId(): string {
  return current;
}

export function setCandidateId(next: string): void {
  const trimmed = next.trim() || DEFAULT_CANDIDATE_ID;
  if (trimmed === current) return;
  current = trimmed;
  window.localStorage.setItem(KEY, current);
  publishIdentity();
  listeners.forEach((listener) => listener());
}

export function subscribeCandidateId(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The headers every request carries — also used by the live stream. */
export function identityHeaders(): Record<string, string> {
  return { "X-Role": "student", "X-Candidate-Id": current };
}

export function publishIdentity(): void {
  setIdentityHeaders(identityHeaders());
}

publishIdentity();
