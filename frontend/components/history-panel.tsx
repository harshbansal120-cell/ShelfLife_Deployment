"use client";

import { History } from "lucide-react";

import { formatDate } from "@/lib/format";
import type { CheckTimeline } from "@/lib/types";
import { cn } from "@/lib/utils";
import { TONE_CLASSES, VERDICT_INFO } from "@/lib/verdicts";

/** Each claim's verdict across every check of this answer, oldest first. */
export function HistoryPanel({
  timeline,
  currentCheckId,
  onOpenCheck,
}: {
  timeline: CheckTimeline | null;
  currentCheckId: string;
  onOpenCheck: (checkId: string) => void;
}) {
  if (!timeline) return null;
  const { checks, claims } = timeline;

  return (
    <section aria-labelledby="history-heading" className="flex flex-col gap-3 px-3">
      <h2 id="history-heading" className="flex items-center gap-1.5 text-sm font-semibold">
        <History className="size-3.5" aria-hidden />
        Check history
      </h2>
      {checks.length < 2 ? (
        <p className="text-sm text-muted-foreground">
          This is the first check of this answer. Check it again later to see how its claims
          change over time.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-md text-xs">
            <caption className="sr-only">Verdicts for each claim in each check of this answer</caption>
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1.5 pr-3 font-normal">Claim</th>
                {checks.map((check) => (
                  <th key={check.id} className="px-1.5 py-1.5 text-center font-normal whitespace-nowrap">
                    {check.id === currentCheckId ? (
                      <span className="font-medium text-foreground">Now</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onOpenCheck(check.id)}
                        className="rounded-sm underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {formatDate(check.checked_at.slice(0, 10))}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => {
                const byCheck = new Map(claim.entries.map((entry) => [entry.check_id, entry]));
                return (
                  <tr key={claim.claim_id} className="border-t">
                    <td className="max-w-64 py-1.5 pr-3">
                      <span className="line-clamp-2">{claim.claim_text}</span>
                    </td>
                    {checks.map((check) => {
                      const entry = byCheck.get(check.id);
                      if (!entry) {
                        return (
                          <td key={check.id} className="px-1.5 text-center text-muted-foreground">
                            <span aria-label="Not found in this check">–</span>
                          </td>
                        );
                      }
                      const info = VERDICT_INFO[entry.verdict];
                      return (
                        <td key={check.id} className="px-1.5 py-1.5 text-center">
                          <span
                            className={cn(
                              "inline-flex rounded-md px-1.5 py-0.5 whitespace-nowrap",
                              TONE_CLASSES[info.tone].badge,
                            )}
                          >
                            {info.label}
                            {entry.score !== null && ` ${entry.score}`}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
