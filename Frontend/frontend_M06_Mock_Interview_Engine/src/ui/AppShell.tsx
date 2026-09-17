/**
 * The chrome: one line at the top, and nothing else.
 *
 * M13 argued a top bar over a rail because its context is one turn. The same
 * holds here for a stronger reason — the student is mid-conversation, and a
 * permanent 240px rail would spend the measure the question needs on links
 * nobody clicks during an interview.
 *
 * The candidate control is the dev identity shape M01 established, and it is
 * here for the same reason it is there: hardcoding one id hides scoping bugs,
 * and generating one per load leaves the history permanently empty. It goes
 * when Platform_Shell grows a login (PLATFORM_TODO §1).
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

import { DependencyAlert } from "@ai/core";

import { useDeps } from "../api";
import {
  DEFAULT_CANDIDATE_ID,
  getCandidateId,
  setCandidateId,
  subscribeCandidateId,
} from "../identity";

const NAV = [
  { to: "/mock", label: "Interview" },
  { to: "/mock/system", label: "System" },
];

function useCandidate(): string {
  return useSyncExternalStore(subscribeCandidateId, getCandidateId, () => DEFAULT_CANDIDATE_ID);
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("m06.theme") as "light" | "dark") || "light",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("m06.theme", theme);
  }, [theme]);

  return (
    <button
      type="button"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="rounded-md px-2 py-1 text-ink-soft transition-colors hover:bg-surface-sunken hover:text-ink"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      <span aria-hidden className="text-sm">
        {theme === "dark" ? "☀" : "☾"}
      </span>
    </button>
  );
}

function CandidateControl() {
  const candidate = useCandidate();
  const [draft, setDraft] = useState(candidate);

  useEffect(() => setDraft(candidate), [candidate]);

  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        setCandidateId(draft);
      }}
    >
      <label htmlFor="candidate" className="text-2xs uppercase tracking-wide text-ink-faint">
        Student
      </label>
      <input
        id="candidate"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => setCandidateId(draft)}
        spellCheck={false}
        className="w-[15ch] rounded-md border border-line bg-surface px-2 py-1 font-mono text-2xs text-ink-soft focus:border-brand focus:outline-none"
        title="No login exists yet (PLATFORM_TODO §1). This is the dev identity."
      />
    </form>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const deps = useDeps();
  const missing = (deps.data ?? []).filter((row) => !row.available);

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex h-12 max-w-6xl items-center gap-4 px-4">
          <Link to="/mock" className="text-sm font-semibold tracking-tight">
            Mock interview
            <span className="ml-2 font-mono text-2xs font-normal text-ink-faint">M06</span>
          </Link>
          <nav aria-label="Sections" className="flex items-center gap-1 text-sm">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  `rounded-md px-2 py-1 transition-colors ${
                    isActive ? "bg-surface-sunken text-ink" : "text-ink-soft hover:text-ink"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <CandidateControl />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {missing.length > 0 && (
        <div className="mx-auto max-w-6xl px-4 pt-4">
          {/* Rule 2 at the top of the page: a missing module narrows the
              session's scope, and says which and how. */}
          <DependencyAlert
            degraded={missing.map((row) => ({
              feature: row.name,
              needs_module: row.module_id,
              needs_module_name: row.name,
              explanation: row.on_missing,
            }))}
          />
        </div>
      )}

      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
