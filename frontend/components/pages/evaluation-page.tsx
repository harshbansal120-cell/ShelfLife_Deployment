"use client";

import { PageContainer } from "@/components/app-shell";
import { ErrorNote, Loading, PageHeader, Panel, Stat, percent } from "@/components/ui-kit";
import { useApi } from "@/hooks/use-api";
import { formatDate, formatDuration } from "@/lib/format";
import type { EvaluationData } from "@/lib/types";
import { workspaceApi } from "@/lib/workspace-api";

const STEPS: { command: string; what: string }[] = [
  {
    command: "uv run python ../scripts/eval_build.py",
    what: "Asks MODEL_STALE the questions in data/eval/questions.jsonl and drafts each answer's claims, without labels.",
  },
  {
    command: 'uv run python ../scripts/eval_label.py --labeller "Your Name"',
    what: "A person marks each claim stale, fresh or static, with a source URL checked that day. Labels are never filled in by a model.",
  },
  {
    command: "uv run python ../scripts/run_eval.py --second-run",
    what: "Runs ShelfLife on every labelled answer and writes eval/results.json, which this page reads.",
  },
  {
    command: "uv run python ../scripts/eval_tune.py",
    what: "Optional: re-scores the saved evidence with other half-lives and thresholds, without new API calls.",
  },
];

const VERDICT_ORDER = ["stale", "uncertain", "fresh", "unverified", "not_time_sensitive", "error", "missed"];

function Results({ summary, meta }: Required<Pick<EvaluationData, "summary" | "meta">>) {
  const predicted = VERDICT_ORDER.filter((verdict) =>
    Object.values(summary.confusion).some((row) => row[verdict] !== undefined),
  );
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Run on {formatDate(meta.run_date)} with {meta.model_fast} and {meta.model_strong}: {summary.answers} answers,{" "}
        {summary.gold_claims} hand-labelled claims (
        {Object.entries(summary.gold_counts)
          .map(([label, count]) => `${count} ${label}`)
          .join(", ")}
        ).
      </p>
      <dl className="grid grid-cols-2 gap-x-8 gap-y-7 rounded-2xl border bg-card p-6 shadow-[0_1px_2px_oklch(0_0_0/0.04)] sm:grid-cols-4">
        <Stat label="Claims found" value={percent(summary.extraction_recall)} hint="of labelled claims extracted" />
        <Stat label="Stale precision" value={percent(summary.stale_strict.precision)} hint="flagged stale and really stale" />
        <Stat label="Stale recall" value={percent(summary.stale_strict.recall)} hint="really stale and flagged stale" />
        <Stat label="F1" value={percent(summary.stale_strict.f1)} hint={`${percent(summary.stale_lenient.f1)} counting uncertain`} />
        <Stat label="False alarms" value={percent(summary.false_alarm_rate)} hint="fresh claims flagged stale" />
        <Stat label="Unverified" value={percent(summary.unverified_rate)} hint="no usable evidence found" />
        <Stat label="Average time" value={summary.avg_latency_ms ? formatDuration(summary.avg_latency_ms) : "–"} />
        <Stat label="Average cost" value={summary.avg_cost_usd === null ? "–" : `$${summary.avg_cost_usd.toFixed(4)}`} hint={meta.cache_hit_rate === null ? undefined : `${percent(meta.cache_hit_rate)} cache hits on re-run`} />
      </dl>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="What ShelfLife said, by true label" description="Rows are the hand labels; columns are ShelfLife's verdicts.">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-normal">Label</th>
                  {predicted.map((verdict) => (
                    <th key={verdict} className="py-1.5 pr-3 text-right font-normal">{verdict.replaceAll("_", " ")}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {Object.entries(summary.confusion).map(([gold, row]) => (
                  <tr key={gold} className="border-t">
                    <td className="py-1.5 pr-3 font-sans">{gold}</td>
                    {predicted.map((verdict) => (
                      <td key={verdict} className="py-1.5 pr-3 text-right">{row[verdict] ?? 0}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="By topic">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-normal">Topic</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Claims</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Found</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Precision</th>
                  <th className="py-1.5 text-right font-normal">Recall</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {Object.entries(summary.by_topic).map(([topic, row]) => (
                  <tr key={topic} className="border-t">
                    <td className="py-1.5 pr-3 font-sans">{topic.replaceAll("_", " ")}</td>
                    <td className="py-1.5 pr-3 text-right">{row.claims}</td>
                    <td className="py-1.5 pr-3 text-right">{percent(row.extraction_recall)}</td>
                    <td className="py-1.5 pr-3 text-right">{percent(row.precision)}</td>
                    <td className="py-1.5 text-right">{percent(row.recall)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}

export function EvaluationPage() {
  const { data, error, loading } = useApi(workspaceApi.evaluation);

  return (
    <PageContainer wide>
      <PageHeader
        title="Evaluation"
        description="How often ShelfLife is right, measured on real AI answers whose claims a person labelled against sources checked on the day."
      />
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data?.available && data.summary && data.meta && <Results summary={data.summary} meta={data.meta} />}
      {data && (
        <Panel
          title={data.available ? "Run it again" : "No evaluation results yet"}
          description={
            data.available
              ? "Labels go stale too, so re-label and re-run before quoting these numbers."
              : "The results appear here after a labelled run against live Bifrost and Tavily. Run these from the backend folder:"
          }
        >
          <ol className="flex flex-col gap-3">
            {STEPS.map((step, index) => (
              <li key={step.command} className="flex flex-col gap-1">
                <p className="text-sm">
                  <span className="mr-1.5 font-mono text-xs text-muted-foreground">{index + 1}.</span>
                  {step.what}
                </p>
                <code className="w-fit max-w-full overflow-x-auto rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs">{step.command}</code>
              </li>
            ))}
          </ol>
        </Panel>
      )}
    </PageContainer>
  );
}
