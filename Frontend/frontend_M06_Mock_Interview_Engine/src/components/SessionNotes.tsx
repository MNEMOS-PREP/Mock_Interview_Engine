/**
 * The notes after a session — FR-6.18, and the Phase 1 shape of spec §15.7.
 *
 * There is no score here, because there is not one yet: M13's evaluations
 * arrive on day 4 and stay un-displayable until they are calibrated against
 * human raters. What a student gets instead is the ladder — what was asked,
 * how far it went, and where the reasoning stopped holding — which is the
 * thing the module actually measured.
 *
 * "Where it stopped" is phrased as a finding, never as a failure: the spec's
 * whole argument about the graceful exit is that the same data can be
 * delivered as "that was tough but fair" or as "that was brutal".
 *
 * 2026-10-03: the end of a session is a moment, so it opens like one — what
 * was done, counted (questions, follow-ups held, minutes, hints), and where to
 * go next. And M13's "not reached" list arrives as key-point ids (`kp_3`), at
 * times with the statement attached; a student was shown the ids. They are
 * read back to the statements this same report lists under "what a strong
 * answer covers", by position, and an id with no statement is left out rather
 * than printed.
 *
 * 2026-10-04 — "how did I do?" gets an answer per question: a band (Strong /
 * Partly there / Not yet) from the share of the strong answer's key points the
 * answer reached, which this report already lists — never a number, which
 * stays behind M13's calibration gate. Each question offers the next step:
 * practise that topic as a focused interview, and see how the answer was
 * marked (M13's evidence page). And the notes can be shared, as text the
 * student copies or sends themselves — nothing is published for them.
 *
 * 2026-10-06 — M11's FR-11.19: a spoken answer the student chose to keep
 * plays back beside its words ("you rarely know how you sound until you hear
 * it"), and every kept answer of the interview can be deleted from here.
 *
 * 2026-10-24 — a correct, a vague and a wrong answer looked alike: the band
 * above existed only for scored questions, the status was a grey phrase, and
 * every question carried the same green ✓ box. Each question now leads with
 * its STATUS (`report._status`: the interview's judgement of the whole
 * thread, eight of them, each a colour AND a shape — `notes.ts`), then the
 * student's own answer, what held, what was missing or wrong, the correct
 * idea, the rubric marked point by point, one strong answer and what to
 * practise. The band survives only as the evaluator's view, flagged when it
 * disagrees with the status. The explanations are written after the session
 * (`notes_writer.py`) and checked against the student's words; until they
 * are ready the page polls and shows what the interview recorded.
 */

import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Card,
  EmptyState,
  ErrorNote,
  Icon,
  SkeletonRows,
  forgetKeptAnswers,
  keptAnswerUrl,
  keptAnswers,
  type KeptAnswer,
} from "@ai/core";

import { WRITEUP_POLL_MAX, m06Keys, useReport, useStar } from "../api";
import { missingStatements, topicName } from "../bands";
import {
  STATUS_META,
  STATUS_ORDER,
  bandConflict,
  correction,
  firstAnswer,
  gaps,
  idealAnswer,
  needsWork,
  nextSteps,
  strengths,
} from "../notes";
import type { QuestionReport, ReportSummary, SessionReport } from "../types";
import { StatusBadge, StatusIcon } from "./Status";

/** The notes as plain text, for the student to send where they choose. */
function summaryText(data: SessionReport): string {
  const lines = [
    `My mock interview — ${data.questions.length} question${data.questions.length === 1 ? "" : "s"}, ${Math.round(data.minutes_used)} minutes`,
    "",
  ];
  data.questions.forEach((q, i) => {
    lines.push(`${i + 1}. ${q.question}`);
    lines.push(`   ${q.status_label ?? "Not marked"}${topicName(q) ? ` · ${topicName(q)}` : ""}`);
  });
  lines.push("", "Practised on AI Interviewer.");
  return lines.join("\n");
}

