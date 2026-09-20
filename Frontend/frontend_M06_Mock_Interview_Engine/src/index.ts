/**
 * M06 — Mock Interview Engine · public surface.
 *
 * Anything not exported here is private to this module. The stage and the
 * notes are exported because M01 links a student straight into a drill and
 * M19 will render the same session notes inside a report — and two copies of
 * the screen that decides what a student may see mid-interview is exactly how
 * "no live score" stops being true in whichever copy fell behind.
 */

export { m06Routes } from "./routes";
export { AppShell } from "./ui/AppShell";
export { InterviewStage } from "./components/InterviewStage";
export { MockHome } from "./components/MockHome";
export { PlanPreview } from "./components/PlanPreview";
export { SessionNotes } from "./components/SessionNotes";
export { SystemPage } from "./components/SystemPage";
export {
  m06Keys,
  useAgents,
  useAnswer,
  useCreateSession,
  useDeps,
  useDropSegment,
  useEnd,
  useHealth,
  useHistory,
  usePause,
  usePlan,
  useReport,
  useResume,
  useSession,
  useStart,
} from "./api";
export { useInterviewStream } from "./stream";
export {
  DEFAULT_CANDIDATE_ID,
  getCandidateId,
  identityHeaders,
  publishIdentity,
  setCandidateId,
  subscribeCandidateId,
} from "./identity";
export type {
  AgentRow,
  AgentsResponse,
  DependencyRow,
  Exchange,
  InterviewPlan,
  Mode,
  QuestionReport,
  Session,
  SessionFlags,
  SessionReport,
  SessionStatus,
  SessionSummary,
  StreamEvent,
  TurnView,
} from "./types";
