/**
 * What this module is running on — the developer's page, not a student's.
 *
 * Two things worth having in the product rather than in a log: which upstreams
 * are up (and the sentence a student is shown when one is not), and which
 * agents are running or ablated. Master plan §26.2 makes ablation a config
 * flag so "what does the multi-agent design buy us?" is an experiment; a
 * switch nobody can see is a switch nobody runs.
 */

import { Card, DependencyTable, ErrorNote, Spinner } from "@ai/core";

import { useAgents, useDeps, useHealth } from "../api";

export function SystemPage() {
  const deps = useDeps();
  const agents = useAgents();
  const health = useHealth();

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">System</h1>
        <p className="mt-2 text-sm text-ink-soft">
          {health.data
            ? `M06 is up, prompts ${health.data.prompt_version}.`
            : "Checking the engine…"}{" "}
          {agents.data && (agents.data.model_on ? "A model is configured." : "No model is configured — questions and probes fall back to their authored wording.")}
        </p>
      </header>

      <section>
        <h2 className="text-sm font-semibold text-ink">Upstream modules</h2>
        <p className="mt-1 text-2xs text-ink-faint">
          None of these is required. Each one missing narrows what a session can do, and the
          session says which.
        </p>
        <div className="mt-3">
          {deps.isLoading ? (
            <Spinner label="Probing upstreams…" />
          ) : deps.isError ? (
            <ErrorNote message="Could not read the dependency report." onRetry={() => deps.refetch()} />
          ) : (
            <DependencyTable statuses={deps.data ?? []} />
          )}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-ink">Agents</h2>
        <div className="mt-3 space-y-2">
          {(agents.data?.agents ?? []).map((agent) => (
            <Card key={agent.name} title={agent.name}>
              <p className="text-sm text-ink-soft">{agent.purpose}</p>
              <p className="mt-2 font-mono text-2xs text-ink-faint">
                {agent.side} · {agent.tier ?? "no model"} ·{" "}
                {agent.enabled ? "on" : "ABLATED"} · {agent.switch}
              </p>
            </Card>
          ))}
        </div>
      </section>

      {agents.data?.step_graph && (
        <section>
          <h2 className="text-sm font-semibold text-ink">One step of the interview</h2>
          <p className="mt-1 text-2xs text-ink-faint">
            The graph the engine actually compiled, as it reports itself.
          </p>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-surface-sunken p-3 font-mono text-2xs leading-relaxed text-ink-soft">
            {agents.data.step_graph}
          </pre>
        </section>
      )}
    </div>
  );
}