function ShareButton({ data }: { data: SessionReport }) {
  const [done, setDone] = useState<string | null>(null);
  const share = async () => {
    const text = summaryText(data);
    try {
      if (navigator.share) {
        await navigator.share({ title: "My mock interview", text });
        setDone("Shared");
      } else {
        await navigator.clipboard.writeText(text);
        setDone("Copied — paste it wherever you like");
      }
    } catch {
      setDone(null); // the student closed the share sheet
    }
  };
  return (
    <button
      type="button"
      onClick={share}
      className="inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm text-ink-soft hover:bg-surface-sunken hover:text-ink"
      title="Copies a short summary: the questions and how each went. Nothing is posted for you."
    >
      <Icon name="send" size={15} />
      {done ?? "Share a summary"}
    </button>
  );
}

/** FR-11.19: the spoken answers M11 kept for this interview — none when the
 *  student kept none, or M11 is not running. */
function useKept(sessionId: string) {
  return useQuery({
    queryKey: ["m11", "kept", sessionId],
    queryFn: () => keptAnswers(sessionId).catch(() => [] as KeptAnswer[]),
    staleTime: 60_000,
  });
}

/** One kept answer, played as it was said. */
function HearIt({ sessionId, turnId, label = "Hear it" }: { sessionId: string; turnId: string; label?: string }) {
  const [state, setState] = useState<"idle" | "loading" | "playing" | "failed">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(
    () => () => {
      audio.current?.pause();
      if (audio.current) URL.revokeObjectURL(audio.current.src);
    },
    [],
  );
  const toggle = async () => {
    if (state === "playing") {
      audio.current?.pause();
      setState("idle");
      return;
    }
    setState("loading");
    try {
      if (!audio.current) {
        audio.current = new Audio(await keptAnswerUrl(sessionId, turnId));
        audio.current.onended = () => setState("idle");
      }
      audio.current.currentTime = 0;
      await audio.current.play();
      setState("playing");
    } catch {
      setState("failed");
    }
  };
  return (
    <button
      type="button"
      onClick={toggle}
      title="Your answer, as you said it"
      className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium text-ink-soft hover:bg-surface-sunken hover:text-ink"
    >
      <span aria-hidden>{state === "playing" ? "■" : "▶"}</span>
      {state === "playing" ? "Stop" : state === "loading" ? "Loading…" : state === "failed" ? "Couldn't play it" : label}
    </button>
  );
}

/** Every kept answer of the interview, deleted at once — the files, not
 *  just the list (M11 removes them). Asked once more before it happens. */
