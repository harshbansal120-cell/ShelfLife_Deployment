"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { RefreshCw, ShieldAlert, UserCog } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { CategoryBars, DailyBars } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorNote, Loading, PageHeader, Panel, Stat, percent } from "@/components/ui-kit";
import { Watchlist } from "@/components/watchlist";
import { useApi } from "@/hooks/use-api";
import { formatCost, formatDate, formatDuration } from "@/lib/format";
import type { CheckSummary, Verdict } from "@/lib/types";
import { CATEGORY_LABELS, VERDICT_INFO } from "@/lib/verdicts";
import { contextLines, workspaceApi } from "@/lib/workspace-api";

const COUNT_ORDER: Verdict[] = ["stale", "uncertain", "fresh", "unverified", "error"];
const GUARD = { show: "Safe to show", show_with_warning: "Show with warning", withhold: "Hold back" };

export function CheckRows({ checks }: { checks: CheckSummary[] }) {
  if (checks.length === 0) return <EmptyState>No checks yet. Run one on the Check page.</EmptyState>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-xl text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-1.5 pr-3 font-normal">Checked</th>
            <th className="py-1.5 pr-3 font-normal">Answer</th>
            <th className="py-1.5 pr-3 text-right font-normal">Freshness</th>
            <th className="py-1.5 pr-3 font-normal">Claims</th>
            <th className="py-1.5 font-normal">Advice</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((check) => (
            <tr key={check.id} className="border-t align-top">
              <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                {formatDate(check.checked_at.slice(0, 10))}
              </td>
              <td className="max-w-80 py-2 pr-3">
                <Link href={`/?check=${check.id}`} className="underline-offset-4 hover:underline">
                  {check.question ?? check.answer_excerpt}
                </Link>
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums">{check.answer_score ?? "–"}</td>
              <td className="py-2 pr-3 text-xs text-muted-foreground">
                {COUNT_ORDER.flatMap((verdict) =>
                  check.verdict_counts[verdict] ? [`${check.verdict_counts[verdict]} ${VERDICT_INFO[verdict].label.toLowerCase()}`] : [],
                ).join(" · ") || "none"}
              </td>
              <td className="py-2 text-xs">{check.guard ? GUARD[check.guard] : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DashboardPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(workspaceApi.dashboard);

  return (
    <PageContainer wide>
      <PageHeader
        title="Dashboard"
        description="Everything ShelfLife has checked: how fresh the answers are, what is due for a re-check, which saved contexts changed, and what Bifrost and Tavily did."
        actions={
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-7 rounded-2xl border bg-card p-6 shadow-[0_1px_2px_oklch(0_0_0/0.04)] sm:grid-cols-4">
            <Stat label="Checks" value={data.totals.checks} />
            <Stat label="Claims checked" value={data.totals.claims_checked} />
            <Stat label="Found stale" value={percent(data.totals.stale_rate)} hint={`${data.totals.verdicts.stale ?? 0} claims`} />
            <Stat label="Average time per check" value={data.usage.avg_latency_ms ? formatDuration(data.usage.avg_latency_ms) : "–"} />
            <Stat label="LLM cost" value={formatCost(data.usage.cost_usd, data.usage.unpriced_calls)} hint={`${data.usage.llm_calls} calls · ${data.usage.tokens.toLocaleString()} tokens`} />
            <Stat label="Bifrost cache hits" value={data.usage.cache_hits} />
            <Stat label="Fallbacks used" value={data.usage.fallbacks} />
            <Stat label="Tavily credits" value={data.usage.tavily_credits} />
          </dl>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Checks per day" description="The last 14 days. Hover a bar for that day's stale claims.">
              <DailyBars data={data.daily} />
            </Panel>
            <Panel title="Verdicts by kind of fact" description="Every time-sensitive claim checked, grouped by what it is about.">
              {Object.keys(data.by_category).length ? (
                <CategoryBars data={data.by_category} labels={CATEGORY_LABELS} />
              ) : (
                <EmptyState>No claims checked yet.</EmptyState>
              )}
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel
              title="Context changes"
              description="Checks made with a saved profile that has changed since. Their verdicts may not fit the reader any more."
            >
              {data.drift.length === 0 ? (
                <EmptyState>No saved profile has changed since its checks.</EmptyState>
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.drift.map((alert) => (
                    <li key={alert.profile_id} className="flex flex-col gap-1.5 text-sm">
                      <p className="flex items-center gap-1.5 font-medium">
                        <UserCog className="size-4" aria-hidden />
                        {alert.profile_name} is now: {contextLines(alert.context).join(" · ") || "no context"}
                      </p>
                      <ul className="flex flex-col gap-1 pl-6 text-muted-foreground">
                        {alert.checks.map((check) => (
                          <li key={check.id}>
                            <Link href={`/?check=${check.id}`} className="underline-offset-4 hover:underline">
                              {check.question ?? check.answer_excerpt}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Answers held back" description="Checks where ShelfLife advised apps not to show the answer.">
              {data.alerts.length === 0 ? (
                <EmptyState>No answers needed holding back.</EmptyState>
              ) : (
                <ul className="flex flex-col gap-2.5 text-sm">
                  {data.alerts.map((alert) => (
                    <li key={alert.check_id} className="flex items-start gap-2">
                      <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                      <span>
                        <Link href={`/?check=${alert.check_id}`} className="underline-offset-4 hover:underline">
                          {alert.answer_excerpt}
                        </Link>
                        <span className="block text-xs text-muted-foreground">{alert.text}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <Panel title="Due for a re-check" description="Claims whose evidence will soon be too old to trust, over the next 14 days.">
            {data.watchlist.length === 0 ? (
              <EmptyState>Nothing is due in the next 14 days.</EmptyState>
            ) : (
              <Watchlist
                bare
                items={data.watchlist}
                onOpen={(id) => router.push(`/?check=${id}`)}
                onRecheck={(id) => router.push(`/?recheck=${id}`)}
              />
            )}
          </Panel>

          <Panel title="Recent checks">
            <CheckRows checks={data.recent} />
          </Panel>
        </>
      )}
    </PageContainer>
  );
}
