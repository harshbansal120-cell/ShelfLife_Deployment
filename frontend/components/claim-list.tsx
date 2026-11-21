"use client";

import { ChevronRight, Database, Shuffle } from "lucide-react";

import { PendingBadge, VerdictBadge } from "@/components/verdict-badge";
import type { ClaimView } from "@/lib/check-state";
import { cn } from "@/lib/utils";
import { CATEGORY_LABELS, KIND_LABELS, timeFrameLabel } from "@/lib/verdicts";

function isBackgroundFact(view: ClaimView): boolean {
  return view.result
    ? view.result.verdict === "not_time_sensitive"
    : !view.claim.time_sensitive || view.claim.category === "static";
}

function ClaimRow({
  view,
  selected,
  onSelect,
}: {
  view: ClaimView;
  selected: boolean;
  onSelect: (claimId: string) => void;
}) {
  const score = view.result?.freshness_score;
  return (
    <li>
      <button
        type="button"
        data-claim-id={view.claim.id}
        aria-current={selected ? "true" : undefined}
        onClick={() => onSelect(view.claim.id)}
        className={cn(
          "group grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1.5 rounded-lg px-3 py-3 text-left outline-none",
          "transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring",
          selected && "bg-muted",
        )}
      >
        <span className="text-sm leading-6">{view.claim.text}</span>
        <span className="flex items-center gap-1 pt-0.5 font-mono text-sm tabular-nums">
          {typeof score === "number" ? score : ""}
          <ChevronRight
            aria-hidden
            className="size-4 text-muted-foreground lg:opacity-0 lg:transition-opacity lg:group-hover:opacity-100"
          />
        </span>
        <span className="col-span-2 flex flex-wrap items-center gap-2">
          {view.result ? (
            <VerdictBadge verdict={view.result.verdict} timeFrame={view.claim.time_frame} />
          ) : (
            <PendingBadge view={view} />
          )}
          <span className="text-xs text-muted-foreground">
            {CATEGORY_LABELS[view.claim.category]}
          </span>
          {timeFrameLabel(view.claim) && (
            <span className="rounded-md border px-1.5 py-0.5 text-xs">{timeFrameLabel(view.claim)}</span>
          )}
          {view.claim.kind !== "fact" && (
            <span className="rounded-md border px-1.5 py-0.5 text-xs">{KIND_LABELS[view.claim.kind]}</span>
          )}
          {view.result?.llm?.is_fallback && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Shuffle className="size-3" aria-hidden />
              Fallback
            </span>
          )}
          {view.result?.llm?.cache_hit && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Database className="size-3" aria-hidden />
              Cached
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

export function ClaimList({
  claims,
  selectedClaimId,
  onSelect,
}: {
  claims: ClaimView[];
  selectedClaimId: string | null;
  onSelect: (claimId: string) => void;
}) {
  const checked = claims.filter((view) => !isBackgroundFact(view));
  const background = claims.filter(isBackgroundFact);

  return (
    <div className="flex flex-col gap-4">
      {checked.length > 0 && (
        <section aria-labelledby="claims-heading">
          <h2 id="claims-heading" className="mb-1 px-3 text-sm font-semibold">
            Claims checked <span className="text-muted-foreground">{checked.length}</span>
          </h2>
          <ul className="flex flex-col">
            {checked.map((view) => (
              <ClaimRow
                key={view.claim.id}
                view={view}
                selected={view.claim.id === selectedClaimId}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </section>
      )}
      {background.length > 0 && (
        <details className="group/details px-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground select-none">
            {background.length === 1
              ? "1 fact that doesn't change over time"
              : `${background.length} facts that don't change over time`}
          </summary>
          <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-5 leading-6 text-muted-foreground">
            {background.map((view) => (
              <li key={view.claim.id}>{view.claim.text}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
