/**
 * The question library — the user's spec §9–§10 (2026-10-22).
 *
 * Every question a student starred, and every one the interview marked as
 * worth practising again (a misunderstanding that stood, a claim not backed
 * up, a question skipped). The two marks are independent and both are shown.
 * Each entry keeps its attempts — how it went each time, in the interview's
 * own words — and the last two are compared. Picking a few and pressing
 * "Practise these again" builds a session of exactly those questions, asked
 * as they were and followed up on the new answers.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { EmptyState, ErrorNote, PageHeader, SkeletonRows, relativeDays } from "@ai/core";

import { useCreateSession, useLibrary, useRemoveFromLibrary } from "../api";
import type { LibraryEntry } from "../types";

type Mark = "all" | "starred" | "flagged";

const MAX_REVISIT = 8;

function Entry({
  entry,
  picked,
  onPick,
  onRemove,
  removing,
}: {
  entry: LibraryEntry;
  picked: boolean;
  onPick: () => void;
  onRemove: () => void;
  removing: boolean;
}) {
  const last = entry.attempts.at(-1);
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={picked}
          onChange={onPick}
          aria-label="Pick this question to practise again"
          className="mt-1 h-4 w-4 accent-[var(--color-brand)]"
        />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-2xs text-ink-faint">
            {entry.topic && <span className="uppercase tracking-wide">{entry.topic}</span>}
            {entry.starred && (
              <span className="rounded-full border border-brand-line px-2 py-0.5 text-brand">★ Starred</span>
            )}
            {entry.flagged && (
              <span
                className="rounded-full border border-line bg-surface-sunken px-2 py-0.5 text-ink-soft"
                title="The interview marked this one as worth practising again"
              >
                Worth practising{entry.flagged_reason ? ` · ${entry.flagged_reason}` : ""}
              </span>
            )}
            {entry.difficulty_band && <span>· {entry.difficulty_band}</span>}
          </p>
          <p className="mt-1 text-sm font-medium leading-snug text-ink">{entry.stem}</p>
          {entry.claim_text && (
            <p className="mt-1 text-2xs text-ink-soft">From your resume: “{entry.claim_text}”</p>
          )}
          <p className="mt-2 text-2xs text-ink-faint">
            {entry.attempts.length === 0
              ? "Not answered yet."
              : `${entry.attempts.length} attempt${entry.attempts.length === 1 ? "" : "s"} · last ${relativeDays(last!.at)}${last?.outcome_words ? ` · ${last.outcome_words.toLowerCase()}` : ""}`}
          </p>
          {entry.last_time && (
            <p className="mt-2 rounded-lg bg-surface-sunken px-3 py-2 text-xs text-ink-soft">{entry.last_time}</p>
          )}
          {entry.attempts.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-2xs text-ink-faint hover:text-ink-soft">
                Your earlier answers
              </summary>
              <ol className="mt-2 space-y-3">
                {entry.attempts.map((attempt) => (
                  <li key={`${attempt.session_id}-${attempt.at}`} className="space-y-1">
                    <p className="text-2xs text-ink-faint">
                      {relativeDays(attempt.at)}
                      {attempt.outcome_words ? ` · ${attempt.outcome_words}` : ""}
                      {attempt.corrected === "prompted" ? " · corrected after a push" : ""}
                      {attempt.corrected === "self" ? " · corrected yourself" : ""}
                    </p>
                    {attempt.misconception && (
                      <p className="text-2xs text-ink-soft">The idea to revisit: {attempt.misconception}</p>
                    )}
                    {attempt.answers.map((said, position) => (
                      <p key={`${position}-${said.slice(0, 12)}`} className="turn-candidate whitespace-pre-wrap">
                        {said}
                      </p>
                    ))}
                    <Link to={`/mock/${attempt.session_id}/report`} className="text-2xs text-brand hover:underline">
                      That interview's notes →
                    </Link>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
        <button
          type="button"
          onClick={onRemove}
          disabled={removing}
          className="text-2xs text-ink-faint hover:text-ink disabled:opacity-60"
          aria-label="Remove from your library"
        >
          Remove
        </button>
      </div>
    </li>
  );
}

export function QuestionLibrary() {
  const library = useLibrary();
  const remove = useRemoveFromLibrary();
  const create = useCreateSession();
  const navigate = useNavigate();
  const [mark, setMark] = useState<Mark>("all");
  const [topic, setTopic] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const shown = useMemo(() => {
    const wanted = topic.trim().toLowerCase();
    return (library.data ?? []).filter(
      (entry) =>
        (mark === "all" || (mark === "starred" ? entry.starred : entry.flagged)) &&
        (!wanted || entry.topic.toLowerCase().includes(wanted) || entry.stem.toLowerCase().includes(wanted)),
    );
  }, [library.data, mark, topic]);

  const toggle = (id: string) =>
    setPicked((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : current.length >= MAX_REVISIT
          ? current
          : [...current, id],
    );

  return (
    <div className="mx-auto max-w-(--container-conversation)">
      <PageHeader
        title="Your question library"
        subtitle="Questions you saved, and the ones the interview marked as worth another go."
        how={
          <>
            <p>
              Star a question during an interview or in its notes and it lands here. The interview
              adds the ones where something didn't hold — and both marks show, side by side.
            </p>
            <p>
              Pick up to {MAX_REVISIT} and practise them again: they are asked as they were, the
              follow-ups come from what you say this time, and the notes compare the two attempts.
            </p>
          </>
        }
      />

      <div className="mt-6 flex flex-wrap items-center gap-2" role="group" aria-label="Show">
        {(["all", "starred", "flagged"] as Mark[]).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={mark === option}
            onClick={() => setMark(option)}
            className={`h-8 rounded-lg border px-3 text-xs font-medium ${
              mark === option ? "border-brand-line bg-brand-soft text-brand" : "border-line text-ink-soft hover:text-ink"
            }`}
          >
            {option === "all" ? "All" : option === "starred" ? "Starred by you" : "Worth practising"}
          </button>
        ))}
        <input
          type="search"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="Filter by topic"
          className="ml-auto h-8 w-48 rounded-lg border border-line bg-surface px-3 text-xs text-ink placeholder:text-ink-faint"
        />
      </div>

      <div className="mt-4">
        {library.isLoading ? (
          <SkeletonRows label="Opening your library" rows={4} />
        ) : library.isError ? (
          <ErrorNote message="Your library could not be loaded." onRetry={() => library.refetch()} />
        ) : shown.length === 0 ? (
          <EmptyState title="Nothing here yet" icon="star">
            Star a question during an interview, or in its notes, and it will be here to practise
            again. Questions where something didn't hold are added for you.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {shown.map((entry) => (
              <Entry
                key={entry.id}
                entry={entry}
                picked={picked.includes(entry.id)}
                onPick={() => toggle(entry.id)}
                onRemove={() => {
                  setPicked((current) => current.filter((x) => x !== entry.id));
                  remove.mutate(entry.id);
                }}
                removing={remove.isPending}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="sticky bottom-4 mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3 shadow-raised">
        <button
          type="button"
          disabled={picked.length === 0 || create.isPending}
          onClick={() =>
            create.mutate(
              {
                minutes: Math.max(10, picked.length * 3 + 2),
                mode: "practice",
                revisit: picked,
              },
              { onSuccess: (session) => navigate(`/mock/${session.id}/plan`) },
            )
          }
          className="inline-flex h-10 items-center rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
        >
          {create.isPending ? "Building it…" : `Practise ${picked.length || ""} again`.replace("  ", " ")}
        </button>
        <p className="text-2xs text-ink-faint">
          {picked.length === 0
            ? "Pick the questions to practise."
            : `${picked.length} picked · up to ${MAX_REVISIT}`}
        </p>
        <Link to="/mock" className="ml-auto text-xs text-ink-soft hover:text-ink">
          Back to interviews
        </Link>
      </div>
    </div>
  );
}
