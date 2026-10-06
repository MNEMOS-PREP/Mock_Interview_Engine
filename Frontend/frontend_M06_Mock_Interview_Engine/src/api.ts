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
  CohortStats,
  DependencyRow,
  Health,
  ModeOption,
  PersonaCard,
  Reliability,
  ResumeState,
  Session,
  SessionReport,
  SessionSummary,
  TurnView,
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
  cohort: ["m06", "cohort"] as const,
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

/** How many interviews were started on the platform this week, and by how
 *  many students. Counts only — the shell's Today card ("you're not the only
 *  one practising"). */
export function useCohortStats() {
  return useQuery({
    queryKey: m06Keys.cohort,
    queryFn: () => api.get<CohortStats>("/v1/interviews/stats"),
    staleTime: 5 * 60_000,
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

/** This student's sessions, newest first. `limit` up to the backend's 200 —
 *  a practice streak needs more history than the recent-sessions list does. */
export function useHistory(limit = 20) {
  const candidateId = getCandidateId();
  return useQuery({
    queryKey: [...m06Keys.history(candidateId), limit],
    queryFn: () =>
      api.get<SessionSummary[]>(
        `/v1/interviews/by-candidate/${candidateId}?limit=${limit}`,
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
    mutationFn: (body: {
      minutes: number;
      mode?: string;
      jd_id?: string;
      company_id?: string;
      drive_id?: string;
      /** Up to three concept ids: "Practise Recursion" plans one segment on them. */
      focus_concepts?: string[];
      focus_label?: string;
    }) =>
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

/** §7 "say that again": the open question, verbatim. */
export function useRepeat(id: string) {
  return useMutation({
    mutationFn: () => api.post<TurnView>(`/v1/interviews/${id}/repeat`),
  });
}

/** M11's FR-11.9: the student started speaking over an interviewer line —
 *  here, in this part, this far through. The transcript dims the rest, and
 *  the interviewer reads the line as far as it was heard. */
export function useHeard(id: string) {
  return useMutation({
    mutationFn: (body: { turn_id: string; part_index: number | null; heard: number }) =>
      api.post<void>(`/v1/interviews/${id}/heard`, body),
  });
}

/** §7's ⚑ — forwarded to M05, which stops selecting the item. */
export function useFlag(id: string) {
  return useMutation({
    mutationFn: (body: {
      question_turn_id: string;
      reason: string;
      note?: string;
    }) =>
      api.post<{ question_id: string; forwarded: boolean }>(
        `/v1/interviews/${id}/flag`,
        body,
      ),
  });
}

/** FR-6.11: the modality contract. Phase 1 has one, so nothing calls this
 *  with anything else yet — the hook exists so the contract has a client. */
export function useSwitchModality(id: string) {
  const write = useSessionWriter(id);
  return useMutation({
    mutationFn: (to: string) =>
      api.post<Session>(`/v1/interviews/${id}/switch-modality`, { to }),
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
