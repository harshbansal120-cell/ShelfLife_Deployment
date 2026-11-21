"use client";

import { useMemo, type KeyboardEvent } from "react";

import type { ClaimView } from "@/lib/check-state";
import { buildSegments, nextClaimInSegment } from "@/lib/segments";
import { cn } from "@/lib/utils";
import { strongestTone, TONE_CLASSES, toneForClaim } from "@/lib/verdicts";

const LEGEND = [
  { tone: "fresh", label: "Fresh" },
  { tone: "uncertain", label: "Uncertain" },
  { tone: "stale", label: "Stale" },
  { tone: "unknown", label: "Unverified" },
] as const;

function isHighlighted(view: ClaimView): boolean {
  return view.result
    ? view.result.verdict !== "not_time_sensitive"
    : view.claim.time_sensitive && view.claim.category !== "static";
}

export function AnswerView({
  answer,
  claims,
  selectedClaimId,
  onSelect,
}: {
  answer: string;
  claims: ClaimView[];
  selectedClaimId: string | null;
  onSelect: (claimId: string) => void;
}) {
  const views = useMemo(
    () => new Map(claims.map((view) => [view.claim.id, view])),
    [claims],
  );
  const segments = useMemo(
    () =>
      buildSegments(
        answer,
        claims
          .filter(isHighlighted)
          .map((view) => ({ id: view.claim.id, span: view.claim.span })),
      ),
    [answer, claims],
  );

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[15px] leading-8 whitespace-pre-wrap">
        {segments.map((segment) => {
          if (segment.claimIds.length === 0) {
            return <span key={segment.start}>{segment.text}</span>;
          }
          const covered = segment.claimIds.flatMap((id) => views.get(id) ?? []);
          const tone = strongestTone(covered.map(toneForClaim));
          const selected =
            selectedClaimId !== null && segment.claimIds.includes(selectedClaimId);
          const open = () => {
            const next = nextClaimInSegment(segment.claimIds, selectedClaimId);
            if (next) onSelect(next);
          };
          const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              open();
            }
          };
          return (
            <mark
              key={segment.start}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={`Open claim: ${covered[0]?.claim.text ?? segment.text}`}
              onClick={open}
              onKeyDown={onKeyDown}
              className={cn(
                "claim-mark cursor-pointer rounded-[3px] px-0.5 py-0.5 text-foreground underline underline-offset-4 outline-none",
                "transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                TONE_CLASSES[tone].mark,
                selected && "ring-1 ring-foreground/50",
              )}
            >
              {segment.text}
            </mark>
          );
        })}
      </p>
      {claims.some(isHighlighted) && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {LEGEND.map(({ tone, label }) => (
            <li key={tone} className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  "claim-mark inline-block h-3 w-5 rounded-[3px] underline",
                  TONE_CLASSES[tone].mark,
                )}
              />
              {label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
