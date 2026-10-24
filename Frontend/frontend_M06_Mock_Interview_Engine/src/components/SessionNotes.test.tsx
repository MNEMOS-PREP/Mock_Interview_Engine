/**
 * The notes page in each of its states (2026-10-24), against the real API
 * client with `fetch` answered here: loading, error, empty, written, still
 * being written — and four different answers that must not look alike.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WRITEUP_POLL_MAX, WRITEUP_POLL_MS } from "../api";
import { line, question, report } from "../testing";
import type { SessionReport } from "../types";
import { SessionNotes } from "./SessionNotes";

type Answer = () => Promise<Response>;

const json = (body: unknown, status = 200): Answer => () =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

/** Answers the report route with each of `answers` in turn (the last repeats);
 *  M11's kept-audio route is down, as it is when the voice service is off. */
function serve(answers: Answer[]) {
  const calls: string[] = [];
  const fetchStub = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/report")) {
      const next = answers.length > 1 ? answers.shift()! : answers[0];
      return next();
    }
    return json({ detail: "not here" }, 404)();
  });
  vi.stubGlobal("fetch", fetchStub);
  return calls;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SessionNotes sessionId="s-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const card = (status: string) => screen.getByRole("article", { name: `A question that was ${status}` });

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the page's states", () => {
  it("says it is putting the notes together while it loads", () => {
    serve([() => new Promise<Response>(() => {})]);
    show();
    expect(screen.getByRole("status", { name: "Putting your notes together" })).toBeTruthy();
  });

  it("says the notes could not be loaded, and offers to try again", async () => {
    serve([json({ detail: "database is down" }, 500)]);
    show();
    expect(await screen.findByText("Those notes could not be loaded.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /try again|retry/i })).toBeTruthy();
  });

  it("says nothing was asked when nothing was", async () => {
    serve([json(report([], { summary: undefined }))]);
    show();
    expect(await screen.findByText("No questions were asked")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Show" })).toBeNull();
  });

  it("asks for the report on the session's own route", async () => {
    const calls = serve([json(report([question("correct")]))]);
    show();
    await screen.findByRole("article", { name: "A question that was correct" });
    expect(calls.some((url) => url.endsWith("/v1/interviews/s-1/report"))).toBe(true);
  });
});

const FOUR: SessionReport = report([
  question("correct", {
    went_well: ["Hashed the key to a bucket"],
    key_points: [
      { statement: "Hashes the key to a bucket index", covered: true },
      { statement: "Names a bounded load factor", covered: true },
    ],
  }),
  question("vague", {
    key_points: [
      { statement: "Hashes the key to a bucket index", covered: false },
      { statement: "Names a bounded load factor", covered: false },
    ],
  }),
  question("incorrect", {
    went_wrong: [{ said: "the keys are kept sorted", why: "A hash map keeps no order." }],
    misconception: "thinks a hash map keeps its keys sorted",
    writeup: {
      headline: "You described a sorted array, not a hash map.",
      strengths: [],
      gaps: [{ point: "Lookup is not a binary search.", evidence: "", fix: "Hash the key to a bucket index." }],
      misconception: "You believe a hash map keeps its keys sorted.",
      correction: "The hash function computes the bucket directly; nothing is sorted.",
      model_answer: "A hash map hashes the key to a bucket index…",
      next_steps: ["Redraw the lookup path: key → hash function → bucket index."],
      model: "stub",
    },
  }),
  question("unanswered", {
    exchanges: [line("interviewer", "Why is lookup O(1)?"), line("candidate", "I don't know this one.")],
    went_well: ["Should never be shown"],
    // As `report._covered` sends them: nothing reached.
    key_points: [
      { statement: "Hashes the key to a bucket index", covered: false },
      { statement: "Names a bounded load factor", covered: false },
    ],
  }),
]);

describe("four different answers look different", () => {
  it("gives each its own status, in words and in colour", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was correct" });

    const expected: [string, string, string][] = [
      ["correct", "Correct", "border-l-confirmed"],
      ["vague", "Too vague", "border-l-agreement"],
      ["incorrect", "Incorrect", "border-l-contested"],
      ["unanswered", "Not answered", "border-l-line-strong"],
    ];
    for (const [status, label, accent] of expected) {
      const article = card(status);
      expect(within(article).getByText(label), status).toBeTruthy();
      expect(article.className, status).toContain(accent);
    }
  });

  it("shows a wrong answer what went wrong and the right reasoning", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was incorrect" });
    const wrong = within(card("incorrect"));
    expect(wrong.getByText("You described a sorted array, not a hash map.")).toBeTruthy();
    expect(wrong.getByText("The correct idea")).toBeTruthy();
    expect(wrong.getByText("You believe a hash map keeps its keys sorted.")).toBeTruthy();
    expect(wrong.getByText(/nothing is sorted/)).toBeTruthy();
    expect(wrong.queryByText("What you got right")).toBeNull();
  });

  it("never tells a correct answer what went wrong", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was correct" });
    const right = within(card("correct"));
    expect(right.getByText("What you got right")).toBeTruthy();
    expect(right.queryByText("The correct idea")).toBeNull();
    expect(right.queryByText("What was missing or incorrect")).toBeNull();
  });

  it("praises nothing in an answer that was not given, and says what the question needed", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was unanswered" });
    const blank = within(card("unanswered"));
    expect(blank.queryByText("What you got right")).toBeNull();
    expect(blank.queryByText("Should never be shown")).toBeNull();
    // What the question needed: the rubric, every point marked not reached.
    expect(blank.getAllByText(/— not covered/)).toHaveLength(2);
    // Their words, under "Your answer" (and again in the whole exchange).
    expect(blank.getAllByText("I don't know this one.")[0].closest("blockquote")).toBeTruthy();
  });

  it("lists a missed key point once, not as a gap and again in the rubric", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was vague" });
    const vague = within(card("vague"));
    expect(vague.getAllByText(/Names a bounded load factor/)).toHaveLength(1);
    expect(vague.queryByText(/^Not covered:/)).toBeNull();
  });

  it("marks each key point reached or not, in words a screen reader hears", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was vague" });
    const vague = within(card("vague"));
    expect(vague.getAllByText(/— not covered/)).toHaveLength(2);
    expect(within(card("correct")).getAllByText(/— you covered this/)).toHaveLength(2);
  });

  it("counts them in the overview, as a distribution and never a score", async () => {
    serve([json(FOUR)]);
    show();
    const bar = await screen.findByRole("img", { name: /1 correct, 1 too vague, 1 incorrect, 1 not answered/ });
    expect(bar).toBeTruthy();
    expect(screen.queryByText(/\d+\s*%|\d+\s*\/\s*10/)).toBeNull();
  });

  it("filters to what needs work, and to what was correct", async () => {
    serve([json(FOUR)]);
    show();
    await screen.findByRole("article", { name: "A question that was correct" });

    fireEvent.click(screen.getByRole("button", { name: "Needs work 3" }));
    expect(screen.queryByRole("article", { name: "A question that was correct" })).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Needs work 3" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Correct 1" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(card("correct")).toBeTruthy();
  });
});

