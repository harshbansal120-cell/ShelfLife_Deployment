"use client";

import { useState } from "react";
import {
  ArrowRight,
  CalendarClock,
  Check,
  Cpu,
  Database,
  ExternalLink,
  FileText,
  Globe,
  History,
  MousePointerClick,
  Shuffle,
  X,
} from "lucide-react";

import { ScoreBreakdownPopover } from "@/components/score-breakdown";
import { Skeleton } from "@/components/ui/skeleton";
import { PendingBadge, VerdictBadge } from "@/components/verdict-badge";
import type { ClaimView } from "@/lib/check-state";
import { confidenceLabel, formatAge, formatDate, safeHref } from "@/lib/format";
import type {
  AffectedAnswer,
  Category,
  ChangeInfo,
  ClaimResult,
  Evidence,
  LlmCallInfo,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { CATEGORY_LABELS, KIND_LABELS, timeFrameLabel, TONE_CLASSES, VERDICT_INFO } from "@/lib/verdicts";

function SourceIcon({ favicon }: { favicon: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!favicon || failed) {
    return <Globe className="size-4 text-muted-foreground" aria-hidden />;
  }
  return (
    // Icons come from many unknown hosts, which next/image would have to allow-list.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={favicon}
      alt=""
      width={16}
      height={16}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="size-4 rounded-sm"
      onError={() => setFailed(true)}
    />
  );
}

function SourceLink({ source }: { source: Evidence }) {
  const href = safeHref(source.url);
  if (!href) return <span className="truncate font-medium">{source.domain}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={source.title || source.url}
      className="group/link inline-flex min-w-0 items-center gap-1 rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="truncate">{source.domain}</span>
      <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

function SourceDate({ source, checkDate }: { source: Evidence; checkDate: string | null }) {
  if (!source.published_date) return <>No date</>;
  return (
    <time dateTime={source.published_date}>
      {formatDate(source.published_date)}
      {checkDate && ` · ${formatAge(source.published_date, checkDate)}`}
    </time>
  );
}

function SourceItem({ source, checkDate }: { source: Evidence; checkDate: string | null }) {
  const supports = source.stance === "supports";
  const StanceIcon = supports ? Check : X;
  return (
    <li className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2 text-sm">
        <SourceIcon favicon={source.favicon} />
        <SourceLink source={source} />
        <span className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs">
          <StanceIcon className="size-3" aria-hidden />
          {supports ? "Supports" : "Contradicts"}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        <SourceDate source={source} checkDate={checkDate} />
      </p>
      {source.quote && (
        <blockquote className="border-l-2 pl-3 text-sm leading-6">{source.quote}</blockquote>
      )}
      {(source.extracted || !source.counted) && (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {source.extracted && (
            <span className="inline-flex items-center gap-1">
              <FileText className="size-3" aria-hidden />
              Full page read with Tavily Extract
            </span>
          )}
          {!source.counted && (
            <span>Same site or story as another source, so it counts once</span>
          )}
        </p>
      )}
    </li>
  );
}

const CHANGE_SUBJECT: Record<Category, string> = {
  pricing: "Price",
  version_api: "Version",
  product_status: "Status",
  statistic: "Figure",
  leadership_role: "Office holder",
  law_regulation: "Rule",
  event_status: "Status",
  static: "Fact",
};

function changeLabel(change: ChangeInfo, category: Category): string {
  switch (change.change_type) {
    case "value_changed":
      return `${CHANGE_SUBJECT[category]} changed`;
    case "superseded":
      return "Replaced by something newer";
    case "deprecated":
      return "Deprecated";
    case "discontinued":
      return "Discontinued";
    case "renamed":
      return "Renamed";
    default:
      return "Changed";
  }
}

function WhatChanged({
  change,
  category,
  answerSaid,
}: {
  change: ChangeInfo;
  category: Category;
  answerSaid: string;
}) {
  const href = change.source_url ? safeHref(change.source_url) : null;
  return (
    <section aria-label="What changed" className="flex flex-col gap-1.5 rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">
        What changed · <span className="font-medium text-foreground">{changeLabel(change, category)}</span>
      </p>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm leading-6">
        <span className="text-muted-foreground line-through decoration-stale-line">
          {change.old_value ?? answerSaid}
        </span>
        <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" aria-label="now" />
        <span className="font-medium">{change.new_value}</span>
      </p>
      {(change.as_of || href) && (
        <p className="text-xs text-muted-foreground">
          {change.as_of && <>As of {formatDate(change.as_of)}</>}
          {change.as_of && href && " · "}
          {href && (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              source<span className="sr-only"> (opens in a new tab)</span>
            </a>
          )}
        </p>
      )}
    </section>
  );
}

function RecheckLine({ recheckBy }: { recheckBy: string | null }) {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <CalendarClock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {recheckBy ? (
        <span>
          <span className="font-medium text-foreground">Re-check by {formatDate(recheckBy)}.</span>{" "}
          After that its newest evidence is too old to keep this verdict, unless something newer
          turns up.
        </span>
      ) : (
        <span>No re-check date: its sources don&apos;t age within five years, or have no dates.</span>
      )}
    </p>
  );
}

function AffectedList({
  items,
  onOpen,
}: {
  items: AffectedAnswer[];
  onOpen?: (checkId: string) => void;
}) {
  return (
    <section aria-label="Earlier answers affected" className="flex flex-col gap-2 border-t pt-4">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <History className="size-3.5" aria-hidden />
        Also in {items.length} earlier {items.length === 1 ? "answer" : "answers"}
      </h3>
      <p className="text-xs text-muted-foreground">
        These answers stated the same fact and were judged current when they were checked.
      </p>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li key={item.check_id} className="flex items-start justify-between gap-3 text-sm">
            <span className="min-w-0">
              <span className="block truncate">{item.answer_excerpt}</span>
              <span className="text-xs text-muted-foreground">
                Checked {formatDate(item.checked_at.slice(0, 10))} · was {item.verdict}
              </span>
            </span>
            {onOpen && (
              <button
                type="button"
                onClick={() => onOpen(item.check_id)}
                className="shrink-0 rounded-sm text-xs underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Open
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function IgnoredSources({
  sources,
  checkDate,
}: {
  sources: Evidence[];
  checkDate: string | null;
}) {
  if (sources.length === 0) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-muted-foreground select-none">
        {sources.length === 1
          ? "1 source didn't address this claim"
          : `${sources.length} sources didn't address this claim`}
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {sources.map((source) => (
          <li key={source.id} className="flex min-w-0 items-center gap-2">
            <SourceIcon favicon={source.favicon} />
            <SourceLink source={source} />
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              <SourceDate source={source} checkDate={checkDate} />
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Which model judged this claim, and whether a fallback or the cache answered. */
function JudgedBy({ call }: { call: LlmCallInfo }) {
  const Icon = call.is_fallback ? Shuffle : Cpu;
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <Icon className="size-3.5" aria-hidden />
        Judged by{" "}
        <span className="font-mono text-foreground">{call.served_by ?? "unknown model"}</span>
      </span>
      {call.is_fallback && (
        <span className="rounded-md border px-1.5 py-0.5 text-foreground">
          Fallback{call.primary_model ? ` for ${call.primary_model}` : ""}
        </span>
      )}
      {call.cache_hit && (
        <span className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-foreground">
          <Database className="size-3" aria-hidden />
          From Bifrost cache
        </span>
      )}
    </p>
  );
}

function formatNumber(value: number | null): string {
  if (value === null) return "?";
  return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function ClaimChip({
  id,
  views,
  onSelect,
}: {
  id: string;
  views: ClaimView[];
  onSelect?: (claimId: string) => void;
}) {
  const view = views.find((item) => item.claim.id === id);
  if (!view) return null;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect?.(id)}
        className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      >
        {view.result ? <VerdictBadge verdict={view.result.verdict} /> : <PendingBadge view={view} />}
        <span className="min-w-0 leading-6">
          <span className="font-mono text-xs text-muted-foreground">{id}</span>{" "}
          {view.claim.text}
          {view.claim.kind !== "fact" && (
            <span className="text-xs text-muted-foreground"> · {KIND_LABELS[view.claim.kind]}</span>
          )}
        </span>
      </button>
    </li>
  );
}

function Recalc({ result, views }: { result: ClaimResult; views: ClaimView[] }) {
  const recalc = result.recalculation;
  if (!recalc) return null;
  const textOf = (id: string) => views.find((v) => v.claim.id === id)?.claim.text ?? id;
  return (
    <section aria-label="Recalculation" className="flex flex-col gap-2 rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">
        Recalculated in code ·{" "}
        <span className="font-mono text-foreground">{recalc.formula || "no formula"}</span>
      </p>
      <ul className="flex flex-col gap-1 text-sm">
        {recalc.inputs.map((input) => (
          <li key={input.claim_id} className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-xs text-muted-foreground">{input.claim_id}</span>
            <span className="min-w-0 truncate text-muted-foreground">{textOf(input.claim_id)}</span>
            <span className="ml-auto font-mono tabular-nums">
              {formatNumber(input.stated)}
              {input.current !== input.stated && <> → {formatNumber(input.current)}</>}
            </span>
          </li>
        ))}
      </ul>
      <p className="border-t pt-2 text-sm">
        Answer said <span className="font-mono">{formatNumber(recalc.stated)}</span>; with current inputs it is{" "}
        <span className="font-mono font-medium">{formatNumber(recalc.recomputed)}</span>.
      </p>
    </section>
  );
}

/** A detail written about a value that changed, such as the release date beside an old version. */
function CoupledNote({
  result,
  views,
  onSelect,
}: {
  result: ClaimResult;
  views: ClaimView[];
  onSelect?: (claimId: string) => void;
}) {
  const anchor = views.find((view) => view.claim.id === result.coupled_to);
  const newValue = anchor?.result?.current_value;
  return (
    <section aria-label="Re-checked for the current value" className="flex flex-col gap-1.5 rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">
        Describes{" "}
        <button
          type="button"
          onClick={() => result.coupled_to && onSelect?.(result.coupled_to)}
          className="rounded-sm font-mono text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {result.coupled_to}
        </button>
        {newValue ? <>, which is now {newValue}</> : null}. True on its own, but in this answer it
        would describe the new value, so it was checked again as:
      </p>
      {result.checked_as && <p className="text-sm leading-6 font-medium">{result.checked_as}</p>}
    </section>
  );
}

function Decision({ result }: { result: ClaimResult }) {
  const decision = result.decision;
  if (!decision) return null;
  const answer = { yes: "Yes", no: "No", unclear: "Unclear" }[decision.holds];
  return (
    <section aria-label="Decision review" className="flex flex-col gap-1.5 rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">
        Does this still hold? <span className="font-medium text-foreground">{answer}</span> · the
        model&apos;s judgement{decision.judged_by && <> ({decision.judged_by})</>}, using only the
        facts below
      </p>
      {decision.reason && <p className="text-sm leading-6">{decision.reason}</p>}
      {decision.revised && (
        <p className="text-sm leading-6">
          <span className="text-muted-foreground">Revised: </span>
          <span className="font-medium">{decision.revised}</span>
        </p>
      )}
    </section>
  );
}

export function ClaimDetail({
  view,
  answer,
  checkDate,
  finished,
  affected = [],
  onOpenCheck,
  allClaims = [],
  onSelect,
}: {
  view: ClaimView | null;
  answer: string;
  checkDate: string | null;
  finished: boolean;
  affected?: AffectedAnswer[];
  onOpenCheck?: (checkId: string) => void;
  allClaims?: ClaimView[];
  onSelect?: (claimId: string) => void;
}) {
  if (!view) {
    return (
      <div className="flex flex-col items-center gap-2 px-6 py-12 text-center text-sm text-muted-foreground">
        <MousePointerClick className="size-5" aria-hidden />
        {finished
          ? "Select a claim to see its evidence."
          : "Results appear here as each claim is checked."}
      </div>
    );
  }

  const { claim, result } = view;
  const answerSaid = claim.span ? answer.slice(claim.span[0], claim.span[1]) : claim.text;
  const relevant = result?.evidence.filter((source) => source.stance !== "irrelevant") ?? [];
  const ignored = result?.evidence.filter((source) => source.stance === "irrelevant") ?? [];
  const score = result?.freshness_score ?? null;
  const independent = result?.score_breakdown?.independent_sources ?? relevant.length;
  const contradicting = relevant.filter((source) => source.stance === "contradicts" && source.counted).length;
  // History never needs re-checking; the time-frame note already says so.
  const showRecheck =
    (result?.verdict === "fresh" || result?.verdict === "uncertain") && claim.time_frame !== "past";

  return (
    <article className="flex min-w-0 flex-col gap-5 p-5 [overflow-wrap:anywhere] sm:p-6" aria-label="Claim details">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {result ? (
            <VerdictBadge verdict={result.verdict} timeFrame={claim.time_frame} />
          ) : (
            <PendingBadge view={view} />
          )}
          <span className="text-xs text-muted-foreground">
            {CATEGORY_LABELS[claim.category]}
          </span>
          {timeFrameLabel(claim) && (
            <span className="rounded-md border px-1.5 py-0.5 text-xs">{timeFrameLabel(claim)}</span>
          )}
          {claim.kind !== "fact" && (
            <span className="rounded-md border px-1.5 py-0.5 text-xs">{KIND_LABELS[claim.kind]}</span>
          )}
          {claim.passport_id && (
            <a
              href={`/claims?id=${claim.passport_id}`}
              title="This claim's verification record across checks"
              className="ml-auto rounded-sm font-mono text-xs text-muted-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              {claim.passport_id}
            </a>
          )}
        </div>
        {result && score !== null && (
          <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
            <dl className="flex flex-wrap items-end gap-x-6 gap-y-1">
              <div>
                <dt className="text-xs text-muted-foreground">Freshness</dt>
                <dd className="flex items-baseline gap-1 whitespace-nowrap">
                  <span
                    className={cn(
                      "font-mono text-3xl font-medium tabular-nums",
                      TONE_CLASSES[VERDICT_INFO[result.verdict].tone].text,
                    )}
                  >
                    {score}
                  </span>
                  <span className="text-sm text-muted-foreground">/ 100</span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Evidence strength</dt>
                <dd className="flex items-baseline gap-1 whitespace-nowrap">
                  <span className="font-mono text-xl tabular-nums">{Math.round(result.confidence * 100)}</span>
                  <span className="text-sm text-muted-foreground">
                    / 100 · {confidenceLabel(result.confidence)}
                  </span>
                </dd>
              </div>
            </dl>
            <ScoreBreakdownPopover result={result} />
          </div>
        )}
        {result && score === 0 && contradicting > 0 && (
          <p className="text-xs leading-5 text-muted-foreground">
            Freshness is 0 because no current source supports this claim, and {contradicting}{" "}
            independent {contradicting === 1 ? "source contradicts" : "sources contradict"} it.
            Evidence strength says how sure that is.
          </p>
        )}
      </header>

      {claim.time_frame === "past" && result && result.verdict !== "not_time_sensitive" && (
        <p className="rounded-lg border px-3 py-2 text-xs leading-5 text-muted-foreground" data-tour="time-frame-note">
          This claim is about {claim.as_of ?? "a past time"}, so it was checked against that time: later changes
          don&apos;t make it wrong, and it never needs re-checking.
        </p>
      )}
      {result?.coupled_to && <CoupledNote result={result} views={allClaims} onSelect={onSelect} />}
      {result?.change && (
        <WhatChanged
          change={result.change}
          // A detail (such as a release date) borrows its value's category for scoring,
          // but what changed is the detail itself, not a version.
          category={result.coupled_to ? "static" : claim.category}
          answerSaid={answerSaid}
        />
      )}
      {result && <Decision result={result} />}
      {result && <Recalc result={result} views={allClaims} />}
      {result?.context_note && (
        <p className="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
          <span className="text-muted-foreground">For your context:</span> {result.context_note}
        </p>
      )}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div className="rounded-lg border p-3">
          <dt className="mb-1 text-xs text-muted-foreground">
            {claim.kind === "assumption" ? "Answer assumed (never stated)" : "Answer said"}
          </dt>
          <dd className="text-sm leading-6">{answerSaid}</dd>
        </div>
        <div className="rounded-lg border p-3">
          <dt className="mb-1 text-xs text-muted-foreground">
            {claim.time_frame === "past" ? `Sources say it was (${claim.as_of ?? "then"})` : "Sources now say"}
          </dt>
          <dd className="text-sm leading-6">
            {!result ? (
              <Skeleton className="mt-1.5 h-4 w-3/4" />
            ) : (
              (result.current_value ?? (
                <span className="text-muted-foreground">No current value found</span>
              ))
            )}
          </dd>
        </div>
      </dl>

      {result ? (
        <>
          {result.explanation && <p className="text-sm leading-6">{result.explanation}</p>}
          {showRecheck && <RecheckLine recheckBy={result.recheck_by} />}
          {score === null && <ScoreBreakdownPopover result={result} />}
          {relevant.length > 0 && (
            <section aria-label="Evidence" className="flex flex-col gap-3 border-t pt-4">
              <h3 className="flex flex-wrap items-baseline gap-x-2 text-sm font-semibold">
                Evidence
                <span className="text-xs font-normal text-muted-foreground">
                  {relevant.length === 1 ? "1 source" : `${relevant.length} sources`}
                  {independent < relevant.length && `, ${independent} independent`}
                </span>
              </h3>
              <ul className="flex flex-col divide-y">
                {relevant.map((source) => (
                  <SourceItem key={source.id} source={source} checkDate={checkDate} />
                ))}
              </ul>
            </section>
          )}
          <IgnoredSources sources={ignored} checkDate={checkDate} />
          {claim.depends_on.length > 0 && (
            <section aria-label="Relies on" className="flex flex-col gap-2 border-t pt-4">
              <h3 className="text-sm font-semibold">
                Relies on
                {result.affected_by.length > 0 && (
                  <span className="text-xs font-normal text-muted-foreground">
                    {" "}· {result.affected_by.length} out of date
                  </span>
                )}
              </h3>
              <ul className="-mx-1.5 flex flex-col">
                {claim.depends_on.map((id) => (
                  <ClaimChip key={id} id={id} views={allClaims} onSelect={onSelect} />
                ))}
              </ul>
            </section>
          )}
          {result.verdict === "stale" && affected.length > 0 && (
            <AffectedList items={affected} onOpen={onOpenCheck} />
          )}
          {result.llm && <JudgedBy call={result.llm} />}
        </>
      ) : (
        <div className="flex flex-col gap-2 border-t pt-4" aria-hidden>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
    </article>
  );
}
