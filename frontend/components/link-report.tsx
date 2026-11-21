"use client";

import { useState } from "react";
import { Link2, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorNote } from "@/components/ui-kit";
import { ApiError } from "@/lib/api";
import { safeHref } from "@/lib/format";
import type { LinkResult } from "@/lib/types";
import { workspaceApi } from "@/lib/workspace-api";

const STATUS_LABELS: Record<LinkResult["status"], string> = {
  ok: "Works",
  changed: "Evidence gone from page",
  moved: "Moved",
  gone: "Page deleted",
  blocked: "Site refused check",
  error: "Couldn't check",
};

export function LinkTable({ results }: { results: LinkResult[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-lg text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-1.5 pr-3 font-normal">Status</th>
            <th className="py-1.5 pr-3 font-normal">Link</th>
            <th className="py-1.5 font-normal">What we found</th>
          </tr>
        </thead>
        <tbody>
          {results.map((item) => {
            const href = safeHref(item.url);
            return (
              <tr key={`${item.url}-${item.claim_id}`} className="border-t align-top">
                <td className="py-2 pr-3 whitespace-nowrap">
                  <span className="rounded-md border px-1.5 py-0.5 text-xs">{STATUS_LABELS[item.status]}</span>
                </td>
                <td className="max-w-64 py-2 pr-3">
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="break-all underline-offset-4 hover:underline">
                      {item.url}
                    </a>
                  ) : (
                    <span className="break-all">{item.url}</span>
                  )}
                  <span className="block text-xs text-muted-foreground">
                    {item.source === "evidence"
                      ? `Evidence for: ${item.claim_text ?? item.claim_id}`
                      : item.source === "answer"
                        ? "Cited in the answer"
                        : "Pasted"}
                    {item.final_url !== item.url && ` · now at ${item.final_url}`}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">{item.detail}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Check that the pages a check relied on still exist and still say the same thing. */
export function LinkReport({ checkId }: { checkId: string }) {
  const [results, setResults] = useState<LinkResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResults((await workspaceApi.checkLinks({ check_id: checkId })).results);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The links couldn't be checked.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Visit every source this check used, and any link in the answer, to find pages that moved,
          were deleted, or no longer contain the quoted evidence.
        </p>
        <Button variant="outline" size="sm" onClick={run} disabled={running}>
          {running ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden /> : <Link2 aria-hidden />}
          {results ? "Check again" : "Check links"}
        </Button>
      </div>
      <ErrorNote message={error} />
      {results && <LinkTable results={results} />}
    </div>
  );
}
