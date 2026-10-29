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

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Card, ErrorNote, PageHeader, api, prepareLine } from "@ai/core";

import {
  useDropSegment,
  usePersonas,
  usePlan,
  useSession,
  useStart,
} from "../api";
import type { PersonaCard, PlannedSegment } from "../types";
import { Face } from "../ui/Face";
import { warmUpcoming } from "../warm";

/**
 * A cold first plan can take several seconds (M02 builds the requirement set,
 * M05 checks the bank), and a sentence on its own read as a stall. The steps
 * are the ones the backend really takes, lit in order on a timer — honest
 * about the shape of the wait, never claiming a step finished that it can't
 * see.
 */
const BUILD_STEPS = [
  "Reading what you're practising for",
  "Checking what your skill graph hasn't seen yet",
  "Choosing questions from the bank",
  "Putting the panel together",
];

function Building() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setStep((s) => Math.min(s + 1, BUILD_STEPS.length - 1)), 1400);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="mx-auto max-w-md py-16" role="status" aria-live="polite">
      <div className="h-1 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-700"
          style={{ width: `${((step + 1) / (BUILD_STEPS.length + 1)) * 100}%` }}
        />
      </div>
      <ol className="mt-6 space-y-2.5">
        {BUILD_STEPS.map((label, i) => (
          <li
            key={label}
            className={`flex items-center gap-2.5 text-sm ${i <= step ? "text-ink" : "text-ink-faint"}`}
          >
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${i < step ? "bg-confirmed" : i === step ? "animate-pulse bg-brand" : "bg-line-strong"}`}
            />
            {label}
          </li>
        ))}
      </ol>
    </div>
  );
}

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

/** A face in a part's row, and how much of the next one shows beside it. */
const FACE = 32;
const FACE_OVERLAP = 22;

/** A part with no topic of its own: the lead's, and nobody sits in on it. */
const BOOKEND = new Set(["warmup", "closing"]);

/** "a", "a and b", "a, b and c". */
function listed(items: string[]): string {
  return items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

/**
 * Everyone the student will meet, before the parts (2026-10-21). The parts
 * each name one person — who asks — so a panel whose second member sits in
 * on the lead's round showed one face down the whole list, and the student
 * read "a panel of one". Each person here says what they do, in the plan's
 * own words: which parts they run, or which they sit in on.
 */
function PanelStrip({
  people,
}: {
  people: { card: PersonaCard; role: string }[];
}) {
  if (people.length < 2) return null;
  return (
    <section aria-labelledby="your-panel" className="mt-5">
      <h2 id="your-panel" className="text-sm font-medium text-ink">
        Your panel · {people.length} interviewers
      </h2>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {people.map(({ card, role }) => (
          <li key={card.id} className="flex items-start gap-3 rounded-lg border border-line bg-surface px-3 py-2.5">
            <Face persona={card.id} name={card.name} size={40} />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">{card.name}</p>
              <p className="text-2xs text-ink-faint">{card.title}</p>
              <p className="mt-1 text-2xs leading-relaxed text-ink-soft">{role}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** What each panelist does, from the plan itself: the parts they run, or
 *  the parts they sit in on. In seating order, the lead first. */
function panelRoles(
  panel: string[],
  live: PlannedSegment[],
  byId: Map<string, PersonaCard>,
): { card: PersonaCard; role: string }[] {
  const middle = live.filter((s) => !BOOKEND.has(s.kind));
  const ids = [...new Set([...live.map((s) => s.persona_id), ...panel])];
  return ids
    .map((id) => byId.get(id))
    .filter((card): card is PersonaCard => card !== undefined)
    .map((card) => {
      const runs = live.filter((s) => s.persona_id === card.id);
      if (runs.length === 0) {
        const on = listed(middle.map((s) => s.title));
        return {
          card,
          role: on
            ? `Sits in on ${on}, and comes in with follow-ups.`
            : "Sits in, and comes in with follow-ups.",
        };
      }
      const opens = runs.some((s) => s.kind === "warmup");
      const closes = runs.some((s) => s.kind === "closing");
      const parts = runs.filter((s) => !BOOKEND.has(s.kind)).map((s) => s.title);
      const doing = [
        ...(opens ? ["opens"] : []),
        ...(parts.length ? [`asks the ${listed(parts)} questions`] : []),
        ...(closes ? ["closes"] : []),
      ];
      const said = listed(doing);
      return { card, role: `${said.charAt(0).toUpperCase()}${said.slice(1)}.` };
    });
}

function SegmentRow({
  segment,
  onDrop,
  busy,
  who,
  alongside = [],
  faceWidth = FACE,
}: {
  segment: PlannedSegment;
  onDrop: () => void;
  busy: boolean;
  /** FR-6.3: a mock is a panel, so the preview says who runs each part. */
  who?: PersonaCard;
  /** Whoever sits in on this part: at the table, with follow-ups. */
  alongside?: PersonaCard[];
  /** The face column's width, the same on every row. */
  faceWidth?: number;
}) {
  const dropped = segment.dropped_reason !== null;
  const others = dropped ? [] : alongside;
  return (
    <li
      className={`flex items-start justify-between gap-4 border-b border-line py-3 last:border-0 ${
        dropped ? "opacity-55" : ""
      }`}
    >
      {who && !dropped && (
        // Everyone at the table for this part, the one asking in front. One
        // width for every row, so the titles line up however many sit in.
        <span className="mt-0.5 flex shrink-0" style={{ width: faceWidth }}>
          <Face persona={who.id} name={who.name} size={FACE} />
          {others.map((card) => (
            <span key={card.id} className="-ml-2.5 rounded-full ring-2 ring-surface">
              <Face persona={card.id} name={card.name} size={FACE} />
            </span>
          ))}
        </span>
      )}
      <div className="min-w-0 flex-1">
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
          {others.length > 0 && `${listed(others.map((card) => card.name))} sitting in · `}
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

/** The picked track's name, as the plan's own part calls it. */
function trackTitle(track: string, segments: { title: string; rubric_round_types?: string[] }[]): string {
  const part = segments.find((s) => s.rubric_round_types?.length === 1 && s.rubric_round_types[0] === track);
  return part?.title ?? track.replace(/_verbal$/, "").replace(/_/g, " ");
}

/** The panel's opening, made ahead by M11 while the plan is read. */
async function prepareOpening(sessionId: string, cards: PersonaCard[]): Promise<void> {
  try {
    const { parts } = await api.get<{ parts: { speaker_id: string; text: string }[] }>(
      `/v1/interviews/${sessionId}/opening`,
    );
    const byId = new Map(cards.map((card) => [card.id, card]));
    await prepareLine(
      `opening-${sessionId}`,
      parts.map((part) => ({
        text: part.text,
        personaId: part.speaker_id,
        voiceId: byId.get(part.speaker_id)?.voice_id ?? null,
      })),
      // Made ahead, with time to spare: the main voice model, first in line
      // (2026-10-09; "live" would take the faster, rougher one).
      "next",
    );
  } catch {
    // Ahead of time only: the opening is still made when it is said.
  }
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

  // While the student reads the plan, M11 makes the panel's opening, so the
  // first words are ready when Start is pressed (2026-10-08: they came 5-6 s
  // after the text). Once per plan; the question itself is chosen at start.
  const planId = built?.id;
  const cardsReady = personas.isSuccess;
  useEffect(() => {
    if (!planId || !planned || !cardsReady) return;
    void prepareOpening(sessionId, personas.data ?? []).then(() =>
      // Then the first questions and the panel's phrases, as warm lines.
      warmUpcoming(sessionId, personas.data ?? []),
    );
    // personas.data is stable once loaded (staleTime: Infinity).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId, planned, cardsReady, sessionId]);

  useEffect(() => {
    // Somebody else started it, or this tab refreshed after starting — or
    // this page's own Start did, and the session went live before Start's
    // own navigation ran. Which of the two lands last is not ours to choose,
    // and this one used to drop the stage's `justStarted`: a first start was
    // greeted "Welcome back" and its opening question went unspoken. So when
    // the start was ours, this one says so too.
    if (session.data && !planned)
      navigate(`/mock/${sessionId}`, {
        replace: true,
        state: start.isPending || start.isSuccess ? { justStarted: true } : undefined,
      });
  }, [session.data, planned, navigate, sessionId, start.isPending, start.isSuccess]);

  if (session.isPending || (!built && plan.isPending)) {
    return <Building />;
  }
  if (session.isError) {
    return <ErrorNote message="That interview could not be loaded." />;
  }

  const segments = built?.segments ?? [];
  const live = segments.filter((s) => s.dropped_reason === null);
  const totalMinutes = live.reduce((sum, s) => sum + s.minutes, 0);
  const totalQuestions = live.reduce((sum, s) => sum + s.question_budget, 0);
  const runsAPart = new Set(live.map((s) => s.persona_id));
  const sittingIn = (built?.panel ?? [])
    .filter((id) => !runsAPart.has(id))
    .map((id) => byId.get(id))
    .filter((card): card is PersonaCard => card !== undefined);
  const panelPeople = panelRoles(built?.panel ?? [], live, byId);

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title="Here is the plan"
        subtitle={
          built?.jd_id
            ? "Built from the job description you chose, so the questions follow what it asks for."
            : segments.some((s) => s.title.startsWith("Focus: "))
              ? "Built around the topic you chose."
              : built?.track
                ? `Every question is on ${trackTitle(built.track, segments)}, the track you picked${
                    built.resume_included ? ", with a part on your resume" : ""
                  }.`
                : "A mix of topics — pick a track, a job description or a drive and the plan follows it."
        }
      />

      <PanelStrip people={panelPeople} />

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
                  alongside={BOOKEND.has(segment.kind) ? [] : sittingIn}
                  faceWidth={FACE + FACE_OVERLAP * sittingIn.length}
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
        {(session.data?.flags.pauses_allowed ?? 1) === 1
          ? " · you can pause once, for up to five minutes"
          : ` · you can pause ${session.data?.flags.pauses_allowed} times, up to five minutes each`}
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
              // Said, so the stage does not greet a first start as a return.
              onSuccess: () => navigate(`/mock/${sessionId}`, { state: { justStarted: true } }),
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