describe("the written explanations", () => {
  it("says they are being written, and shows them when they are", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const pending = report([question("vague")], { writeups: "pending" });
    const ready = report(
      [
        question("vague", {
          writeup: {
            headline: "You named buckets but never said how a lookup avoids scanning.",
            strengths: [],
            gaps: [],
            misconception: "",
            correction: "",
            model_answer: "",
            next_steps: [],
            model: "stub",
          },
        }),
      ],
      { writeups: "ready" },
    );
    const calls = serve([json(pending), json(ready)]);
    show();

    expect(await screen.findByText(/Writing a detailed explanation of each answer/)).toBeTruthy();
    expect(within(card("vague")).getByText("Writing a detailed explanation of this answer…")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(WRITEUP_POLL_MS + 100);
    });
    expect(await screen.findByText("You named buckets but never said how a lookup avoids scanning.")).toBeTruthy();
    expect(screen.queryByText(/Writing a detailed explanation/)).toBeNull();

    const before = calls.filter((url) => url.includes("/report")).length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(WRITEUP_POLL_MS * 3);
    });
    expect(calls.filter((url) => url.includes("/report")).length, "stops asking once ready").toBe(before);
  });

  it("stops promising once it stops asking, and offers to check again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = serve([json(report([question("vague")], { writeups: "pending" }))]);
    show();
    await screen.findByText(/Writing a detailed explanation of each answer/);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(WRITEUP_POLL_MS * (WRITEUP_POLL_MAX + 2));
    });
    const asked = calls.filter((url) => url.includes("/report")).length;
    expect(asked).toBeLessThanOrEqual(WRITEUP_POLL_MAX + 1);
    expect(screen.queryAllByText(/Writing a detailed explanation/)).toHaveLength(0);
    expect(screen.getByText(/taking longer than usual/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(calls.filter((url) => url.includes("/report")).length).toBe(asked + 1);
  });

  it("says when some could not be written, and shows what the interview recorded", async () => {
    serve([json(report([question("vague")], { writeups: "partial" }))]);
    show();
    expect(await screen.findByText(/Some answers could not be explained in detail/)).toBeTruthy();
    expect(within(card("vague")).getByText("Detail for vague.")).toBeTruthy();
  });
});
