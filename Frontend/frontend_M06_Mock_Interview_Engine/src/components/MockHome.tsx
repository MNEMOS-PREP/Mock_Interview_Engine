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

import { ErrorNote, Icon, SkeletonRows, relativeDays } from "@ai/core";

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

/** The design's own icons (Lucide, as drawn in the Figma), served from assets. */
const FIGMA_ICONS = import.meta.glob("../assets/figma/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

function Fig({ name, size }: { name: string; size: number }) {
  return <img src={FIGMA_ICONS[`../assets/figma/${name}.svg`]} width={size} height={size} alt="" className="shrink-0" />;
}

/** Where "Group discussion" lives: the GD Arena, mounted beside this module. */
const GD_URL: string = import.meta.env.VITE_GD_URL ?? "/gd";

const MODE_ICON: Record<string, string> = { practice: "sprout", mock: "timer", real_drive: "briefcase", final_boss: "flame" };
const MODE_TAGLINE: Record<string, string> = {
  practice: "A good place to start",
  mock: "Feel the real round",
  real_drive: "Job description required",
  final_boss: "Bring your best reasoning",
};
const PART_COLOURS = ["#c9f4c8", "#8dcba4", "#6eaa8a", "#dce6b5"];
const AVATAR_COLOURS = ["#c9f4c8", "#f0ecdd", "#eae5f6"];

function initials(name: string): string {
  return name
    .replace(/^Dr\.?\s+/i, "")
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/** A numbered step: its number small and green, then its question. */
function StepHead({ n, title, note }: { n: string; title: string; note?: string }) {
  return (
    <div className="flex items-center gap-2.5 whitespace-nowrap leading-normal">
      <span className="text-[10px] text-brand">{n}</span>
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {note && <span className="text-[11px] text-ink-soft">{note}</span>}
    </div>
  );
}

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
      className="choice flex min-w-0 items-start gap-2.5"
    >
      {icon && <Icon name={icon} size={16} className={`mt-0.5 shrink-0 ${active ? "text-brand" : "text-ink-faint"}`} />}
      <span className="min-w-0">
        {/* Wraps too: "Course: Database Management Systems" is the name of
            what is being practised, and was cut to "Course: Database Mana…". */}
        <span className="line-clamp-2 block text-sm font-medium">{title}</span>
        {/* Two lines, not one truncated: "Across the topics you haven't s…"
            hid what General practice is (2026-10-13). */}
        {sub && <span className="line-clamp-2 block text-2xs leading-relaxed text-ink-faint">{sub}</span>}
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
      // A flex column, so a card in a tall row keeps its title at the top: a
      // button centres its content, which floated the shorter cards' titles
      // half a line below their neighbours' (2026-10-13).
      className="choice flex min-w-0 flex-col justify-start"
    >
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0 text-sm font-medium leading-snug">{track.title}</span>
        {!track.scored && (
          // "not scored", not "practice": the chip sat on the same page as
          // the Practice mode and read as one of its settings.
          <span
            className="shrink-0 whitespace-nowrap rounded-full bg-surface-sunken px-1.5 py-px text-2xs text-ink-faint"
            title="Its questions are new and no person has reviewed them yet, so answers are practised, not scored."
          >
            not scored
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
  // From the skill graph or Today: one topic, planned as one segment. From a
  // course on Today: its syllabus's topics, comma-separated (up to eight).
  const focus = params.get("focus");
  const focusConcepts = (focus ?? "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean)
    .slice(0, 8);
  const create = useCreateSession();
  const history = useHistory();
  const navigate = useNavigate();
  const tracks = useTracks();
  const resumes = useResumes();
  // `?track=ml_verbal` from a link; otherwise a mixed interview.
  const [track, setTrack] = useState<string | null>(() => params.get("track"));
  const [withResume, setWithResume] = useState(false);
  const [focusOpen, setFocusOpen] = useState(false);
  // What is being set up: an interview here, or a group discussion in the GD arena.
  const [kind, setKind] = useState<"interview" | "gd">("interview");
  const [jdText, setJdText] = useState("");
  const [allPersonas, setAllPersonas] = useState(false);
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
  const choose = (next: Record<string, string>) => setParams(next, { replace: true });

  const target = focus
    ? focusConcepts.length > 1
      ? `Course: ${label ?? `${focusConcepts.length} topics`}`
      : `Topic: ${label ?? focus.split(":").pop()?.replace(/_/g, " ")}`
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

  let step = 0;
  const num = () => String(++step).padStart(2, "0");
  const lead = (personas.data ?? [])[0];
  const second = (personas.data ?? [])[1];
  const third = (personas.data ?? [])[2];
  const modeLabel = (modes.data ?? []).find((m) => m.id === mode)?.label ?? mode;
  const topicTitle = target ?? (track ? (tracks.data?.tracks.find((t) => t.round_type === track)?.title ?? track) : "A mix of topics");
  // An indicative split; the real plan is built and shown on the next screen.
  const a = Math.max(2, Math.round(minutes * 0.1));
  const b = Math.round(minutes * 0.4);
  const c = Math.round(minutes * 0.33);
  const d = Math.max(2, minutes - a - b - c);
  const parts = [
    { t: "Settle in & introduce yourself", who: lead, m: a },
    { t: withResume && pickedResume ? "Your projects & trade-offs" : "Core questions", who: second ?? lead, m: b },
    { t: "Going deeper, with follow-ups", who: third ?? second ?? lead, m: c },
    { t: "Reflect & wrap up", who: lead, m: d },
  ];
  const meetThree = (personas.data ?? []).slice(0, allPersonas ? undefined : 3);

  // The GD arena is part of this app (the shell frames it at /gd), so go there
  // inside the router; a full page load would drop the shell around it.
  const openGd = () => {
    if (GD_URL.startsWith("/")) navigate(GD_URL);
    else window.location.assign(GD_URL);
  };
  // An interview already planned or running: go back into it.
  const continueIt = () => {
    if (unfinished) navigate(unfinished.status === "planned" ? `/mock/${unfinished.id}/plan` : `/mock/${unfinished.id}`);
  };

  const startPlan = () =>
    // Via the plan, not straight into the first question: a student
    // should see what they are about to be asked (FR-6.2).
    create.mutate(
      {
        minutes,
        mode,
        jd_id: jd ?? undefined,
        company_id: company ?? undefined,
        drive_id: drive ?? undefined,
        // One concept from Today, several from a course: comma-separated.
        focus_concepts: focusConcepts.length ? focusConcepts : undefined,
        focus_label: focus ? (label ?? undefined) : undefined,
        track: general && track ? track : undefined,
        include_resume: withResume && Boolean(pickedResume),
        resume_id: withResume && pickedResume ? pickedResume.id : undefined,
      },
      { onSuccess: (s) => navigate(`/mock/${s.id}/plan`) },
    );

  const divider = "border-t border-line pt-6";

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        <p className="text-[11px] leading-normal tracking-[1.6px] text-brand">YOUR PRACTICE SPACE</p>
        <h1 className="text-[43px] font-medium leading-[1.15] tracking-[-1.8px] text-ink">A little practice today?</h1>
        <p className="text-[15px] leading-[1.65] text-ink-soft">
          Choose your round and your pace. We&rsquo;ll bring a panel that listens — and a plan that fits.
        </p>
      </header>
    <div className="flex flex-col items-stretch gap-8 xl:flex-row xl:items-start">

      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <div className="flex flex-col gap-7 rounded-[20px] border border-line bg-surface p-7">
          {/* 01 — format */}
          <section className="flex flex-col gap-4" aria-label="Format">
            <StepHead n={num()} title="What are we practising?" />
            <div className="flex flex-col gap-3 sm:flex-row">
              <button type="button" aria-pressed={kind === "interview"} onClick={() => setKind("interview")} className="choice flex flex-1 flex-col gap-3 self-stretch">
                <span className="flex items-start justify-between">
                  <Fig name="mic" size={21} />
                  <Fig name={kind === "interview" ? "circle-check" : "circle"} size={17} />
                </span>
                <span className="flex flex-col gap-1.5">
                  <span className="text-base font-semibold text-ink">Interview</span>
                  <span className="text-xs leading-[1.6] text-ink-soft">A live AI panel that follows your answers.</span>
                </span>
              </button>
              <button type="button" aria-pressed={kind === "gd"} onClick={() => setKind("gd")} className="choice flex flex-1 flex-col gap-3 self-stretch">
                <span className="flex items-start justify-between">
                  <Fig name="messages-square" size={21} />
                  <Fig name={kind === "gd" ? "circle-check" : "circle"} size={17} />
                </span>
                <span className="flex flex-col gap-1.5">
                  <span className="text-base font-semibold text-ink">Group discussion</span>
                  <span className="text-xs leading-[1.6] text-ink-soft">3–5 AI peers. Three topic tracks.</span>
                </span>
              </button>
            </div>
            <a href="#gd-room" className="flex items-center gap-1.5 text-[11px] leading-normal text-ink-soft no-underline">
              <Fig name="info" size={13} />
              <span>Curious about GD? Explore tracks &amp; assessment below ↓</span>
            </a>
          </section>

          {kind === "interview" && (<>
          {/* 02 — focus */}
          <section className={`flex flex-col gap-3.5 ${divider}`} aria-label="Focus">
            <StepHead n={num()} title="Choose your focus" />
            <div className="relative">
              <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={focusOpen}
                onClick={() => setFocusOpen((open) => !open)}
                className="flex h-[58px] w-full items-center gap-3 rounded-lg border border-line bg-surface px-4 text-left hover:border-line-strong"
              >
                <Fig name="code-xml" size={19} />
                <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                  <span className="truncate text-[13px] text-ink">{target ?? (currentKey === "general" ? "General practice" : topicTitle)}</span>
                  <span className="truncate text-[10px] text-ink-soft">
                    {currentKey === "general" ? "Across the topics you haven't shown yet" : (targets.find((t) => t.key === currentKey)?.sub ?? "From the link you followed")}
                  </span>
                </span>
                <Fig name="chevron-down" size={17} />
              </button>
              {focusOpen && (
                <ul
                  role="listbox"
                  aria-label="Focus"
                  className="absolute z-20 mt-2 max-h-72 w-full overflow-y-auto rounded-xl border border-line bg-surface p-1.5 shadow-[0_16px_48px_rgba(22,59,39,0.12)]"
                >
                  {[
                    { key: "general", label: "General practice", sub: "Across the topics you haven't shown yet", params: {} as Record<string, string> },
                    ...targets.map((t) => ({ key: t.key, label: t.label, sub: t.sub, params: t.params })),
                  ].map((o) => (
                    <li key={o.key} role="option" aria-selected={currentKey === o.key}>
                      <button
                        type="button"
                        onClick={() => {
                          choose(o.params);
                          setFocusOpen(false);
                        }}
                        className={`flex w-full flex-col gap-0.5 rounded-lg px-3 py-2.5 text-left hover:bg-brand-soft ${currentKey === o.key ? "bg-brand-soft" : ""}`}
                      >
                        <span className="text-[13px] font-medium text-ink">{o.label}</span>
                        {o.sub && <span className="text-[11px] text-ink-soft">{o.sub}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {general && groups.length > 0 && (
              <div className="mt-1 flex flex-col gap-3">
                <button
                  type="button"
                  aria-pressed={track === null}
                  onClick={() => setTrack(null)}
                  className="choice min-w-0"
                >
                  <span className="block text-sm font-medium">A mix</span>
                  <span className="mt-0.5 block text-2xs leading-relaxed text-ink-soft">
                    A few rounds on different topics, different each time.
                  </span>
                </button>
                {groups.map(({ group, tracks: inGroup }) => (
                  <div key={group}>
                    <p className="text-[11px] font-medium text-ink-soft">{group}</p>
                    <div className="mt-1.5 grid gap-3 sm:grid-cols-2">
                      {inGroup.map((t) => (
                        <TrackChoice key={t.round_type} track={t} active={track === t.round_type} onClick={() => setTrack(t.round_type)} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {tracks.data?.note && <p className="text-[11px] text-ink-soft">{tracks.data.note}</p>}
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] leading-[1.6] text-ink-soft">
              <Link to="/jd" className="font-medium text-brand">+ Paste a job description</Link>
              <Link to="/companies" className="font-medium text-brand">+ Practise for a company's drive</Link>
              <Link to="/skills" className="font-medium text-brand">+ Pick a topic from your skill graph</Link>
            </p>
          </section>

          {/* 03 — length */}
          <section className="flex flex-col gap-3.5" aria-label="Length">
            <StepHead n={num()} title="How much time do you have?" />
            <div className="flex gap-2.5" role="group" aria-label="Length">
              {LENGTHS.map((option) => {
                const on = minutes === option.minutes;
                return (
                  <button
                    key={option.minutes}
                    type="button"
                    aria-pressed={on}
                    onClick={() => {
                      chosen.current = true;
                      setMinutes(option.minutes);
                    }}
                    className={`flex h-[46px] min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg border text-[13px] font-semibold ${
                      on ? "border-brand bg-brand text-on-brand" : "border-line bg-surface-sunken text-ink-soft hover:border-line-strong"
                    }`}
                  >
                    {option.label}
                    {on && <img src={FIGMA_ICONS["../assets/figma/check.svg"]} width={13} height={13} alt="" className="brightness-0 invert" />}
                  </button>
                );
              })}
            </div>
          </section>

          {/* 04 — intensity */}
          {(modes.data ?? []).length > 0 && (
            <section className={`flex flex-col gap-4 ${divider}`} aria-label="Intensity">
              <StepHead n={num()} title="Set the intensity" />
              <div className="grid gap-3 sm:grid-cols-2">
                {(modes.data ?? []).map((option) => {
                  const on = mode === option.id;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => {
                        chosen.current = true;
                        setMode(option.id);
                      }}
                      className="choice flex flex-col items-stretch justify-start gap-2.5"
                    >
                      <span className="flex items-center justify-between">
                        <Fig name={MODE_ICON[option.id] ?? "timer"} size={18} />
                        <Fig name={on ? "circle-check-sm" : "circle-sm"} size={16} />
                      </span>
                      <span className="block text-sm font-semibold text-ink">{option.label}</span>
                      <span className="block text-xs leading-[1.55] text-ink-soft">{option.summary}</span>
                      <span className="block text-[10px] font-medium leading-normal text-brand">{MODE_TAGLINE[option.id]}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          {/* 05 — context */}
          <section className={`flex flex-col gap-3.5 ${divider}`} aria-label="Context">
            <StepHead n={num()} title="Give the panel context" note="Optional" />
            <p className="text-xs leading-[1.6] text-ink-soft">
              The planning agent uses your JD or resume to tailor the time split and questions. Real drive requires a JD.
            </p>
            <div className="flex flex-col gap-[9px]">
              <label htmlFor="jd-text" className="text-[11px] leading-normal text-ink">Job description</label>
              <textarea
                id="jd-text"
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
                placeholder="Paste the role, responsibilities and skills here…"
                className="min-h-[94px] w-full resize-y rounded-lg border border-line bg-canvas p-3.5 text-xs leading-normal text-ink placeholder:text-ink-soft"
              />
              {jdText.trim().length > 0 && (
                <button
                  type="button"
                  onClick={() => navigate("/jd", { state: { jdText } })}
                  className="self-start text-[11px] font-semibold text-brand"
                >
                  Review and use this job description →
                </button>
              )}
            </div>
            {myResumes.length === 0 ? (
              <Link
                to="/resume"
                className="flex items-center gap-3 rounded-lg border border-dashed border-line p-3.5 no-underline"
              >
                <Fig name="upload" size={18} />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-xs text-brand">{resumes.isLoading ? "Looking for your resume…" : "Upload a resume"}</span>
                  <span className="text-[10px] text-ink-soft">PDF · up to 5 MB · optional</span>
                </span>
                <Fig name="plus" size={17} />
              </Link>
            ) : (
              <>
                <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-dashed border-line p-3.5 text-xs text-ink">
                  <input
                    type="checkbox"
                    checked={withResume}
                    onChange={(e) => setWithResume(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-[var(--color-brand)]"
                  />
                  <span className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-brand">Ask me about my projects too</span>
                    <span className="text-[10px] leading-[1.5] text-ink-soft">
                      Off: every question is on the topics. On: a short part on lines from your resume an interviewer would push on, not scored.
                    </span>
                  </span>
                </label>
                {withResume && myResumes.length > 1 && (
                  <div className="grid gap-3 sm:grid-cols-2">
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
                  <p className="text-[11px] text-ink-soft">
                    Nothing on {myResumes.length > 1 ? "that resume" : "your resume"} reads as a line an interviewer would push on, so there won't be a projects part.
                  </p>
                )}
              </>
            )}
            <p className="flex items-center gap-1.5 text-[10px] leading-normal text-ink-soft">
              <Fig name="lock" size={12} />
              Only add information you&rsquo;re comfortable using in this practice.
            </p>
          </section>
          </>)}
        </div>

        {/* Group discussion, discovered from here */}
        <section id="gd-room" className="flex flex-col gap-[18px] rounded-[20px] bg-brand-soft p-[26px]" aria-label="Group discussion">
          <div className="flex items-center justify-between">
            <p className="text-[11px] uppercase leading-normal tracking-[1.6px] text-brand">A different kind of room</p>
            <Fig name="messages-square-lg" size={19} />
          </div>
          <div className="flex flex-col gap-[9px]">
            <p className="text-[22px] leading-normal tracking-[-0.6px] text-ink">Prefer a group discussion?</p>
            <p className="text-xs leading-[1.65] text-ink-soft">
              Switch to GD to join 3–5 AI participants: assertive, quiet, off-topic and supportive. Your voice matters; so does how you listen.
            </p>
          </div>
          <div className="flex flex-col gap-2.5">
            <p className="text-[11px] font-semibold text-ink">Choose a topic track in GD</p>
            <div className="flex flex-wrap gap-[7px]">
              {["Current affairs", "Abstract", "Case-based"].map((t) => (
                <span key={t} className="rounded-full border border-line bg-surface px-2.5 py-1.5 text-[11px] font-medium leading-normal text-brand">
                  {t}
                </span>
              ))}
            </div>
            <p className="text-[11px] leading-[1.7] text-ink-soft">
              AI in campus assessments · A world without deadlines · Reducing a college canteen&rsquo;s food waste
            </p>
          </div>
          <div className="flex flex-col gap-[7px] border-t border-line pt-3.5 text-[11px]">
            <p className="font-semibold text-ink">Feedback on every contribution</p>
            <p className="leading-[1.8] text-ink-soft">Initiating · Structuring · Listening · Building on others · Concluding</p>
          </div>
          <button type="button" onClick={openGd} className="flex w-full items-start justify-between bg-transparent p-0 text-left text-xs leading-normal text-brand">
            Set up a GD instead
            <Fig name="arrow-right" size={16} />
          </button>
        </section>

        {unfinished && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-line bg-brand-soft p-3.5 text-sm">
            <p className="text-ink">You have an interview in progress.</p>
            <Link to={`/mock/${unfinished.id}`} className="font-medium text-brand">
              Go back to it
            </Link>
          </div>
        )}

        {create.isError && (
          <ErrorNote
            message="That didn't start."
            detail={create.error instanceof Error ? create.error.message : undefined}
            onRetry={() => create.reset()}
          />
        )}
      </div>

      <aside className="flex w-full shrink-0 flex-col gap-6 xl:w-[400px]">
        {/* The session, planned: the one dark panel on the screen. */}
        <section aria-label="Your session, planned" className="flex flex-col gap-[22px] rounded-[20px] bg-[#142d27] p-[26px] text-white shadow-[0_16px_48px_rgba(22,59,39,0.06)]">
          <div className="flex items-center justify-between">
            <p className="text-[11px] uppercase leading-normal tracking-[1.6px] text-[#c9f4c8]">Your session, planned</p>
            <Fig name="sparkles" size={18} />
          </div>
          <div className="flex flex-col gap-2.5">
            <p className="text-[25px] font-medium leading-[1.2] tracking-[-0.8px] text-white">{kind === "gd" ? "A group discussion" : topicTitle}</p>
            <div className="flex flex-wrap gap-2">
              {(kind === "gd" ? ["3–5 AI peers", "Open, for/against or case"] : [`${minutes} min`, modeLabel, mode === "practice" ? "Hints on" : mode === "final_boss" ? "No hints" : "Hints cost credit"]).map((t) => (
                <span key={t} className="rounded-full border border-[#3c574b] bg-[#203e35] px-2.5 py-1.5 text-[11px] font-medium leading-normal text-[#c9f4c8]">
                  {t}
                </span>
              ))}
            </div>
          </div>
          {kind === "gd" ? (
            <p className="border-t border-[#3c574b] pt-5 text-[13px] leading-[1.65] text-[#adc4b8]">
              You set the topic, the time and who is at the table on the next step. Everyone speaks, and you get feedback on every contribution afterwards.
            </p>
          ) : (<>
          <ol className="flex flex-col gap-[18px] border-t border-[#3c574b] pt-5">
            {parts.map((part, i) => (
              <li key={i} className="flex items-center gap-3">
                <span className="h-[34px] w-[3px] shrink-0 rounded-sm" style={{ background: PART_COLOURS[i] }} />
                <span className="flex min-w-0 flex-1 flex-col gap-[5px]">
                  <span className="text-xs leading-[1.4] text-white">{part.t}</span>
                  <span className="text-[10px] leading-normal text-[#adc4b8]">
                    {part.who ? `${part.who.name.split(" ")[0]} · ${part.who.title.toLowerCase()}` : "Your panel"}
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-0.5 leading-normal">
                  <span className="text-xl text-[#c9f4c8]">{String(part.m).padStart(2, "0")}</span>
                  <span className="text-[8px] text-[#adc4b8]">MIN</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="flex items-start gap-2 text-[11px] leading-[1.6] text-[#adc4b8]">
            <Fig name="route" size={15} />
            <span>
              Planned from your topic + {minutes}-minute length. Follow-ups and handovers adapt to what you say. The final plan is confirmed on the next screen.
            </span>
          </p>
          </>)}
          <div className="flex flex-col gap-3">
            {kind === "gd" ? (
              <button
                type="button"
                onClick={openGd}
                className="start-plan flex h-[50px] w-full items-center justify-center gap-3 rounded-lg px-5 text-sm font-semibold"
              >
                Set up the discussion
                <Fig name="arrow-right-lg" size={17} />
              </button>
            ) : unfinished ? (
              <>
                <button
                  type="button"
                  onClick={continueIt}
                  className="start-plan flex h-[50px] w-full items-center justify-center gap-3 rounded-lg px-5 text-sm font-semibold"
                >
                  Continue your interview
                  <Fig name="arrow-right-lg" size={17} />
                </button>
                <button
                  type="button"
                  onClick={startPlan}
                  disabled={create.isPending}
                  className="h-9 w-full rounded-lg bg-transparent text-[12px] text-[#adc4b8] underline-offset-2 hover:text-white hover:underline disabled:opacity-50"
                >
                  {create.isPending ? "Building your plan…" : "Start a new one instead"}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={startPlan}
                disabled={create.isPending}
                className="start-plan flex h-[50px] w-full items-center justify-center gap-3 rounded-lg px-5 text-sm font-semibold disabled:opacity-50"
              >
                {create.isPending ? "Building your plan…" : "Start practice interview"}
                <Fig name="arrow-right-lg" size={17} />
              </button>
            )}
            <p className="text-center text-[10px] leading-normal text-[#adc4b8]">
              {kind === "gd"
                ? "Topic, time and panel are chosen on the next step"
                : `${pauses === 1 ? "One pause" : `${pauses} pauses`} of up to 5 minutes · ending early still gives you notes`}
            </p>
          </div>
        </section>

        {(personas.data ?? []).length > 0 && (
          <section className="flex flex-col gap-[18px] rounded-xl border border-line bg-surface p-[22px]" aria-label="Your interview panel">
            <div className="flex items-start justify-between">
              <h2 className="whitespace-nowrap text-sm font-semibold text-ink">Three perspectives. One panel.</h2>
              <Fig name="users-round" size={17} />
            </div>
            <ul className={`flex flex-col gap-[18px] ${allPersonas ? "max-h-72 overflow-y-auto pr-1" : ""}`}>
              {meetThree.map((persona, i) => (
                <li key={persona.id} className="flex items-center gap-2.5">
                  <span
                    className="grid size-8 shrink-0 place-items-center rounded-full text-[11px] text-[#192d28]"
                    style={{ background: AVATAR_COLOURS[i % AVATAR_COLOURS.length] }}
                  >
                    {initials(persona.name)}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                    <span className="text-xs font-semibold text-ink">{persona.name.split(" ")[0]}</span>
                    <span className="text-[11px] leading-[1.4] text-ink-soft">
                      {persona.title}
                      {persona.style ? ` · ${persona.style.split(/[.;]/)[0].toLowerCase()}` : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            {(personas.data ?? []).length > 3 && (
              <button
                type="button"
                aria-expanded={allPersonas}
                onClick={() => setAllPersonas((open) => !open)}
                className="flex items-start justify-between text-[11px] leading-normal text-brand"
              >
                {allPersonas ? "Show fewer" : `Explore all ${(personas.data ?? []).length} AI interviewers`}
                <Fig name="arrow-up-right" size={14} />
              </button>
            )}
          </section>
        )}

        <section className="rounded-xl border border-line bg-surface p-[22px]" aria-label="Your interviews">
          <h2 className="text-sm font-semibold text-ink">Your interviews</h2>
          {history.isLoading ? (
            <SkeletonRows label="Loading your interviews" rows={3} className="mt-4" />
          ) : (history.data ?? []).length === 0 ? (
            <p className="mt-3 text-[11px] text-ink-soft">Nothing yet. Each interview is listed here with its notes.</p>
          ) : (
            <ul className="mt-2">
              {(history.data ?? []).slice(0, 6).map((session) => (
                <HistoryRow key={session.id} session={session} />
              ))}
            </ul>
          )}
          <div className="mt-3 flex items-center justify-between text-[11px] font-semibold text-brand">
            <Link to="/mock/library">Your question library</Link>
            {(history.data ?? []).length > 6 && <Link to="/history">All your interviews</Link>}
          </div>
        </section>

        <p className="flex items-start gap-[9px] px-3 text-[11px] leading-[1.7] text-ink-soft">
          <Fig name="notebook-pen" size={16} />
          <span>After your round: detailed notes on every question, plus focused practice for the gaps.</span>
        </p>
      </aside>
    </div>
    </div>
  );
}
