/**
 * The question bank card on the shell's Today page (2026-11-18).
 *
 * `q_bank_discovered.pdf` is every question the student has answered in an
 * interview — by subject, each with the answer to say and the follow-ups that
 * came next — and it grows after every question. M06 owns the card, as M22
 * owns its goal card, so Today never re-counts the bank: it mounts this.
 *
 * Progressive disclosure, like the rest of Today: nothing until there is a
 * question in the bank. The counts are what is in the file right now; while
 * answers are still being written the card says so, and asks again.
 */
import { useState } from "react";

import { Icon } from "@ai/core";

import { downloadQuestionBank, useQuestionBank } from "../api";

/** Subjects named on the card; the rest are counted. */
const SHOWN = 4;

function updatedLabel(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.round((Date.now() - then.getTime()) / 60_000);
  if (minutes < 1) return "Updated just now";
  if (minutes < 60) return `Updated ${minutes} min ago`;
  const time = then.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const sameDay = new Date().toDateString() === then.toDateString();
  return sameDay
    ? `Updated today, ${time}`
    : `Updated ${then.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

function DownloadGlyph() {
  return (
    <svg aria-hidden width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}

export function QuestionBankCard({ name, className = "" }: { name?: string; className?: string }) {
  const bank = useQuestionBank(name);
  const [state, setState] = useState<"idle" | "busy" | "failed">("idle");
  const data = bank.data;
  if (!data || data.questions === 0) return null;

  const shown = data.subjects.slice(0, SHOWN);
  const more = data.subjects.length - shown.length;

  async function download() {
    setState("busy");
    try {
      await downloadQuestionBank(name);
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  return (
    <section className={`panel p-6 ${className}`} aria-label="Your question bank">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-xs font-medium text-ink-faint">
          <Icon name="document" size={14} />
          Your question bank
        </p>
        <span className="text-[0.6875rem] text-ink-faint">{updatedLabel(data.updated_at)}</span>
      </div>

      <p className="mt-3 flex items-baseline gap-2">
        <span className="text-4xl font-semibold tracking-tight text-ink" data-numeric>
          {data.questions}
        </span>
        <span className="text-sm text-ink-faint">
          question{data.questions === 1 ? "" : "s"} you've met
        </span>
      </p>
      <p className="mt-0.5 text-xs text-ink-soft">
        {data.follow_ups} follow-up{data.follow_ups === 1 ? "" : "s"} · {data.subjects.length} subject
        {data.subjects.length === 1 ? "" : "s"} · an answer to say for each
      </p>

      <ul className="mt-4 space-y-1.5">
        {shown.map((s) => (
          <li key={s.title} className="flex items-center gap-2 text-sm">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: s.accent }} />
            <span className="min-w-0 flex-1 truncate text-ink-soft">{s.title}</span>
            <span className="shrink-0 text-xs text-ink-faint" data-numeric>
              {s.questions}
            </span>
          </li>
        ))}
        {more > 0 && (
          <li className="pl-4 text-xs text-ink-faint">
            and {more} more subject{more === 1 ? "" : "s"}
          </li>
        )}
      </ul>

      {data.pending > 0 && (
        <p className="mt-4 rounded-lg bg-surface-sunken px-3 py-2 text-xs text-ink-soft">
          Writing the answers for {data.pending} question{data.pending === 1 ? "" : "s"} — they'll be
          in your next download.
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
        <button
          type="button"
          onClick={download}
          disabled={state === "busy"}
          className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand px-3.5 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-60"
        >
          <DownloadGlyph />
          {state === "busy" ? "Preparing…" : "Download PDF"}
        </button>
        <span className="font-mono text-[0.6875rem] text-ink-faint">{data.file_name}</span>
      </div>
      {state === "failed" && (
        <p role="alert" className="mt-2 text-xs text-contested">
          The file could not be fetched. Try again in a moment.
        </p>
      )}
    </section>
  );
}
