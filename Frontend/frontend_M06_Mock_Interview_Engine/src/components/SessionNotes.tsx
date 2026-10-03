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
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import {
  ANSWER_BAND_LABEL,
  Card,
  EmptyState,
  ErrorNote,
  Icon,
  SkeletonRows,
  type AnswerBand,
} from "@ai/core";

import { useReport } from "../api";
import { bandOf, missingStatements, topicName } from "../bands";
import type { QuestionReport, SessionReport } from "../types";

const BAND_STYLE: Record<AnswerBand, string> = {
  strong: "border-mastery-strong/40 bg-mastery-strong/12 text-mastery-strong",
  partly: "border-mastery-ok/40 bg-mastery-ok/12 text-mastery-ok",
  not_yet: "border-mastery-weak/40 bg-mastery-weak/12 text-mastery-weak",
};

/** The notes as plain text, for the student to send where they choose. */
function summaryText(data: SessionReport): string {
  const lines = [
    `My mock interview — ${data.questions.length} question${data.questions.length === 1 ? "" : "s"}, ${Math.round(data.minutes_used)} minutes`,
    "",
  ];
  data.questions.forEach((q, i) => {
    const band = bandOf(q);
    lines.push(`${i + 1}. ${q.question}`);
    lines.push(`   ${band ? ANSWER_BAND_LABEL[band] : "Not marked"}${topicName(q) ? ` · ${topicName(q)}` : ""}`);
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
      title="Copies a short summary: the questions and their bands. Nothing is posted for you."
    >
      <Icon name="send" size={15} />
      {done ?? "Share a summary"}
    </button>
  );
}

function depthSentence(question: QuestionReport): string {
  if (
    question.moved_on &&
    !question.exchanges.some((e) => e.role === "candidate")
  ) {
    // Not a break and not a fail: the student chose to leave it.
    return "We moved on from this one after a pause.";
  }
  if (question.break_depth === 0) {
    return "We stopped at the opening question.";
  }
  if (question.break_depth !== null) {
    return `Your reasoning held for ${question.break_depth} follow-up${
      question.break_depth === 1 ? "" : "s"
    }, then reached its edge.`;
  }
  if (question.ceiling !== null) {
    return `You held this to ${question.ceiling} follow-ups, which is as far as it goes.`;
  }
  if (question.depth_reached === 0) {
    return "No follow-ups on this one.";
  }
  return `You held this through ${question.depth_reached} follow-up${
    question.depth_reached === 1 ? "" : "s"
  }.`;
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div>
      <p className="text-2xl font-semibold tracking-tight text-ink tabular-nums">{value}</p>
      <p className="mt-0.5 text-2xs text-ink-faint">{label}</p>
    </div>
  );
}

