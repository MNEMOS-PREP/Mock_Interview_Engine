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

/**
 * `kp_3`, `[kp_3] Says the worst case degrades…` → the statement, once.
 * Key points are numbered in the order "what a strong answer covers" lists
 * them, so `kp_N` is entry N-1 when the item carries no text of its own.
 */
function missingStatements(missing: string[], covers: string[]): string[] {
  const out = new Map<string, string>();
  for (const raw of missing) {
    const match = /^\[?(kp_\d+)\]?\s*(.*)$/i.exec(raw.trim());
    const id = match?.[1]?.toLowerCase() ?? raw;
    const text = match?.[2]?.trim() || covers[Number(id.replace(/\D/g, "")) - 1] || "";
    if (text && !out.has(id)) out.set(id, text);
  }
  return [...out.values()];
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
          <Link
            to="/"
            className="inline-flex h-9 items-center rounded-lg px-3 text-sm text-ink-soft hover:text-ink"
          >
            Back to today
          </Link>
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
