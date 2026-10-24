/**
 * An answer's status, drawn (2026-10-24) — the one badge the notes, the
 * shell's My answers and its Today card all show, so a question cannot read
 * "Incorrect" in one place and "Strong" in another. Colour AND shape (WCAG
 * 1.4.1); the meanings are `notes.ts`'s.
 */
import type { ReactNode } from "react";

import { STATUS_META, type StatusMeta } from "../notes";
import type { AnswerStatus } from "../types";

const SHAPES: Record<StatusMeta["icon"], ReactNode> = {
  check: <path d="M3.5 8.5l3 3 6-6.5" />,
  half: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" />
    </>
  ),
  wave: <path d="M2 9c1.5-2.5 3-2.5 4 0s2.5 2.5 4 0 2.5-2.5 4 0" />,
  cross: <path d="M4.5 4.5l7 7m0-7l-7 7" />,
  circle: <circle cx="8" cy="8" r="5.5" />,
  question: (
    <>
      <path d="M5.8 6a2.3 2.3 0 1 1 3.2 2.1c-.6.3-1 .7-1 1.4v.4" />
      <circle cx="8" cy="12.6" r=".6" fill="currentColor" />
    </>
  ),
  dash: <path d="M4.5 8h7" />,
};

export function StatusIcon({ icon, size = 14 }: { icon: StatusMeta["icon"]; size?: number }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0"
    >
      {SHAPES[icon]}
    </svg>
  );
}

/** `label` is the report's own word for this answer when it has one
 *  ("Mostly correct", "Skipped"); `count` makes it a tally ("2 correct"). */
export function StatusBadge({
  status,
  label,
  qualifier,
  count,
  size = "md",
}: {
  status: AnswerStatus;
  label?: string | null;
  qualifier?: string | null;
  count?: number;
  size?: "sm" | "md";
}) {
  const meta = STATUS_META[status];
  const word = label ?? meta.label;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${meta.badge} ${
        size === "sm" ? "px-2 py-0.5 text-2xs" : "px-2.5 py-1 text-xs"
      }`}
    >
      <StatusIcon icon={meta.icon} size={size === "sm" ? 12 : 14} />
      {count !== undefined ? (
        <>
          <span data-numeric>{count}</span> {word.toLowerCase()}
        </>
      ) : (
        word
      )}
      {qualifier && <span className="font-normal opacity-80">· {qualifier}</span>}
    </span>
  );
}
