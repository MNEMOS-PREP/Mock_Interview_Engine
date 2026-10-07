/**
 * The setup screen — spec §2.2 ("must take under 60 seconds").
 *
 * What it offers is only what the engine can actually do today, which is the
 * whole discipline of this screen: a modality picker with a disabled "Voice"
 * radio would be a promise the session breaks. The modes are offered because
 * since day 9 they are real — each is described by `/v1/interviews/modes`,
 * which serves only mechanics the engine enforces.
 *
 * 2026-10-04 — what the student is practising FOR is now chosen here, not only
 * arrived at by a URL: general, a drive or posting the host knows they are
 * aiming at (`MockTargetsContext`), or one topic from the skill graph
 * (`?focus=`, planned by M06 as one segment on that concept). The panel they
 * may meet is shown with faces before they start, and the pause rule says
 * what it now is: one per 15 planned minutes.
 *
 * 2026-10-07 — WHAT to be interviewed on is a choice too: every track the
 * bank holds questions for (`/v1/interviews/tracks`), grouped, or a mixed
 * interview. An ML interview used to ask DSA and the resume because nothing
 * here said "ML". The resume is opt-in — "not every interview is meant to ask
 * from resume" — and, with several, the student picks which.
 */

import { useContext, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ErrorNote, Icon, PageHeader, SkeletonRows, relativeDays } from "@ai/core";

import {
  useCreateSession,
  useHistory,
  useModes,
  usePersonas,
  useResumes,
  useTracks,
} from "../api";
import { MockTargetsContext } from "../targets";
import type { Mode, ResumeOption, SessionSummary, TrackOption } from "../types";
import { Face, voiceKind } from "../ui/Face";

const LENGTHS = [
  { minutes: 15, label: "15 min", hint: "5–7 questions" },
  { minutes: 30, label: "30 min", hint: "a proper round" },
  { minutes: 45, label: "45 min", hint: "a full interview" },
];

const LIVE = new Set(["planned", "live", "paused"]);

const MODES: readonly Mode[] = ["practice", "mock", "real_drive", "final_boss"];

/** The same pause rule the backend enforces (state.pause_allowance). */
function pausesFor(minutes: number): number {
  return Math.max(1, Math.floor(minutes / 15));
}

function Choice({
  active,
  onClick,
  title,
  sub,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  sub?: string;
  icon?: "compass" | "building" | "listChecks" | "target";
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex min-w-0 items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
        active
          ? "border-brand bg-brand-soft text-ink"
          : "border-line bg-surface text-ink-soft hover:border-line-strong"
      }`}
    >
      {icon && <Icon name={icon} size={16} className={`mt-0.5 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />}
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{title}</span>
        {sub && <span className="block truncate text-2xs text-ink-faint">{sub}</span>}
      </span>
    </button>
  );
}

/** One track: its name, what it covers, and — when no person has reviewed
 *  its questions yet — that answers in it are practised, not scored. */
function TrackChoice({
  track,
  active,
  onClick,
}: {
  track: TrackOption;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-w-0 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
        active
          ? "border-brand bg-brand-soft text-ink"
          : "border-line bg-surface text-ink-soft hover:border-line-strong"
      }`}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0 text-sm font-medium leading-snug">{track.title}</span>
        {!track.scored && (
          <span
            className="shrink-0 rounded-full bg-surface-sunken px-1.5 py-px text-2xs text-ink-faint"
            title="Its questions are new and no person has reviewed them yet, so answers are practised, not scored."
          >
            practice
          </span>
        )}
      </span>
      {track.blurb && (
        <span className="mt-0.5 line-clamp-2 block text-2xs leading-relaxed text-ink-faint">
          {track.blurb}
        </span>
      )}
    </button>
  );
}

function resumeName(resume: ResumeOption): string {
  return resume.filename ?? `Resume from ${resume.created_at ? relativeDays(resume.created_at) : "earlier"}`;
}

function HistoryRow({ session }: { session: SessionSummary }) {
  const unfinished = LIVE.has(session.status);
  return (
    <li>
      <Link
        to={unfinished ? `/mock/${session.id}` : `/mock/${session.id}/report`}
        className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-surface-sunken"
      >
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface-sunken text-ink-soft">
          <Icon name={session.kind === "drill" ? "zap" : "mic"} size={15} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">
            {session.kind === "drill" ? "Defend drill" : `${session.requested_minutes}-minute interview`}
          </span>
          <span className="block text-2xs text-ink-faint">{relativeDays(session.created_at)}</span>
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-2xs font-medium ${
            unfinished ? "border border-brand-line bg-brand-soft text-brand" : "bg-surface-sunken text-ink-soft"
          }`}
        >
          {unfinished ? "Continue" : "Notes"}
        </span>
      </Link>
    </li>
  );
}

