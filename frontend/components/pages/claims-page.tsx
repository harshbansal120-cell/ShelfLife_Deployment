"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BadgeCheck, Search } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorNote, Loading, NativeSelect, PageHeader, Panel } from "@/components/ui-kit";
import { VerdictBadge } from "@/components/verdict-badge";
import { useApi } from "@/hooks/use-api";
import { API_URL } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Passport } from "@/lib/types";
import { CATEGORY_LABELS, KIND_LABELS } from "@/lib/verdicts";
import { workspaceApi } from "@/lib/workspace-api";

function PassportCard({ id }: { id: string }) {
  const { data, error, loading } = useApi(() => workspaceApi.claim(id), id);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return null;
  const rows: [string, string][] = [
    ["Claim ID", data.id],
    ["Kind", `${KIND_LABELS[data.kind]} · ${CATEGORY_LABELS[data.category]}`],
    ["First checked", formatDate(data.first_checked.slice(0, 10))],
    ["Last checked", formatDate(data.last_checked.slice(0, 10))],
    ["Checks", `${data.checks} across ${data.answers} ${data.answers === 1 ? "answer" : "answers"}`],
    ["Sources now", data.sources.join(", ") || "none"],
    ["Strongest source", data.authority === null ? "none" : data.authority >= 1 ? "Official" : data.authority >= 0.8 ? "Major news" : data.authority >= 0.6 ? "Trade press or Wikipedia" : "Other"],
    ["Re-check by", data.recheck_by ? formatDate(data.recheck_by) : "–"],
  ];
  return (
    <Panel
      title="Verification passport"
      description="A record of every check of this claim. It shows what was verified and when, not a promise that it stays true."
      actions={
        <a href={`${API_URL}/api/claims/${data.id}`} target="_blank" rel="noopener noreferrer" className="text-xs underline underline-offset-4">
          JSON
        </a>
      }
    >
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <VerdictBadge verdict={data.status} />
          {data.score !== null && <span className="font-mono text-sm tabular-nums">{data.score}/100</span>}
        </div>
        <p className="text-sm leading-6 font-medium">{data.text}</p>
        {data.current_value && <p className="text-sm text-muted-foreground">Sources now say: {data.current_value}</p>}
      </div>
      <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className={label === "Claim ID" ? "font-mono" : ""}>{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-2 border-t pt-3">
        <h3 className="text-sm font-semibold">History</h3>
        <ul className="flex flex-col gap-1.5">
          {(data.history ?? []).slice().reverse().map((entry) => (
            <li key={entry.check_id} className="flex flex-wrap items-center gap-2 text-sm">
              <VerdictBadge verdict={entry.verdict} />
              <Link href={`/?check=${entry.check_id}`} className="text-muted-foreground underline-offset-4 hover:underline">
                {new Date(entry.checked_at).toLocaleString()}
              </Link>
              {entry.current_value && <span className="text-xs text-muted-foreground">· {entry.current_value}</span>}
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

export function ClaimsPage() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const { data, error, loading } = useApi(() => workspaceApi.claims(status, search), `${status}|${search}`);

  // Wait for a pause in typing before searching.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) Promise.resolve().then(() => setSelected(id));
  }, []);

  return (
    <PageContainer wide>
      <PageHeader
        title="Claims"
        description="Every claim ShelfLife has checked, with one verification record per claim, so an app can see when a fact was last confirmed before trusting it again."
      />
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1">
          <span className="sr-only">Search claims</span>
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input className="h-9 pl-8" placeholder="Search claims" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <NativeSelect aria-label="Filter by verdict" className="sm:w-48" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All verdicts</option>
          <option value="stale">Stale</option>
          <option value="uncertain">Uncertain</option>
          <option value="fresh">Fresh</option>
          <option value="unverified">Unverified</option>
          <option value="not_time_sensitive">Doesn&apos;t change</option>
        </NativeSelect>
      </div>
      <ErrorNote message={error} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="min-w-0">
          {loading && !data && <Loading />}
          {data && data.claims.length === 0 && <EmptyState>No claims match.</EmptyState>}
          {data && data.claims.length > 0 && (
            <ul className="flex flex-col divide-y rounded-2xl border bg-card">
              {data.claims.map((claim: Passport) => (
                <li key={claim.id}>
                  <button
                    type="button"
                    aria-current={selected === claim.id ? "true" : undefined}
                    onClick={() => setSelected(claim.id)}
                    className="flex w-full flex-col gap-1.5 px-4 py-3 text-left outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring aria-[current=true]:bg-muted"
                  >
                    <span className="text-sm leading-6">{claim.text}</span>
                    <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <VerdictBadge verdict={claim.status} />
                      <span className="font-mono">{claim.id}</span>
                      <span>{KIND_LABELS[claim.kind]}</span>
                      <span>checked {claim.checks}×</span>
                      <span>last {formatDate(claim.last_checked.slice(0, 10))}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="min-w-0 lg:sticky lg:top-6 lg:self-start">
          {selected ? (
            <PassportCard id={selected} />
          ) : (
            <p className="flex items-center gap-2 rounded-xl border px-4 py-6 text-sm text-muted-foreground">
              <BadgeCheck className="size-4" aria-hidden />
              Select a claim to see its verification passport.
            </p>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
