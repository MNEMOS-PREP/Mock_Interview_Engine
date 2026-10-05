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
 */

import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  Button,
  ErrorNote,
  Icon,
  Skeleton,
  useInterviewerVoice,
  type InterviewerVoice,
} from "@ai/core";

import {
  useAnswer,
  useEnd,
  useFlag,
  useHint,
  useIdle,
  useMoveOn,
  usePause,
  useRepeat,
  useResume,
  useResumeState,
  useRetry,
  useSession,
  useStart,
} from "../api";
import { fillerCount, useDictation } from "../speech";
import { useInterviewStream } from "../stream";
import type { HintOffer, Session, TurnView } from "../types";
import { Face } from "../ui/Face";

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
}: {
  session: Session;
  waiting: boolean;
  connected: boolean;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
  busy: boolean;
  voice: Voice;
}) {
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
        <Avatar
          name={session.interviewer?.name ?? "Interviewer"}
          speaking={voice.speakingKey !== null}
          mouth={voice.mouth}
        />
        <span className="leading-tight">
          <span className="block text-sm font-medium text-ink">
            {session.interviewer?.name ?? "Your interviewer"}
            {session.interviewer?.title && (
              <span className="font-normal text-ink-faint"> · {session.interviewer.title}</span>
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
}: {
  name: string;
  size?: number;
  speaking?: boolean;
  mouth?: (now: number) => number;
}) {
  return <Face name={name} size={size} speaking={speaking} mouth={mouth} />;
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
}: {
  name: string;
  children: ReactNode;
  soft?: boolean;
  speaking?: boolean;
  mouth?: (now: number) => number;
}) {
  return (
    <div className="flex gap-3">
      <Avatar name={name} speaking={speaking} mouth={mouth} />
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-2xs font-medium text-ink-faint">{name}</p>
        <div className={`turn-interviewer mt-1 whitespace-pre-wrap ${soft ? "text-ink-soft" : ""}`}>
          {children}
        </div>
      </div>
    </div>
  );
}

