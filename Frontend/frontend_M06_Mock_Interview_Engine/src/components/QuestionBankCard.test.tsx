/**
 * Today's question bank card (2026-11-18), against the real API client with
 * `fetch` answered here: nothing before the first question, the counts and
 * the download once there is one, and the download fetched with identity —
 * a plain link would not carry it — and saved under the bank's own name.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { QuestionBank } from "../types";
import { QuestionBankCard } from "./QuestionBankCard";

const BANK: QuestionBank = {
  file_name: "q_bank_discovered.pdf",
  questions: 55,
  follow_ups: 63,
  pending: 0,
  updated_at: new Date().toISOString(),
  subjects: [
    { title: "Computer networks", questions: 1, accent: "#176b55" },
    { title: "Data structures and algorithms", questions: 23, accent: "#2b5c8a" },
    { title: "Operating systems", questions: 3, accent: "#6b4c9a" },
    { title: "Backend engineering", questions: 2, accent: "#0e6b75" },
    { title: "Machine learning", questions: 9, accent: "#9b2f55" },
  ],
};

function serve(bank: QuestionBank) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url.includes("/question-bank.pdf")) {
        return Promise.resolve(new Response(new Blob(["%PDF-1.4"]), { status: 200 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify(bank), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }),
  );
  return calls;
}

function show(name?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <QuestionBankCard name={name} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the question bank card", () => {
  it("is not there before the first question", async () => {
    serve({ ...BANK, questions: 0, follow_ups: 0, subjects: [] });
    const { container } = show();
    await act(async () => {});
    expect(container.innerHTML).toBe("");
  });

  it("counts the bank, names four subjects and counts the rest", async () => {
    serve(BANK);
    show();
    expect(await screen.findByText("55")).toBeTruthy();
    expect(screen.getByText("Data structures and algorithms")).toBeTruthy();
    expect(screen.getByText("and 1 more subject")).toBeTruthy();
    expect(screen.queryByText(/Writing the answers/)).toBeNull();
  });

  it("says when answers are still being written", async () => {
    serve({ ...BANK, pending: 3 });
    show();
    expect(await screen.findByText(/Writing the answers for 3 questions/)).toBeTruthy();
  });

  it("downloads the file under its own name, with the name for the cover", async () => {
    const calls = serve(BANK);
    const saved: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:bank", revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    show("Varun");
    fireEvent.click(await screen.findByRole("button", { name: /Download PDF/ }));
    await act(async () => {});
    expect(calls.some((u) => u.includes("/v1/interviews/question-bank.pdf?name=Varun"))).toBe(true);
    expect(saved).toEqual(["q_bank_discovered.pdf"]);
    click.mockRestore();
  });
});
