/**
 * What the notes say about one answer (`notes.ts`), pinned without a browser.
 *
 * The bug this file exists for: a correct, a vague and a wrong answer looked
 * alike — the same grey status phrase, and the same green ✓ box on every
 * question, wrong ones included.
 */
import { describe, expect, it } from "vitest";

import {
  STATUS_META,
  STATUS_ORDER,
  bandConflict,
  correction,
  gaps,
  idealAnswer,
  needsWork,
  nextSteps,
  strengths,
  weakest,
} from "./notes";
import { question } from "./testing";
import type { AnswerStatus, Writeup } from "./types";

const ALL: AnswerStatus[] = [
  "correct",
  "partial",
  "vague",
  "incorrect",
  "unanswered",
  "unsupported",
  "not_judged",
  "not_reached",
];

const WRITTEN: Writeup = {
  headline: "You treated a hash map as a sorted structure.",
  strengths: [{ point: "Named buckets", evidence: "buckets", fix: "" }],
  gaps: [{ point: "No load factor", evidence: "", fix: "Say the load factor stays bounded." }],
  misconception: "You believe the keys are kept sorted.",
  correction: "The hash function picks the bucket directly; nothing is sorted.",
  model_answer: "A hash map hashes the key to a bucket index…",
  next_steps: ["Redraw the lookup path: key → hash → bucket."],
  model: "stub",
};

describe("each status looks like itself", () => {
  it("has a label, a badge, an accent and a shape for every status", () => {
    for (const status of ALL) {
      const meta = STATUS_META[status];
      expect(meta.label, status).toBeTruthy();
      expect(meta.badge, status).toMatch(/text-/);
      expect(meta.accent, status).toMatch(/^border-l-/);
      expect(meta.icon, status).toBeTruthy();
    }
    expect([...STATUS_ORDER].sort()).toEqual([...ALL].sort());
  });

  it("never gives two of the judged answers the same colour and shape", () => {
    const judged: AnswerStatus[] = ["correct", "partial", "vague", "incorrect", "unanswered"];
    const looks = judged.map((s) => `${STATUS_META[s].accent}|${STATUS_META[s].icon}`);
    expect(new Set(looks).size).toBe(judged.length);
    // And the shapes alone tell them apart (WCAG 1.4.1: not colour only).
    expect(new Set(judged.map((s) => STATUS_META[s].icon)).size).toBe(judged.length);
  });

  it("is green only for a correct answer and red only for a wrong one", () => {
    expect(STATUS_META.correct.accent).toBe("border-l-confirmed");
    expect(STATUS_META.incorrect.accent).toBe("border-l-contested");
    for (const status of ALL.filter((s) => s !== "correct")) {
      expect(STATUS_META[status].badge, status).not.toMatch(/confirmed/);
    }
  });

  it("counts every answer that needs work, and nothing that does not", () => {
    const work = ALL.filter((status) => needsWork(question(status)));
    expect(work.sort()).toEqual(["incorrect", "partial", "unanswered", "unsupported", "vague"]);
    expect(needsWork(question(null))).toBe(false);
  });
});

describe("what to practise next", () => {
  const on = (status: AnswerStatus, topic: string) =>
    question(status, { concept_id: `concept:${topic}`, topic });

  it("picks the most urgent answer, in the notes' own order", () => {
    const qs = [on("partial", "graphs"), on("vague", "hashing"), on("incorrect", "recursion"), on("correct", "dp")];
    expect(weakest(qs)?.topic).toBe("recursion");
    expect(weakest(qs.filter((q) => q.status !== "incorrect"))?.topic).toBe("hashing");
  });

  it("skips what has no topic to practise, and is null when every answer held", () => {
    expect(weakest([question("incorrect", { concept_id: "resume:c-7" }), on("partial", "graphs")])?.topic).toBe(
      "graphs",
    );
    expect(weakest([on("correct", "dp"), on("not_reached", "trees")])).toBeNull();
  });
});

describe("what went right", () => {
  it("is nothing for an answer that was never given, whatever else says so", () => {
    expect(strengths(question("unanswered", { went_well: ["Named buckets"], writeup: WRITTEN }))).toEqual([]);
    expect(strengths(question("not_reached", { went_well: ["x"] }))).toEqual([]);
  });

  it("is the checked write-up's when there is one, else what the interview recorded", () => {
    expect(strengths(question("partial", { writeup: WRITTEN }))).toEqual(WRITTEN.strengths);
    expect(strengths(question("partial", { went_well: ["Named buckets"] }))).toEqual([{ point: "Named buckets" }]);
  });
});

describe("what was missing or wrong", () => {
  it("prefers the write-up's gaps", () => {
    expect(gaps(question("incorrect", { writeup: WRITTEN }))).toEqual(WRITTEN.gaps);
  });

  it("falls back to the wrong sentences, leaving missed key points to the rubric", () => {
    const q = question("incorrect", {
      went_wrong: [{ said: "the keys are sorted", why: "A hash map keeps no order." }],
      key_points: [
        { statement: "Hashes the key to a bucket index", covered: true },
        { statement: "Names a bounded load factor", covered: false },
      ],
    });
    expect(gaps(q)).toEqual([{ point: "A hash map keeps no order.", evidence: "the keys are sorted" }]);
  });
});

describe("the correct idea and the answer to compare against", () => {
  it("pairs the wrong idea with the right one", () => {
    expect(correction(question("incorrect", { writeup: WRITTEN }))).toEqual({
      wrong: WRITTEN.misconception,
      right: WRITTEN.correction,
    });
    expect(correction(question("incorrect", { misconception: "thinks keys are sorted" }))).toEqual({
      wrong: "thinks keys are sorted",
      right: "",
    });
    expect(correction(question("correct"))).toBeNull();
  });

  it("says whose answer the ideal is", () => {
    expect(idealAnswer(question("vague", { one_strong_answer: "Reviewed.", strong_answer_reviewed: true }))).toEqual({
      text: "Reviewed.",
      source: "reviewed",
    });
    expect(idealAnswer(question("vague", { one_strong_answer: "Drafted.", strong_answer_reviewed: false }))).toEqual({
      text: "Drafted.",
      source: "unreviewed",
    });
    expect(idealAnswer(question("vague", { writeup: WRITTEN }))).toEqual({
      text: WRITTEN.model_answer,
      source: "written",
    });
    expect(idealAnswer(question("vague"))).toBeNull();
  });

  it("takes the written next steps, else the study list", () => {
    expect(nextSteps(question("vague", { writeup: WRITTEN, study: ["Read chapter 3"] }))).toEqual(WRITTEN.next_steps);
    expect(nextSteps(question("vague", { study: ["Read chapter 3"] }))).toEqual(["Read chapter 3"]);
  });
});

describe("when the evaluator and the interview disagree", () => {
  // M13 names the missed key points by id, as it does on the wire.
  const marked = (missing: string[]) => [{ dimension: "correctness", reasoning: "", missing, quotes: [] }];

  it("says so for a strong band on a wrong answer, and for a weak band on a correct one", () => {
    expect(bandConflict(question("incorrect", { feedback: marked([]) }))).toMatch(/differently/);
    expect(bandConflict(question("correct", { feedback: marked(["kp_1", "kp_2"]) }))).toMatch(/differently/);
  });

  it("is quiet when they agree, or when there is no band", () => {
    expect(bandConflict(question("correct", { feedback: marked([]) }))).toBeNull();
    expect(bandConflict(question("incorrect"))).toBeNull();
  });
});
