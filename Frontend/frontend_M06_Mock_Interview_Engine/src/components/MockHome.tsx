/**
 * The setup screen — spec §2.2 ("must take under 60 seconds").
 *
 * What it offers is only what the engine can actually do today, which is the
 * whole discipline of this screen: a modality picker with a disabled "Voice"
 * radio, or a Final Boss mode that changes nothing yet, would be a promise the
 * session breaks. So there is one choice — how long — and a line saying what
 * is coming.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Card, EmptyState, ErrorNote, Spinner } from "@ai/core";

import { useCreateSession, useHistory } from "../api";
import type { SessionSummary } from "../types";

const LENGTHS = [
  { minutes: 15, label: "15 min", hint: "a few questions" },
  { minutes: 30, label: "30 min", hint: "a proper round" },
  { minutes: 45, label: "45 min", hint: "a full interview" },
];

const LIVE = new Set(["planned", "live", "paused"]);

function relative(iso: string): string {
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

function HistoryRow({ session }: { session: SessionSummary }) {
  const navigate = useNavigate();
  const unfinished = LIVE.has(session.status);
  return (
    <li className="flex items-center justify-between gap-4 border-b border-line py-3 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm text-ink">
          {session.kind === "drill" ? "Defend drill" : `${session.requested_minutes}-minute mock`}
          <span className="ml-2 text-2xs uppercase tracking-wide text-ink-faint">
            {session.status}
          </span>
        </p>
        <p className="text-2xs text-ink-faint">{relative(session.created_at)}</p>
      </div>
      <Button
        variant={unfinished ? "primary" : "ghost"}
        size="sm"
        onClick={() =>
          navigate(unfinished ? `/mock/${session.id}` : `/mock/${session.id}/report`)
        }
      >
        {unfinished ? "Continue" : "Notes"}
      </Button>
    </li>
  );
}

export function MockHome() {
  const [minutes, setMinutes] = useState(30);
  const create = useCreateSession();
  const history = useHistory();
  const navigate = useNavigate();

  const unfinished = (history.data ?? []).find((session) => LIVE.has(session.status));

  return (
    <div className="mx-auto grid max-w-5xl gap-8 md:grid-cols-[1.4fr_1fr]">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Practise an interview</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-soft">
          A real interviewer asks a question, listens to your answer, and keeps going until it
          finds the edge of what you know. This one does the same, typed, and tells you
          afterwards where the edge was.
        </p>

        <fieldset className="mt-6">
          <legend className="text-2xs uppercase tracking-wide text-ink-faint">How long</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {LENGTHS.map((option) => (
              <button
                key={option.minutes}
                type="button"
                aria-pressed={minutes === option.minutes}
                onClick={() => setMinutes(option.minutes)}
                className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                  minutes === option.minutes
                    ? "border-brand bg-brand-soft text-ink"
                    : "border-line bg-surface text-ink-soft hover:border-line-strong"
                }`}
              >
                <span className="block text-sm font-medium">{option.label}</span>
                <span className="block text-2xs text-ink-faint">{option.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button
            onClick={() => create.mutate({ minutes }, { onSuccess: (s) => navigate(`/mock/${s.id}`) })}
            disabled={create.isPending || Boolean(unfinished)}
          >
            {create.isPending ? "Setting up…" : "Start interview"}
          </Button>
          <p className="text-2xs text-ink-faint">
            You can pause once, for five minutes. Ending early still gives you notes.
          </p>
        </div>

        {unfinished && (
          <div className="mt-4 rounded-lg border border-brand-line bg-brand-soft p-3 text-sm">
            <p className="text-ink">
              You have an interview in progress — two at once would overwrite each other.
            </p>
            {/* `Button` sets its own className, so spacing goes on a wrapper. */}
            <div className="mt-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => navigate(`/mock/${unfinished.id}`)}
              >
                Go back to it
              </Button>
            </div>
          </div>
        )}

        {create.isError && (
          <div className="mt-4">
            <ErrorNote
              message="That didn't start."
              detail={create.error instanceof Error ? create.error.message : undefined}
              onRetry={() => create.reset()}
            />
          </div>
        )}

        <p className="mt-8 max-w-prose text-2xs leading-relaxed text-ink-faint">
          Typed only for now — speaking out loud arrives with the voice engine. Questions come
          from the platform's bank; when it cannot reach it, the interview says so and runs from a
          short backup set instead of pretending.
        </p>
      </section>

      <aside>
        <Card title="Your sessions">
          {history.isLoading ? (
            <Spinner label="Looking up your sessions…" />
          ) : (history.data ?? []).length === 0 ? (
            <EmptyState title="Nothing yet" icon="clock">
              Your interviews and drills will be listed here, with the notes from each.
            </EmptyState>
          ) : (
            <ul>
              {(history.data ?? []).map((session) => (
                <HistoryRow key={session.id} session={session} />
              ))}
            </ul>
          )}
        </Card>
      </aside>
    </div>
  );
}
