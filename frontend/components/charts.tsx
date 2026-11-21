"use client";

import { useState } from "react";

import type { Verdict } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One series of bars over days, with a hover tooltip and a table view. */
export function DailyBars({
  data,
}: {
  data: { date: string; checks: number; stale: number }[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((day) => day.checks));
  const label = (iso: string) =>
    new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" }).format(
      Date.parse(`${iso}T00:00:00Z`),
    );
  const active = hover !== null ? data[hover] : null;

  return (
    <figure className="flex flex-col gap-2">
      <div className="relative">
        <div className="flex h-36 items-end gap-0.5 border-b" role="img" aria-label="Checks per day over the last 14 days">
          {data.map((day, index) => (
            <button
              key={day.date}
              type="button"
              aria-label={`${label(day.date)}: ${day.checks} checks, ${day.stale} stale claims`}
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              className="flex h-full flex-1 items-end outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span
                className={cn(
                  "block w-full rounded-t-[5px] bg-brand/55 transition-colors",
                  hover === index && "bg-brand",
                )}
                style={{ height: day.checks ? `${(day.checks / max) * 100}%` : "0" }}
              />
            </button>
          ))}
        </div>
        {active && (
          <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-sm">
            <span className="font-medium">{label(active.date)}</span>: {active.checks} checks ·{" "}
            {active.stale} stale claims
          </div>
        )}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{data.length ? label(data[0].date) : ""}</span>
        <span>Most in a day: {max}</span>
        <span>{data.length ? label(data[data.length - 1].date) : ""}</span>
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">Show as a table</summary>
        <table className="mt-2 w-full">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-normal">Day</th>
              <th className="py-1 text-right font-normal">Checks</th>
              <th className="py-1 text-right font-normal">Stale claims</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {data.map((day) => (
              <tr key={day.date} className="border-t">
                <td className="py-1 font-sans">{label(day.date)}</td>
                <td className="py-1 text-right">{day.checks}</td>
                <td className="py-1 text-right">{day.stale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

const SEGMENTS: { key: string; label: string; verdicts: Verdict[]; className: string }[] = [
  { key: "stale", label: "Stale", verdicts: ["stale"], className: "bg-stale-line" },
  { key: "uncertain", label: "Uncertain", verdicts: ["uncertain"], className: "bg-uncertain-line" },
  { key: "fresh", label: "Fresh", verdicts: ["fresh"], className: "bg-fresh-line" },
  { key: "other", label: "Unverified or failed", verdicts: ["unverified", "error"], className: "bg-unknown-line" },
];

/** Verdicts per category as stacked bars, in a fixed order, with a legend and table. */
export function CategoryBars({
  data,
  labels,
}: {
  data: Record<string, Partial<Record<Verdict, number>>>;
  labels: Record<string, string>;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = Object.entries(data).map(([category, counts]) => {
    const segments = SEGMENTS.map((segment) => ({
      ...segment,
      count: segment.verdicts.reduce((sum, verdict) => sum + (counts[verdict] ?? 0), 0),
    }));
    return { category, segments, total: segments.reduce((sum, s) => sum + s.count, 0) };
  });
  const max = Math.max(1, ...rows.map((row) => row.total));

  return (
    <figure className="flex flex-col gap-3">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
        {SEGMENTS.map((segment) => (
          <li key={segment.key} className="flex items-center gap-1.5">
            <span aria-hidden className={cn("inline-block size-2.5 rounded-sm", segment.className)} />
            {segment.label}
          </li>
        ))}
      </ul>
      <ul className="flex flex-col gap-2.5">
        {rows.map((row) => (
          <li key={row.category} className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 text-sm">
            <span className="truncate text-muted-foreground">{labels[row.category] ?? row.category}</span>
            <span className="flex h-3.5 gap-0.5" style={{ width: `${(row.total / max) * 100}%` }}>
              {row.segments
                .filter((segment) => segment.count > 0)
                .map((segment, index, shown) => {
                  const id = `${row.category}-${segment.key}`;
                  return (
                    <span
                      key={segment.key}
                      tabIndex={0}
                      role="img"
                      aria-label={`${labels[row.category] ?? row.category}: ${segment.count} ${segment.label.toLowerCase()}`}
                      onMouseEnter={() => setHover(id)}
                      onMouseLeave={() => setHover(null)}
                      onFocus={() => setHover(id)}
                      onBlur={() => setHover(null)}
                      className={cn(
                        "relative h-full outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        segment.className,
                        index === 0 && "rounded-l-[4px]",
                        index === shown.length - 1 && "rounded-r-[4px]",
                      )}
                      style={{ flexGrow: segment.count, flexBasis: 0 }}
                    >
                      {hover === id && (
                        <span className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 rounded-md border bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow-sm">
                          {segment.label}: {segment.count}
                        </span>
                      )}
                    </span>
                  );
                })}
            </span>
            <span className="text-right font-mono text-xs tabular-nums text-muted-foreground">{row.total}</span>
          </li>
        ))}
      </ul>
      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground">Show as a table</summary>
        <table className="mt-2 w-full">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-normal">Category</th>
              {SEGMENTS.map((segment) => (
                <th key={segment.key} className="py-1 text-right font-normal">{segment.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {rows.map((row) => (
              <tr key={row.category} className="border-t">
                <td className="py-1 font-sans">{labels[row.category] ?? row.category}</td>
                {row.segments.map((segment) => (
                  <td key={segment.key} className="py-1 text-right">{segment.count}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
