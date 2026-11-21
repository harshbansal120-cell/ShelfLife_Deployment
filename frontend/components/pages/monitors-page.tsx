"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { CircleCheck, CircleX, FileUp, Link2, ListChecks, LoaderCircle, Play, Plus, Trash2 } from "lucide-react";

import { PageContainer } from "@/components/app-shell";
import { LinkTable } from "@/components/link-report";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorNote, Field, Loading, NativeSelect, PageHeader, Panel, Tabs } from "@/components/ui-kit";
import { useApi } from "@/hooks/use-api";
import { ApiError } from "@/lib/api";
import { MAX_BATCH, parseBatchCsv, parseBatchText, type BatchInput } from "@/lib/batch";
import type { BatchStatus, CheckContext, LinkResult, Profile, RegressionRun, RegressionTest } from "@/lib/types";
import { VERDICT_INFO } from "@/lib/verdicts";
import { COUNTRIES, contextLines, titleCase, workspaceApi } from "@/lib/workspace-api";

type Tab = "tests" | "links" | "batch" | "profiles";

const TABS: { id: Tab; label: string }[] = [
  { id: "tests", label: "Regression tests" },
  { id: "links", label: "Link checker" },
  { id: "batch", label: "Batch check" },
  { id: "profiles", label: "Context profiles" },
];

const message = (caught: unknown, fallback: string) => (caught instanceof ApiError ? caught.message : fallback);

// --- regression tests ----------------------------------------------------------

function PassMark({ passed }: { passed: boolean }) {
  return passed ? (
    <span className="inline-flex items-center gap-1 text-fresh"><CircleCheck className="size-4" aria-hidden />Passed</span>
  ) : (
    <span className="inline-flex items-center gap-1 text-stale"><CircleX className="size-4" aria-hidden />Failed</span>
  );
}

