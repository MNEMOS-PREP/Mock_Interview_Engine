/**
 * M06 — API client. One hook per endpoint, and no hook without one.
 *
 * Spec: plan_in_depth/M06_Mock_Interview_Engine.md §7.
 *
 * `POST /answer` returns the whole session, so the answer box does not need a
 * second fetch to show the interviewer's next line — and the live stream is
 * for what happens without this tab asking: the interviewer's tokens as they
 * arrive, and another tab ending the session.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@ai/core";

import { getCandidateId } from "./identity";
import type {
  AgentsResponse,
  DependencyRow,
  Health,
  ModeOption,
  PersonaCard,
  Reliability,
  ResumeState,
  Session,
  SessionReport,
  SessionSummary,
} from "./types";

export const m06Keys = {
  health: ["m06", "health"] as const,
  deps: ["m06", "deps"] as const,
  agents: ["m06", "agents"] as const,
  reliability: ["m06", "reliability"] as const,
  modes: ["m06", "modes"] as const,
  personas: ["m06", "personas"] as const,
  session: (id: string) => ["m06", "session", id] as const,
  resume: (id: string) => ["m06", "resume", id] as const,
  report: (id: string) => ["m06", "report", id] as const,
  history: (candidateId: string) => ["m06", "history", candidateId] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: m06Keys.health,
    queryFn: () => api.get<Health>("/health"),
    retry: false,
  });
}

export function useDeps() {
  return useQuery({
    queryKey: m06Keys.deps,
    queryFn: () => api.get<DependencyRow[]>("/v1/deps"),
    retry: false,
  });
}

export function useAgents() {
  return useQuery({
    queryKey: m06Keys.agents,
    queryFn: () => api.get<AgentsResponse>("/v1/agents"),
    retry: false,
  });
}

/** AC-6.9 and §10's ladder, across every session. A student gets a 403,
 *  and the System page simply leaves the card out. */
export function useReliability() {
  return useQuery({
    queryKey: m06Keys.reliability,
    queryFn: () => api.get<Reliability>("/v1/interviews/reliability"),
    retry: false,
  });
}

/** FR-6.8 — the four modes, each described by what it actually does. */
export function useModes() {
  return useQuery({
    queryKey: m06Keys.modes,
    queryFn: () => api.get<ModeOption[]>("/v1/interviews/modes"),
    staleTime: Infinity,
  });
}

/** §6.7 — who might be asking, for the plan preview. */
export function usePersonas() {
  return useQuery({
    queryKey: m06Keys.personas,
    queryFn: () => api.get<PersonaCard[]>("/v1/interviews/personas"),
    staleTime: Infinity,
  });
}

export function useSession(id: string | undefined) {
  return useQuery({
    queryKey: m06Keys.session(id ?? "none"),
    queryFn: () => api.get<Session>(`/v1/interviews/${id}`),
    enabled: Boolean(id),
    // The stream says when something changed; polling would fight it.
    staleTime: Infinity,
  });
}

/** §6.8: where the student was. Fetched on demand — after the stream has
 *  re-attached, so the return it reports has already been recorded. */
export function useResumeState(id: string | undefined) {
  return useQuery({
    queryKey: m06Keys.resume(id ?? "none"),
    queryFn: () => api.get<ResumeState>(`/v1/interviews/${id}/resume-state`),
    enabled: false,
    staleTime: 0,
  });
}

export function useReport(id: string | undefined) {
  return useQuery({
    queryKey: m06Keys.report(id ?? "none"),
    queryFn: () => api.get<SessionReport>(`/v1/interviews/${id}/report`),
    enabled: Boolean(id),
  });
}

export function useHistory() {
  const candidateId = getCandidateId();
  return useQuery({
    queryKey: m06Keys.history(candidateId),
    queryFn: () =>
      api.get<SessionSummary[]>(
        `/v1/interviews/by-candidate/${candidateId}?limit=20`,
      ),
  });
}

/** The one place a session's cached copy is replaced. */
function useSessionWriter(id: string | undefined) {
  const client = useQueryClient();
  return (session: Session) => {
    client.setQueryData(m06Keys.session(session.id), session);
    client.invalidateQueries({ queryKey: m06Keys.report(session.id) });
    client.invalidateQueries({
      queryKey: m06Keys.history(session.candidate_id),
    });
    if (id && id !== session.id)
      client.invalidateQueries({ queryKey: m06Keys.session(id) });
  };
}

export function useCreateSession() {
  const write = useSessionWriter(undefined);
  return useMutation({
    mutationFn: (body: { minutes: number; mode?: string; jd_id?: string }) =>
      api.post<Session>("/v1/interviews", body),
    onSuccess: write,
  });
}

export function usePlan(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/plan`),
    onSuccess: write,
  });
}

export function useDropSegment(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (index: number) =>
      api.del<Session>(`/v1/interviews/${id}/plan/segments/${index}`),
    onSuccess: write,
  });
}

export function useHint(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/hint`),
    onSuccess: write,
  });
}

export function useStart(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/start`),
    onSuccess: write,
  });
}

export function useAnswer(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (body: { question_turn_id: string; text: string }) =>
      api.post<Session>(`/v1/interviews/${id}/answer`, body),
    onSuccess: write,
  });
}

export function usePause(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/pause`),
    onSuccess: write,
  });
}

export function useResume(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/resume`),
    onSuccess: write,
  });
}

/** §15.4, Practice: take the offered retry — the same question, not scored. */
export function useRetry(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/retry`),
    onSuccess: write,
  });
}

/** EC-6.1: the student has been quiet on the open line. `n` is the prompt
 *  expected next, so a retried request changes nothing (AC-6.16). A 409 means
 *  "not yet" or "already answered" — both are fine to ignore. */
export function useIdle(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (body: { question_turn_id: string; n: number }) =>
      api.post<Session>(`/v1/interviews/${id}/idle`, body),
    onSuccess: write,
  });
}

/** §15.4: decline the retry and carry on. EC-6.1: take the offer to move on. */
export function useMoveOn(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: () => api.post<Session>(`/v1/interviews/${id}/move-on`),
    onSuccess: write,
  });
}

export function useEnd(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (reason: string) =>
      api.post<Session>(`/v1/interviews/${id}/end`, { reason }),
    onSuccess: write,
  });
}
