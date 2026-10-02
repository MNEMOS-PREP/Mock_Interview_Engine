/**
 * What the interview will be, before it is — FR-6.2, spec §6.1.
 *
 * The screen exists because of Trap 1's other half: a student who is told
 * "we built you a 45-minute interview" and then asked four questions about
 * SQL has been misled by an interface, not by a model. So the preview says
 * what each part is, how long it takes, how many questions it holds, and —
 * in M02's own words — why it is there at all.
 *
 * Two things it deliberately shows rather than hides:
 *
 *   · a part that will NOT run, with the reason. A coding round with no M07
 *     behind it is dropped, and a student who was expecting one should read
 *     that here rather than notice its absence afterwards.
 *   · what the posting asks for that this session cannot reach (M02's
 *     `uncovered`). A plan that quietly covers three of eight requirements
 *     is exactly the plan somebody needs to be told about.
 *
 * Dropping is a delete on the plan, not on the screen: the segment stays in
 * the list, greyed, because the report has to be able to say what was
 * planned as well as what happened.
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Card, ErrorNote, Spinner } from "@ai/core";

import {
  useDropSegment,
  usePersonas,
  usePlan,
  useSession,
  useStart,
} from "../api";
import type { PersonaCard, PlannedSegment } from "../types";

const KIND_LABEL: Record<string, string> = {
  warmup: "Warm-up",
  technical: "Technical",
  behavioural: "Behavioural",
  project: "Your projects",
  closing: "Closing",
};

function minutes(value: number): string {
  return Number.isInteger(value) ? `${value} min` : `${value.toFixed(1)} min`;
}

function SegmentRow({
  segment,
  onDrop,
  busy,
  who,
}: {
  segment: PlannedSegment;
  onDrop: () => void;
  busy: boolean;
  /** FR-6.3: a mock is a panel, so the preview says who runs each part. */
  who?: PersonaCard;
}) {
  const dropped = segment.dropped_reason !== null;
  return (
    <li
      className={`flex items-start justify-between gap-4 border-b border-line py-3 last:border-0 ${
        dropped ? "opacity-55" : ""
      }`}
    >
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-2">
          <span
            className={`text-sm font-medium text-ink ${dropped ? "line-through" : ""}`}
          >
            {segment.title}
          </span>
          <span className="text-2xs uppercase tracking-wide text-ink-faint">
            {KIND_LABEL[segment.kind] ?? segment.kind}
          </span>
        </p>
        <p className="mt-0.5 text-2xs text-ink-faint">
          {who && !dropped && `with ${who.name}, ${who.title} · `}
          {minutes(segment.minutes)}
          {segment.question_budget > 0 &&
            ` · ${segment.question_budget} question${segment.question_budget === 1 ? "" : "s"}`}
        </p>
        {segment.rationale && !dropped && (
          <p className="mt-1 max-w-prose text-2xs leading-relaxed text-ink-soft">
            {segment.rationale}
          </p>
        )}
        {dropped && (
          <p className="mt-1 max-w-prose text-2xs leading-relaxed text-ink-soft">
            {segment.dropped_reason}
          </p>
        )}
      </div>
      {!dropped && !segment.is_reserved && (
        <Button variant="ghost" size="sm" onClick={onDrop} disabled={busy}>
          Remove
        </Button>
      )}
    </li>
  );
}

export function PlanPreview({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const plan = usePlan(sessionId);
  const drop = useDropSegment(sessionId);
  const start = useStart(sessionId);
  const personas = usePersonas();
  const byId = new Map((personas.data ?? []).map((card) => [card.id, card]));
  const navigate = useNavigate();

  const built = session.data?.plan;
  const planned = session.data?.status === "planned";

  // Build it once, when the session has been read and has none. `usePlan` is
  // idempotent on the server, so a double render costs a round trip and not
  // a second plan.
  useEffect(() => {
    if (session.isSuccess && !built && planned && plan.isIdle) plan.mutate();
  }, [session.isSuccess, built, planned, plan]);

  useEffect(() => {
    // Somebody else started it, or this tab refreshed after starting.
    if (session.data && !planned)
      navigate(`/mock/${sessionId}`, { replace: true });
  }, [session.data, planned, navigate, sessionId]);

  if (session.isPending || (!built && plan.isPending)) {
    return <Spinner label="Working out what to ask you…" />;
  }
  if (session.isError) {
    return <ErrorNote message="That interview could not be loaded." />;
  }

  const segments = built?.segments ?? [];
  const live = segments.filter((s) => s.dropped_reason === null);
  const totalMinutes = live.reduce((sum, s) => sum + s.minutes, 0);
  const totalQuestions = live.reduce((sum, s) => sum + s.question_budget, 0);

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">
        Here is the plan
      </h1>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-soft">
        {built?.jd_id
          ? "Built from the job description you added, so the questions follow what the posting asks for."
          : "Not tailored to a job description — add one and the plan follows it instead."}
      </p>

      <div className="mt-5">
        <Card>
          {segments.length === 0 ? (
            <p className="text-sm text-ink-soft">
              There is nothing to ask yet — the question bank had nothing for
              this session.
            </p>
          ) : (
            <ul>
              {segments.map((segment) => (
                <SegmentRow
                  key={segment.index}
                  who={byId.get(segment.persona_id)}
                  segment={segment}
                  busy={drop.isPending}
                  onDrop={() => drop.mutate(segment.index)}
                />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="mt-3 text-2xs text-ink-faint">
        {minutes(totalMinutes)} · {totalQuestions} question
        {totalQuestions === 1 ? "" : "s"}
        {" · you can pause once, for five minutes"}
      </p>

      {(built?.uncovered.length ?? 0) > 0 && (
        <p className="mt-4 max-w-prose text-2xs leading-relaxed text-ink-soft">
          Not covered this time: {built?.uncovered.join(", ")}. There was not
          enough time for everything the posting asks for.
        </p>
      )}

      {drop.isError && (
        <div className="mt-4">
          <ErrorNote
            message="That part could not be removed."
            detail={
              drop.error instanceof Error ? drop.error.message : undefined
            }
            onRetry={() => drop.reset()}
          />
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button
          onClick={() =>
            start.mutate(undefined, {
              onSuccess: () => navigate(`/mock/${sessionId}`),
            })
          }
          disabled={start.isPending || drop.isPending}
        >
          {start.isPending ? "Starting…" : "Start the interview"}
        </Button>
        <Button
          variant="ghost"
          onClick={() => navigate("/mock")}
          disabled={start.isPending}
        >
          Not now
        </Button>
      </div>

      {start.isError && (
        <div className="mt-4">
          <ErrorNote
            message="That didn't start."
            detail={
              start.error instanceof Error ? start.error.message : undefined
            }
            onRetry={() => start.reset()}
          />
        </div>
      )}
    </div>
  );
}