function RunDetail({ run }: { run: RegressionRun }) {
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <PassMark passed={run.passed} />
        <span className="text-xs text-muted-foreground">
          {new Date(run.ran_at).toLocaleString()} · {run.model}
        </span>
        {run.check_id && (
          <Link href={`/?check=${run.check_id}`} className="text-xs underline underline-offset-4">
            Open the check
          </Link>
        )}
      </p>
      {run.problems.length > 0 && (
        <ul className="flex list-disc flex-col gap-0.5 pl-5 text-muted-foreground">
          {run.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TestRow({ test, onChanged }: { test: RegressionTest; onChanged: () => void }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latest, setLatest] = useState<RegressionRun | null>(null);
  const [runs, setRuns] = useState<RegressionRun[] | null>(null);
  const run = latest ?? test.last_run;

  async function runNow() {
    setRunning(true);
    setError(null);
    try {
      setLatest(await workspaceApi.runTest(test.id));
      setRuns(null);
      onChanged();
    } catch (caught) {
      setError(message(caught, "The test couldn't run."));
    } finally {
      setRunning(false);
    }
  }

  async function toggleHistory() {
    if (runs) return setRuns(null);
    try {
      setRuns((await workspaceApi.testRuns(test.id)).runs);
    } catch (caught) {
      setError(message(caught, "The history couldn't load."));
    }
  }

  async function remove() {
    if (!window.confirm(`Delete the test "${test.name}" and its run history?`)) return;
    try {
      await workspaceApi.deleteTest(test.id);
      onChanged();
    } catch (caught) {
      setError(message(caught, "The test couldn't be deleted."));
    }
  }

  return (
    <li className="flex flex-col gap-3 py-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-sm font-medium">{test.name}</p>
          <p className="text-sm text-muted-foreground">{test.question}</p>
          <p className="text-xs text-muted-foreground">
            Model: {test.model ?? "the default stale-answer model"}
            {test.must_include.length > 0 && <> · Must mention: {test.must_include.join(", ")}</>}
          </p>
          {test.recent.length > 0 && (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              Last runs:
              {test.recent.map((passed, index) => (
                <span
                  key={index}
                  role="img"
                  aria-label={passed ? "passed" : "failed"}
                  className={`inline-block size-2.5 rounded-full ${passed ? "bg-fresh-line" : "bg-stale-line"}`}
                />
              ))}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" onClick={runNow} disabled={running}>
            {running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <Play aria-hidden />}
            Run
          </Button>
          <Button variant="ghost" size="sm" onClick={toggleHistory}>
            {runs ? "Hide history" : "History"}
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label={`Delete ${test.name}`} onClick={remove}>
            <Trash2 aria-hidden />
          </Button>
        </div>
      </div>
      <ErrorNote message={error} />
      {run && !runs && <RunDetail run={run} />}
      {runs && (
        <ul className="flex flex-col gap-3 border-l-2 pl-3">
          {runs.length === 0 && <li className="text-sm text-muted-foreground">No runs yet.</li>}
          {runs.map((item) => (
            <li key={item.id}>
              <RunDetail run={item} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function RegressionTests({ demoQuestion }: { demoQuestion?: string }) {
  const tests = useApi(workspaceApi.tests);
  const [name, setName] = useState("");
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function create(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await workspaceApi.createTest({
        name: name.trim(),
        question: question.trim(),
        model: model.trim() || null,
        must_include: mustInclude.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setName("");
      setQuestion("");
      setModel("");
      setMustInclude("");
      tests.reload();
    } catch (caught) {
      setError(message(caught, "The test couldn't be saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Panel
        title="Saved tests"
        description="Each run asks the model the question through Bifrost, then checks its answer. A run fails if any claim is stale or a required term is missing."
      >
        <ErrorNote message={tests.error} />
        {tests.loading && !tests.data && <Loading inline />}
        {tests.data && tests.data.tests.length === 0 && <EmptyState>No tests yet. Add one to watch a question over time.</EmptyState>}
        {tests.data && tests.data.tests.length > 0 && (
          <ul className="-my-4 flex flex-col divide-y">
            {tests.data.tests.map((test) => (
              <TestRow key={test.id} test={test} onChanged={tests.reload} />
            ))}
          </ul>
        )}
      </Panel>
      <Panel
        title="New test"
        actions={
          demoQuestion ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setName("Acme pricing answer");
                setQuestion(demoQuestion);
                setMustInclude("Acme");
              }}
            >
              Fill example
            </Button>
          ) : undefined
        }
      >
        <form onSubmit={create} className="flex flex-col gap-3">
          <Field label="Name" htmlFor="test-name">
            <Input id="test-name" className="h-9" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Question to ask" htmlFor="test-question">
            <Textarea id="test-question" required maxLength={2000} value={question} onChange={(e) => setQuestion(e.target.value)} />
          </Field>
          <Field label="Model (optional)" htmlFor="test-model" hint="A Bifrost model name such as provider/model. Leave empty for MODEL_STALE.">
            <Input id="test-model" className="h-9" maxLength={120} value={model} onChange={(e) => setModel(e.target.value)} />
          </Field>
          <Field label="Must mention (optional)" htmlFor="test-include" hint="Comma-separated words the answer has to contain.">
            <Input id="test-include" className="h-9" value={mustInclude} onChange={(e) => setMustInclude(e.target.value)} />
          </Field>
          <ErrorNote message={error} />
          <Button type="submit" disabled={saving || !name.trim() || !question.trim()}>
            <Plus aria-hidden />
            Save test
          </Button>
        </form>
      </Panel>
    </div>
  );
}

// --- link checker ----------------------------------------------------------------

function LinkChecker() {
  const checks = useApi(() => workspaceApi.checks(30));
  const [checkId, setCheckId] = useState("");
  const [urls, setUrls] = useState("");
  const [results, setResults] = useState<LinkResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const pasted = urls.split(/\s+/).map((url) => url.trim()).filter(Boolean);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResults((await workspaceApi.checkLinks({ check_id: checkId || undefined, urls: pasted })).results);
    } catch (caught) {
      setError(message(caught, "The links couldn't be checked."));
    } finally {
      setRunning(false);
    }
  }

  const broken = results?.filter((item) => item.status !== "ok").length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <Panel
        title="Check links"
        description="Visit the sources a check relied on, and any links you paste, to find pages that moved, were deleted, or no longer contain the quoted evidence. Only public web addresses are visited."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Sources from a saved check" htmlFor="links-check">
            <NativeSelect id="links-check" value={checkId} onChange={(e) => setCheckId(e.target.value)}>
              <option value="">None</option>
              {checks.data?.checks.map((check) => (
                <option key={check.id} value={check.id}>
                  {new Date(check.checked_at).toLocaleDateString()} · {(check.question ?? check.answer_excerpt).slice(0, 70)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Links to check" htmlFor="links-urls" hint="One per line, up to 40.">
            <Textarea id="links-urls" className="min-h-20 font-mono text-xs" value={urls} onChange={(e) => setUrls(e.target.value)} placeholder="https://example.com/pricing" />
          </Field>
        </div>
        <div className="flex justify-end">
          <Button onClick={run} disabled={running || (!checkId && pasted.length === 0)}>
            {running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <Link2 aria-hidden />}
            Check links
          </Button>
        </div>
        <ErrorNote message={error} />
      </Panel>
      {results && (
        <Panel title={broken ? `${broken} of ${results.length} links need attention` : `All ${results.length} links still work`}>
          <LinkTable results={results} />
        </Panel>
      )}
    </div>
  );
}

// --- batch checks ----------------------------------------------------------------

const BATCH_STATUS: Record<BatchStatus["items"][number]["status"], string> = {
  queued: "Waiting",
  running: "Checking",
  done: "Done",
  failed: "Failed",
};

function BatchCheck({ demo }: { demo?: string[] }) {
  const [text, setText] = useState("");
  const [fromFile, setFromFile] = useState<{ name: string; items: BatchInput[] } | null>(null);
  const [country, setCountry] = useState("");
  const [batch, setBatch] = useState<BatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const items = fromFile ? fromFile.items : parseBatchText(text);

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);

  async function poll(id: string) {
    try {
      const status = await workspaceApi.batch(id);
      setBatch(status);
      if (!status.finished) timer.current = window.setTimeout(() => void poll(id), 1500);
    } catch (caught) {
      setError(message(caught, "Lost track of the batch."));
    }
  }

  async function start() {
    setError(null);
    setBatch(null);
    try {
      const context: CheckContext | null = country ? { country } : null;
      const { batch_id } = await workspaceApi.startBatch({ items: items.slice(0, MAX_BATCH), context });
      void poll(batch_id);
    } catch (caught) {
      setError(message(caught, "The batch couldn't start."));
    }
  }

  async function readFile(file: File | undefined) {
    if (!file) return;
    const content = await file.text();
    const parsed = file.name.toLowerCase().endsWith(".csv") ? parseBatchCsv(content) : parseBatchText(content);
    setFromFile({ name: file.name, items: parsed });
  }

  const running = batch !== null && !batch.finished;
  const done = batch?.items.filter((item) => item.status === "done" || item.status === "failed").length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <Panel
        title="Check many answers"
        description={`Paste answers separated by a line with only ---, or upload a CSV with an answer column (and optionally a question column). Up to ${MAX_BATCH} at a time; they run one after another.`}
        actions={
          demo?.length ? (
            <Button variant="ghost" size="sm" onClick={() => { setFromFile(null); setText(demo.join("\n---\n")); }}>
              Fill example
            </Button>
          ) : undefined
        }
      >
        {fromFile ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2.5 text-sm">
            <span>
              <span className="font-medium">{fromFile.name}</span>: {fromFile.items.length} answers found
            </span>
            <Button variant="ghost" size="sm" onClick={() => setFromFile(null)}>Remove file</Button>
          </div>
        ) : (
          <Textarea
            aria-label="Answers to check"
            className="min-h-48"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"Q: What does Acme Cloud cost?\nAcme Cloud costs $10 a month.\n---\nAnother answer to check."}
          />
        )}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-muted focus-within:ring-2 focus-within:ring-ring">
              <FileUp className="size-4" aria-hidden />
              Upload CSV or text
              <input type="file" accept=".csv,.txt,text/csv,text/plain" className="sr-only" onChange={(e) => void readFile(e.target.files?.[0])} />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Country</span>
              <NativeSelect className="w-44" value={country} onChange={(e) => setCountry(e.target.value)}>
                <option value="">Any</option>
                {COUNTRIES.map((item) => (
                  <option key={item} value={item}>{titleCase(item)}</option>
                ))}
              </NativeSelect>
            </label>
          </div>
          <Button onClick={start} disabled={running || items.length === 0}>
            {running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <ListChecks aria-hidden />}
            Check {Math.min(items.length, MAX_BATCH) || ""} {items.length === 1 ? "answer" : "answers"}
          </Button>
        </div>
        {items.length > MAX_BATCH && (
          <p className="text-xs text-muted-foreground">Only the first {MAX_BATCH} of {items.length} will be checked.</p>
        )}
        <ErrorNote message={error} />
      </Panel>
      {batch && (
        <Panel title={batch.finished ? "Batch finished" : `Checking ${done + 1} of ${batch.items.length}`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-lg text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-normal">#</th>
                  <th className="py-1.5 pr-3 font-normal">Answer</th>
                  <th className="py-1.5 pr-3 font-normal">Status</th>
                  <th className="py-1.5 pr-3 text-right font-normal">Freshness</th>
                  <th className="py-1.5 font-normal">Claims</th>
                </tr>
              </thead>
              <tbody>
                {batch.items.map((item) => (
                  <tr key={item.index} className="border-t align-top">
                    <td className="py-2 pr-3 font-mono text-xs tabular-nums">{item.index + 1}</td>
                    <td className="max-w-72 py-2 pr-3">
                      {item.check_id ? (
                        <Link href={`/?check=${item.check_id}`} className="underline-offset-4 hover:underline">
                          {item.question ?? item.answer_excerpt}
                        </Link>
                      ) : (
                        item.question ?? item.answer_excerpt
                      )}
                      {item.error && <span className="block text-xs text-muted-foreground">{item.error}</span>}
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {item.status === "running" && <LoaderCircle className="mr-1 inline size-3.5 motion-safe:animate-spin" aria-hidden />}
                      {BATCH_STATUS[item.status]}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums">{item.answer_score ?? "–"}</td>
                    <td className="py-2 text-xs text-muted-foreground">
                      {item.verdict_counts
                        ? Object.entries(item.verdict_counts)
                            .map(([verdict, count]) => `${count} ${VERDICT_INFO[verdict as keyof typeof VERDICT_INFO].label.toLowerCase()}`)
                            .join(" · ")
                        : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

// --- context profiles --------------------------------------------------------------

const EMPTY_CONTEXT: CheckContext = { country: null, edition: null, environment: null, currency: null };

function ProfileForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: Profile;
  submitLabel: string;
  onSubmit: (name: string, context: CheckContext) => Promise<void>;
  onCancel?: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [context, setContext] = useState<CheckContext>(initial?.context ?? EMPTY_CONTEXT);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const prefix = initial ? `profile-${initial.id}` : "profile-new";
  const set = (key: keyof CheckContext, value: string) => setContext((current) => ({ ...current, [key]: value || null }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit(name.trim(), context);
      if (!initial) {
        setName("");
        setContext(EMPTY_CONTEXT);
      }
    } catch (caught) {
      setError(message(caught, "The profile couldn't be saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label="Name" htmlFor={`${prefix}-name`}>
        <Input id={`${prefix}-name`} className="h-9" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Customer in India" />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Country" htmlFor={`${prefix}-country`}>
          <NativeSelect id={`${prefix}-country`} value={context.country ?? ""} onChange={(e) => set("country", e.target.value)}>
            <option value="">Any</option>
            {COUNTRIES.map((item) => (
              <option key={item} value={item}>{titleCase(item)}</option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Plan or edition" htmlFor={`${prefix}-edition`}>
          <Input id={`${prefix}-edition`} className="h-9" maxLength={120} value={context.edition ?? ""} onChange={(e) => set("edition", e.target.value)} />
        </Field>
        <Field label="Software environment" htmlFor={`${prefix}-environment`}>
          <Input id={`${prefix}-environment`} className="h-9" maxLength={120} value={context.environment ?? ""} onChange={(e) => set("environment", e.target.value)} />
        </Field>
        <Field label="Currency" htmlFor={`${prefix}-currency`}>
          <Input id={`${prefix}-currency`} className="h-9" maxLength={12} value={context.currency ?? ""} onChange={(e) => set("currency", e.target.value)} />
        </Field>
      </div>
      <ErrorNote message={error} />
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
        )}
        <Button type="submit" disabled={saving || !name.trim()}>{submitLabel}</Button>
      </div>
    </form>
  );
}

function Profiles() {
  const profiles = useApi(workspaceApi.profiles);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove(profile: Profile) {
    if (!window.confirm(`Delete the profile "${profile.name}"? Checks made with it keep their saved context.`)) return;
    try {
      await workspaceApi.deleteProfile(profile.id);
      profiles.reload();
    } catch (caught) {
      setError(message(caught, "The profile couldn't be deleted."));
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Panel
        title="Saved profiles"
        description="Who an answer is for. Choose one on the Check page; when you change a profile later, checks made with the old version are flagged here and on the dashboard."
      >
        <ErrorNote message={profiles.error ?? error} />
        {profiles.loading && !profiles.data && <Loading inline />}
        {profiles.data && profiles.data.profiles.length === 0 && <EmptyState>No profiles yet.</EmptyState>}
        {profiles.data && profiles.data.profiles.length > 0 && (
          <ul className="-my-3 flex flex-col divide-y">
            {profiles.data.profiles.map((profile) => (
              <li key={profile.id} className="flex flex-col gap-2 py-3">
                {editing === profile.id ? (
                  <ProfileForm
                    initial={profile}
                    submitLabel="Save changes"
                    onCancel={() => setEditing(null)}
                    onSubmit={async (name, context) => {
                      await workspaceApi.updateProfile(profile.id, { name, context });
                      setEditing(null);
                      profiles.reload();
                    }}
                  />
                ) : (
                  <>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex flex-col gap-0.5">
                        <p className="text-sm font-medium">
                          {profile.name} <span className="font-normal text-muted-foreground">· version {profile.version}</span>
                        </p>
                        <p className="text-sm text-muted-foreground">{contextLines(profile.context).join(" · ") || "No context set"}</p>
                      </div>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setEditing(profile.id)}>Edit</Button>
                        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${profile.name}`} onClick={() => void remove(profile)}>
                          <Trash2 aria-hidden />
                        </Button>
                      </div>
                    </div>
                    {profile.drifted_checks && profile.drifted_checks.length > 0 && (
                      <div className="rounded-lg border px-3 py-2 text-sm">
                        <p className="font-medium">
                          {profile.drifted_checks.length} {profile.drifted_checks.length === 1 ? "check was" : "checks were"} made with an older version
                        </p>
                        <ul className="mt-1 flex flex-col gap-0.5 text-muted-foreground">
                          {profile.drifted_checks.map((check) => (
                            <li key={check.id} className="flex flex-wrap gap-x-2">
                              <Link href={`/?check=${check.id}`} className="underline-offset-4 hover:underline">
                                {check.question ?? check.answer_excerpt}
                              </Link>
                              <Link href={`/?recheck=${check.id}`} className="text-xs underline underline-offset-4">
                                Re-check now
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="New profile">
        <ProfileForm
          submitLabel="Save profile"
          onSubmit={async (name, context) => {
            await workspaceApi.createProfile({ name, context });
            profiles.reload();
          }}
        />
      </Panel>
    </div>
  );
}

// --- page ------------------------------------------------------------------------------

export function MonitorsPage() {
  const [tab, setTab] = useState<Tab>("tests");
  const demo = useApi(workspaceApi.demo);
  const scenarios = demo.data?.scenarios ?? [];
  const demoQuestion = scenarios.find((item) => item.id === "facts")?.question;
  const demoAnswers = scenarios.flatMap((item) =>
    item.answer ? [`Q: ${item.question}\n${item.answer}`] : (item.answers ?? []).slice(0, 1).map((a) => `Q: ${item.question}\n${a.answer}`),
  );

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (TABS.some((item) => item.id === requested)) Promise.resolve().then(() => setTab(requested as Tab));
  }, []);

  function choose(next: Tab) {
    setTab(next);
    window.history.replaceState(null, "", `?tab=${next}`);
  }

  return (
    <PageContainer wide>
      <PageHeader
        title="Monitors"
        description="Keep answers fresh after the first check: re-ask saved questions to catch a model going out of date, find broken sources, check answers in bulk, and keep track of who answers are for."
      />
      <Tabs tabs={TABS} value={tab} onChange={choose} label="Monitors" />
      <div role="tabpanel" aria-labelledby={`tab-${tab}`} className="flex flex-col gap-6">
        {tab === "tests" && <RegressionTests demoQuestion={demoQuestion} />}
        {tab === "links" && <LinkChecker />}
        {tab === "batch" && <BatchCheck demo={demoAnswers} />}
        {tab === "profiles" && <Profiles />}
      </div>
    </PageContainer>
  );
}
