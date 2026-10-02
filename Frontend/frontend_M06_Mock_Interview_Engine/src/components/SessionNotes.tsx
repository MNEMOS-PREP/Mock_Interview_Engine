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
 */

import { Link } from "react-router-dom";

import { Card, EmptyState, ErrorNote, Spinner } from "@ai/core";

import { useReport } from "../api";
import type { QuestionReport } from "../types";

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

function QuestionBlock({
  question,
  index,
}: {
  question: QuestionReport;
  index: number;
}) {
  return (
    <section className="border-b border-line py-6 last:border-0">
      <p className="text-2xs uppercase tracking-wide text-ink-faint">
        Question {index + 1}
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
        <div className="mt-4 space-y-3 rounded-lg border border-line p-3">
          <p className="text-2xs uppercase tracking-wide text-ink-faint">
            What the evaluator noticed
          </p>
          {question.feedback.map((item) => (
            <div key={item.dimension} className="space-y-1">
              <p className="text-2xs font-medium text-ink-soft">
                {item.dimension}
              </p>
              {item.reasoning && (
                <p className="text-sm text-ink">{item.reasoning}</p>
              )}
              {item.quotes.map((quote) => (
                <p key={quote} className="turn-candidate text-sm">
                  “{quote}”
                </p>
              ))}
              {item.missing.length > 0 && (
                <p className="text-2xs text-ink-faint">
                  Not reached: {item.missing.join(" · ")}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {!question.scored && question.not_scored_reason && (
        <p className="mt-2 text-2xs text-ink-faint">
          {question.not_scored_reason}
        </p>
      )}

      {question.strong_answer_covers.length > 0 && (
        <div className="mt-4 rounded-lg border border-line bg-surface-sunken p-3">
          <p className="text-2xs uppercase tracking-wide text-ink-faint">
            What a strong answer covers
          </p>
          <ul className="mt-1.5 space-y-1 text-sm text-ink-soft">
            {question.strong_answer_covers.map((point) => (
              <li key={point}>· {point}</li>
            ))}
          </ul>
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

  if (report.isLoading) return <Spinner label="Putting your notes together…" />;
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

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      <header>
        <p className="text-2xs uppercase tracking-wide text-ink-faint">
          {data.kind === "drill" ? "Defend drill" : `${data.mode} interview`} ·{" "}
          {data.minutes_used} of {data.minutes_planned} min
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">
          Your notes
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          {data.framing}
        </p>
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
            Scores are not shown anywhere yet. The evaluator is a separate
            module that never sees who you are, and its numbers stay hidden
            until they agree with human raters — so what you get today is what
            was asked and how far it went.
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
