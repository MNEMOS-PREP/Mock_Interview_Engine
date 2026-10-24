/**
 * What the notes show about one answer, in one place (2026-10-24).
 *
 * A correct, a vague and a wrong answer used to look alike: the status was a
 * grey phrase, the only coloured badge was M13's (scored questions only), and
 * every question — wrong ones included — carried the same green box of ✓
 * marks. The page is now built around the status the backend derives from the
 * interview's own judgement (`report._status`), and everything it shows about
 * an answer is chosen here: the written explanation when it is ready and
 * checked (`notes_writer`), else what the interview recorded. Pure, so the
 * rules are tested without a browser.
 */
import { bandOf } from "./bands";
import type { AnswerStatus, QuestionReport } from "./types";

export interface StatusMeta {
  label: string;
  /** Tailwind classes, from the theme's semantic tokens (light and dark). */
  badge: string;
  accent: string;
  /** The overview's bar segment. */
  bar: string;
  /** A shape per status, so colour is never the only signal (WCAG 1.4.1). */
  icon: "check" | "half" | "wave" | "cross" | "circle" | "question" | "dash";
}

export const STATUS_META: Record<AnswerStatus, StatusMeta> = {
  correct: {
    label: "Correct",
    badge: "border-confirmed-line bg-confirmed-soft text-confirmed",
    accent: "border-l-confirmed",
    bar: "bg-confirmed",
    icon: "check",
  },
  partial: {
    label: "Partly correct",
    badge: "border-reported-line bg-reported-soft text-reported",
    accent: "border-l-reported",
    bar: "bg-reported",
    icon: "half",
  },
  vague: {
    label: "Too vague",
    badge: "border-agreement-line bg-agreement-soft text-agreement",
    accent: "border-l-agreement",
    bar: "bg-agreement",
    icon: "wave",
  },
  incorrect: {
    label: "Incorrect",
    badge: "border-contested-line bg-contested-soft text-contested",
    accent: "border-l-contested",
    bar: "bg-contested",
    icon: "cross",
  },
  unsupported: {
    label: "Not backed up",
    badge: "border-reported-line bg-reported-soft text-reported",
    accent: "border-l-reported",
    bar: "bg-reported/60",
    icon: "question",
  },
  unanswered: {
    label: "Not answered",
    badge: "border-line-strong bg-surface-sunken text-ink-soft",
    accent: "border-l-line-strong",
    bar: "bg-line-strong",
    icon: "circle",
  },
  not_judged: {
    label: "Not judged",
    badge: "border-line bg-surface-sunken text-ink-faint",
    accent: "border-l-line",
    bar: "bg-line",
    icon: "dash",
  },
  not_reached: {
    label: "Not reached",
    badge: "border-line bg-surface-sunken text-ink-faint",
    accent: "border-l-line",
    bar: "bg-line",
    icon: "dash",
  },
};

/** The order a summary counts them in — what held first, then what did not. */
export const STATUS_ORDER: AnswerStatus[] = [
  "correct",
  "partial",
  "vague",
  "unsupported",
  "incorrect",
  "unanswered",
  "not_judged",
  "not_reached",
];

/** What to work on first, most urgent first — `report.FOCUS_ORDER`, so the
 *  "practise this next" link agrees with the notes' own "Work on first". */
export const FOCUS_ORDER: AnswerStatus[] = ["incorrect", "unanswered", "vague", "unsupported", "partial"];

export function needsWork(question: QuestionReport): boolean {
  return question.status ? FOCUS_ORDER.includes(question.status) : false;
}

/** The answer most worth practising again, among those with a topic to
 *  practise — or null when every answer held. */
export function weakest(questions: QuestionReport[]): QuestionReport | null {
  for (const status of FOCUS_ORDER) {
    const found = questions.find((q) => q.status === status && q.concept_id?.startsWith("concept:"));
    if (found) return found;
  }
  return null;
}

export interface Point {
  point: string;
  /** The student's own words, when there are some to show. */
  evidence?: string;
  fix?: string;
}

/** What the answer got right — never invented for an answer not given. */
export function strengths(question: QuestionReport): Point[] {
  if (question.status === "unanswered" || question.status === "not_reached") return [];
  if (question.writeup) return question.writeup.strengths;
  return (question.went_well ?? []).map((point) => ({ point }));
}

/** What was missing or wrong: the write-up's, else the student's wrong
 *  sentences. Not the key points no answer reached — the rubric right below
 *  marks those ✕, and listing them here too showed every one twice (found by
 *  the page tests, 2026-10-24). */
export function gaps(question: QuestionReport): Point[] {
  if (question.writeup) return question.writeup.gaps;
  return (question.went_wrong ?? []).map((finding) => ({
    point: finding.why || "This did not hold.",
    evidence: finding.said,
  }));
}

/** For a wrong answer: the wrong idea and the right one. */
export function correction(question: QuestionReport): { wrong: string; right: string } | null {
  const wrong = question.writeup?.misconception || question.misconception || "";
  const right = question.writeup?.correction || "";
  if (!wrong && !right) return null;
  return { wrong, right };
}

/** The answer to compare against: the reviewed reference, else the written
 *  model answer — and which, so an unreviewed one is labelled as such. */
export function idealAnswer(
  question: QuestionReport,
): { text: string; source: "reviewed" | "unreviewed" | "written" } | null {
  if (question.one_strong_answer) {
    return {
      text: question.one_strong_answer,
      source: question.strong_answer_reviewed === false ? "unreviewed" : "reviewed",
    };
  }
  if (question.writeup?.model_answer) return { text: question.writeup.model_answer, source: "written" };
  return null;
}

export function nextSteps(question: QuestionReport): string[] {
  const written = question.writeup?.next_steps ?? [];
  return written.length ? written : (question.study ?? []);
}

/** The student's first answer — what they said before any follow-up. */
export function firstAnswer(question: QuestionReport): string | null {
  return question.exchanges.find((exchange) => exchange.role === "candidate")?.text ?? null;
}

/** When M13's key-point band and the interview's status point opposite ways,
 *  say so rather than show two verdicts that disagree in silence. */
export function bandConflict(question: QuestionReport): string | null {
  const band = bandOf(question);
  const status = question.status;
  if (!band || !status) return null;
  const good = status === "correct";
  const bad = status === "incorrect" || status === "unanswered" || status === "vague";
  if ((band === "strong" && bad) || (band === "not_yet" && good)) {
    return (
      "The evaluator read this answer differently from the interview. The status above is the " +
      "interview's judgement of the whole conversation; the evaluator's notes are below."
    );
  }
  return null;
}
