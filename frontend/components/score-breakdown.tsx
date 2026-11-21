"use client";

import { Calculator } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { ClaimResult } from "@/lib/types";

const STANCE_LABELS = { supports: "Supports", contradicts: "Contradicts" } as const;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}

export function ScoreBreakdownPopover({ result }: { result: ClaimResult }) {
  const breakdown = result.score_breakdown;
  if (!breakdown) return null;

  const relevant = result.evidence.filter((source) => source.stance !== "irrelevant");
  const scored = result.freshness_score !== null && breakdown.agreement !== null;

  return (
    <Popover>
      <PopoverTrigger
        render={<Button variant="ghost" size="sm" className="-mr-1 text-muted-foreground" />}
      >
        <Calculator aria-hidden />
        How it was scored
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(25rem,calc(100vw-2rem))] gap-3 p-4">
        <PopoverHeader>
          <PopoverTitle>Score breakdown</PopoverTitle>
          <PopoverDescription className="text-xs leading-5">
            Calculated in code from each source&apos;s authority and age. This kind of
            claim loses half its recency every {breakdown.half_life_days} days.
          </PopoverDescription>
        </PopoverHeader>

        {relevant.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1 pr-2 font-normal">Source</th>
                  <th className="py-1 pr-2 text-right font-normal">Authority</th>
                  <th className="py-1 pr-2 text-right font-normal">Recency</th>
                  <th className="py-1 text-right font-normal">Weight</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {relevant.map((source) => (
                  <tr key={source.id} className="border-t">
                    <td className="max-w-36 py-1.5 pr-2 font-sans">
                      <span className="block truncate">{source.domain}</span>
                      <span className="text-muted-foreground">
                        {STANCE_LABELS[source.stance as keyof typeof STANCE_LABELS]}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right align-top">
                      {source.authority.toFixed(2)}
                    </td>
                    <td className="py-1.5 pr-2 text-right align-top">
                      {source.recency.toFixed(2)}
                    </td>
                    <td className="py-1.5 text-right align-top">{source.weight.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <dl className="flex flex-col gap-1 border-t pt-3 text-xs">
          <Row label="Supporting weight" value={breakdown.supporting_weight.toFixed(2)} />
          <Row
            label="Contradicting weight"
            value={breakdown.contradicting_weight.toFixed(2)}
          />
          {breakdown.agreement !== null && (
            <Row label="Agreement" value={breakdown.agreement.toFixed(2)} />
          )}
          <Row
            label="Best supporting recency"
            value={breakdown.best_recency.toFixed(2)}
          />
        </dl>

        <p className="rounded-md bg-muted px-2.5 py-2 text-xs leading-5">
          {scored ? (
            <>
              100 × {breakdown.agreement!.toFixed(2)} × (0.5 + 0.5 ×{" "}
              {breakdown.best_recency.toFixed(2)}) ={" "}
              <strong className="font-medium">{result.freshness_score}</strong>
            </>
          ) : (
            "The combined weight is under the 0.15 minimum, so this claim gets no score."
          )}
        </p>
      </PopoverContent>
    </Popover>
  );
}
