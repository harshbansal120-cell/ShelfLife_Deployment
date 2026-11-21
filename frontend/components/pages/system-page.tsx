"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { BookmarkPlus, CircleAlert, CircleCheck, Copy, LoaderCircle, RefreshCw } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { IntegrationsPanel } from "@/components/integrations-panel";
import { Button } from "@/components/ui/button";
import { ErrorNote, Loading, PageHeader, Panel } from "@/components/ui-kit";
import { useApi } from "@/hooks/use-api";
import { API_URL, ApiError } from "@/lib/api";
import { formatResetPeriod } from "@/lib/format";
import { workspaceApi } from "@/lib/workspace-api";

function Status({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      {ok ? <CircleCheck className="size-4 text-fresh" aria-hidden /> : <CircleAlert className="size-4 text-stale" aria-hidden />}
      {children}
    </span>
  );
}

function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[10rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const ENDPOINTS: [string, string, string][] = [
  ["POST", "/api/verify", "Check an answer and wait for the full result (for apps and scripts)."],
  ["POST", "/api/checks", "Start a check in the background; returns its id."],
  ["GET", "/api/checks/{id}/events", "Live progress as server-sent events."],
  ["GET", "/api/checks/{id}", "A finished check."],
  ["GET", "/api/checks/{id}/export?format=md", "The check as a Markdown report (or format=json)."],
  ["POST", "/api/compare", "Compare 2 to 5 apps' answers to the same question."],
  ["GET", "/api/claims", "The claim registry (verification passports)."],
  ["GET", "/api/claims/{id}", "One claim's passport and history."],
  ["GET", "/api/dashboard", "Totals, charts, watchlist, context changes and usage."],
  ["GET", "/api/watchlist", "Claims due for a re-check."],
  ["GET, POST", "/api/tests", "Regression tests; POST /api/tests/{id}/run runs one."],
  ["GET, POST", "/api/profiles", "Context profiles; PUT and DELETE /api/profiles/{id}."],
  ["POST", "/api/links/check", "Check that sources still exist and still say the same."],
  ["POST", "/api/batch", "Check up to 20 answers; poll GET /api/batch/{id}."],
  ["GET", "/api/system", "This page's data."],
  ["GET", "/api/health", "Whether Bifrost and Tavily are reachable."],
];

const CURL = `curl -s -X POST ${API_URL}/api/verify \\
  -H "Content-Type: application/json" \\
  -d '{"answer": "Paste the AI answer here.", "context": {"country": "india"}}'`;

function Bookmarklet() {
  const link = useRef<HTMLAnchorElement>(null);
  const [code, setCode] = useState("");
  const [copied, setCopied] = useState(false);

  // React blocks javascript: links in JSX, so the href is set directly once the page's address is known.
  useEffect(() => {
    const source =
      "javascript:(()=>{const t=String(getSelection()).trim();" +
      "if(!t){alert('Select an AI answer on the page first.');return;}" +
      `window.open('${window.location.origin}/?answer='+encodeURIComponent(t.slice(0,6000)),'_blank');})()`;
    link.current?.setAttribute("href", source);
    Promise.resolve().then(() => setCode(source));
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Panel
      title="Check from any page"
      description="Drag this button to your bookmarks bar. On ChatGPT, Gemini or any other site, select an answer and click the bookmark: ShelfLife opens with the answer filled in."
    >
      <div className="flex flex-wrap items-center gap-2">
        <a
          ref={link}
          href="#bookmarklet"
          onClick={(event) => event.preventDefault()}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium hover:bg-muted"
        >
          <BookmarkPlus className="size-4" aria-hidden />
          Check with ShelfLife
        </a>
        <Button variant="ghost" size="sm" onClick={copy} disabled={!code}>
          <Copy aria-hidden />
          {copied ? "Copied" : "Copy the code"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        It only reads the text you select, and only when you click it. Long answers are cut to 6,000 characters.
      </p>
    </Panel>
  );
}

export function SystemPage() {
  const { data, error, loading, reload } = useApi(workspaceApi.system);
  const [enabling, setEnabling] = useState(false);
  const [cacheError, setCacheError] = useState<string | null>(null);

  async function enableCache() {
    setEnabling(true);
    setCacheError(null);
    try {
      await workspaceApi.enableCache();
      reload();
    } catch (caught) {
      setCacheError(caught instanceof ApiError ? caught.message : "The cache couldn't be enabled.");
    } finally {
      setEnabling(false);
    }
  }

  return (
    <PageContainer wide>
      <PageHeader
        title="System"
        description="The services ShelfLife runs on, how they are set up, and how to call ShelfLife from other apps."
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
          {data.missing_settings.length > 0 && (
            <ErrorNote message={`Missing settings in .env: ${data.missing_settings.join(", ")}.`} />
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Bifrost" description="The gateway every model call goes through.">
              <Rows
                rows={[
                  ["Status", <Status key="s" ok={data.bifrost.ok}>{data.bifrost.detail}</Status>],
                  ["Address", data.bifrost.url ?? "–"],
                  [
                    "Virtual key",
                    data.bifrost.virtual_key ? (
                      <Status key="vk" ok={data.bifrost.virtual_key.ok}>{data.bifrost.virtual_key.detail}</Status>
                    ) : (
                      "–"
                    ),
                  ],
                  [
                    "Budget",
                    data.budget.error ??
                      (data.budget.budgets.length
                        ? data.budget.budgets
                            .map((budget) =>
                              `$${budget.current_usage.toFixed(2)} of ${budget.max_limit === null ? "no limit" : `$${budget.max_limit.toFixed(2)}`}` +
                              (formatResetPeriod(budget.reset_duration) ? ` per ${formatResetPeriod(budget.reset_duration)}` : ""),
                            )
                            .join("; ")
                        : data.budget.configured
                          ? "No budget set on the key"
                          : "No virtual key"),
                  ],
                  ["Fast model", <code key="f" className="font-mono text-xs">{data.settings.model_fast}</code>],
                  ["Strong model", <code key="m" className="font-mono text-xs">{data.settings.model_strong}</code>],
                  ["Answer model", <code key="a" className="font-mono text-xs">{data.settings.model_stale}</code>],
                  ["Fallbacks", [...data.settings.fallbacks_fast, ...data.settings.fallbacks_strong].join(", ") || "none"],
                  ["Providers", `${data.settings.providers.length}: ${data.settings.providers.join(", ")}`],
                ]}
              />
            </Panel>
            <Panel title="Tavily" description="Every web search and page read.">
              <Rows
                rows={[
                  [
                    "Status",
                    <Status key="t" ok={data.tavily.ok && !data.tavily.rate_limited}>
                      {data.tavily.rate_limited ? "rate limited: wait a minute" : data.tavily.detail}
                    </Status>,
                  ],
                  [
                    "Credits",
                    data.tavily.credits_used === undefined || data.tavily.credits_used === null
                      ? "–"
                      : `${data.tavily.credits_used} used${data.tavily.credits_limit ? ` of ${data.tavily.credits_limit}` : ""}`,
                  ],
                  ["Full-page reads", data.settings.use_tavily_extract ? "On, for thin search snippets" : "Off"],
                  ["Searches at once", String(data.settings.tavily_concurrency)],
                  ["Search cache", `${data.settings.search_cache_ttl_hours} hours`],
                  ["Stale alerts webhook", data.settings.alert_webhook ? "Set" : "Not set (ALERT_WEBHOOK_URL)"],
                ]}
              />
            </Panel>
          </div>
          <Panel
            title="Bifrost semantic cache"
            description="Caches model replies so repeated checks are faster and cheaper. Needs BIFROST_SETUP_TOKEN (or admin user and password) in .env, and a vector store in Bifrost's config."
            actions={
              data.cache_plugin.known && !data.cache_plugin.enabled ? (
                <Button size="sm" onClick={enableCache} disabled={enabling}>
                  {enabling && <LoaderCircle className="motion-safe:animate-spin" aria-hidden />}
                  Enable cache
                </Button>
              ) : undefined
            }
          >
            <Status ok={Boolean(data.cache_plugin.enabled)}>{data.cache_plugin.detail}</Status>
            <ErrorNote message={cacheError} />
          </Panel>
          <IntegrationsPanel />
          <Bookmarklet />
          <Panel title="API" description={`Other apps can call ShelfLife directly at ${API_URL}. Full schema at ${API_URL}/docs.`}>
            <pre className="overflow-x-auto rounded-lg bg-muted px-3 py-2.5 font-mono text-xs leading-5">{CURL}</pre>
            <div className="overflow-x-auto">
              <table className="w-full min-w-lg text-sm">
                <tbody>
                  {ENDPOINTS.map(([method, path, what]) => (
                    <tr key={path} className="border-t align-top first:border-t-0">
                      <td className="w-24 py-1.5 pr-3 font-mono text-xs text-muted-foreground">{method}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs whitespace-nowrap">{path}</td>
                      <td className="py-1.5 text-muted-foreground">{what}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </PageContainer>
  );
}
