/**
 * M06 — routes.
 *
 * Under `/mock`, not at the index: Platform_Shell mounts these flat and
 * absolute beside four other modules, and M01 already hands out
 * `/mock/{session_id}` as the URL a defend drill lands on (its `DrillHandoff`
 * says M06 owns that shape).
 */

import { Navigate, Route, useParams } from "react-router-dom";

import { InterviewStage } from "./components/InterviewStage";
import { PlanPreview } from "./components/PlanPreview";
import { MockHome } from "./components/MockHome";
import { QuestionLibrary } from "./components/QuestionLibrary";
import { SessionNotes } from "./components/SessionNotes";
import { SystemPage } from "./components/SystemPage";

function StageRoute() {
  const { sessionId } = useParams();
  if (!sessionId) return <Navigate to="/mock" replace />;
  return <InterviewStage sessionId={sessionId} />;
}

function PlanRoute() {
  const { sessionId } = useParams();
  if (!sessionId) return <Navigate to="/mock" replace />;
  return <PlanPreview sessionId={sessionId} />;
}

function NotesRoute() {
  const { sessionId } = useParams();
  if (!sessionId) return <Navigate to="/mock" replace />;
  return <SessionNotes sessionId={sessionId} />;
}

export const m06Routes = (
  <Route key="m06">
    <Route path="/mock" element={<MockHome />} />
    <Route path="/mock/system" element={<SystemPage />} />
    <Route path="/mock/library" element={<QuestionLibrary />} />
    <Route path="/mock/:sessionId/plan" element={<PlanRoute />} />
    <Route path="/mock/:sessionId" element={<StageRoute />} />
    <Route path="/mock/:sessionId/report" element={<NotesRoute />} />
  </Route>
);