export function MockHome() {
  const [params, setParams] = useSearchParams();
  // `?minutes=15&mode=practice` — what Today and the welcome step send for a
  // first interview. Anything else falls back to a 30-minute Mock.
  const asked = { minutes: Number(params.get("minutes")), mode: params.get("mode") as Mode | null };
  const [minutes, setMinutes] = useState(() =>
    LENGTHS.some((l) => l.minutes === asked.minutes) ? asked.minutes : 30,
  );
  const [mode, setMode] = useState<Mode>(() =>
    asked.mode && MODES.includes(asked.mode) ? asked.mode : "mock",
  );
  // Once the student (or a link) has chosen, the defaults below stand down.
  const chosen = useRef(Boolean(params.get("minutes") || params.get("mode")));
  const modes = useModes();
  const personas = usePersonas();
  const targets = useContext(MockTargetsContext);
  const jd = params.get("jd");
  // From M15's "Practise this format": a company and the drive being sat.
  // The backend asks M02 for that drive's requirement set (§2.3 door 1).
  const company = params.get("company");
  const drive = params.get("drive");
  const label = params.get("label");
  // From the skill graph or Today: one topic, planned as one segment.
  const focus = params.get("focus");
  const create = useCreateSession();
  const history = useHistory();
  const navigate = useNavigate();
  const tracks = useTracks();
  const resumes = useResumes();
  // `?track=ml_verbal` from a link; otherwise a mixed interview.
  const [track, setTrack] = useState<string | null>(() => params.get("track"));
  const [withResume, setWithResume] = useState(false);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const myResumes = resumes.data?.resumes ?? [];
  // The one the student is asked about unless they pick another: the
  // current one, as M01 marks it, else the newest.
  const pickedResume =
    myResumes.find((r) => r.id === resumeId) ?? myResumes.find((r) => r.is_active) ?? myResumes[0];

  // A student who has never sat one gets the gentlest real start: 15 minutes
  // of Practice — hints on, a retry allowed — rather than 30 of Mock.
  useEffect(() => {
    if (chosen.current || !history.data) return;
    chosen.current = true;
    if (!history.data.some((s) => s.started_at)) {
      setMinutes(15);
      setMode("practice");
    }
  }, [history.data]);

  const unfinished = (history.data ?? []).find((session) => LIVE.has(session.status));

  const currentKey = focus ? `focus:${focus}` : jd ? `jd:${jd}` : drive ? `drive:${drive}` : "general";
  const known = targets.some((t) => t.key === currentKey);
  const choose = (next: Record<string, string>) => setParams(next, { replace: true });

  const target = focus
    ? `Topic: ${label ?? focus.split(":").pop()?.replace(/_/g, " ")}`
    : jd
      ? label ?? "The job description you came from"
      : company && drive
        ? label ?? "This drive"
        : null;
  const pauses = pausesFor(minutes);
  // A posting, a drive or one topic decides what is asked; a track only
  // narrows general practice.
  const general = currentKey === "general";
  const groups = (() => {
    const all = tracks.data?.tracks ?? [];
    const named = tracks.data?.groups ?? [];
    const order = [...named, ...all.map((t) => t.group).filter((g) => !named.includes(g))];
    return [...new Set(order)]
      .map((group) => ({ group, tracks: all.filter((t) => t.group === group) }))
      .filter((g) => g.tracks.length > 0);
  })();

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="min-w-0">
        <PageHeader
          title="Practise an interview"
          subtitle="An interviewer asks, listens, and follows up until it finds the edge of what you know."
          how={
            <>
              <p>
                Questions come from the platform's bank, chosen for what you are practising for and
                for what your skill graph says you haven't shown yet. If the bank can't be reached,
                the interview says so and runs from a short backup set.
              </p>
              <p>
                Speak your answers with the mic or type them; either way you read and edit before
                anything is sent. Afterwards you get notes on every question.
              </p>
            </>
          }
        />

        <fieldset className="mt-7">
          <legend className="text-sm font-medium text-ink">Practising for</legend>
          <div className="mt-2.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <Choice
              active={currentKey === "general"}
              onClick={() => choose({})}
              title="General practice"
              sub="Across the topics you haven't shown yet"
              icon="compass"
            />
            {targets.map((t) => (
              <Choice
                key={t.key}
                active={currentKey === t.key}
                onClick={() => choose(t.params)}
                title={t.label}
                sub={t.sub}
                icon={t.key.startsWith("jd:") ? "listChecks" : "building"}
              />
            ))}
            {!known && target && (
              <Choice active onClick={() => undefined} title={target} sub="From the link you followed" icon={focus ? "target" : "listChecks"} />
            )}
          </div>
          <p className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-ink-faint">
            <Link to="/jd" className="font-medium text-brand">
              + Paste a job description
            </Link>
            <Link to="/companies" className="font-medium text-brand">
              + Practise for a company's drive
            </Link>
            <Link to="/skills" className="font-medium text-brand">
              + Pick a topic from your skill graph
            </Link>
          </p>
        </fieldset>

        {general && groups.length > 0 && (
          <fieldset className="mt-7">
            <legend className="text-sm font-medium text-ink">Interview on</legend>
            <div className="mt-2.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <button
                type="button"
                aria-pressed={track === null}
                onClick={() => setTrack(null)}
                className={`min-w-0 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                  track === null
                    ? "border-brand bg-brand-soft text-ink"
                    : "border-line bg-surface text-ink-soft hover:border-line-strong"
                }`}
              >
                <span className="block text-sm font-medium">A mix</span>
                <span className="mt-0.5 block text-2xs leading-relaxed text-ink-faint">
                  A few rounds on different topics, different each time.
                </span>
              </button>
            </div>
            {groups.map(({ group, tracks: inGroup }) => (
              <div key={group} className="mt-3">
                <p className="text-2xs font-medium uppercase tracking-wide text-ink-faint">{group}</p>
                <div className="mt-1.5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {inGroup.map((t) => (
                    <TrackChoice
                      key={t.round_type}
                      track={t}
                      active={track === t.round_type}
                      onClick={() => setTrack(t.round_type)}
                    />
                  ))}
                </div>
              </div>
            ))}
            {tracks.data?.note && <p className="mt-2.5 text-2xs text-ink-faint">{tracks.data.note}</p>}
          </fieldset>
        )}

        <fieldset className="mt-7">
          <legend className="text-sm font-medium text-ink">Your resume</legend>
          {myResumes.length === 0 ? (
            <p className="mt-2 text-2xs text-ink-faint">
              {resumes.isLoading
                ? "Looking for your resume…"
                : resumes.data?.note ?? "No resume yet, so the questions are all about the topics."}{" "}
              {!resumes.isLoading && !resumes.data?.note && (
                <Link to="/resume" className="font-medium text-brand">
                  Add one
                </Link>
              )}
            </p>
          ) : (
            <>
              <label className="mt-2.5 flex cursor-pointer items-start gap-2.5 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={withResume}
                  onChange={(e) => setWithResume(e.target.checked)}
                  className="mt-0.5 h-4 w-4 accent-[var(--color-brand)]"
                />
                <span>
                  Ask me about my projects too
                  <span className="block text-2xs text-ink-faint">
                    Off: every question is on the topics. On: a short part on lines from your resume
                    an interviewer would push on, not scored.
                  </span>
                </span>
              </label>
              {withResume && myResumes.length > 1 && (
                <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
                  {myResumes.map((r) => (
                    <Choice
                      key={r.id}
                      active={pickedResume?.id === r.id}
                      onClick={() => setResumeId(r.id)}
                      title={resumeName(r)}
                      sub={
                        r.defendable === 0
                          ? "Nothing on it to push on"
                          : `${r.defendable} line${r.defendable === 1 ? "" : "s"} to defend${r.is_active ? " · current" : ""}`
                      }
                    />
                  ))}
                </div>
              )}
              {withResume && pickedResume && pickedResume.defendable === 0 && (
                <p className="mt-2 text-2xs text-ink-faint">
                  Nothing on {myResumes.length > 1 ? "that resume" : "your resume"} reads as a line an
                  interviewer would push on, so there won't be a projects part.
                </p>
              )}
            </>
          )}
        </fieldset>

        <fieldset className="mt-7">
          <legend className="text-sm font-medium text-ink">How long</legend>
          <div className="mt-2.5 flex flex-wrap gap-2">
            {LENGTHS.map((option) => (
              <button
                key={option.minutes}
                type="button"
                aria-pressed={minutes === option.minutes}
                onClick={() => {
                  chosen.current = true;
                  setMinutes(option.minutes);
                }}
                className={`rounded-xl border px-3.5 py-2 text-left transition-colors ${
                  minutes === option.minutes
                    ? "border-brand bg-brand-soft text-ink"
                    : "border-line bg-surface text-ink-soft hover:border-line-strong"
                }`}
              >
                <span className="block text-sm font-medium">{option.label}</span>
                <span className="block text-2xs text-ink-faint">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        {(modes.data ?? []).length > 0 && (
          <fieldset className="mt-7">
            <legend className="text-sm font-medium text-ink">What kind</legend>
            <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
              {(modes.data ?? []).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={mode === option.id}
                  onClick={() => {
                    chosen.current = true;
                    setMode(option.id);
                  }}
                  className={`rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                    mode === option.id
                      ? "border-brand bg-brand-soft text-ink"
                      : "border-line bg-surface text-ink-soft hover:border-line-strong"
                  }`}
                >
                  <span className="block text-sm font-medium">{option.label}</span>
                  <span className="block text-2xs leading-relaxed text-ink-faint">{option.summary}</span>
                </button>
              ))}
            </div>
          </fieldset>
        )}

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() =>
              // Via the plan, not straight into the first question: a student
              // should see what they are about to be asked (FR-6.2).
              create.mutate(
                {
                  minutes,
                  mode,
                  jd_id: jd ?? undefined,
                  company_id: company ?? undefined,
                  drive_id: drive ?? undefined,
                  focus_concepts: focus ? [focus] : undefined,
                  focus_label: focus ? (label ?? undefined) : undefined,
                  track: general && track ? track : undefined,
                  include_resume: withResume && Boolean(pickedResume),
                  resume_id: withResume && pickedResume ? pickedResume.id : undefined,
                },
                { onSuccess: (s) => navigate(`/mock/${s.id}/plan`) },
              )
            }
            disabled={create.isPending || Boolean(unfinished)}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-brand px-5 text-sm font-semibold text-white shadow-glow hover:bg-brand-hover disabled:opacity-50"
          >
            <Icon name="mic" size={16} />
            {create.isPending ? "Building your plan…" : "Start interview"}
          </button>
          <p className="text-2xs text-ink-faint">
            {pauses === 1 ? "One pause" : `${pauses} pauses`} of up to 5 minutes · ending early still
            gives you notes
          </p>
        </div>

        {unfinished && (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-brand-line bg-brand-soft p-3.5 text-sm">
            <p className="text-ink">You have an interview in progress.</p>
            <Link to={`/mock/${unfinished.id}`} className="font-medium text-brand">
              Go back to it →
            </Link>
          </div>
        )}

        {create.isError && (
          <div className="mt-4">
            <ErrorNote
              message="That didn't start."
              detail={create.error instanceof Error ? create.error.message : undefined}
              onRetry={() => create.reset()}
            />
          </div>
        )}
      </section>

      <aside className="space-y-5">
        {(personas.data ?? []).length > 0 && (
          <section className="panel p-5">
            <h2 className="text-sm font-semibold text-ink">Who you might meet</h2>
            <p className="mt-1 text-2xs text-ink-faint">A mock is a panel; the plan says who runs each part.</p>
            <ul className="mt-4 space-y-3.5">
              {(personas.data ?? []).map((persona) => (
                <li key={persona.id} className="flex items-start gap-3">
                  <Face name={persona.name} size={40} kind={voiceKind(persona.voice_id)} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-ink">{persona.name}</span>
                    <span className="block text-2xs text-ink-faint">{persona.title}</span>
                    {persona.style && (
                      <span className="mt-0.5 block text-2xs leading-relaxed text-ink-soft">{persona.style}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="panel p-5">
          <h2 className="text-sm font-semibold text-ink">Your interviews</h2>
          {history.isLoading ? (
            <SkeletonRows label="Loading your interviews" rows={3} className="mt-4" />
          ) : (history.data ?? []).length === 0 ? (
            <p className="mt-3 text-sm text-ink-faint">
              Nothing yet. Each interview is listed here with its notes.
            </p>
          ) : (
            <ul className="mt-2">
              {(history.data ?? []).slice(0, 6).map((session) => (
                <HistoryRow key={session.id} session={session} />
              ))}
            </ul>
          )}
          {(history.data ?? []).length > 6 && (
            <Link to="/history" className="mt-2 inline-block text-2xs font-medium text-brand">
              All your interviews →
            </Link>
          )}
        </section>
      </aside>
    </div>
  );
}
