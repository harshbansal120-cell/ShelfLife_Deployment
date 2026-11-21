"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CalendarClock,
  Download,
  LoaderCircle,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { AnswerView } from "@/components/answer-view";
import { CheckForm } from "@/components/check-form";
import { ClaimDetail } from "@/components/claim-detail";
import { ClaimList } from "@/components/claim-list";
import { ContextPicker } from "@/components/context-picker";
import { CorrectedAnswer } from "@/components/corrected-answer";
import { DependencyView } from "@/components/dependency-view";
import { HistoryPanel } from "@/components/history-panel";
import { LinkReport } from "@/components/link-report";
import { MetricsPanel } from "@/components/metrics-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorNote, NativeSelect, Tabs } from "@/components/ui-kit";
import { Watchlist } from "@/components/watchlist";
import { useCheck } from "@/hooks/use-check";
import {
  ApiError,
  exportUrl,
  getAffected,
  getBudget,
  getCheckOutcome,
  getHistory,
  getWatchlist,
} from "@/lib/api";
import { checkProgress, type CheckState } from "@/lib/check-state";
import { formatDate } from "@/lib/format";
import type {
  AffectedAnswer,
  BudgetStatus,
  CheckContext,
  CheckResult,
  CheckTimeline,
  DemoScenario,
  FreshnessPolicy,
  Profile,
  Verdict,
  WatchItem,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { TONE_CLASSES, toneForScore, VERDICT_INFO } from "@/lib/verdicts";
import { contextLines, workspaceApi } from "@/lib/workspace-api";

type AnswerTab = "highlights" | "corrected" | "dependencies" | "links";

const TABS: { id: AnswerTab; label: string }[] = [
  { id: "highlights", label: "Checked answer" },
  { id: "corrected", label: "Corrected answer" },
  { id: "dependencies", label: "Dependencies" },
  { id: "links", label: "Links" },
];

const COUNT_ORDER: Verdict[] = ["stale", "uncertain", "fresh", "unverified", "error"];

const GUARD_TEXT = {
  show: "Advice for apps: safe to show",
  show_with_warning: "Advice for apps: show with a warning",
  withhold: "Advice for apps: hold this answer back",
};

function Summary({ state }: { state: CheckState }) {
  const { finished, total } = checkProgress(state);
  const result = state.result;

  if (!result) {
    const status = !state.claimsReady
      ? "Finding the claims in this answer"
      : total === 0
        ? "Finishing up"
        : `Checked ${finished} of ${total} claims`;
    return (
      <div className="flex flex-col gap-2" role="status">
        <p className="flex items-center gap-2 text-sm">
          <LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden />
          {status}
          {state.deep && <span className="text-muted-foreground">· Deep verify</span>}
          {!state.useCache && <span className="text-muted-foreground">· Cache off</span>}
        </p>
        <div className="h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-foreground/70 transition-[width] duration-300"
            style={{ width: `${total ? Math.max(4, (finished / total) * 100) : 4}%` }}
          />
        </div>
      </div>
    );
  }

  const counts = COUNT_ORDER.flatMap((verdict) => {
    const count = result.verdict_counts[verdict];
    return count ? [`${count} ${VERDICT_INFO[verdict].label.toLowerCase()}`] : [];
  });
  const context = contextLines(result.context);
  const GuardIcon = result.guard?.action === "show" ? ShieldCheck : ShieldAlert;

  return (
    <div className="flex flex-col gap-3" role="status" data-tour="summary-done">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {result.answer_score !== null ? (
          <p className="flex items-baseline gap-1.5">
            <span
              className={cn(
                "font-mono text-4xl font-medium tabular-nums",
                TONE_CLASSES[toneForScore(result.answer_score)].text,
              )}
            >
              {result.answer_score}
            </span>
            <span className="text-sm text-muted-foreground">/ 100 freshness</span>
          </p>
        ) : (
          <p className="text-sm font-medium">
            {result.claims.length === 0 ? "No factual claims found in this answer." : "No claim could be scored."}
          </p>
        )}
        {counts.length > 0 && <p className="text-sm text-muted-foreground">{counts.join(" · ")}</p>}
      </div>
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        {result.recheck_by && (
          <p className="flex items-center gap-1.5">
            <CalendarClock className="size-3.5" aria-hidden />
            Re-check this answer by {formatDate(result.recheck_by)}
            {result.checked_at && <> · checked {formatDate(result.checked_at.slice(0, 10))}</>}
          </p>
        )}
        {context.length > 0 && <p>Checked for: {context.join(" · ")}</p>}
      </div>
      {result.guard && (
        <p className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm" data-tour="guard">
          <GuardIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            <span className="font-medium">{GUARD_TEXT[result.guard.action]}.</span>{" "}
            <span className="text-muted-foreground">{result.guard.reason}</span>
          </span>
        </p>
      )}
    </div>
  );
}

export function ShelfLifeApp() {
  const { state, start, reset, select, load } = useCheck();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [deep, setDeep] = useState(false);
  const [useCache, setUseCache] = useState(true);
  const [context, setContext] = useState<CheckContext>({});
  const [profileId, setProfileId] = useState("");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [policies, setPolicies] = useState<FreshnessPolicy[]>([]);
  const [policyId, setPolicyId] = useState("");
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [timeline, setTimeline] = useState<CheckTimeline | null>(null);
  const [affected, setAffected] = useState<{ checkId: string; claims: Record<string, AffectedAnswer[]> } | null>(null);
  const [watchItems, setWatchItems] = useState<WatchItem[]>([]);
  const [openError, setOpenError] = useState<string | null>(null);
  const [tab, setTab] = useState<AnswerTab>("highlights");
  const detailRef = useRef<HTMLElement>(null);

  // Load profiles and demo scenarios once, and follow links like /?check=id or /?answer=text.
  useEffect(() => {
    let active = true;
    workspaceApi.profiles().then((value) => active && setProfiles(value.profiles)).catch(() => undefined);
    workspaceApi.demo().then((value) => active && setScenarios(value.scenarios)).catch(() => undefined);
    workspaceApi
      .policies()
      .then((value) => {
        if (!active) return;
        setPolicies(value.policies);
        setPolicyId(value.default);
      })
      .catch(() => undefined);
    const params = new URLSearchParams(window.location.search);
    Promise.resolve().then(() => {
      if (!active) return;
      const checkId = params.get("check");
      const recheckId = params.get("recheck");
      if (recheckId) void recheck(recheckId);
      else if (checkId) void openCheck(checkId);
      if (params.get("answer")) setAnswer(params.get("answer")!.slice(0, 20_000));
      if (params.get("question")) setQuestion(params.get("question")!.slice(0, 2_000));
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finishedCheckId = state.phase === "done" ? state.checkId : null;

  // Refresh the budget at load and after each finished check, since checks spend it.
  useEffect(() => {
    let active = true;
    getBudget()
      .then((value) => active && setBudget(value))
      .catch(() => active && setBudget(null));
    return () => {
      active = false;
    };
  }, [finishedCheckId]);

  // After a check finishes (or a saved one opens), load what history knows about it.
  useEffect(() => {
    let active = true;
    getWatchlist()
      .then((items) => active && setWatchItems(items))
      .catch(() => undefined);
    if (finishedCheckId) {
      getHistory(finishedCheckId)
        .then((value) => active && setTimeline(value))
        .catch(() => undefined);
      getAffected(finishedCheckId)
        .then((claims) => active && setAffected({ checkId: finishedCheckId, claims }))
        .catch(() => undefined);
    }
    return () => {
      active = false;
    };
  }, [finishedCheckId]);

  async function fetchSaved(checkId: string): Promise<CheckResult | null> {
    setOpenError(null);
    try {
      const outcome = await getCheckOutcome(checkId);
      if (outcome.status === "done") return outcome.result;
      setOpenError(outcome.status === "failed" ? outcome.error.message : "That check is still running.");
    } catch (error) {
      setOpenError(error instanceof ApiError ? error.message : "That check couldn't be opened.");
    }
    return null;
  }

  async function openCheck(checkId: string) {
    const result = await fetchSaved(checkId);
    if (!result) return;
    setQuestion(result.question ?? "");
    setAnswer(result.answer);
    load(result);
    window.scrollTo({ top: 0 });
  }

  async function recheck(checkId: string) {
    const result = await fetchSaved(checkId);
    if (!result) return;
    setQuestion(result.question ?? "");
    setAnswer(result.answer);
    void start({
      answer: result.answer,
      question: result.question ?? undefined,
      deep,
      use_cache: useCache,
      context: result.context,
      profile_id: result.profile_id,
      policy_id: result.policy_id ?? (policyId || null),
    });
  }

  function applyScenario(scenario: DemoScenario) {
    setQuestion(scenario.question);
    setAnswer(scenario.answer ?? "");
    setProfileId("");
    setContext(scenario.context ?? {});
  }

  const currentTimeline =
    timeline && timeline.checks.some((check) => check.id === state.checkId) ? timeline : null;
  const currentAffected = affected && affected.checkId === state.checkId ? affected.claims : {};
  const showResults = state.phase === "running" || state.phase === "done";
  const selected = state.claims.find((view) => view.claim.id === state.selectedClaimId) ?? null;

  function submit() {
    void start({
      answer: answer.trim(),
      question: question.trim() || undefined,
      deep,
      use_cache: useCache,
      context: profileId ? null : context,
      profile_id: profileId || null,
      policy_id: policyId || null,
    });
  }

  function runAgain(withCache: boolean) {
    setUseCache(withCache);
    void start({
      answer: state.answer,
      question: question.trim() || undefined,
      deep: state.deep,
      use_cache: withCache,
      context: profileId ? null : context,
      profile_id: profileId || null,
      policy_id: policyId || null,
    });
  }

  function selectClaim(claimId: string) {
    select(claimId);
    // On one-column layouts the detail is off screen, so bring it into view.
    if (window.matchMedia("(max-width: 63.99rem)").matches) {
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      detailRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    }
  }

  const checkScenarios = scenarios.filter((scenario) => scenario.answer);

  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-8 sm:py-12 lg:px-12">
      {!showResults ? (
        <div className="mx-auto flex max-w-3xl flex-col gap-10">
          <div className="flex flex-col gap-4">
            <p className="text-xs font-semibold tracking-[0.14em] text-brand uppercase">Freshness check</p>
            <h1 className="text-[2.25rem] leading-[1.1] font-semibold tracking-tight text-balance sm:text-[3rem]">
              Is this AI answer still true?
            </h1>
            <p className="max-w-[62ch] text-[1.05rem] leading-8 text-pretty text-muted-foreground">
              ShelfLife finds the claims that can go out of date, including hidden assumptions,
              figures and advice built on them. It re-checks them against live sources, scores each
              one from the evidence, and repairs the answer.
            </p>
          </div>
          <CheckForm
            question={question}
            answer={answer}
            deep={deep}
            useCache={useCache}
            error={state.phase === "failed" ? state.error : null}
            submitting={state.phase === "starting"}
            onQuestionChange={setQuestion}
            onAnswerChange={setAnswer}
            onDeepChange={setDeep}
            onUseCacheChange={setUseCache}
            onSubmit={submit}
            examples={
              checkScenarios.length > 0 ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="mr-1 text-muted-foreground">Examples:</span>
                  {checkScenarios.map((scenario) => (
                    <Button
                      key={scenario.id}
                      data-tour={`example-${scenario.id}`}
                      type="button"
                      variant="ghost"
                      size="sm"
                      title={scenario.description}
                      className="rounded-full border bg-surface px-3 text-foreground/85 hover:border-brand/50 hover:bg-brand-soft hover:text-foreground"
                      onClick={() => applyScenario(scenario)}
                    >
                      {scenario.label}
                    </Button>
                  ))}
                  <Link href="/compare" className="inline-flex h-8 items-center rounded-full border bg-surface px-3 text-[0.8rem] font-medium text-foreground/85 hover:border-brand/50 hover:bg-brand-soft">
                    Three assistants disagree
                  </Link>
                </div>
              ) : undefined
            }
            extra={
              <div className="flex flex-col gap-4">
                <ContextPicker
                  context={context}
                  onContextChange={setContext}
                  profiles={profiles}
                  profileId={profileId}
                  onProfileChange={setProfileId}
                />
                {policies.length > 0 && (
                  <label className="flex flex-col gap-1.5 text-sm" data-tour="policy-picker">
                    <span className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <span className="font-medium">Freshness policy</span>
                      <Link href="/policies" className="text-xs text-muted-foreground underline-offset-4 hover:underline">
                        What each one does
                      </Link>
                    </span>
                    <NativeSelect value={policyId} onChange={(event) => setPolicyId(event.target.value)}>
                      {policies.map((policy) => (
                        <option key={policy.id} value={policy.id}>
                          {policy.name}
                        </option>
                      ))}
                    </NativeSelect>
                    <span className="text-xs text-muted-foreground">
                      {policies.find((policy) => policy.id === policyId)?.description}
                    </span>
                  </label>
                )}
              </div>
            }
          />
          <ErrorNote message={openError} />
          <Watchlist items={watchItems} onOpen={openCheck} onRecheck={recheck} />
        </div>
      ) : (
        <div className="results-grid">
          <section aria-label="Checked answer" className="flex min-w-0 flex-col gap-6 [grid-area:answer]">
            <div className="-ml-2 flex flex-wrap items-center gap-x-1 gap-y-1.5">
              <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={reset} data-tour="back">
                <ArrowLeft aria-hidden />
                Check another answer
              </Button>
              {state.phase === "done" && state.checkId && (
                <>
                  <a
                    href={exportUrl(state.checkId, "md")}
                    className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "text-muted-foreground")}
                  >
                    <Download aria-hidden />
                    Markdown
                  </a>
                  <a
                    href={exportUrl(state.checkId, "json")}
                    className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "text-muted-foreground")}
                  >
                    <Download aria-hidden />
                    JSON
                  </a>
                  <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => runAgain(true)}>
                    <RotateCw aria-hidden />
                    Run again
                  </Button>
                  <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => runAgain(false)}>
                    Run without cache
                  </Button>
                </>
              )}
            </div>
            <Summary state={state} />
            {question.trim() && <p className="text-sm text-muted-foreground">{question.trim()}</p>}
            <div className="flex flex-col gap-4">
              <div data-tour="answer-tabs">
                <Tabs tabs={TABS} value={tab} onChange={setTab} label="Answer view" />
              </div>
              <div role="tabpanel" aria-labelledby={`tab-${tab}`} data-tour="answer-panel">
                {tab === "highlights" && (
                  <AnswerView
                    answer={state.answer}
                    claims={state.claims}
                    selectedClaimId={state.selectedClaimId}
                    onSelect={selectClaim}
                  />
                )}
                {tab === "corrected" && (
                  <CorrectedAnswer answer={state.answer} rewrite={state.rewrite} running={state.phase !== "done"} />
                )}
                {tab === "dependencies" && <DependencyView claims={state.claims} onSelect={selectClaim} />}
                {tab === "links" &&
                  (state.phase === "done" && state.checkId ? (
                    <LinkReport checkId={state.checkId} />
                  ) : (
                    <p className="text-sm text-muted-foreground">Links can be checked once the check finishes.</p>
                  ))}
              </div>
            </div>
          </section>

          <aside
            ref={detailRef}
            data-tour="claim-detail"
            aria-label="Selected claim"
            className="min-w-0 scroll-mt-4 rounded-2xl border bg-card shadow-[0_1px_2px_oklch(0_0_0/0.04)] [grid-area:detail] lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto"
          >
            <ClaimDetail
              key={selected?.claim.id ?? "none"}
              view={selected}
              answer={state.answer}
              checkDate={state.result?.check_date ?? null}
              finished={state.phase === "done"}
              affected={selected ? currentAffected[selected.claim.id] : undefined}
              onOpenCheck={openCheck}
              allClaims={state.claims}
              onSelect={selectClaim}
            />
          </aside>

          <div className="-mx-3 min-w-0 [grid-area:claims]" data-tour="claim-list">
            <ClaimList claims={state.claims} selectedClaimId={state.selectedClaimId} onSelect={selectClaim} />
            {state.phase === "done" && state.checkId && (
              <div className="mt-6 border-t pt-6">
                <HistoryPanel timeline={currentTimeline} currentCheckId={state.checkId} onOpenCheck={openCheck} />
              </div>
            )}
          </div>

          {state.liveMetrics && (
            <div className="-mx-3 min-w-0 border-t pt-6 [grid-area:metrics]" data-tour="metrics">
              <MetricsPanel
                metrics={state.liveMetrics}
                previous={state.previousMetrics}
                running={state.phase !== "done"}
                budget={budget}
              />
            </div>
          )}
        </div>
      )}
    </main>
  );
}
