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

import logo from "../assets/logo.png";
import { useDeps } from "../api";
import {
  DEFAULT_CANDIDATE_ID,
  getCandidateId,
  setCandidateId,
  subscribeCandidateId,
} from "../identity";

const NAV = [
  { to: "/mock", label: "Practise" },
  { to: "/mock/library", label: "Question library" },
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
        {theme === "dark" ? "Light" : "Dark"}
      </span>
    </button>
  );
}

function CandidateControl() {
  const candidate = useCandidate();
  const [draft, setDraft] = useState(candidate);

  useEffect(() => setDraft(candidate), [candidate]);

  return (
    <details className="relative">
      <summary
        className="grid size-9 cursor-pointer list-none place-items-center rounded-full bg-[#c9f4c8] text-[11px] font-semibold text-[#192d28] [&::-webkit-details-marker]:hidden"
        title="Who you are practising as"
      >
        {candidate.slice(0, 2).toUpperCase()}
      </summary>
      <form
        className="absolute right-0 z-20 mt-2 flex w-64 flex-col gap-2 rounded-xl border border-line bg-surface p-3.5 shadow-[0_16px_48px_rgba(22,59,39,0.12)]"
        onSubmit={(event) => {
          event.preventDefault();
          setCandidateId(draft);
        }}
      >
        <label htmlFor="candidate" className="text-[11px] text-ink-soft">
          Student id
        </label>
        <input
          id="candidate"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => setCandidateId(draft)}
          spellCheck={false}
          className="rounded-lg border border-line bg-surface px-2.5 py-2 font-mono text-2xs text-ink-soft focus:border-brand focus:outline-none"
        />
        <p className="text-[10px] leading-normal text-ink-faint">No login exists yet (PLATFORM_TODO §1), so this is the dev identity.</p>
      </form>
    </details>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const deps = useDeps();
  const missing = (deps.data ?? []).filter((row) => !row.available);

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex min-h-[72px] max-w-[1440px] flex-wrap items-center gap-x-8 gap-y-1 px-5 py-2 md:px-10 xl:px-20">
          <Link to="/mock" className="inline-flex items-center no-underline" aria-label="Home">
            <img src={logo} alt="" className="h-9 w-auto" />
          </Link>
          <nav aria-label="Sections" className="flex items-center gap-6 text-[13px]">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  `border-b-2 py-1 no-underline transition-colors ${
                    isActive ? "border-brand font-semibold text-ink" : "border-transparent text-ink-soft hover:text-ink"
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

      <main className="mx-auto max-w-[1440px] px-5 py-8 md:px-10 xl:px-20 xl:py-10">{children}</main>
    </div>
  );
}