function Turn({
  turn,
  interviewer,
  speaking = false,
  mouth,
}: {
  turn: TurnView;
  interviewer: string;
  speaking?: boolean;
  mouth?: (now: number) => number;
}) {
  if (turn.role === "candidate") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md border border-brand-line bg-brand-soft px-4 py-3">
          <p className="text-2xs font-medium text-brand">You</p>
          <p className="turn-candidate mt-1 whitespace-pre-wrap">{turn.text}</p>
        </div>
      </div>
    );
  }
  return (
    <Said name={interviewer} speaking={speaking} mouth={mouth}>
      {turn.text}
    </Said>
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
  const dictation = useDictation((phrase) => {
    if (!phrase) return;
    setDraft((current) => (current.trim() ? `${current.trimEnd()} ${phrase}` : phrase));
    setSpoken((current) => `${current} ${phrase}`);
  });
  const [preview, setPreview] = useState("");
  const [thinking, setThinking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const data = session.data;
  // Each line it speaks is measured and posted to M11's latency ledger
  // (`@ai/core` v0.15.0); the room adds the two marks only it knows. Since
  // v0.16.0 it speaks in the voice M11 casts for this interviewer when M11 is
  // running, and in the browser's own voice when it is not.
  const voice = useInterviewerVoice(data?.interviewer?.voice_id, {
    sessionId,
    personaId: data?.interviewer?.id,
  });
  const waiting =
    answer.isPending || start.isPending || retry.isPending || moveOn.isPending;

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
  const heard = useRef<Set<string> | null>(null);
  const idleHeard = useRef<string | null>(null);
  const lastTurnId = data?.transcript.at(-1)?.turn_id;
  useEffect(() => {
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
        const final = opening.at(-1);
        if (final) voice.speak(opening.map((turn) => turn.text).join(" "), final.turn_id);
      }
      return;
    }
    const fresh = lines.filter((turn) => !heard.current!.has(turn.turn_id));
    for (const turn of fresh) heard.current.add(turn.turn_id);
    const final = fresh.at(-1);
    if (final) {
      voice.speak(fresh.map((turn) => turn.text).join(" "), final.turn_id);
    } else if (idleKey && idleKey !== idleHeard.current && data.status === "live") {
      // EC-6.1's prompt is the interviewer talking too.
      voice.speak(data.idle_line!, "idle");
    }
    idleHeard.current = idleKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.transcript.length, lastTurnId, data?.idle_line, data?.idle_prompts]);

  // A pause is a pause: the voice stops with the clock.
  useEffect(() => {
    if (data?.status === "paused") voice.stop("pause");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.status]);

  // Under 800 ms nothing changes on screen (spec §8).
  useEffect(() => {
    if (!waiting) {
      setThinking(false);
      return;
    }
    const timer = window.setTimeout(() => setThinking(true), THINKING_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [waiting]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [data?.transcript.length, preview, thinking]);

  // §6.8: "Welcome back — we were on question 4". Said when this page joins a
  // session already under way (a reload) or the feed comes back after a drop
  // — never on a first start, where there is nothing to come back to.
  const [welcome, setWelcome] = useState<string | null>(null);
  const underWayAtLoad = useRef<boolean | null>(null);
  const everConnected = useRef(false);
  const dropped = useRef(false);
  if (data && underWayAtLoad.current === null) {
    underWayAtLoad.current =
      !justStarted && data.status === "live" && data.transcript.length > 0;
  }
  useEffect(() => {
    if (!connected) {
      if (everConnected.current) dropped.current = true;
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
  const [keptThinking, setKeptThinking] = useState(false);
  useEffect(() => setKeptThinking(false), [data?.open_turn_id]);
  useEffect(() => {
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
  const lastLine = [...data.transcript].reverse().find((turn) => turn.role === "interviewer")?.text ?? "";

  function submit() {
    const typed = draft.trim();
    if (!typed || !data?.open_turn_id) return;
    voice.stop("send");
    voice.mark("answer_sent");
    if (dictation.listening) dictation.stop();
    // Fenced, so the evaluator reads code as code rather than as prose.
    const text = codeMode ? "```\n" + draft.replace(/\s+$/, "") + "\n```" : typed;
    setDraft("");
    setSpoken("");
    setPreview("");
    answer.mutate({ question_turn_id: data.open_turn_id, text });
  }
  const fillers = spoken.trim() ? fillerCount(spoken) : null;

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      {data.status === "planned" ? (
        <section className="mx-auto max-w-xl py-10 text-center">
          {data.interviewer && (
            <div className="mb-6 flex flex-col items-center gap-3">
              <Avatar name={data.interviewer.name} size={56} />
              <p className="text-sm text-ink-soft">
                <span className="font-medium text-ink">{data.interviewer.name}</span> ·{" "}
                {data.interviewer.title}
              </p>
            </div>
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
                    ? `${data.interviewer.name} reads each question aloud — the speaker button turns that off. `
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
            {lastLine ? `${who} asks: ${lastLine}` : ""}
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
              return (
                <Fragment key={turn.turn_id}>
                  {crossed && title && <RoundRule title={title} />}
                  <Turn
                    turn={turn}
                    interviewer={who}
                    speaking={voice.speakingKey === turn.turn_id}
                    mouth={voice.mouth}
                  />
                </Fragment>
              );
            })}

            {preview && (
              <Said name={who} soft>
                {preview}
              </Said>
            )}

            {thinking && !preview && (
              <div className="flex gap-3" aria-hidden>
                <Avatar name={who} />
                <span className="mt-1 flex h-9 items-center gap-1.5 rounded-2xl rounded-tl-md bg-surface-sunken px-4">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </span>
              </div>
            )}

            {data.status === "live" && data.idle_line && (
              // EC-6.1: beside the question, not a new one — the answer box
              // still answers what was asked.
              <div role="status">
                <Said name={who} soft speaking={voice.speakingKey === "idle"} mouth={voice.mouth}>
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
                          voice.repeat(turn.text, "repeat");
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
                <span className="ml-auto hidden text-2xs text-ink-faint sm:inline">
                  Ctrl / ⌘ + Enter
                </span>
                <Button type="submit" disabled={!canAnswer || !draft.trim()}>
                  {data.in_closing ? "Ask" : "Answer"} →
                </Button>
              </div>
              </div>
              <p className="mt-2 text-center text-2xs text-ink-faint">
                {dictation.error
                  ? dictation.error
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
