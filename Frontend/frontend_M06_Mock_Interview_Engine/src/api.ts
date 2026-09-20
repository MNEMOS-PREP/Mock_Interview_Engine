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
  Session,
  SessionReport,
  SessionSummary,
} from "./types";

export const m06Keys = {
  health: ["m06", "health"] as const,
  deps: ["m06", "deps"] as const,
  agents: ["m06", "agents"] as const,
  session: (id: string) => ["m06", "session", id] as const,
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

export function useSession(id: string | undefined) {
  return useQuery({
    queryKey: m06Keys.session(id ?? "none"),
    queryFn: () => api.get<Session>(`/v1/interviews/${id}`),
    enabled: Boolean(id),
    // The stream says when something changed; polling would fight it.
    staleTime: Infinity,
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
      api.get<SessionSummary[]>(`/v1/interviews/by-candidate/${candidateId}?limit=20`),
  });
}

/** The one place a session's cached copy is replaced. */
function useSessionWriter(id: string | undefined) {
  const client = useQueryClient();
  return (session: Session) => {
    client.setQueryData(m06Keys.session(session.id), session);
    client.invalidateQueries({ queryKey: m06Keys.report(session.id) });
    client.invalidateQueries({ queryKey: m06Keys.history(session.candidate_id) });
    if (id && id !== session.id) client.invalidateQueries({ queryKey: m06Keys.session(id) });
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

export function useEnd(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (reason: string) => api.post<Session>(`/v1/interviews/${id}/end`, { reason }),
    onSuccess: write,
  });
}
