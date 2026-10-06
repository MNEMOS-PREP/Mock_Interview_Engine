/**
 * The interview itself — spec §2.2 (the screen) and §8 (the states).
 *
 * What is deliberately absent is the design: no live score, no
 * correct/incorrect marker, no progress bar toward a grade. The question is
 * the largest thing on the page and the answer box is directly under it.
 *
 * The three states that had to be designed rather than defaulted:
 *   · under 800 ms after a submit — nothing changes on screen at all;
 *   · past that — three dots beside the interviewer, and no text, because
 *     "Thinking…" reads as a stall;
 *   · tokens arriving — the line writes itself, and is replaced by the text of
 *     record when `question.asked` lands (the guard may have swapped it).
 *
 * 2026-10-03: drawn as a conversation. The interviewer speaks beside their
 * avatar in the page's voice; the student's words sit in their own bubble on
 * the right; the header holds who is asking, the state, and the clock; the
 * answer box stays in reach at the bottom. Still no score, no marker, no bar.
 *
 * 2026-10-04: the student can SPEAK an answer (the browser's own speech
 * recognition, into the same box, editable before it is sent), switch the box
 * to code for a DSA question, and see where they are in the plan — warm-up,
 * the rounds, the closing — which is position, not performance. Pauses are one
 * per 15 planned minutes (FR-6.12, revised), and the button says how many are
 * left. The interviewer has a face rather than initials.
 *
 * 2026-10-05: the interviewer SPEAKS each line of record, in the voice
 * the persona file names (`useInterviewerVoice` — M11's, in `@ai/core` since
 * v0.14.0), and the face's mouth moves while it does. The line on screen is
 * still the line; the voice reads it. It stops when the mic opens, the answer
 * is sent or the session pauses, and one button turns it off for good.
 *
 * 2026-10-06: a PANEL. Each line says who said it, part by part — the opening
 * has every panelist say hello, a hand-over is the one leaving and the one
 * arriving — and each part is shown under its own speaker's name and face and
 * said in their own voice (`@ai/core` v0.17.0). The header shows the panel,
 * with whoever is speaking lit. Before this every line was labelled with the
 * CURRENT interviewer's name, so a hand-over relabelled the whole transcript.
 *
 * 2026-10-06: "Talk freely" (M11 day 3, `useListening`): the student may keep
 * the mic open and start speaking at any time — over the interviewer too,
 * who stops (barge-in, spec §6.5; Final Boss finishes up to 1.5 s first, once
 * a round) — and their words land in the box. Off unless they turn it on.
 * Where M11 can transcribe (day 4), the words in the box are its recogniser's
 * — Whisper, with the question as its prompt, so "Dijkstra" is Dijkstra — and
 * the browser's own recognition is the live caption while they speak; where
 * it cannot, the browser's words go in the box as before.
 *
 * Day 5 (`useTurnTaking`): the room knows when the student has FINISHED — a
 * silence as long as their own pauses run, then M11's turn model hearing
 * whether it sounds finished — and the answer is sent then, the way a spoken
 * interview works: nobody presses a button to stop talking. Without M11's
 * recogniser the words wait in the box for "Answer", as before.
 *
 * Days 11–12 (`spokenRoom.ts`): the interviewer answers no sooner than a
 * person would — the gap is the speaker's own, and Final Boss sometimes holds
 * a silence on purpose — and a fresh line appears as it is said, part by part,
 * so a hand-over reads as two people. While an answer runs the asker says
 * "okay" now and then (never in Final Boss); "let me note that down" is
 * followed by a pause. The room hears its own voice coming back (echo) and
 * says so; turning Talk freely off mid-answer keeps what was said. Hold to
 * talk is the student's choice, or the room's on a poor connection, after two
 * drops or repeated echo; two answers nobody could write down switch to
 * typing. With the student's say-so, spoken answers are kept for the notes.
 */

import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  Button,
  ErrorNote,
  Icon,
  Skeleton,
  isEcho,
  keepAnswerAudio,
  keepingAnswers,
  serverAsrAvailable,
  setKeepingAnswers,
  useInterviewerVoice,
  useTurnTaking,
  type AsrResult,
  type InterviewerVoice,
  type SpokenPart,
} from "@ai/core";

import {
  useAnswer,
  useEnd,
  useFlag,
  useHint,
  useIdle,
  useHeard,
  useMoveOn,
  usePause,
  usePersonas,
  useRepeat,
  useResume,
  useResumeState,
  useRetry,
  useSession,
  useStart,
} from "../api";
import { fillerCount, useDictation } from "../speech";
import {
  notBeforeFor,
  nowMs,
  poorConnection,
  useBackchannels,
  usePoorConnection,
  usePushToTalk,
  useReveal,
  useWarmBackchannels,
  type HeldTurn,
} from "../spokenRoom";
import { useInterviewStream } from "../stream";
import type { HintOffer, PersonaCard, Session, TurnPart, TurnView } from "../types";
import { Face, voiceKind } from "../ui/Face";

type Voice = InterviewerVoice;

/** A speaker, with sound waves when on and a stroke through it when off. */
function SpeakerIcon({ on }: { on: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M11 5 6 9H3v6h3l5 4V5Z" />
      {on ? (
        <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
      ) : (
        <path d="m22 9-6 6M16 9l6 6" />
      )}
    </svg>
  );
}

/** The voice's one control: on, off, or — when the browser held the sound
 *  back until a click — play. */
function VoiceToggle({ voice, name }: { voice: Voice; name: string }) {
  if (!voice.supported) return null;
  if (voice.blocked && voice.enabled)
    return (
      <Button size="sm" variant="secondary" onClick={voice.replay}>
        <SpeakerIcon on /> Hear {name}
      </Button>
    );
  return (
    <button
      type="button"
      onClick={() => voice.setEnabled(!voice.enabled)}
      aria-pressed={voice.enabled}
      aria-label="Interviewer's voice"
      title={
        voice.enabled
          ? `Reads each question aloud${voice.voiceName ? ` — ${voice.voiceName}` : ""}. Using a screen reader? You may prefer it off.`
          : "Read each question aloud"
      }
      className={`grid h-8 w-8 place-items-center rounded-lg ${
        voice.enabled ? "text-brand hover:bg-surface-sunken" : "text-ink-faint hover:bg-surface-sunken hover:text-ink"
      }`}
    >
      <SpeakerIcon on={voice.enabled} />
    </button>
  );
}

/** Below this a word is one the recogniser was unsure of (M11's asr.py). */
const UNSURE_WORD = 0.45;

/** What the recogniser was unsure of, as character ranges of the answer —
 *  its words are joined by single spaces, after whatever the box held. */
function unsureRanges(asr: AsrResult, offset: number): [number, number][] {
  const ranges: [number, number][] = [];
  let at = offset;
  for (const word of asr.words) {
    const end = at + word.word.length;
    if (word.confidence < UNSURE_WORD) {
      const last = ranges[ranges.length - 1];
      if (last && at - last[1] <= 1) last[1] = end;
      else ranges.push([at, end]);
    }
    at = end + 1;
  }
  return ranges;
}

/** A student's answer, with the words the recogniser was unsure of marked. */
function AnswerText({ turn }: { turn: TurnView }) {
  const ranges = turn.unsure ?? [];
  if (ranges.length === 0) return <>{turn.text}</>;
  const out: ReactNode[] = [];
  let at = 0;
  ranges.forEach(([start, end], i) => {
    if (start > at) out.push(turn.text.slice(at, start));
    out.push(
      <span
        key={i}
        className="underline decoration-dotted decoration-ink-faint underline-offset-4"
        title="The recogniser wasn't sure of these words, so they are never quoted back as yours."
      >
        {turn.text.slice(start, end)}
      </span>,
    );
    at = Math.max(at, end);
  });
  if (at < turn.text.length) out.push(turn.text.slice(at));
  return <>{out}</>;
}

/** "Talk freely" is remembered for this browser, like the voice switch. */
const TALK_FREELY_KEY = "m06.talkFreely";

function readTalkFreely(): boolean {
  try {
    return localStorage.getItem(TALK_FREELY_KEY) === "on";
  } catch {
    return false;
  }
}

/** How loud the student is, drawn per frame without re-rendering the room. */
function LevelMeter({ level }: { level: () => number }) {
  const bar = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let frame = 0;
    const draw = () => {
      if (bar.current) bar.current.style.transform = `scaleX(${Math.max(0.04, level()).toFixed(3)})`;
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [level]);
  return (
    <span aria-hidden className="inline-block h-1.5 w-10 overflow-hidden rounded-full bg-surface-sunken">
      <span ref={bar} className="block h-full origin-left rounded-full bg-session-listening" />
    </span>
  );
}

const THINKING_AFTER_MS = 800;
/** A drop shorter than this is a blip: no banner, as the server counts no
 *  reconnect for it either (presence.LOST_AFTER_S is 5 s). */
