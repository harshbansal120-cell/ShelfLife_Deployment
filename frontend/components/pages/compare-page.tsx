"use client";

import { useState } from "react";
import { LoaderCircle, Plus, Scale, X } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorNote, Field, NativeSelect, PageHeader, Panel } from "@/components/ui-kit";
import { VerdictBadge } from "@/components/verdict-badge";
import { useApi } from "@/hooks/use-api";
import { ApiError } from "@/lib/api";
import { safeHref } from "@/lib/format";
import type { Comparison } from "@/lib/types";
import { CATEGORY_LABELS } from "@/lib/verdicts";
import { COUNTRIES, titleCase, workspaceApi } from "@/lib/workspace-api";

const EMPTY = [
  { app: "Sales assistant", answer: "" },
  { app: "Support assistant", answer: "" },
];

function Result({ result }: { result: Comparison }) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm">
        <span className="font-medium">
          {result.conflicts === 0
            ? "The apps agree."
            : `${result.conflicts} ${result.conflicts === 1 ? "fact" : "facts"} where the apps disagree.`}
        </span>{" "}
        <span className="text-muted-foreground">Each fact was searched once and every app&apos;s version judged against the same sources.</span>
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {result.apps.map((app) => (
          <div key={app.app} className="flex flex-col gap-1 rounded-lg border p-3 text-sm">
            <p className="font-medium">{app.app}</p>
            <p className="text-muted-foreground">
              {app.stale} stale · {app.fresh} fresh · {app.other} unconfirmed
            </p>
          </div>
        ))}
      </div>
      <ul className="flex flex-col gap-4">
        {result.clusters.map((cluster) => (
          <li key={cluster.topic} className="flex flex-col gap-4 rounded-2xl border bg-card p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-medium">{cluster.topic}</p>
              <span className="text-xs text-muted-foreground">
                {CATEGORY_LABELS[cluster.category]}
                {cluster.conflict && " · apps disagree"}
                {cluster.current_value && <> · sources now say <span className="font-medium text-foreground">{cluster.current_value}</span></>}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-lg text-sm">
                <tbody>
                  {cluster.entries.map((row) => {
                    const href = row.source_url ? safeHref(row.source_url) : null;
                    return (
                      <tr key={`${row.app}-${row.claim}`} className="border-t align-top first:border-t-0">
                        <td className="w-40 py-2 pr-3 font-medium">{row.app}</td>
                        <td className="py-2 pr-3">
                          {row.claim}
                          {row.quote && (
                            <span className="mt-1 block text-xs text-muted-foreground">
                              “{row.quote}”{" "}
                              {href && (
                                <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">
                                  source
                                </a>
                              )}
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-right whitespace-nowrap">
                          <VerdictBadge verdict={row.verdict} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ComparePage() {
  const [question, setQuestion] = useState("");
  const [country, setCountry] = useState("");
  const [answers, setAnswers] = useState(EMPTY);
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const demo = useApi(workspaceApi.demo);
  const past = useApi(workspaceApi.comparisons, result?.id ?? "");
  const scenario = demo.data?.scenarios.find((item) => item.answers);

  function update(index: number, key: "app" | "answer", value: string) {
    setAnswers((current) => current.map((item, i) => (i === index ? { ...item, [key]: value } : item)));
  }

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(
        await workspaceApi.compare({
          question: question.trim() || undefined,
          answers: answers.map((item) => ({ app: item.app.trim() || "App", answer: item.answer.trim() })),
          context: country ? { country } : null,
        }),
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The comparison failed.");
    } finally {
      setRunning(false);
    }
  }

  const ready = answers.filter((item) => item.answer.trim()).length === answers.length && answers.length >= 2;

  return (
    <PageContainer wide>
      <PageHeader
        title="Compare AI apps"
        description="Paste how different assistants answered the same question. ShelfLife lines up the facts they state, checks each against current sources, and shows which app is out of date."
        actions={
          scenario?.answers ? (
            <Button
              variant="outline"
              size="sm"
              data-tour="load-example"
              onClick={() => {
                setQuestion(scenario.question);
                setAnswers(scenario.answers!.map((item) => ({ ...item })));
              }}
            >
              Load example: {scenario.label}
            </Button>
          ) : undefined
        }
      />
      <Panel>
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_14rem]">
          <Field label="Question (optional)" htmlFor="compare-question">
            <Input id="compare-question" className="h-9" value={question} maxLength={2000} onChange={(e) => setQuestion(e.target.value)} />
          </Field>
          <Field label="Country (optional)" htmlFor="compare-country">
            <NativeSelect id="compare-country" value={country} onChange={(e) => setCountry(e.target.value)}>
              <option value="">Any</option>
              {COUNTRIES.map((item) => (
                <option key={item} value={item}>{titleCase(item)}</option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <ul className="grid gap-4 lg:grid-cols-2">
          {answers.map((item, index) => (
            <li key={index} className="flex flex-col gap-2 rounded-lg border p-3">
              <div className="flex items-center gap-2">
                <Input
                  aria-label={`Name of app ${index + 1}`}
                  className="h-8 font-medium"
                  value={item.app}
                  maxLength={60}
                  onChange={(e) => update(index, "app", e.target.value)}
                />
                {answers.length > 2 && (
                  <Button variant="ghost" size="icon-sm" aria-label={`Remove ${item.app}`} onClick={() => setAnswers((c) => c.filter((_, i) => i !== index))}>
                    <X aria-hidden />
                  </Button>
                )}
              </div>
              <Textarea
                aria-label={`Answer from ${item.app}`}
                className="min-h-28"
                value={item.answer}
                maxLength={20000}
                placeholder="Paste this app's answer."
                onChange={(e) => update(index, "answer", e.target.value)}
              />
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={answers.length >= 5}
            onClick={() => setAnswers((current) => [...current, { app: `App ${current.length + 1}`, answer: "" }])}
          >
            <Plus aria-hidden />
            Add another app
          </Button>
          <Button onClick={run} disabled={!ready || running} data-tour="compare-run">
            {running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <Scale aria-hidden />}
            Compare answers
          </Button>
        </div>
        <ErrorNote message={error} />
      </Panel>

      {result && (
        <div data-tour="compare-result">
          <Result result={result} />
        </div>
      )}

      <Panel title="Earlier comparisons">
        {past.data?.comparisons.length ? (
          <ul className="flex flex-col divide-y text-sm">
            {past.data.comparisons.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  {item.question ?? item.apps.map((app) => app.app).join(", ")}
                  <span className="block text-xs text-muted-foreground">
                    {item.apps.length} apps · {item.conflicts} conflicts · {new Date(item.created_at).toLocaleString()}
                  </span>
                </span>
                <Button variant="ghost" size="sm" onClick={() => setResult(item)}>View</Button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>No comparisons yet.</EmptyState>
        )}
      </Panel>
    </PageContainer>
  );
}