function KeptAnswers({ sessionId, count }: { sessionId: string; count: number }) {
  const client = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const forget = async () => {
    setBusy(true);
    try {
      await forgetKeptAnswers(sessionId);
      await client.invalidateQueries({ queryKey: ["m11", "kept", sessionId] });
      setAsking(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <p className="mt-2 flex flex-wrap items-center gap-2 text-sm leading-relaxed text-ink-soft">
      {count === 1 ? "One spoken answer is" : `${count} spoken answers are`} kept, because you chose to
      keep them — only you and the platform's staff can play them.
      {asking ? (
        <span className="inline-flex items-center gap-2">
          <button
            type="button"
            onClick={forget}
            disabled={busy}
            className="rounded-lg border border-line px-2 py-0.5 text-xs font-medium text-ink hover:border-line-strong"
          >
            {busy ? "Deleting…" : `Delete ${count === 1 ? "it" : `all ${count}`}`}
          </button>
          <button type="button" onClick={() => setAsking(false)} className="text-xs text-ink-faint hover:text-ink">
            Keep them
          </button>
        </span>
      ) : (
        <button type="button" onClick={() => setAsking(true)} className="text-xs font-medium text-brand hover:underline">
          Delete the recordings
        </button>
      )}
      {failed && <span className="text-xs text-session-degraded">That didn't go through — try again.</span>}
    </p>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-4">
      <h4 className="text-2xs font-semibold uppercase tracking-wide text-ink-faint">{title}</h4>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}

/** "Your words" — the student's own quote under a point, never anyone else's. */
function Said({ text }: { text?: string }) {
  if (!text) return null;
  return <p className="mt-0.5 text-2xs leading-relaxed text-ink-soft">You said “{text}”</p>;
}

/** The strong answer's points, each reached or not — the rubric with the
 *  items that applied marked (the Gradescope pattern), in a neutral frame:
 *  until 2026-10-24 this was a green box of ✓ marks on every question,
 *  wrong ones included. */
function KeyPoints({ question }: { question: QuestionReport }) {
  const points = question.key_points?.length
    ? question.key_points
    : question.strong_answer_covers.map((statement) => ({ statement, covered: null }));
  if (!points.length) return null;
  return (
    <Section title="What a strong answer covers">
      <ul className="space-y-1.5">
        {points.map((point) => (
          <li key={point.statement} className="flex gap-2 text-sm leading-relaxed text-ink">
            <span
              className={
                point.covered === true
                  ? "mt-0.5 text-confirmed"
                  : point.covered === false
                    ? "mt-0.5 text-contested"
                    : "mt-0.5 text-ink-faint"
              }
            >
              <StatusIcon icon={point.covered === true ? "check" : point.covered === false ? "cross" : "dash"} />
            </span>
            <span>
              {point.statement}
              <span className="sr-only">
                {point.covered === true ? " — you covered this" : point.covered === false ? " — not covered" : ""}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** How the answers went across the interview — a distribution, never a score
 *  — and the few things to take away first. */
function Overview({ data }: { data: SessionReport }) {
  const counts = data.summary?.status_counts ?? {};
  const shown = STATUS_ORDER.filter((status) => counts[status]);
  const total = shown.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
  if (!total) return null;
  const focus = data.summary?.focus ?? [];
  const repeated = data.summary?.repeated_misconceptions ?? [];
  const described = shown
    .map((status) => `${counts[status]} ${STATUS_META[status].label.toLowerCase()}`)
    .join(", ");
  return (
    <section aria-labelledby="overview-title" className="mt-5 rounded-2xl border border-line bg-surface p-5">
      <h2 id="overview-title" className="text-sm font-semibold text-ink">
        How your answers went
      </h2>
      <div
        role="img"
        aria-label={described}
        className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-surface-sunken"
      >
        {shown.map((status) => (
          <span
            key={status}
            className={STATUS_META[status].bar}
            style={{ width: `${(100 * (counts[status] ?? 0)) / total}%` }}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-soft">
        {shown.map((status) => (
          <li key={status} className="inline-flex items-center gap-1.5">
            <span className={STATUS_META[status].badge.split(" ").find((c) => c.startsWith("text-"))}>
              <StatusIcon icon={STATUS_META[status].icon} />
            </span>
            {counts[status]} {STATUS_META[status].label.toLowerCase()}
          </li>
        ))}
      </ul>
      {(focus.length > 0 || repeated.length > 0) && (
        <div className="mt-4 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
          {focus.length > 0 && (
            <div>
              <h3 className="text-2xs font-semibold uppercase tracking-wide text-ink-faint">Work on first</h3>
              <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-sm leading-relaxed text-ink">
                {focus.slice(0, 3).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            </div>
          )}
          {repeated.length > 0 && (
            <div>
              <h3 className="text-2xs font-semibold uppercase tracking-wide text-ink-faint">
                Came up more than once
              </h3>
              <ul className="mt-1.5 space-y-1 text-sm leading-relaxed text-ink">
                {repeated.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** The rest of the interview in brief — held, corrected, said, claimed. */
function More({ summary }: { summary: ReportSummary }) {
  const blocks: [string, string[]][] = [
    ["Held up", summary.held],
    ["Corrected along the way", summary.corrected],
    ["Claims to back up", summary.unsupported_claims],
    ["How each topic went", summary.topics],
    ["How you said it", summary.communication],
  ];
  const shown = blocks.filter(([, lines]) => lines.length > 0);
  if (!shown.length) return null;
  return (
    <section className="mt-3 grid gap-3 sm:grid-cols-2" aria-label="More about this interview">
      {shown.map(([title, lines]) => (
        <div key={title} className="rounded-xl border border-line bg-surface p-4">
          <h3 className="text-2xs font-semibold uppercase tracking-wide text-ink-faint">{title}</h3>
          <ul className="mt-2 space-y-1.5">
            {lines.map((line) => (
              <li key={line} className="text-sm leading-relaxed text-ink">
                {line}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

/** For a resume line: what the interview found about the claim itself. */
function ClaimFindings({ question }: { question: QuestionReport }) {
  const unsupported = question.unsupported ?? [];
  const contradictions = question.contradictions ?? [];
  if (!question.claim_check && !unsupported.length && !contradictions.length) return null;
  const resumeLine = question.source === "m01_probe";
  return (
    <Section title={resumeLine ? "About this line on your resume" : "Claims in your answer"}>
      {question.claim_check && <p className="text-sm font-medium text-ink">{question.claim_check}</p>}
      {unsupported.map((claim) => (
        <p key={claim} className="mt-1 text-sm leading-relaxed text-ink-soft">
          “{claim}” —{" "}
          {resumeLine
            ? "be ready with the number, the baseline and how you measured it."
            : "say why it holds, not only that it does."}
        </p>
      ))}
      {contradictions.map((pair) => (
        <p key={`${pair.why}-${pair.said}`} className="mt-1 text-sm leading-relaxed text-ink-soft">
          Earlier you said “{pair.why}”{pair.said ? `, then “${pair.said}”` : ""} — those don't fit together.
        </p>
      ))}
    </Section>
  );
}

function QuestionCard({
  question,
  index,
  sessionId,
  kept,
  writing,
}: {
  question: QuestionReport;
  index: number;
  sessionId: string;
  /** Answers with audio kept (FR-11.19), by turn id. */
  kept: Set<string>;
  /** The written explanations are still being written. */
  writing: boolean;
}) {
  const meta = question.status ? STATUS_META[question.status] : null;
  const firstHeard = question.exchanges.find(
    (exchange) => exchange.role === "candidate" && exchange.turn_id && kept.has(exchange.turn_id),
  )?.turn_id;
  const answer = firstAnswer(question);
  const answers = question.exchanges.filter((exchange) => exchange.role === "candidate").length;
  const right = strengths(question);
  const missed = gaps(question);
  const fixed = correction(question);
  const ideal = idealAnswer(question);
  const steps = nextSteps(question);
  const conflict = bandConflict(question);
  const correct = question.status === "correct";
  const headingId = `question-${index + 1}`;
  const missedTitle = correct
    ? "To make it even stronger"
    : question.status === "unanswered"
      ? "What the question needed"
      : "What was missing or incorrect";
  return (
    <article
      aria-labelledby={headingId}
      className={`mt-4 rounded-2xl border border-l-4 border-line bg-surface p-5 ${meta?.accent ?? "border-l-line"}`}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        {question.status && (
          <StatusBadge
            status={question.status}
            label={question.status_label}
            qualifier={question.status_qualifier}
          />
        )}
        <span className="text-2xs uppercase tracking-wide text-ink-faint">Question {index + 1}</span>
        {topicName(question) && <span className="text-2xs text-ink-faint">· {topicName(question)}</span>}
        {question.asked_by && <span className="text-2xs text-ink-faint">· {question.asked_by}</span>}
        <span className="ml-auto">
          <SaveToggle sessionId={sessionId} question={question} />
        </span>
      </header>
      <h3 id={headingId} className="mt-2 text-base font-semibold leading-snug text-ink">
        {question.question}
      </h3>
      {(question.writeup?.headline || question.status_detail) && (
        <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">
          {question.writeup?.headline || question.status_detail}
        </p>
      )}
      {writing && !question.writeup && question.status && question.status !== "not_reached" && (
        <p className="mt-1 text-2xs text-ink-faint">Writing a detailed explanation of this answer…</p>
      )}
      {conflict && (
        <p role="note" className="mt-2 rounded-lg border border-line bg-surface-sunken px-3 py-2 text-2xs leading-relaxed text-ink-soft">
          {conflict}
        </p>
      )}

      {answer && (
        <Section title="Your answer">
          <blockquote className="turn-candidate whitespace-pre-wrap">{answer}</blockquote>
          {answers > 1 && (
            <p className="mt-1 text-2xs text-ink-faint">
              And {answers - 1} more answer{answers > 2 ? "s" : ""} to follow-ups — in the whole exchange below.
            </p>
          )}
        </Section>
      )}

      {right.length > 0 && (
        <Section title="What you got right">
          <ul className="space-y-2">
            {right.map((point) => (
              <li key={point.point} className="flex gap-2 text-sm leading-relaxed text-ink">
                <span className="mt-0.5 text-confirmed">
                  <StatusIcon icon="check" />
                </span>
                <span>
                  {point.point}
                  <Said text={point.evidence} />
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {missed.length > 0 && (
        <Section title={missedTitle}>
          <ul className="space-y-2.5">
            {missed.map((point) => (
              <li key={point.point} className="flex gap-2 text-sm leading-relaxed text-ink">
                <span className={correct ? "mt-0.5 text-reported" : "mt-0.5 text-contested"}>
                  <StatusIcon icon={correct ? "half" : "cross"} />
                </span>
                <span>
                  {point.point}
                  <Said text={point.evidence} />
                  {point.fix && <span className="mt-0.5 block text-sm text-ink">→ {point.fix}</span>}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {fixed && !correct && (
        <Section title="The correct idea">
          {fixed.wrong && (
            <p className="text-sm leading-relaxed text-ink-soft">
              <span className="font-medium text-contested">What went wrong: </span>
              {fixed.wrong}
            </p>
          )}
          {fixed.right && (
            <p className="mt-1 text-sm leading-relaxed text-ink">
              <span className="font-medium text-confirmed">The right reasoning: </span>
              {fixed.right}
            </p>
          )}
        </Section>
      )}

      <ClaimFindings question={question} />
      <KeyPoints question={question} />

      {ideal && (
        <details open={!correct && question.status !== "not_reached"} className="mt-4 rounded-xl bg-surface-sunken p-3">
          <summary className="cursor-pointer text-2xs font-semibold uppercase tracking-wide text-ink-soft hover:text-ink">
            {ideal.source === "written" ? "A model answer" : "One strong answer"}
            {ideal.source === "unreviewed" ? " · not yet reviewed by a person" : ""}
            {ideal.source === "written" ? " · written for these notes" : ""}
          </summary>
          <p className="mt-2 text-sm leading-relaxed text-ink">{ideal.text}</p>
          <p className="mt-1 text-2xs text-ink-faint">
            One way to answer it well — a different correct approach is just as good.
          </p>
        </details>
      )}

      {steps.length > 0 && (
        <Section title="What to practise next">
          <ul className="space-y-1.5 text-sm text-ink">
            {steps.map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden className="text-ink-faint">→</span>
                {line}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {question.last_time && (
        <p className="mt-4 rounded-lg bg-surface-sunken px-3 py-2 text-sm text-ink-soft">{question.last_time}</p>
      )}
      {question.hints_used > 0 && (
        <p className="mt-2 text-2xs text-ink-faint">
          You took {question.hints_used} hint{question.hints_used === 1 ? "" : "s"} here.
        </p>
      )}
      {!question.scored && question.not_scored_reason && (
        <p className="mt-2 text-2xs text-ink-faint">{question.not_scored_reason}</p>
      )}

      {question.feedback.length > 0 && (
        // M13's words, never its numbers: the display gate holds those until
        // they agree with human raters.
        <details className="mt-4">
          <summary className="cursor-pointer text-2xs font-medium text-ink-soft hover:text-ink">
            How the evaluator marked it
          </summary>
          <div className="mt-3 space-y-4">
            {question.feedback.map((item) => {
              const notYet = missingStatements(item.missing, question.strong_answer_covers);
              return (
                <div key={item.dimension} className="space-y-2">
                  <p>
                    <span className="rounded-full border border-line bg-surface-sunken px-2 py-0.5 text-2xs font-medium text-ink-soft capitalize">
                      {item.dimension}
                    </span>
                  </p>
                  {item.reasoning && <p className="text-sm leading-relaxed text-ink">{item.reasoning}</p>}
                  {item.quotes.map((quote) => (
                    <blockquote
                      key={quote}
                      className="border-l-2 border-brand-line pl-3 text-sm leading-relaxed text-ink-soft"
                    >
                      “{quote}”
                    </blockquote>
                  ))}
                  {notYet.length > 0 && (
                    <p className="text-2xs leading-relaxed text-ink-faint">Not covered yet: {notYet.join(" · ")}</p>
                  )}
                </div>
              );
            })}
          </div>
        </details>
      )}

      {(question.concept_id?.startsWith("concept:") ||
        (question.turn_id && question.feedback.length > 0) ||
        firstHeard) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {firstHeard && <HearIt sessionId={sessionId} turnId={firstHeard} label="Hear your answer" />}
          {/* A topic the bank asks about. A resume line or the opener is not
              one — a focus on it plans an empty part; star it instead. */}
          {question.concept_id?.startsWith("concept:") && (
            <Link
              to={`/mock?focus=${encodeURIComponent(question.concept_id)}&label=${encodeURIComponent(topicName(question) ?? "")}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-3 text-xs font-medium text-ink hover:border-brand-line hover:text-brand"
            >
              <Icon name="refresh" size={13} />
              Practise {topicName(question)} again
            </Link>
          )}
          {question.turn_id && question.feedback.length > 0 && (
            <Link
              to={`/turns/${question.turn_id}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium text-ink-soft hover:bg-surface-sunken hover:text-ink"
            >
              How this answer was marked →
            </Link>
          )}
        </div>
      )}

      <details className="mt-4">
        <summary className="cursor-pointer text-2xs text-ink-faint hover:text-ink-soft">The whole exchange</summary>
        {(question.how_it_went ?? []).length > 0 && (
          // Why each follow-up came — the decisions, in plain words.
          <ol className="mt-3 list-decimal space-y-1 pl-5 text-2xs text-ink-faint">
            {(question.how_it_went ?? []).map((step, position) => (
              <li key={`${position}-${step}`}>{step}</li>
            ))}
          </ol>
        )}
        <div className="mt-3 space-y-3">
          {question.exchanges.map((exchange, position) => (
            <div key={`${position}-${exchange.text.slice(0, 12)}`}>
              <p
                className={
                  exchange.role === "candidate" ? "turn-candidate whitespace-pre-wrap" : "whitespace-pre-wrap text-sm text-ink"
                }
              >
                {exchange.text}
              </p>
              {exchange.role === "candidate" && exchange.turn_id && kept.has(exchange.turn_id) && (
                <HearIt sessionId={sessionId} turnId={exchange.turn_id} />
              )}
            </div>
          ))}
        </div>
      </details>
    </article>
  );
}

type Shown = "all" | "work" | "correct";

/** The question's star (2026-10-22): saved to practise again. The
 *  interview's own flag is shown beside it and survives an unstar. */
function SaveToggle({ sessionId, question }: { sessionId: string; question: QuestionReport }) {
  const star = useStar(sessionId);
  const [starred, setStarred] = useState(Boolean(question.starred));
  const anchor = question.turn_id;
  if (!anchor) return null;
  return (
    <span className="inline-flex items-center gap-2">
      {question.flagged && (
        <span
          className="rounded-full border border-line bg-surface-sunken px-2 py-0.5 text-2xs text-ink-soft"
          title="The interview marked this one as worth practising again"
        >
          Worth practising
        </span>
      )}
      <button
        type="button"
        aria-pressed={starred}
        disabled={star.isPending}
        onClick={() =>
          star.mutate(
            { turnId: anchor, on: !starred },
            { onSuccess: (result) => setStarred(result.starred) },
          )
        }
        className="text-2xs font-medium text-brand hover:underline disabled:opacity-60"
      >
        {starred ? "★ Saved" : "☆ Save to your library"}
      </button>
    </span>
  );
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div>
      <p className="text-2xl font-semibold tracking-tight text-ink tabular-nums">{value}</p>
      <p className="mt-0.5 text-2xs text-ink-faint">{label}</p>
    </div>
  );
}

export function SessionNotes({ sessionId }: { sessionId: string }) {
  const report = useReport(sessionId);
  const client = useQueryClient();
  const keptList = useKept(sessionId);
  const kept = new Set((keptList.data ?? []).map((answer) => answer.turn_id));
  const [shown, setShown] = useState<Shown>("all");

  if (report.isLoading) {
    return (
      <div className="mx-auto max-w-(--container-conversation)">
        <SkeletonRows label="Putting your notes together" rows={5} />
      </div>
    );
  }
  if (report.isError || !report.data) {
    return (
      <ErrorNote
        message="Those notes could not be loaded."
        detail={report.error instanceof Error ? report.error.message : undefined}
        onRetry={() => report.refetch()}
      />
    );
  }

  const data = report.data;
  const hints = data.questions.reduce((sum, q) => sum + (q.hints_used ?? 0), 0);
  const minutes = data.minutes_used < 1 ? "<1" : String(Math.round(data.minutes_used));
  // The page stops asking after WRITEUP_POLL_MAX polls; past that, "Writing…"
  // would be a promise nothing is keeping, so it says so and offers a check.
  // Reading `dataUpdatedAt` is what re-renders the page on every poll: React
  // Query re-renders only for what a component reads, and an answer identical
  // to the last (still pending, nothing new written) changes nothing else.
  const updates = report.dataUpdatedAt
    ? (client.getQueryState(m06Keys.report(sessionId))?.dataUpdateCount ?? 0)
    : 0;
  const stalled = data.writeups === "pending" && updates >= WRITEUP_POLL_MAX;
  const writing = data.writeups === "pending" && !stalled;
  const judged = data.questions.some((q) => q.status);
  const work = data.questions.filter(needsWork).length;
  const right = data.questions.filter((q) => q.status === "correct").length;
  const visible = data.questions
    .map((question, index) => ({ question, index }))
    .filter(({ question }) =>
      shown === "all" ? true : shown === "work" ? needsWork(question) : question.status === "correct",
    );

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      <header className="relative overflow-hidden rounded-2xl border border-line bg-surface p-6 shadow-raised">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-20 -right-10 h-48 w-48 rounded-full bg-brand opacity-15 blur-3xl"
        />
        <p className="relative inline-flex items-center gap-1.5 rounded-full border border-confirmed-line bg-confirmed-soft px-2.5 py-1 text-2xs font-medium text-confirmed">
          ✓ {data.kind === "drill" ? "Drill complete" : "Session complete"}
        </p>
        <h1 className="relative mt-3 text-3xl font-semibold tracking-tight text-ink">Your notes</h1>
        <p className="relative mt-2 text-sm leading-relaxed text-ink-soft">{data.framing}</p>
        <div className="relative mt-5 grid grid-cols-3 gap-4 border-t border-line pt-5">
          <Stat value={data.questions.length} label={data.questions.length === 1 ? "question" : "questions"} />
          <Stat value={`${minutes}/${data.minutes_planned}`} label="minutes" />
          <Stat value={hints} label={hints === 1 ? "hint taken" : "hints taken"} />
        </div>
        <div className="relative mt-5 flex flex-wrap gap-2">
          <Link
            to="/mock"
            className="inline-flex h-9 items-center rounded-lg bg-brand px-3.5 text-sm font-semibold text-white hover:bg-brand-hover"
          >
            Practise again →
          </Link>
          <Link
            to="/skills"
            className="inline-flex h-9 items-center rounded-lg border border-line px-3.5 text-sm font-medium text-ink hover:border-line-strong"
          >
            See your skill graph
          </Link>
          <ShareButton data={data} />
        </div>
      </header>

      <Overview data={data} />
      {data.summary && <More summary={data.summary} />}

      {data.notes.length > 0 && (
        <ul className="mt-5 space-y-1.5 rounded-lg border border-line bg-surface p-4">
          {data.notes.map((note) => (
            <li key={note} className="text-2xs text-ink-soft">
              {note}
            </li>
          ))}
        </ul>
      )}

      <p aria-live="polite" className="mt-4 text-2xs text-ink-faint">
        {writing
          ? "Writing a detailed explanation of each answer — they appear here as they are ready."
          : stalled
            ? "The detailed explanations are taking longer than usual. Until they arrive, each answer shows what the interview recorded."
            : data.writeups === "partial"
              ? "Some answers could not be explained in detail; those show what the interview recorded."
              : ""}
        {stalled && (
          <button
            type="button"
            onClick={() => report.refetch()}
            className="ml-2 font-medium text-brand hover:underline"
          >
            Check again
          </button>
        )}
      </p>

      <section aria-labelledby="questions-title" className="mt-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="questions-title" className="mr-auto text-sm font-semibold text-ink">
            Question by question
          </h2>
          {judged && data.questions.length > 1 && (
            <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
              {(
                [
                  ["all", `All ${data.questions.length}`],
                  ["work", `Needs work ${work}`],
                  ["correct", `Correct ${right}`],
                ] as [Shown, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={shown === value}
                  onClick={() => setShown(value)}
                  className={`h-8 rounded-lg border px-3 text-xs font-medium ${
                    shown === value ? "border-brand-line bg-brand-soft text-brand" : "border-line text-ink-soft hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
        {data.questions.length === 0 ? (
          <div className="mt-6">
            <EmptyState title="No questions were asked" icon="clock">
              Nothing was asked before this session ended, so there is nothing to look back at. Starting
              another takes a few seconds.
            </EmptyState>
          </div>
        ) : visible.length === 0 ? (
          <p className="mt-4 rounded-lg border border-line bg-surface p-4 text-sm text-ink-soft">
            {shown === "work" ? "Nothing here needs work — every answer held." : "No answer was fully correct this time."}
          </p>
        ) : (
          visible.map(({ question, index }) => (
            <QuestionCard
              key={index}
              question={question}
              index={index}
              sessionId={sessionId}
              kept={kept}
              writing={writing}
            />
          ))
        )}
      </section>

      {data.plan_changes.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold text-ink">How the plan changed</h2>
          <p className="mt-1 text-2xs text-ink-faint">During the session you saw only what changed. This is why.</p>
          <ul className="mt-3 space-y-2">
            {data.plan_changes.map((change) => (
              <li key={change} className="text-sm leading-relaxed text-ink-soft">
                {change}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.your_questions.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold text-ink">Your questions for the interviewer</h2>
          <ul className="mt-3 space-y-2">
            {data.your_questions.map((asked, position) => (
              <li key={`${position}-${asked.slice(0, 12)}`} className="turn-candidate whitespace-pre-wrap">
                {asked}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="mt-8 space-y-3">
        <Card title="About these notes">
          <p className="text-sm leading-relaxed text-ink-soft">{data.persona_note}</p>
          <p className="mt-2 text-sm leading-relaxed text-ink-soft">
            Each answer's status is the interview's judgement of the whole conversation on that question.
            The detailed explanations are written by a language model after the session and are checked
            against your own words before they are shown. The evaluator never sees who you are, and its
            numbers stay hidden until they agree with human raters.
          </p>
          {kept.size > 0 && <KeptAnswers sessionId={sessionId} count={kept.size} />}
        </Card>
        <Link
          to="/mock"
          className="inline-flex items-center rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink hover:border-line-strong"
        >
          Back to interviews
        </Link>
      </footer>
    </div>
  );
}