const LOST_BANNER_AFTER_MS = 1500;

function clock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The timer, announced at 10, 5 and 1 minute (spec §8, accessibility). */
function TimeRemaining({
  session,
  running,
}: {
  session: Session;
  running: boolean;
}) {
  const [left, setLeft] = useState(session.time_remaining_s);
  const announced = useRef<Set<number>>(new Set());
  const [announcement, setAnnouncement] = useState("");

  useEffect(
    () => setLeft(session.time_remaining_s),
    [session.time_remaining_s, session.status],
  );

  useEffect(() => {
    // §8: "Disconnected — timer paused". The server stops its clock too.
    if (session.status !== "live" || !running) return;
    const timer = window.setInterval(
      () => setLeft((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [session.status, running]);

  useEffect(() => {
    for (const minutes of [10, 5, 1]) {
      const mark = minutes * 60;
      if (left <= mark && left > mark - 60 && !announced.current.has(minutes)) {
        announced.current.add(minutes);
        setAnnouncement(
          `${minutes} minute${minutes === 1 ? "" : "s"} remaining`,
        );
      }
    }
  }, [left]);

  return (
    <>
      <span
        className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 font-mono text-xs tabular-nums ${
          left <= 60 ? "border-session-degraded text-session-degraded" : "border-line text-ink-soft"
        }`}
        title="Time remaining"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" strokeLinecap="round" />
        </svg>
        {clock(left)}
      </span>
      <span aria-live="polite" className="sr-only">
        {announcement}
      </span>
    </>
  );
}

function StatusStrip({
  session,
  waiting,
  connected,
  onPause,
  onResume,
  onEnd,
  busy,
  voice,
  panel,
  speakingId,
}: {
  session: Session;
  waiting: boolean;
  connected: boolean;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
  busy: boolean;
  voice: Voice;
  /** Everyone on the panel (FR-6.3), the lead first. */
  panel: PersonaCard[];
  /** Who is speaking now, or null. */
  speakingId: string | null;
}) {
  const asking = session.interviewer;
  const shown = panel.find((p) => p.id === speakingId) ?? asking;
  const tone =
    session.status === "paused"
      ? "bg-session-idle"
      : waiting
        ? "bg-session-thinking"
        : session.status === "live"
          ? "bg-session-listening"
          : "bg-session-idle";
  const label =
    session.status === "paused"
      ? "Paused"
      : session.status === "live"
        ? waiting
          ? "Reading your answer"
          : "Your turn"
        : session.status === "planned"
          ? "Not started"
          : "Finished";

  return (
    <div className="sticky top-16 z-20 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-line bg-surface/85 px-4 py-3 shadow-raised backdrop-blur-xl">
      <span className="flex items-center gap-3">
        {panel.length > 1 ? (
          <span
            className="flex items-center -space-x-2"
            role="img"
            aria-label={`Your panel: ${panel.map((p) => `${p.name}, ${p.title}`).join("; ")}`}
          >
            {panel.map((p) => (
              <span
                key={p.id}
                title={`${p.name} · ${p.title}`}
                className={`rounded-full ring-2 ${
                  p.id === (speakingId ?? asking?.id) ? "relative z-10 ring-brand" : "ring-surface opacity-80"
                }`}
              >
                <Avatar
                  name={p.name}
                  size={32}
                  kind={voiceKind(p.voice_id)}
                  speaking={p.id === speakingId}
                  mouth={p.id === speakingId ? voice.mouth : undefined}
                />
              </span>
            ))}
          </span>
        ) : (
          <Avatar
            name={asking?.name ?? "Interviewer"}
            kind={voiceKind(asking?.voice_id)}
            speaking={voice.speakingKey !== null}
            mouth={voice.mouth}
          />
        )}
        <span className="leading-tight">
          <span className="block text-sm font-medium text-ink">
            {shown?.name ?? "Your interviewer"}
            {shown?.title && (
              <span className="font-normal text-ink-faint"> · {shown.title}</span>
            )}
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 text-2xs text-ink-soft">
            <span
              className={`status-dot ${tone} ${session.status === "live" ? "status-dot-live" : ""}`}
              style={{ color: "var(--color-session-listening)" }}
              aria-hidden
            />
            {voice.speakingKey !== null ? "Speaking" : label}
          </span>
        </span>
      </span>
      <span className="rounded-full border border-line px-2.5 py-1 text-2xs text-ink-soft">
        {session.kind === "drill"
          ? "Defend drill · not scored"
          : `Question ${Math.max(session.questions_asked, 1)}${
              plannedQuestions(session) ? ` of about ${plannedQuestions(session)}` : ""
            }`}
        {session.kind !== "drill" &&
          roundTitle(session) &&
          ` · ${roundTitle(session)}`}
      </span>
      {(session.flags.degradation_level === "L3" ||
        session.flags.degradation_level === "panic") &&
        session.status === "live" && (
          // §8: a subtle badge, and the only sign of it. The questions keep
          // coming; they are simply not being phrased by a model.
          <span className="text-2xs text-session-degraded" role="status">
            Wrapping up a little early
          </span>
        )}
      <div className="ml-auto flex items-center gap-2">
        <VoiceToggle voice={voice} name={session.interviewer?.name ?? "the interviewer"} />
        <TimeRemaining session={session} running={connected} />
        {!connected && session.status === "live" && (
          <span
            className="text-2xs text-session-degraded"
            title="Reconnecting to the live feed"
          >
            offline
          </span>
        )}
        {session.status === "live" && !session.flags.pause_used && (
          <PauseButton
            onPause={onPause}
            busy={busy}
            left={Math.max(0, (session.flags.pauses_allowed ?? 1) - (session.flags.pauses_used ?? 0))}
          />
        )}
        {session.status === "paused" && (
          <Button size="sm" onClick={onResume} disabled={busy}>
            Resume
          </Button>
        )}
        {(session.status === "live" || session.status === "paused") && (
          <Button size="sm" variant="ghost" onClick={onEnd} disabled={busy}>
            End
          </Button>
        )}
      </div>
    </div>
  );
}

/** The interviewer's face. Personas have names ("Priya · Senior Engineer"),
 *  so the room has someone in it — drawn, not initials (ui/Face.tsx). */
function Avatar({
  name,
  size = 36,
  speaking = false,
  mouth,
  kind,
}: {
  name: string;
  size?: number;
  speaking?: boolean;
  mouth?: (now: number) => number;
  kind?: string;
}) {
  return <Face name={name} size={size} speaking={speaking} mouth={mouth} kind={kind} />;
}

/** The plan's question budget, summed — "about", because follow-ups and a
 *  replan move it. Null for a drill or before there is a plan. */
function plannedQuestions(session: Session): number | null {
  if (session.kind === "drill" || !session.plan) return null;
  const n = session.plan.segments
    .filter((s) => s.dropped_reason === null)
    .reduce((sum, s) => sum + s.question_budget, 0);
  return n > 0 ? n : null;
}

const STEP_LABEL: Record<string, string> = { warmup: "Warm-up", closing: "Your questions" };

/**
 * Where the student is in the plan (3.4): position, never performance. The
 * rounds are the plan's own, in order, with the current one lit.
 */
function Stepper({ session }: { session: Session }) {
  const segments = (session.plan?.segments ?? []).filter((s) => s.dropped_reason === null);
  if (segments.length < 2 || session.kind === "drill") return null;
  const at = segments.findIndex((s) => s.index === session.current_segment);
  return (
    <ol aria-label="Interview progress" className="mt-3 flex items-center gap-1.5 overflow-x-auto px-1 [scrollbar-width:none]">
      {segments.map((segment, i) => {
        const done = at >= 0 && i < at;
        const current = i === at;
        return (
          <li key={segment.index} className="flex shrink-0 items-center gap-1.5">
            {i > 0 && <span aria-hidden className={`h-px w-4 ${done || current ? "bg-brand" : "bg-line"}`} />}
            <span
              aria-current={current ? "step" : undefined}
              className={`inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-2xs font-medium ${
                current
                  ? "bg-brand text-white"
                  : done
                    ? "bg-brand-soft text-brand"
                    : "border border-line text-ink-faint"
              }`}
            >
              {done && <Icon name="check" size={11} />}
              {STEP_LABEL[segment.kind] ?? segment.title}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** One line from the interviewer, beside their avatar. */
function Said({
  name,
  children,
  soft = false,
  speaking = false,
  mouth,
  kind,
}: {
  name: string;
  children: ReactNode;
  soft?: boolean;
  speaking?: boolean;
  mouth?: (now: number) => number;
  kind?: string;
}) {
  return (
    <div className="flex gap-3">
      <Avatar name={name} speaking={speaking} mouth={mouth} kind={kind} />
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-2xs font-medium text-ink-faint">{name}</p>
        <div className={`turn-interviewer mt-1 whitespace-pre-wrap ${soft ? "text-ink-soft" : ""}`}>
          {children}
        </div>
      </div>
    </div>
  );
}

/** A part of an interviewer line, with what the student did not hear — they
 *  started speaking over it (M11's FR-11.9) — dimmed. The line stays whole:
 *  it is what was said. */
function HeardText({ text, index, turn }: { text: string; index: number; turn: TurnView }) {
  if (turn.heard === null || turn.heard === undefined) return <>{text}</>;
  const cutPart = turn.heard_part ?? 0;
  if (index < cutPart) return <>{text}</>;
  let upto = index > cutPart ? 0 : Math.round(text.length * turn.heard);
  // A word half-said is not heard.
  if (upto > 0 && upto < text.length && text[upto] !== " ") upto = Math.max(0, text.lastIndexOf(" ", upto));
  return (
    <>
      {text.slice(0, upto)}
      {index === cutPart && <span className="text-2xs text-ink-faint" title="You started speaking here"> ⟨you came in⟩ </span>}
      <span className="text-ink-faint">{text.slice(upto)}</span>
    </>
  );
}

/** An interviewer line as its voices said it: each part with its speaker. */
function partsOf(turn: TurnView, fallback: string | null): TurnPart[] {
  if (turn.parts && turn.parts.length > 0) return turn.parts;
  return [{ speaker_id: turn.speaker_id ?? fallback ?? "", text: turn.text }];
}

/** The room's name for one part of a line — what the voice reports back. */
function partKey(turn: TurnView, index: number): string {
  return `${turn.turn_id}:${index}`;
}

/** A line's parts as the room shows them: consecutive parts by one voice
 *  under one name — "let me note that down", a pause, then the question, is
 *  still one person talking. */
function byVoice(parts: TurnPart[]): { speaker_id: string; at: number[] }[] {
  const groups: { speaker_id: string; at: number[] }[] = [];
  parts.forEach((part, index) => {
    const last = groups[groups.length - 1];
    if (last && last.speaker_id === part.speaker_id) last.at.push(index);
    else groups.push({ speaker_id: part.speaker_id, at: [index] });
  });
  return groups;
}

function Turn({
  turn,
  nameOf,
  kindOf,
  fallback,
  speakingPart,
  mouth,
  shown = () => true,
}: {
  turn: TurnView;
  nameOf: (id: string) => string;
  kindOf: (id: string) => string | undefined;
  /** Who said a line that does not say (an event from before speakers). */
  fallback: string | null;
  /** The part being heard now, or null. */
  speakingPart: string | null;
  mouth?: (now: number) => number;
  /** Whether a part may be shown yet: a fresh line appears as it is said. */
  shown?: (partId: string) => boolean;
}) {
  if (turn.role === "candidate") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md border border-brand-line bg-brand-soft px-4 py-3">
          <p className="text-2xs font-medium text-brand">You</p>
          <p className="turn-candidate mt-1 whitespace-pre-wrap">
            <AnswerText turn={turn} />
          </p>
        </div>
      </div>
    );
  }
  const parts = partsOf(turn, fallback);
  const groups = byVoice(parts)
    .map((group) => ({ ...group, at: group.at.filter((index) => shown(partKey(turn, index))) }))
    .filter((group) => group.at.length > 0);
  if (groups.length === 0) return null;
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <Said
          key={partKey(turn, group.at[0]!)}
          name={nameOf(group.speaker_id)}
          kind={kindOf(group.speaker_id)}
          speaking={group.at.some((index) => speakingPart === partKey(turn, index))}
          mouth={mouth}
        >
          {group.at.map((index, n) => (
            <Fragment key={index}>
              {n > 0 && " "}
              <HeardText text={parts[index]!.text} index={index} turn={turn} />
            </Fragment>
          ))}
        </Said>
      ))}
    </div>
  );
}

/**
 * The `RoundTransition` of spec §15.5, as a rule rather than a card.
 *
 * §3.2.3 — "a hard cut from DSA to HR feels like a page load" — is answered
 * twice over, and deliberately not three times: the interviewer SAYS the
 * bridge ("Let's move to the next part: SQL"), and the transcript SHOWS where
 * one round ended. Drawing the spoken line again in a box would be the same
 * sentence twice on one screen, which reads as a bug.
 *
 * The title comes from the plan, so it is M02's words for the requirement.
 */
function RoundRule({ title }: { title: string }) {
  return (
    <div
      className="flex items-center gap-3 pt-2"
      role="separator"
      aria-label={`New round: ${title}`}
    >
      <span className="h-px flex-1 bg-line" />
      <span className="text-2xs uppercase tracking-wide text-ink-faint">
        {title}
      </span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

/**
 * The hint, with its price on it — FR-6.7, master plan §32.5.
 *
 * The deduction is M13's and it is shown BEFORE the hint is taken, because a
 * deduction discovered afterwards is a penalty and one published beforehand
 * is a choice. When there is no hint to give the button says why rather than
 * vanishing: a control that disappears reads as a bug, and "Final Boss runs
 * without hints" is a rule the student should know they are playing under.
 */
function HintButton({
  offer,
  busy,
  onTake,
}: {
  offer: HintOffer;
  busy: boolean;
  onTake: () => void;
}) {
  if (!offer.available) {
    return offer.unavailable_reason ? (
      <span className="text-2xs text-ink-faint">
        {offer.unavailable_reason}
      </span>
    ) : null;
  }
  const kept = Math.round(offer.credit * 100);
  return (
    <span className="flex items-center gap-2">
      <Button variant="secondary" size="sm" onClick={onTake} disabled={busy}>
        Hint
      </Button>
      <span className="text-2xs text-ink-faint">
        {kept < 100
          ? `this answer would then count for ${kept}%`
          : "no deduction for this one"}
        {offer.hints_left > 1 && ` · ${offer.hints_left} left`}
      </span>
    </span>
  );
}

/** The round the student is in, by M02's name for it — "Data structures",
 *  not "segment 2". None for the warm-up and the closing, which say so. */
function roundTitle(session: Session): string | null {
  const segment = session.plan?.segments.find(
    (s) => s.index === session.current_segment,
  );
  if (!segment || segment.kind === "warmup" || segment.kind === "closing")
    return null;
  return segment.title || null;
}

/** FR-6.12, revised: one pause per 15 planned minutes, five minutes each.
 *  Spending one is a choice, so it asks, and says how many are left. */
function PauseButton({
  onPause,
  busy,
  left,
}: {
  onPause: () => void;
  busy: boolean;
  left: number;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setAsking(true)}
        disabled={busy}
      >
        Pause{left > 1 ? ` (${left})` : ""}
      </Button>
    );
  }
  return (
    <span
      className="flex items-center gap-2"
      role="group"
      aria-label="Pause the interview"
    >
      <span className="text-2xs text-ink-soft">
        Up to 5 min, the clock stops ·{" "}
        {left - 1 === 0 ? "your last pause" : `${left - 1} left after this`}
      </span>
      <Button
        size="sm"
        onClick={() => {
          setAsking(false);
          onPause();
        }}
        disabled={busy}
      >
        Pause now
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
        Not yet
      </Button>
    </span>
  );
}

/** §7's ⚑: a question that is broken goes back to the bank's owner (M05). */
const FLAG_REASONS = ["Unclear", "Wrong or broken", "Not relevant to the role"];

export function InterviewStage({ sessionId }: { sessionId: string }) {
  const session = useSession(sessionId);
  const start = useStart(sessionId);
  const answer = useAnswer(sessionId);
  const pause = usePause(sessionId);
  const resume = useResume(sessionId);
  const end = useEnd(sessionId);
  const hint = useHint(sessionId);
  const retry = useRetry(sessionId);
  const moveOn = useMoveOn(sessionId);
  const idle = useIdle(sessionId);
  const repeat = useRepeat(sessionId);
  const heardLine = useHeard(sessionId);
  const flag = useFlag(sessionId);
  const [repeated, setRepeated] = useState<string | null>(null);
  const [flagging, setFlagging] = useState(false);
  const [flagged, setFlagged] = useState<string | null>(null);
  const resumeState = useResumeState(sessionId);
  const navigate = useNavigate();
  // The plan screen starts the session and then comes here; the session is
  // already live with its first question, which looks exactly like a reload.
  const justStarted = Boolean((useLocation().state as { justStarted?: boolean } | null)?.justStarted);

  const [draft, setDraft] = useState("");
  const [codeMode, setCodeMode] = useState(false);
  const [spoken, setSpoken] = useState("");
  /** Words into the answer box, after whatever is there. */
  const append = (words: string) => {
    if (!words) return;
    setDraft((current) => (current.trim() ? `${current.trimEnd()} ${words}` : words));
    setSpoken((current) => `${current} ${words}`);
  };
  // Day 4: while M11's recogniser writes the box, the browser's phrases are
  // held here — the fallback if the recogniser cannot answer.
  const serverWrites = useRef(false);
  const held = useRef<string[]>([]);
  const dictation = useDictation((phrase) => {
    if (!phrase) return;
    if (serverWrites.current) held.current.push(phrase);
    else append(phrase);
  });
  const [preview, setPreview] = useState("");
  const [thinking, setThinking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const data = session.data;
  // FR-6.3: who is on the panel, by the persona files' own cards.
  const personaCards = usePersonas();
  const cards = useMemo(
    () => new Map((personaCards.data ?? []).map((card) => [card.id, card])),
    [personaCards.data],
  );
  const panel = useMemo(() => {
    // The plan's panel (anyone sitting in included), then whoever a re-plan
    // has handed a part to since.
    const ids = [
      ...new Set([
        ...(data?.plan?.panel ?? []),
        ...(data?.plan?.segments ?? [])
          .filter((segment) => segment.dropped_reason === null && segment.persona_id)
          .map((segment) => segment.persona_id),
      ]),
    ];
    return ids.map((id) => cards.get(id)).filter((card): card is PersonaCard => card !== undefined);
  }, [data?.plan, cards]);
  const nameOf = (id: string) => cards.get(id)?.name ?? data?.interviewer?.name ?? "Interviewer";
  const kindOf = (id: string) => voiceKind(cards.get(id)?.voice_id ?? data?.interviewer?.voice_id);
  /** A line as the voice says it: each part in its own speaker's voice, with
   *  any quiet inside it — the note-taking pause (M11's FR-11.12). */
  const voiced = (turn: TurnView): SpokenPart[] =>
    partsOf(turn, data?.interviewer?.id ?? null).map((part, index) => ({
      text: part.text,
      personaId: part.speaker_id || null,
      voiceId: cards.get(part.speaker_id)?.voice_id ?? null,
      id: partKey(turn, index),
      ...(part.pause_after_ms ? { pauseAfterMs: part.pause_after_ms } : {}),
    }));
  // FR-11.17: a connection too poor for the open mic is too poor to fetch
  // every sentence's audio as well. Decided once, as the room opens — the
  // browser's own voice downloads nothing, and a voice never changes
  // mid-interview.
  const [poorAtStart] = useState(poorConnection);
  // Each line it speaks is measured and posted to M11's latency ledger
  // (`@ai/core` v0.15.0); the room adds the two marks only it knows. Since
  // v0.16.0 it speaks in the voice M11 casts for this interviewer when M11 is
  // running, and in the browser's own voice when it is not.
  const voice = useInterviewerVoice(data?.interviewer?.voice_id, {
    sessionId,
    personaId: data?.interviewer?.id,
    server: !poorAtStart,
  });
  // Spec §8: while the voice can be heard, a fresh line appears as it is said.
  const followVoice = voice.supported && voice.enabled && !voice.blocked;
  const reveal = useReveal(voice, followVoice);
  const waiting =
    answer.isPending || start.isPending || retry.isPending || moveOn.isPending;
  /** When the student last finished an answer: the interviewer's calibrated
   *  silence (FR-11.10) counts from there, not from when the line landed. */
  const answeredAt = useRef<number | null>(null);

  // M11 day 3: the mic open while the interviewer speaks, so the student can
  // start any time — and the interviewer stops when they do.
  const [talkFreely, setTalkFreelyState] = useState(readTalkFreely);
  const setTalkFreely = (on: boolean) => {
    setTalkFreelyState(on);
    try {
      localStorage.setItem(TALK_FREELY_KEY, on ? "on" : "off");
    } catch {
      /* still applies for this visit */
    }
  };
  // FR-11.17's ladder: hold to talk where the open mic cannot work — the
  // student's choice, or the room's on a poor connection, after two drops,
  // or when the mic keeps hearing the interviewer. `ladder` says why.
  const [holdToTalk, setHoldToTalk] = useState(false);
  const [ladder, setLadder] = useState<string | null>(null);
  const poor = usePoorConnection();
  // Final Boss contests a barge-in once a round (§6.5); these rounds have.
  const contested = useRef(new Set<number>());
  // Day 4: M11's recogniser, if it can run.
  const [serverAsr, setServerAsr] = useState(false);
  useEffect(() => {
    void serverAsrAvailable().then(setServerAsr);
  }, []);
  const freeMic = talkFreely && !holdToTalk;
  serverWrites.current = (freeMic || holdToTalk) && serverAsr;
  // FR-11.19: whether the student chose to keep their spoken answers.
  const [keep, setKeep] = useState(keepingAnswers);
  const [keepNote, setKeepNote] = useState<string | null>(null);
  // EC-11.8, EC-11.9: what the room noticed about the mic, said once.
  const [micNote, setMicNote] = useState<string | null>(null);
  /** EC-11.9's "didn't catch that", said by the asker — not on the record:
   *  nothing was answered, so nothing is judged. */
  const [askedAgain, setAskedAgain] = useState<{ who: string; text: string } | null>(null);
  const echoes = useRef(0);
  const unheard = useRef(0);
  // The box's text, read by a turn that ends after this render.
  const draftNow = useRef("");
  draftNow.current = draft;
  const lastAsked = () =>
    [...(data?.transcript ?? [])].reverse().find((turn) => turn.role === "interviewer");
  /** The question being answered: the recogniser's prompt. */
  const askedNow = () => {
    const asked = lastAsked();
    return asked?.question_text ?? asked?.text;
  };
  /** The student came in over the interviewer, who stops — and where they
   *  came in goes on the record: the part being heard ("turn:part") and how
   *  far through it (FR-11.9). */
  const comeIn = (startedAt: number) => {
    if (!data) return;
    const round = data.current_segment;
    const contest = data.mode === "final_boss" && !contested.current.has(round);
    const onCut = (cut: { key: string; partId: string | null; heard: number }) => {
      const [turnId, part] = (cut.partId ?? `${cut.key}:0`).split(":");
      heardLine.mutate({ turn_id: turnId!, part_index: Number(part ?? 0) || 0, heard: cut.heard });
    };
    if (voice.bargeIn(startedAt, { contest, onCut }) && contest) contested.current.add(round);
  };
  /** EC-11.9, spec §6.9: an answer the recogniser could not write down.
   *  Twice running, and the room switches to typing for now. */
  const missed = () => {
    unheard.current += 1;
    if (unheard.current < 2) {
      const id = lastAsked()?.speaker_id ?? data?.interviewer?.id ?? "";
      const card = cards.get(id);
      const line = card?.didnt_catch ?? "Sorry, I didn't catch that. Could you say it again?";
      setAskedAgain({ who: id, text: line });
      voice.speak([{ text: line, personaId: id || null, voiceId: card?.voice_id ?? null }], "didnt_catch");
      return;
    }
    setAskedAgain(null);
    unheard.current = 0;
    setTalkFreelyState(false); // for now, not as the student's preference
    setHoldToTalk(false);
    setLadder("Switching to typing for now — the voice service couldn't write down your last two answers.");
  };
  /** A spoken answer, either way of speaking. "switch" is the student turning
   *  the mic off mid-answer to type (FR-11.14): what they said so far goes in
   *  the box and waits for them. */
  const takeTurn = (turn: HeldTurn, how: "end" | "switch") => {
    if (dictation.listening) dictation.stop();
    const browserWords = held.current.join(" ");
    held.current = [];
    const long = turn.endedAt - turn.startedAt;
    if (turn.text === null) {
      // No recogniser: the browser's words stay in the box for "Answer".
      append(browserWords);
      if (serverAsr && !browserWords && long > 1500) missed();
      return;
    }
    if (!turn.text) {
      // Heard as speech, written as nothing: a cough — unless it went on.
      if (long > 2500) missed();
      return;
    }
    unheard.current = 0;
    if (how === "switch") {
      append(turn.text);
      return;
    }
    // EC-11.8: the interviewer's own words, back through the speakers.
    if (isEcho(turn.text, lastAsked()?.text ?? "")) {
      echoes.current += 1;
      if (echoes.current >= 2) {
        setHoldToTalk(true);
        setLadder(
          "Your mic keeps picking up the interviewer's voice, so it's hold-to-talk for now. With headphones you can talk freely again.",
        );
      } else {
        setMicNote("That sounded like the interviewer's own voice coming back through your mic — headphones fix it.");
      }
      return;
    }
    const full = draftNow.current.trim() ? `${draftNow.current.trimEnd()} ${turn.text}` : turn.text;
    const open = data?.status === "live" && Boolean(data.open_turn_id) && !waiting && !codeMode;
    // How sure the recogniser was, and of which words (FR-11.15/11.16):
    // M06 asks again rather than judging words nobody could make out.
    const note = turn.asr
      ? {
          mean_confidence: turn.asr.mean_confidence,
          unsure: unsureRanges(turn.asr, full.length - turn.text.length),
          model: turn.asr.model,
          language: turn.asr.language,
        }
      : undefined;
    const audio = turn.audio ? { audio: turn.audio, startedAt: turn.startedAt, endedAt: turn.endedAt } : undefined;
    if (open) submit(full, turn.endedAt, note, audio);
    else append(turn.text);
  };
  // FR-11.11: while an answer runs, the asker says "okay" now and then.
  const backchannel = useBackchannels({
    enabled: freeMic && data?.mode !== "final_boss",
    voice,
    asker: () => {
      const id = lastAsked()?.speaker_id ?? data?.interviewer?.id;
      return id ? cards.get(id) : undefined;
    },
  });
  useWarmBackchannels(
    freeMic &&
      data?.status === "live" &&
      data.mode !== "final_boss" &&
      voice.tier === "server" &&
      voice.speakingKey === null,
    panel,
  );
  // Day 5: a spoken turn, start to finish — and the answer sent at its end.
  const listening = useTurnTaking({
    enabled: freeMic && data?.status === "live",
    playing: voice.isSpeaking,
    context: askedNow,
    onTurn: (turn) => takeTurn(turn, turn.how === "switch" ? "switch" : "end"),
    onPause: backchannel,
    onSpeechStart: (startedAt) => {
      if (!data) return;
      comeIn(startedAt);
      // Their words go in the box, as if they had pressed the mic.
      const open = data.status === "live" && Boolean(data.open_turn_id) && !waiting;
      if (open && !codeMode && dictation.supported && !dictation.listening) dictation.start();
    },
  });
  // FR-11.17: hold to talk — one answer per hold, sent when it is let go,
  // and the interviewer stops when the button goes down.
  const ptt = usePushToTalk({
    enabled: holdToTalk && serverAsr && data?.status === "live",
    context: askedNow,
    onPress: (at) => {
      comeIn(at);
      // FR-11.18: the live caption while they hold — the browser's own
      // recognition; M11's words replace it when they let go.
      if (!codeMode && dictation.supported && !dictation.listening) dictation.start();
    },
    onTurn: (turn) => takeTurn(turn, "end"),
  });
  // A poor connection moves the open mic to hold-to-talk, once, and says why.
  useEffect(() => {
    if (!poor || !talkFreely || holdToTalk) return;
    setHoldToTalk(true);
    setLadder(
      "Your connection looks slow, so it's hold-to-talk for now: hold the button while you speak, and let go when you're done.",
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poor, talkFreely]);

  const { connected } = useInterviewStream(
    data?.status === "live" ? sessionId : undefined,
    {
      onToken: (text) => {
        voice.mark("first_token");
        setPreview((current) => current + text);
      },
      onEvent: (event) => {
        // The text of record has landed; the preview has served its purpose.
        if (event.kind === "question.asked" || event.kind === "session.ended")
          setPreview("");
        session.refetch();
      },
    },
  );

  // The interviewer says each new line of record — never the streaming
  // preview, which the guard may still replace. On arrival what was already
  // said stays said: a reload does not read the interview back. A session
  // started from the plan screen is the exception — its opening was asked as
  // the student arrived, so the lines since the student last spoke are said.
  //
  // M11 day 11: not before a person would answer (FR-11.10) — the gap after
  // the student's last word is the first speaker's own, from their patience,
  // and in Final Boss sometimes longer on purpose — and each part appears as
  // it is said. A layout effect, so a held part is never painted first.
  const heard = useRef<Set<string> | null>(null);
  const idleHeard = useRef<string | null>(null);
  const lastTurnId = data?.transcript.at(-1)?.turn_id;
  const say = (lines: TurnView[]) => {
    const final = lines.at(-1);
    if (!final || !data) return;
    const first = partsOf(lines[0]!, data.interviewer?.id ?? null)[0];
    const notBefore = notBeforeFor(answeredAt.current, final, cards.get(first?.speaker_id ?? ""), data.mode);
    answeredAt.current = null;
    const parts = lines.flatMap(voiced);
    reveal.hold(
      parts.map((part) => part.id!),
      notBefore,
    );
    voice.speak(parts, final.turn_id, { notBefore });
  };
  useLayoutEffect(() => {
    if (!data) return;
    const lines = data.transcript.filter((turn) => turn.role === "interviewer");
    const idleKey = data.idle_line ? `${data.open_turn_id}:${data.idle_prompts}` : null;
    if (heard.current === null) {
      heard.current = new Set(lines.map((turn) => turn.turn_id));
      idleHeard.current = idleKey;
      if (justStarted && data.status === "live") {
        const lastStudent = data.transcript.map((turn) => turn.role).lastIndexOf("candidate");
        const opening = data.transcript
          .slice(lastStudent + 1)
          .filter((turn) => turn.role === "interviewer");
        say(opening);
      }
      return;
    }
    const fresh = lines.filter((turn) => !heard.current!.has(turn.turn_id));
    for (const turn of fresh) heard.current.add(turn.turn_id);
    if (fresh.length > 0) {
      say(fresh);
    } else if (idleKey && idleKey !== idleHeard.current && data.status === "live") {
      // EC-6.1's prompt is the interviewer talking too.
      voice.speak(data.idle_line!, "idle");
    }
    idleHeard.current = idleKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.transcript.length, lastTurnId, data?.idle_line, data?.idle_prompts]);

  // EC-11.13: "students background the tab and then miss the question".
  // The voice carries on in a hidden tab; when they come back to a line said
  // while they were away, the room says so, once, with the way to hear it.
  const [awayNote, setAwayNote] = useState<string | null>(null);
  const away = useRef<{ at: number; lines: number; speaking: boolean } | null>(null);
  const linesNow = useRef(0);
  linesNow.current = data?.transcript.filter((turn) => turn.role === "interviewer").length ?? 0;
  const speakingNow = useRef(false);
  speakingNow.current = voice.speakingKey !== null;
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        away.current = { at: Date.now(), lines: linesNow.current, speaking: speakingNow.current };
        return;
      }
      const was = away.current;
      away.current = null;
      if (!was || Date.now() - was.at < 2000) return;
      if (linesNow.current > was.lines || was.speaking) {
        setAwayNote(
          "You were in another tab while the interviewer was speaking — the question is just above, and \"Repeat the question\" says it again.",
        );
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  useEffect(() => setAwayNote(null), [data?.questions_asked, data?.transcript.length]);

  // A pause is a pause: the voice stops with the clock.
  useEffect(() => {
    if (data?.status === "paused") voice.stop("pause");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.status]);

  // Under 800 ms nothing changes on screen (spec §8). A line waiting on its
  // voice past the silence meant for it is the same wait, so the dots stay
  // on across the hand-off rather than blinking out and back.
  const busy = waiting || reveal.overdue;
  useEffect(() => {
    if (!busy) {
      const timer = window.setTimeout(() => setThinking(false), 60);
      return () => window.clearTimeout(timer);
    }
    if (thinking) return;
    const timer = window.setTimeout(() => setThinking(true), THINKING_AFTER_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [data?.transcript.length, preview, thinking, reveal.version]);

  // §6.8: "Welcome back — we were on question 4". Said when this page joins a
  // session already under way (a reload) or the feed comes back after a drop
  // — never on a first start, where there is nothing to come back to.
  const [welcome, setWelcome] = useState<string | null>(null);
  const underWayAtLoad = useRef<boolean | null>(null);
  const everConnected = useRef(false);
  const dropped = useRef(false);
  const drops = useRef(0);
  if (data && underWayAtLoad.current === null) {
    underWayAtLoad.current =
      !justStarted && data.status === "live" && data.transcript.length > 0;
  }
  useEffect(() => {
    if (!connected) {
      if (everConnected.current) {
        dropped.current = true;
        drops.current += 1;
        // FR-11.17, spec §6.9: two drops and the open mic gives way to
        // hold-to-talk — one upload per answer survives a poor line.
        if (drops.current === 2 && talkFreely && !holdToTalk) {
          setHoldToTalk(true);
          setLadder(
            "The connection keeps dropping, so it's hold-to-talk for now: hold the button while you speak, and let go when you're done.",
          );
        }
      }
      return;
    }
    const returning =
      dropped.current || (!everConnected.current && underWayAtLoad.current);
    everConnected.current = true;
    dropped.current = false;
    if (!returning) return;
    // After the stream is back, so the return it reports is on the log.
    resumeState
      .refetch()
      .then((result) => setWelcome(result.data?.welcome ?? null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);
  useEffect(() => setWelcome(null), [data?.questions_asked]);

  // §8: "Lost connection — reconnecting…", after a moment, so a blip the
  // server does not count as a disconnect does not flash a banner either.
  const [lost, setLost] = useState(false);
  useEffect(() => {
    if (connected || data?.status !== "live" || !everConnected.current) {
      setLost(false);
      return;
    }
    const timer = window.setTimeout(() => setLost(true), LOST_BANNER_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [connected, data?.status]);

  // EC-6.1: the interviewer's patience, counted from the last keystroke —
  // typing is not silence, which is why the browser says when and the server
  // only decides what. Each prompt restarts the count for the next; after the
  // offer to move on there are no more.
  //
  // Speaking is not silence either, and neither is the question still being
  // said. A live run (2026-10-06) heard "Take your time." the moment a
  // student finished a spoken answer: the count had run through the
  // question's own synthesis and the whole answer, because only keystrokes
  // reset it. Now it starts when the interviewer stops and the student is
  // quiet, and any speech starts it again.
  const studentBusy =
    listening.speaking || listening.deciding || listening.writing || ptt.held || ptt.sending;
  const interviewerTalking = voice.speakingKey !== null || reveal.overdue;
  const [keptThinking, setKeptThinking] = useState(false);
  useEffect(() => setKeptThinking(false), [data?.open_turn_id]);
  useEffect(() => {
    setMicNote(null);
    setAskedAgain(null);
    setRepeated(null);
    setFlagged(null);
    setFlagging(false);
    setCodeMode(false);
  }, [data?.questions_asked]);
  useEffect(() => {
    if (
      !data ||
      data.status !== "live" ||
      !data.open_turn_id ||
      !data.interviewer
    )
      return;
    if (data.idle_offered || !connected) return;
    if (studentBusy || interviewerTalking) return;
    const body = {
      question_turn_id: data.open_turn_id,
      n: data.idle_prompts + 1,
    };
    const timer = window.setTimeout(
      () => idle.mutate(body, { onError: () => undefined }),
      data.interviewer.idle_after_s * 1000,
    );
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    data?.open_turn_id,
    data?.idle_prompts,
    data?.idle_offered,
    data?.status,
    connected,
    draft,
    studentBusy,
    interviewerTalking,
  ]);

  const notices = useMemo(
    () => [
      ...Object.values(data?.flags.degraded ?? {}),
      ...(data?.connection_note ? [data.connection_note] : []),
    ],
    [data],
  );

  if (session.isLoading) {
    return (
      <div className="mx-auto max-w-(--container-conversation) space-y-6" role="status" aria-label="Opening the interview">
        <Skeleton className="h-16 w-full rounded-2xl" />
        <div className="flex gap-3">
          <Skeleton className="h-9 w-9 shrink-0 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-5 w-4/5" />
            <Skeleton className="h-5 w-3/5" />
          </div>
        </div>
        <Skeleton className="h-36 w-full rounded-2xl" />
      </div>
    );
  }
  if (session.isError || !data) {
    return (
      <ErrorNote
        message="That interview could not be opened."
        detail={
          session.error instanceof Error ? session.error.message : undefined
        }
        onRetry={() => session.refetch()}
      />
    );
  }

  const canAnswer =
    data.status === "live" && Boolean(data.open_turn_id) && !waiting;
  const who = data.interviewer?.name ?? "Interviewer";
  // What a screen reader hears when the interviewer speaks: the newest line,
  // in a polite live region. The transcript itself is not live — announcing
  // the whole conversation on every change would bury the question.
  const lastTurn = [...data.transcript].reverse().find((turn) => turn.role === "interviewer");
  const lastLine = lastTurn?.text ?? "";
  const lastAsker = lastTurn?.speaker_id ? nameOf(lastTurn.speaker_id) : who;
  // Whose face is lit: the part being heard says who is speaking.
  const partSpeaker = new Map(
    data.transcript.flatMap((turn) =>
      turn.role === "interviewer"
        ? partsOf(turn, data.interviewer?.id ?? null).map(
            (part, index) => [partKey(turn, index), part.speaker_id] as const,
          )
        : [],
    ),
  );
  const speakingId =
    (voice.speakingPart && partSpeaker.get(voice.speakingPart)) ||
    (voice.speakingKey !== null ? (data.interviewer?.id ?? null) : null);

  /** Send the answer: what is in the box — or, at the end of a spoken turn,
   *  everything said (`spoken`), which the box has not caught up with yet. */
  function submit(
    spoken?: string,
    speechEndedAt?: number,
    asr?: {
      mean_confidence: number;
      unsure: [number, number][];
      model?: string | null;
      language?: string | null;
    },
    audio?: { audio: Blob; startedAt: number; endedAt: number },
  ) {
    const typed = (spoken ?? draft).trim();
    if (!typed || !data?.open_turn_id || (spoken === undefined && listening.writing)) return;
    voice.stop("send");
    voice.mark("answer_sent", speechEndedAt);
    answeredAt.current = speechEndedAt ?? nowMs();
    setAskedAgain(null);
    if (dictation.listening) dictation.stop();
    // Fenced, so the evaluator reads code as code rather than as prose.
    const text = codeMode && spoken === undefined ? "```\n" + draft.replace(/\s+$/, "") + "\n```" : typed;
    setDraft("");
    setSpoken("");
    setPreview("");
    answer.mutate(
      { question_turn_id: data.open_turn_id, text, ...(asr ? { asr } : {}) },
      {
        onSuccess: (after) => {
          // FR-11.19: kept only with the student's say-so, beside the turn
          // it answered, on the clock it was said on.
          if (!audio || !keep) return;
          const turnId = after.transcript.filter((turn) => turn.role === "candidate").at(-1)?.turn_id;
          if (!turnId) return;
          keepAnswerAudio(sessionId, turnId, audio.audio, {
            startedAt: audio.startedAt,
            endedAt: audio.endedAt,
          })
            .then(() => setKeepNote(null))
            .catch(() => setKeepNote("That answer's audio couldn't be kept. Your words are saved as usual."));
        },
      },
    );
  }
  const fillers = spoken.trim() ? fillerCount(spoken) : null;

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      {data.status === "planned" ? (
        <section className="mx-auto max-w-xl py-10 text-center">
          {panel.length > 1 ? (
            // FR-6.3: a panel — who the student is about to meet, in the
            // order they will meet them.
            <div className="mb-6 flex flex-col items-center gap-3">
              <div className="flex items-end justify-center gap-4">
                {panel.map((p) => (
                  <div key={p.id} className="flex w-24 flex-col items-center gap-2">
                    <Avatar name={p.name} size={48} kind={voiceKind(p.voice_id)} />
                    <p className="text-center text-2xs leading-tight text-ink-soft">
                      <span className="block font-medium text-ink">{p.name}</span>
                      {p.title}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-2xs text-ink-faint">Your panel</p>
            </div>
          ) : (
            data.interviewer && (
              <div className="mb-6 flex flex-col items-center gap-3">
                <Avatar
                  name={data.interviewer.name}
                  size={56}
                  kind={voiceKind(data.interviewer.voice_id)}
                />
                <p className="text-sm text-ink-soft">
                  <span className="font-medium text-ink">{data.interviewer.name}</span> ·{" "}
                  {data.interviewer.title}
                </p>
              </div>
            )
          )}
          <h1 className="text-3xl font-semibold tracking-tight text-ink">
            {data.kind === "drill"
              ? "Defend one line from your resume"
              : "Ready when you are"}
          </h1>
          {data.drill_claim && (
            <blockquote className="mt-4 border-l-2 border-brand-line bg-brand-soft/40 p-3 text-sm text-ink">
              {data.drill_claim}
            </blockquote>
          )}
          <p className="mt-4 text-sm leading-relaxed text-ink-soft">
            {data.kind === "drill"
              ? "Two minutes, typed, and not scored. I'll ask you to defend it and stop as soon as we reach the edge."
              : `About ${data.requested_minutes} minutes. ${
                  voice.supported && data.interviewer
                    ? panel.length > 1
                      ? "Each of them speaks in their own voice — the speaker button turns that off. "
                      : `${data.interviewer.name} reads each question aloud — the speaker button turns that off. `
                    : ""
                }Speak or type your answers. You can pause ${
                  (data.flags.pauses_allowed ?? 1) === 1 ? "once" : `${data.flags.pauses_allowed} times`
                }, and ending early still gives you notes.`}
          </p>
          <div className="mt-6">
            <Button onClick={() => start.mutate()} disabled={start.isPending}>
              {start.isPending ? "Starting…" : "Start"}
            </Button>
          </div>
        </section>
      ) : (
        <>
          <h1 className="sr-only">Interview with {who}</h1>
          <p className="sr-only" aria-live="polite">
            {lastLine ? `${lastAsker} asks: ${lastLine}` : ""}
          </p>
          <StatusStrip
            session={data}
            waiting={waiting}
            connected={connected}
            busy={pause.isPending || resume.isPending || end.isPending}
            onPause={() => pause.mutate()}
            onResume={() => resume.mutate()}
            onEnd={() => {
              voice.stop("end");
              end.mutate("ended_by_student");
            }}
            voice={voice}
            panel={panel}
            speakingId={speakingId}
          />
          <Stepper session={data} />

          {lost && (
            <p
              className="mt-3 rounded-lg border border-line bg-surface-sunken px-3 py-2 text-2xs text-session-degraded"
              role="status"
            >
              Lost connection — reconnecting… The clock is paused until you're
              back.
            </p>
          )}
          {!lost && welcome && (
            <p
              className="mt-3 rounded-lg border border-brand-line bg-brand-soft/40 px-3 py-2 text-sm text-ink"
              role="status"
            >
              {welcome}
            </p>
          )}

          {data.drill_claim && (
            <p className="mt-3 text-2xs text-ink-faint">
              Defending:{" "}
              <span className="text-ink-soft">{data.drill_claim}</span>
            </p>
          )}

          <div className="mt-6 space-y-6">
            {data.transcript.map((turn, index) => {
              const previous = data.transcript[index - 1];
              // A rule is drawn where the segment changes, never before the
              // first turn: the interview opening is not a round ending.
              const crossed =
                previous !== undefined &&
                previous.segment_index !== turn.segment_index;
              const title = data.plan?.segments.find(
                (segment) => segment.index === turn.segment_index,
              )?.title;
              // A round's rule appears with its first words, not before.
              const showing =
                turn.role !== "interviewer" ||
                partsOf(turn, data.interviewer?.id ?? null).some((_, i) => reveal.shown(partKey(turn, i)));
              return (
                <Fragment key={turn.turn_id}>
                  {crossed && title && showing && <RoundRule title={title} />}
                  <Turn
                    turn={turn}
                    nameOf={nameOf}
                    kindOf={kindOf}
                    fallback={data.interviewer?.id ?? null}
                    speakingPart={voice.speakingPart}
                    mouth={voice.mouth}
                    shown={reveal.shown}
                  />
                </Fragment>
              );
            })}

            {/* The line writing itself — unless the voice is to be heard,
                when it appears as it is said instead. */}
            {preview && !followVoice && (
              <Said name={who} soft kind={voiceKind(data.interviewer?.voice_id)}>
                {preview}
              </Said>
            )}

            {thinking && (!preview || followVoice) && (
              <div className="flex gap-3" aria-hidden>
                <Avatar name={who} kind={voiceKind(data.interviewer?.voice_id)} />
                <span className="mt-1 flex h-9 items-center gap-1.5 rounded-2xl rounded-tl-md bg-surface-sunken px-4">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </span>
              </div>
            )}

            {data.status === "live" && askedAgain && (
              <div role="status">
                <Said
                  name={nameOf(askedAgain.who)}
                  soft
                  kind={kindOf(askedAgain.who)}
                  speaking={voice.speakingKey === "didnt_catch"}
                  mouth={voice.mouth}
                >
                  {askedAgain.text}
                </Said>
              </div>
            )}

            {data.status === "live" && data.idle_line && (
              // EC-6.1: beside the question, not a new one — the answer box
              // still answers what was asked.
              <div role="status">
                <Said
                  name={who}
                  soft
                  kind={voiceKind(data.interviewer?.voice_id)}
                  speaking={voice.speakingKey === "idle"}
                  mouth={voice.mouth}
                >
                  {data.idle_line}
                </Said>
              </div>
            )}
            {data.status === "live" && data.idle_offered && !keptThinking && (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  size="sm"
                  onClick={() => moveOn.mutate()}
                  disabled={waiting}
                >
                  {data.in_closing ? "Wrap up" : "Move on"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setKeptThinking(true)}
                >
                  Keep thinking
                </Button>
              </div>
            )}
            <div ref={bottom} />
          </div>

          {notices.length > 0 && (
            <ul className="mt-6 space-y-1">
              {notices.map((note) => (
                <li key={note} className="text-2xs text-session-degraded">
                  {note}
                </li>
              ))}
            </ul>
          )}

          {data.status === "live" && data.plan_notes.length > 0 && (
            // §6.4: the newest change only, and only what changed — the why
            // is in the notes afterwards.
            <p className="mt-4 text-2xs text-ink-faint" role="status">
              {data.plan_notes[data.plan_notes.length - 1]}
            </p>
          )}

          {data.status === "live" && data.retry_offered ? (
            // §15.4: the interviewer asked; the student chooses. Two buttons,
            // because a typed "yes" would be judged as an answer.
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button onClick={() => retry.mutate()} disabled={waiting}>
                Try it again
              </Button>
              <Button
                variant="ghost"
                onClick={() => moveOn.mutate()}
                disabled={waiting}
              >
                Move on
              </Button>
              <span className="text-2xs text-ink-faint">
                Practice only. Your first attempt is the one that counts.
              </span>
            </div>
          ) : data.status === "live" || data.status === "paused" ? (
            <form
              className="sticky bottom-4 z-10 mt-8"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <label htmlFor="answer" className="sr-only">
                Your answer
              </label>
              <div className="overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-raised focus-within:border-brand">
              <textarea
                id="answer"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey))
                    submit();
                  // In code mode Tab indents, as in an editor. Escape leaves
                  // the box first, so keyboard users are never trapped.
                  if (codeMode && event.key === "Tab" && !event.shiftKey) {
                    event.preventDefault();
                    const el = event.currentTarget;
                    const { selectionStart: s, selectionEnd: e } = el;
                    const next = `${draft.slice(0, s)}  ${draft.slice(e)}`;
                    setDraft(next);
                    requestAnimationFrame(() => el.setSelectionRange(s + 2, s + 2));
                  }
                  if (event.key === "Escape") event.currentTarget.blur();
                }}
                spellCheck={!codeMode}
                disabled={!canAnswer}
                rows={codeMode ? 8 : 4}
                maxLength={8000}
                placeholder={
                  data.status === "paused"
                    ? "Paused — resume to keep going."
                    : !canAnswer
                      ? "One sec…"
                      : data.in_closing
                        ? "Ask anything — the team, the work, what happens next. Or just say that's all."
                        : codeMode
                          ? "Write your code. Tab indents; Esc leaves the box."
                          : dictation.supported
                            ? "Speak with the mic, or type. Say what you'd say out loud."
                            : "Type your answer. Say what you'd say out loud."
                }
                className={`block w-full resize-none bg-transparent px-4 pt-4 pb-2 text-ink outline-none placeholder:text-ink-faint focus-visible:shadow-none disabled:opacity-60 ${
                  codeMode ? "font-mono text-[0.8125rem] leading-6" : "text-[0.9375rem] leading-relaxed"
                }`}
              />
              {dictation.listening && (
                <p className="flex items-center gap-2 px-4 pb-2 text-2xs text-ink-soft" role="status">
                  <span aria-hidden className="status-dot status-dot-live bg-session-listening" style={{ color: "var(--color-session-listening)" }} />
                  Listening{dictation.interim ? `: ${dictation.interim}` : " — speak your answer"}
                </p>
              )}
              {holdToTalk && serverAsr && (
                // FR-11.17, spec §6.9: "a big hold-to-talk button, a visible
                // upload progress, and the same interviewer behaviour".
                <div className="border-t border-line px-3 py-3">
                  <button
                    type="button"
                    disabled={!canAnswer || !ptt.active || ptt.sending}
                    onPointerDown={(event) => {
                      event.currentTarget.setPointerCapture(event.pointerId);
                      ptt.press();
                    }}
                    onPointerUp={ptt.release}
                    onPointerCancel={ptt.release}
                    onKeyDown={(event) => {
                      if ((event.key === " " || event.key === "Enter") && !event.repeat) {
                        event.preventDefault();
                        ptt.press();
                      }
                    }}
                    onKeyUp={(event) => {
                      if (event.key === " " || event.key === "Enter") {
                        event.preventDefault();
                        ptt.release();
                      }
                    }}
                    aria-pressed={ptt.held}
                    className={`flex h-14 w-full touch-none select-none items-center justify-center gap-3 rounded-xl text-sm font-semibold disabled:opacity-50 ${
                      ptt.held ? "bg-session-listening text-white" : "bg-brand-soft text-brand hover:brightness-95"
                    }`}
                  >
                    <Icon name="mic" size={18} />
                    {ptt.sending
                      ? "Sending your answer…"
                      : ptt.held
                        ? "Listening — let go when you're done"
                        : !ptt.active
                          ? "Opening the microphone…"
                          : "Hold to talk"}
                    {ptt.held && <LevelMeter level={ptt.level} />}
                  </button>
                  {ptt.sending && (
                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-sunken" role="progressbar" aria-label="Sending your answer">
                      <div className="h-full w-1/3 animate-pulse rounded-full bg-brand" />
                    </div>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
                {dictation.supported && !codeMode && (
                  <button
                    type="button"
                    onClick={() => {
                      if (dictation.listening) return dictation.stop();
                      // The student starting to speak is the interviewer's cue
                      // to stop — the part of barge-in a browser can do.
                      voice.stop("mic");
                      dictation.start();
                    }}
                    disabled={!canAnswer}
                    aria-pressed={dictation.listening}
                    aria-label={dictation.listening ? "Stop speaking" : "Speak your answer"}
                    title={dictation.listening ? "Stop" : "Speak your answer"}
                    className={`grid h-8 w-8 place-items-center rounded-lg disabled:opacity-40 ${
                      dictation.listening
                        ? "bg-session-listening text-white"
                        : "text-ink-soft hover:bg-surface-sunken hover:text-ink"
                    }`}
                  >
                    <Icon name="mic" size={16} />
                  </button>
                )}
                {voice.supported && (
                  <button
                    type="button"
                    onClick={() => {
                      if (freeMic) {
                        // Type instead: what was said so far goes in the box.
                        listening.flush();
                        setTalkFreely(false);
                        return;
                      }
                      setTalkFreely(true);
                      setHoldToTalk(false);
                      setLadder(null);
                      echoes.current = 0;
                    }}
                    aria-pressed={freeMic}
                    title={
                      freeMic
                        ? `The mic stays open: start speaking any time, even over the interviewer.${
                            serverAsr
                              ? ` When you finish, what you said is written down by the voice service's recogniser and sent as your answer; ${
                                  keep ? "the audio is kept for your notes." : "the audio is not kept."
                                }`
                              : " Your words go in the box; press Answer when you are done."
                          } Headphones keep their voice out of your mic. Turn this off to type instead — what you've said so far stays in the box.`
                        : "Keep the mic open, so you can start speaking any time — even over the interviewer"
                    }
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-2xs font-medium ${
                      freeMic ? "bg-brand-soft text-brand" : "text-ink-soft hover:bg-surface-sunken hover:text-ink"
                    }`}
                  >
                    Talk freely
                    {freeMic && listening.active && <LevelMeter level={listening.level} />}
                  </button>
                )}
                {voice.supported && serverAsr && (
                  <button
                    type="button"
                    onClick={() => {
                      if (holdToTalk) {
                        setHoldToTalk(false);
                        setLadder(null);
                        return;
                      }
                      if (freeMic) listening.flush();
                      setHoldToTalk(true);
                      setLadder(null);
                    }}
                    aria-pressed={holdToTalk}
                    title={
                      holdToTalk
                        ? "Hold the big button while you speak and let go when you're done — the answer is sent then. Turn this off to talk freely or type."
                        : "Speak only while you hold a button: for a slow connection, a noisy room, or speakers without headphones"
                    }
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-2xs font-medium ${
                      holdToTalk ? "bg-brand-soft text-brand" : "text-ink-soft hover:bg-surface-sunken hover:text-ink"
                    }`}
                  >
                    Hold to talk
                  </button>
                )}
                {serverAsr && (freeMic || holdToTalk) && (
                  <label
                    className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2 text-2xs text-ink-soft hover:bg-surface-sunken hover:text-ink"
                    title="Keeps the audio of each spoken answer so you can hear yourself in the notes afterwards. Only you — and the platform's staff — can play it back, and you can delete it from the notes at any time."
                  >
                    <input
                      type="checkbox"
                      checked={keep}
                      onChange={(event) => {
                        setKeep(event.target.checked);
                        setKeepingAnswers(event.target.checked);
                      }}
                      className="accent-(--color-brand)"
                    />
                    Keep my answers
                  </label>
                )}
                {!data.in_closing && (
                  <button
                    type="button"
                    onClick={() => {
                      if (dictation.listening) dictation.stop();
                      setCodeMode((on) => !on);
                    }}
                    disabled={!canAnswer}
                    aria-pressed={codeMode}
                    title={codeMode ? "Back to a written answer" : "Answer with code"}
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-2xs font-medium disabled:opacity-40 ${
                      codeMode ? "bg-brand-soft text-brand" : "text-ink-soft hover:bg-surface-sunken hover:text-ink"
                    }`}
                  >
                    <Icon name="code" size={15} />
                    Code
                  </button>
                )}
                {!data.in_closing && (
                  <HintButton
                    offer={data.hint}
                    busy={hint.isPending || !canAnswer}
                    onTake={() => hint.mutate()}
                  />
                )}
                {!data.in_closing && canAnswer && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      repeat.mutate(undefined, {
                        onSuccess: (turn) => {
                          setRepeated(turn.text);
                          // In the voice of whoever asked it — an expert who
                          // came in asks their own question again.
                          const asker = lastTurn?.speaker_id ?? data.interviewer?.id ?? null;
                          voice.repeat(
                            [
                              {
                                text: turn.text,
                                personaId: asker,
                                voiceId: (asker && cards.get(asker)?.voice_id) || null,
                              },
                            ],
                            "repeat",
                          );
                        },
                      })
                    }
                    disabled={repeat.isPending}
                  >
                    Repeat the question
                  </Button>
                )}
                {!data.in_closing && canAnswer && !flagged && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setFlagging((v) => !v)}
                    aria-label="Flag this question as broken or unclear"
                  >
                    ⚑ Flag
                  </Button>
                )}
                <span className="ml-auto hidden text-2xs text-ink-faint xl:inline">
                  Ctrl / ⌘ + Enter
                </span>
                <span className="ml-auto xl:ml-0">
                  <Button type="submit" disabled={!canAnswer || !draft.trim() || listening.writing}>
                    {listening.writing ? "Writing it down…" : `${data.in_closing ? "Ask" : "Answer"} →`}
                  </Button>
                </span>
              </div>
              </div>
              <p className="mt-2 text-center text-2xs text-ink-faint">
                {dictation.error
                  ? dictation.error
                  : freeMic && listening.error
                    ? listening.error
                  : holdToTalk && ptt.error
                    ? ptt.error
                  : ladder
                    ? ladder
                  : awayNote
                    ? awayNote
                  : micNote
                    ? micNote
                  : keepNote
                    ? keepNote
                  : fillers && fillers.total > 0
                    ? `You said ${fillers.total} filler word${fillers.total === 1 ? "" : "s"} (${fillers.top.join(", ")}) — worth noticing, not a mark.`
                    : "There is no score on this screen — the notes come at the end."}
              </p>
              {repeated && (
                // §7: verbatim — the words that were asked, nearest the box.
                <p
                  className="mt-3 turn-interviewer whitespace-pre-wrap text-ink-soft"
                  role="status"
                >
                  {repeated}
                </p>
              )}
              {flagging && data.open_turn_id && (
                <div
                  className="mt-3 flex flex-wrap items-center gap-2"
                  role="group"
                  aria-label="Why flag it"
                >
                  {FLAG_REASONS.map((reason) => (
                    <Button
                      key={reason}
                      size="sm"
                      variant="secondary"
                      disabled={flag.isPending}
                      onClick={() =>
                        flag.mutate(
                          { question_turn_id: data.open_turn_id!, reason },
                          {
                            onSuccess: (out) => {
                              setFlagging(false);
                              setFlagged(
                                out.forwarded
                                  ? "Thanks — flagged. It won't be picked for anyone again until it's fixed."
                                  : "Recorded here — the question bank was unreachable, so it hasn't been excluded yet.",
                              );
                            },
                            onError: () => {
                              setFlagging(false);
                              setFlagged(
                                "This one comes from the backup set, so there's no bank entry to flag.",
                              );
                            },
                          },
                        )
                      }
                    >
                      {reason}
                    </Button>
                  ))}
                </div>
              )}
              {flagged && (
                <p className="mt-2 text-2xs text-ink-faint" role="status">
                  {flagged}
                </p>
              )}
              {answer.isError && (
                <div className="mt-3">
                  <ErrorNote
                    message="That answer didn't go through."
                    detail={
                      answer.error instanceof Error
                        ? answer.error.message
                        : undefined
                    }
                    onRetry={() => answer.reset()}
                  />
                </div>
              )}
            </form>
          ) : (
            <section className="mt-10 rounded-2xl border border-brand-line bg-brand-soft p-6 text-center">
              <h2 className="text-lg font-semibold text-ink">
                {data.end_reason === "system_failure"
                  ? "That one's on us."
                  : data.kind === "drill"
                    ? "That's the drill."
                    : "That's time."}
              </h2>
              <p className="mt-1 text-sm text-ink-soft">
                Your notes are ready — what was asked, how far each question
                went, and where it stopped.
              </p>
              <div className="mt-5 flex justify-center gap-2">
                <Button onClick={() => navigate(`/mock/${sessionId}/report`)}>
                  See the notes
                </Button>
                <Link
                  to="/mock"
                  className="inline-flex items-center rounded-lg px-3 py-1.5 text-sm text-ink-soft hover:text-ink"
                >
                  Not now
                </Link>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