function QuestionBlock({
  question,
  index,
}: {
  question: QuestionReport;
  index: number;
}) {
  return (
    <section className="border-b border-line py-6 last:border-0">
      <p className="flex flex-wrap items-center gap-2 text-2xs text-ink-faint">
        <span className="uppercase tracking-wide">Question {index + 1}</span>
        {question.asked_by && <span>· {question.asked_by}</span>}
        {bandOf(question) && (
          <span
            className={`rounded-full border px-2 py-0.5 text-2xs font-semibold ${BAND_STYLE[bandOf(question)!]}`}
            title="The share of a strong answer's key points your answer reached"
          >
            {ANSWER_BAND_LABEL[bandOf(question)!]}
          </span>
        )}
      </p>
      <h2 className="mt-1 text-base font-semibold leading-snug text-ink">
        {question.question}
      </h2>
      <p className="mt-2 text-sm text-ink-soft">{depthSentence(question)}</p>

      {question.hints_used > 0 && (
        <p className="mt-1 text-2xs text-ink-faint">
          You took {question.hints_used} hint
          {question.hints_used === 1 ? "" : "s"} here.
        </p>
      )}

      {question.feedback.length > 0 && (
        // M13's words, never its numbers: the display gate holds those until
        // they agree with human raters.
        <div className="mt-4 space-y-4 rounded-xl border border-line bg-surface p-4">
          <p className="text-2xs uppercase tracking-wide text-ink-faint">
            What the evaluator noticed
          </p>
          {question.feedback.map((item) => {
            const notYet = missingStatements(item.missing, question.strong_answer_covers);
            return (
              <div key={item.dimension} className="space-y-2 pt-1">
                <p>
                  <span className="rounded-full border border-line bg-surface-sunken px-2 py-0.5 text-2xs font-medium text-ink-soft capitalize">
                    {item.dimension}
                  </span>
                </p>
                {item.reasoning && (
                  <p className="text-sm leading-relaxed text-ink">{item.reasoning}</p>
                )}
                {item.quotes.map((quote) => (
                  <blockquote
                    key={quote}
                    className="border-l-2 border-brand-line pl-3 text-sm leading-relaxed text-ink-soft"
                  >
                    “{quote}”
                  </blockquote>
                ))}
                {notYet.length > 0 && (
                  <p className="text-2xs leading-relaxed text-ink-faint">
                    Not covered yet: {notYet.join(" · ")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!question.scored && question.not_scored_reason && (
        <p className="mt-2 text-2xs text-ink-faint">
          {question.not_scored_reason}
        </p>
      )}

      {question.strong_answer_covers.length > 0 && (
        <div className="mt-4 rounded-xl border border-confirmed-line bg-confirmed-soft p-4">
          <p className="text-2xs uppercase tracking-wide text-ink-faint">
            What a strong answer covers
          </p>
          <ul className="mt-2 space-y-1.5 text-sm text-ink">
            {question.strong_answer_covers.map((point) => (
              <li key={point} className="flex gap-2">
                <span aria-hidden className="text-confirmed">✓</span>
                {point}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(question.concept_id || question.turn_id) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {question.concept_id && (
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
        <summary className="cursor-pointer text-2xs text-ink-faint hover:text-ink-soft">
          The exchange
        </summary>
        <div className="mt-3 space-y-3">
          {question.exchanges.map((exchange, position) => (
            <p
              key={`${position}-${exchange.text.slice(0, 12)}`}
              className={
                exchange.role === "candidate"
                  ? "turn-candidate whitespace-pre-wrap"
                  : "whitespace-pre-wrap text-sm text-ink"
              }
            >
              {exchange.text}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}

export function SessionNotes({ sessionId }: { sessionId: string }) {
  const report = useReport(sessionId);

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
        detail={
          report.error instanceof Error ? report.error.message : undefined
        }
        onRetry={() => report.refetch()}
      />
    );
  }

  const data = report.data;
  const followUps = data.questions.reduce((sum, q) => sum + (q.depth_reached ?? 0), 0);
  const hints = data.questions.reduce((sum, q) => sum + (q.hints_used ?? 0), 0);
  const minutes =
    data.minutes_used < 1 ? "<1" : String(Math.round(data.minutes_used));

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
        <h1 className="relative mt-3 text-3xl font-semibold tracking-tight text-ink">
          Your notes
        </h1>
        <p className="relative mt-2 text-sm leading-relaxed text-ink-soft">
          {data.framing}
        </p>
        <div className="relative mt-5 grid grid-cols-2 gap-4 border-t border-line pt-5 sm:grid-cols-4">
          <Stat value={data.questions.length} label={data.questions.length === 1 ? "question" : "questions"} />
          <Stat value={followUps} label="follow-ups you held" />
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

      {data.notes.length > 0 && (
        <ul className="mt-5 space-y-1.5 rounded-lg border border-line bg-surface p-4">
          {data.notes.map((note) => (
            <li key={note} className="text-2xs text-ink-soft">
              {note}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2">
        {data.questions.length === 0 ? (
          <div className="mt-6">
            <EmptyState title="No questions were asked" icon="clock">
              Nothing was asked before this session ended, so there is nothing
              to look back at. Starting another takes a few seconds.
            </EmptyState>
          </div>
        ) : (
          data.questions.map((question, index) => (
            <QuestionBlock key={index} question={question} index={index} />
          ))
        )}
      </div>

      {data.plan_changes.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold text-ink">
            How the plan changed
          </h2>
          <p className="mt-1 text-2xs text-ink-faint">
            During the session you saw only what changed. This is why.
          </p>
          <ul className="mt-3 space-y-2">
            {data.plan_changes.map((change) => (
              <li
                key={change}
                className="text-sm leading-relaxed text-ink-soft"
              >
                {change}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.your_questions.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold text-ink">
            Your questions for the interviewer
          </h2>
          <ul className="mt-3 space-y-2">
            {data.your_questions.map((asked, position) => (
              <li
                key={`${position}-${asked.slice(0, 12)}`}
                className="turn-candidate whitespace-pre-wrap"
              >
                {asked}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="mt-8 space-y-3">
        <Card title="About these notes">
          <p className="text-sm leading-relaxed text-ink-soft">
            {data.persona_note}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-ink-soft">
            The band on each answer is the share of a strong answer's key points
            it reached. The evaluator never sees who you are, and its numbers
            stay hidden until they agree with human raters.
          </p>
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
