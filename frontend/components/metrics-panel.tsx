import { Database, Shuffle, Wallet } from "lucide-react";

import { formatCost, formatDuration, formatResetPeriod } from "@/lib/format";
import type {
  BudgetStatus,
  LlmStageMetrics,
  Metrics,
  SearchStageMetrics,
} from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  extract: "Extract claims",
  adjudicate: "Judge evidence",
  decision: "Re-judge advice",
  rewrite: "Rewrite answer",
  regression: "Ask model under test",
  generate: "Generate answer",
};

function isLlmStage(stage: LlmStageMetrics | SearchStageMetrics): stage is LlmStageMetrics {
  return "calls" in stage;
}

/** Group identical fallbacks, so six identical lines read as one line "× 6". */
export function groupFallbacks(metrics: Metrics) {
  const groups = new Map<string, { stage: string; served: string; primary: string; count: number }>();
  for (const event of metrics.fallback_events) {
    const served = `${event.provider}/${event.model}`;
    const primary = `${event.primary_provider}/${event.primary_model}`;
    const key = `${event.stage}|${served}|${primary}`;
    const group = groups.get(key) ?? { stage: event.stage, served, primary, count: 0 };
    group.count += 1;
    groups.set(key, group);
  }
  return [...groups.values()];
}

function Stat({
  label,
  value,
  previous,
}: {
  label: string;
  value: string;
  previous?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm tabular-nums">
        {value}
        {previous !== undefined && previous !== value && (
          <span className="block text-xs text-muted-foreground">was {previous}</span>
        )}
      </dd>
    </div>
  );
}

function credits(metrics: Metrics): string {
  const search = metrics.per_stage.retrieve as SearchStageMetrics | undefined;
  return search?.cached_searches
    ? `${metrics.tavily_credits} (${search.cached_searches} cached)`
    : metrics.tavily_credits.toLocaleString();
}

function BudgetLine({ budget }: { budget: BudgetStatus | null }) {
  if (!budget?.configured) return null;
  const limits = budget.budgets.filter((item) => item.max_limit !== null);
  return (
    <p className="flex items-start gap-2 text-xs">
      <Wallet className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>
        Virtual key {budget.name ? <span className="font-medium">{budget.name}</span> : null}
        {limits.length === 0
          ? " has no budget set."
          : limits.map((item, index) => {
              const period = formatResetPeriod(item.reset_duration);
              return (
                <span key={index}>
                  {": "}
                  <span className="font-mono tabular-nums">
                    ${item.current_usage.toFixed(4)} of ${item.max_limit!.toFixed(2)}
                  </span>{" "}
                  used{period ? ` this ${period}` : ""}
                </span>
              );
            })}
        {budget.is_active === false && " The key is inactive."}
      </span>
    </p>
  );
}

export function MetricsPanel({
  metrics,
  previous,
  running,
  budget,
}: {
  metrics: Metrics;
  previous: Metrics | null;
  running: boolean;
  budget: BudgetStatus | null;
}) {
  const stages = Object.entries(metrics.per_stage).flatMap(([name, stage]) =>
    isLlmStage(stage) ? [{ name, stage }] : [],
  );
  const tokens = (m: Metrics) => (m.tokens_in + m.tokens_out).toLocaleString();
  const was = <T,>(format: (m: Metrics) => T) => (previous ? format(previous) : undefined);

  return (
    <section aria-labelledby="metrics-heading" className="flex flex-col gap-4 px-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="metrics-heading" className="text-sm font-semibold">
          Run metrics{" "}
          {running && <span className="font-normal text-muted-foreground">· updating</span>}
        </h2>
        {previous && !running && (
          <p className="text-xs text-muted-foreground">Compared with the previous run</p>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Stat
          label={running ? "Time so far" : "Total time"}
          value={formatDuration(metrics.latency_ms)}
          previous={running ? undefined : was((m) => formatDuration(m.latency_ms))}
        />
        <Stat
          label="LLM calls"
          value={metrics.llm_calls.toLocaleString()}
          previous={was((m) => m.llm_calls.toLocaleString())}
        />
        <Stat label="Tokens" value={tokens(metrics)} previous={was(tokens)} />
        <Stat
          label="LLM cost"
          value={formatCost(metrics.cost_usd, metrics.unpriced_calls)}
          previous={was((m) => formatCost(m.cost_usd, m.unpriced_calls))}
        />
        <Stat
          label="Bifrost cache hits"
          value={metrics.cache_hits.toLocaleString()}
          previous={was((m) => m.cache_hits.toLocaleString())}
        />
        <Stat label="Tavily credits" value={credits(metrics)} previous={was(credits)} />
      </dl>

      {stages.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-md text-xs">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-normal">Stage</th>
                <th className="py-1.5 pr-3 text-right font-normal">Calls</th>
                <th className="py-1.5 pr-3 text-right font-normal">Tokens in</th>
                <th className="py-1.5 pr-3 text-right font-normal">Tokens out</th>
                <th className="py-1.5 pr-3 text-right font-normal">Cache hits</th>
                <th className="py-1.5 text-right font-normal">Model time</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {stages.map(({ name, stage }) => (
                <tr key={name} className="border-t">
                  <td className="py-1.5 pr-3 font-sans">{STAGE_LABELS[name] ?? name}</td>
                  <td className="py-1.5 pr-3 text-right">{stage.calls}</td>
                  <td className="py-1.5 pr-3 text-right">{stage.tokens_in.toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right">{stage.tokens_out.toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right">{stage.cache_hits}</td>
                  <td className="py-1.5 text-right">{formatDuration(stage.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-col gap-1.5 text-xs">
        {groupFallbacks(metrics).map((group) => (
          <p key={`${group.stage}|${group.served}|${group.primary}`} className="flex items-start gap-2">
            <Shuffle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              <span className="font-medium">Served by fallback: {group.served}</span>{" "}
              <span className="text-muted-foreground">
                instead of {group.primary} ({STAGE_LABELS[group.stage] ?? group.stage}
                {group.count > 1 ? `, ${group.count} calls` : ""})
              </span>
            </span>
          </p>
        ))}
        {!running && metrics.llm_calls > 0 && metrics.cache_hits === metrics.llm_calls && (
          <p className="flex items-start gap-2">
            <Database className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Every LLM call was answered from Bifrost&apos;s cache.
          </p>
        )}
        <BudgetLine budget={budget} />
      </div>
    </section>
  );
}
