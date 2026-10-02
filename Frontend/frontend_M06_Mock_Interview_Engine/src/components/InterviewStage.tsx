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
 */

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button, ErrorNote, Spinner } from "@ai/core";

import {
  useAnswer,
  useEnd,
  useHint,
  useIdle,
  useMoveOn,
  usePause,
  useResume,
  useResumeState,
  useRetry,
  useSession,
  useStart,
} from "../api";
import { useInterviewStream } from "../stream";
import type { HintOffer, Session, TurnView } from "../types";

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
        className="font-mono text-2xs tabular-nums text-ink-soft"
        title="Time remaining"
      >
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
}: {
  session: Session;
  waiting: boolean;
  connected: boolean;
  onPause: () => void;
  onResume: () => void;
  onEnd: () => void;
  busy: boolean;
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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line pb-3">
      <span className="flex items-center gap-2 text-sm text-ink">
        <span className={`status-dot ${tone}`} aria-hidden />
        {label}
      </span>
      {session.interviewer && (
        <span className="text-2xs text-ink-soft">
          {session.interviewer.name}
          <span className="text-ink-faint"> · {session.interviewer.title}</span>
        </span>
      )}
      <span className="text-2xs text-ink-faint">
        {session.kind === "drill"
          ? "Defend drill · not scored"
          : `Question ${Math.max(session.questions_asked, 1)}`}
      </span>
      <div className="ml-auto flex items-center gap-2">
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
          <Button size="sm" variant="ghost" onClick={onPause} disabled={busy}>
            Pause
          </Button>
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

function Turn({ turn }: { turn: TurnView }) {
  if (turn.role === "candidate") {
    return <p className="turn-candidate whitespace-pre-wrap">{turn.text}</p>;
  }
  return <p className="turn-interviewer whitespace-pre-wrap">{turn.text}</p>;
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
  const resumeState = useResumeState(sessionId);
  const navigate = useNavigate();

  const [draft, setDraft] = useState("");
  const [preview, setPreview] = useState("");
  const [thinking, setThinking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const data = session.data;
  const waiting =
    answer.isPending || start.isPending || retry.isPending || moveOn.isPending;

  const { connected } = useInterviewStream(
    data?.status === "live" ? sessionId : undefined,
    {
      onToken: (text) => setPreview((current) => current + text),
      onEvent: (event) => {
        // The text of record has landed; the preview has served its purpose.
        if (event.kind === "question.asked" || event.kind === "session.ended")
          setPreview("");
        session.refetch();
      },
    },
  );

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
      data.status === "live" && data.transcript.length > 0;
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

  if (session.isLoading) return <Spinner label="Opening the interview…" />;
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

  function submit() {
    const text = draft.trim();
    if (!text || !data?.open_turn_id) return;
    setDraft("");
    setPreview("");
    answer.mutate({ question_turn_id: data.open_turn_id, text });
  }

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      {data.status === "planned" ? (
        <section>
          <h1 className="text-xl font-semibold tracking-tight">
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
              : `About ${data.requested_minutes} minutes, typed. You can pause once, and ending early still gives you notes.`}
          </p>
          <div className="mt-6">
            <Button onClick={() => start.mutate()} disabled={start.isPending}>
              {start.isPending ? "Starting…" : "Start"}
            </Button>
          </div>
        </section>
      ) : (
        <>
          <StatusStrip
            session={data}
            waiting={waiting}
            connected={connected}
            busy={pause.isPending || resume.isPending || end.isPending}
            onPause={() => pause.mutate()}
            onResume={() => resume.mutate()}
            onEnd={() => end.mutate("ended_by_student")}
          />

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

          <div className="mt-6 space-y-5">
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
                  <Turn turn={turn} />
                </Fragment>
              );
            })}

            {preview && (
              <p className="turn-interviewer whitespace-pre-wrap text-ink-soft">
                {preview}
              </p>
            )}

            {thinking && !preview && (
              <p className="flex items-center gap-1.5" aria-hidden>
                <span className="thinking-dot" />
                <span className="thinking-dot" />
                <span className="thinking-dot" />
              </p>
            )}

            {data.status === "live" && data.idle_line && (
              // EC-6.1: beside the question, not a new one — the answer box
              // still answers what was asked.
              <p
                className="turn-interviewer whitespace-pre-wrap text-ink-soft"
                role="status"
              >
                {data.idle_line}
              </p>
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
              className="mt-8"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <label htmlFor="answer" className="sr-only">
                Your answer
              </label>
              <textarea
                id="answer"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey))
                    submit();
                }}
                disabled={!canAnswer}
                rows={5}
                maxLength={8000}
                placeholder={
                  data.status === "paused"
                    ? "Paused — resume to keep going."
                    : !canAnswer
                      ? "One sec…"
                      : data.in_closing
                        ? "Ask anything — the team, the work, what happens next. Or just say that's all."
                        : "Type your answer. Say what you'd say out loud."
                }
                className="w-full resize-y rounded-lg border border-line bg-surface p-3 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none disabled:bg-surface-sunken"
              />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={!canAnswer || !draft.trim()}>
                  {data.in_closing ? "Ask" : "Answer"}
                </Button>
                {!data.in_closing && (
                  <HintButton
                    offer={data.hint}
                    busy={hint.isPending || !canAnswer}
                    onTake={() => hint.mutate()}
                  />
                )}
                <span className="text-2xs text-ink-faint">
                  Ctrl or ⌘ + Enter sends. There is no score on this screen —
                  the notes come at the end.
                </span>
              </div>
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
            <section className="mt-8 rounded-xl border border-line bg-surface p-5">
              <h2 className="text-sm font-semibold text-ink">
                {data.kind === "drill" ? "That's the drill." : "That's time."}
              </h2>
              <p className="mt-1 text-sm text-ink-soft">
                Your notes are ready — what was asked, how far each question
                went, and where it stopped.
              </p>
              <div className="mt-4 flex gap-2">
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
