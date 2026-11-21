"use client";

import { CalendarClock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import type { WatchItem } from "@/lib/types";

/** Claims from earlier checks whose evidence is getting too old to trust. */
export function Watchlist({
  items,
  onOpen,
  onRecheck,
  bare = false,
}: {
  items: WatchItem[];
  onOpen: (checkId: string) => void;
  onRecheck: (checkId: string) => void;
  /** Leave out the heading and top border, for use inside a titled panel. */
  bare?: boolean;
}) {
  if (items.length === 0) return null;
  const overdue = items.filter((item) => item.status === "overdue").length;

  return (
    <section aria-labelledby={bare ? undefined : "watchlist-heading"} className={bare ? "flex flex-col" : "flex flex-col gap-3 border-t pt-6"}>
      <div className={bare ? "sr-only" : "flex flex-col gap-1"}>
        <h2 id="watchlist-heading" className="flex items-center gap-1.5 text-sm font-semibold">
          <CalendarClock className="size-4" aria-hidden />
          Due for a re-check
        </h2>
        <p className="text-xs text-muted-foreground">
          {overdue > 0 && `${overdue} overdue. `}
          A due date doesn&apos;t mean a claim is wrong, only that its evidence is getting old.
        </p>
      </div>
      <ul className="flex flex-col divide-y">
        {items.map((item) => (
          <li
            key={`${item.check_id}-${item.claim_id}`}
            className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between"
          >
            <div className="min-w-0">
              <p className="text-sm leading-6">{item.claim_text}</p>
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  {item.status === "overdue" ? "Overdue since" : "Due"}{" "}
                  {formatDate(item.recheck_by)}
                </span>
                {" · "}
                <span className="break-words">From: {item.question ?? item.answer_excerpt}</span>
              </p>
            </div>
            <div className="flex shrink-0 gap-1">
              <Button variant="ghost" size="sm" onClick={() => onOpen(item.check_id)}>
                Open
              </Button>
              <Button variant="outline" size="sm" onClick={() => onRecheck(item.check_id)}>
                Re-check
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
