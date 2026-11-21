"use client";

import { useMemo, useState } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { buildDiff, editCitations, editClaimIds, splitCitation } from "@/lib/diff";
import { formatDate, safeHref } from "@/lib/format";
import type { Rewrite } from "@/lib/types";
import { cn } from "@/lib/utils";

function Markers({ numbers, prefix }: { numbers: number[]; prefix: string }) {
  if (numbers.length === 0) return null;
  return (
    <sup className="ml-0.5">
      {numbers.map((number) => (
        <a
          key={number}
          href={`#${prefix}-${number}`}
          className="rounded-sm px-0.5 font-mono text-xs text-muted-foreground underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Source ${number}`}
        >
          [{number}]
        </a>
      ))}
    </sup>
  );
}

export function CorrectedAnswer({
  answer,
  rewrite,
  running,
  idPrefix = "source",
}: {
  answer: string;
  rewrite: Rewrite | null;
  running: boolean;
  /** Keeps source anchors unique when several corrected texts share a page. */
  idPrefix?: string;
}) {
  const [showChanges, setShowChanges] = useState(true);
  const [copied, setCopied] = useState(false);
  const diff = useMemo(
    () => (rewrite ? buildDiff(answer, rewrite.edits) : null),
    [answer, rewrite],
  );

  if (!rewrite || !diff) {
    return (
      <p className="text-sm text-muted-foreground">
        {running
          ? "The corrected answer appears once every claim has been checked."
          : "No corrected answer is available for this check."}
      </p>
    );
  }

  // A merged edit corrects several claims at once, such as a version and its release date.
  const changes = rewrite.edits
    .filter((edit) => edit.kind === "replace")
    .reduce((total, edit) => total + editClaimIds(edit).length, 0);
  const flags = rewrite.edits.filter((edit) => edit.kind !== "replace").length;

  async function copy() {
    try {
      await navigator.clipboard.writeText(rewrite!.corrected_answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {rewrite.edits.length === 0
            ? "Nothing needed changing."
            : `${changes} ${changes === 1 ? "claim" : "claims"} corrected, ${flags} flagged.`}{" "}
          Everything else is word for word.
        </p>
        <div className="flex items-center gap-1">
          {rewrite.edits.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              aria-pressed={showChanges}
              onClick={() => setShowChanges((value) => !value)}
            >
              {showChanges ? "Hide changes" : "Show changes"}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={copy}>
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>

      <div className="text-[15px] leading-8 whitespace-pre-wrap">
        {diff.parts.map((part, index) => {
              if (part.type === "same") return <span key={index}>{part.text}</span>;
              if (!showChanges) {
                // The clean copy: corrected text only, with its citation markers.
                return (
                  <span key={index}>
                    {part.type === "replace" ? part.added : `${part.text} ${part.flag}`}
                    <Markers numbers={part.citations} prefix={idPrefix} />
                  </span>
                );
              }
              if (part.type === "replace") {
                return (
                  <span key={index}>
                    <del className="claim-mark rounded-[3px] bg-stale-soft px-0.5 text-stale decoration-stale-line">
                      <span className="sr-only">Removed: </span>
                      {part.removed}
                    </del>{" "}
                    <ins className="claim-mark rounded-[3px] bg-fresh-soft px-0.5 text-foreground no-underline">
                      <span className="sr-only">Added: </span>
                      {part.added}
                    </ins>
                    <Markers numbers={part.citations} prefix={idPrefix} />
                  </span>
                );
              }
              return (
                <span key={index}>
                  {part.text}{" "}
                  <span className="rounded-[3px] bg-unknown-soft px-1 text-sm text-unknown italic">
                    {part.flag}
                  </span>
                  <Markers numbers={part.citations} prefix={idPrefix} />
                </span>
              );
            })}
      </div>

      {diff.notes.length > 0 && (
        <ul className="flex flex-col gap-1.5 border-l-2 pl-3 text-sm">
          {diff.notes.map((note) => (
            <li key={note.claim_id}>
              {splitCitation(note.after)}
              <Markers numbers={editCitations(note)} prefix={idPrefix} />
            </li>
          ))}
        </ul>
      )}

      {rewrite.citations.length > 0 && (
        <section aria-labelledby={`${idPrefix}-heading`} className="flex flex-col gap-2 border-t pt-4">
          <h3 id={`${idPrefix}-heading`} className="text-sm font-semibold">
            Sources
          </h3>
          <ol className="flex flex-col gap-1.5 text-sm">
            {rewrite.citations.map((citation) => {
              const href = safeHref(citation.url);
              return (
                <li
                  key={citation.number}
                  id={`${idPrefix}-${citation.number}`}
                  className={cn("flex min-w-0 gap-2 scroll-mt-6 rounded-sm")}
                >
                  <span className="font-mono text-xs leading-5 text-muted-foreground">
                    [{citation.number}]
                  </span>
                  <span className="min-w-0">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex max-w-full items-center gap-1 font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="truncate">{citation.title || citation.domain}</span>
                        <ExternalLink className="size-3 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="sr-only">(opens in a new tab)</span>
                      </a>
                    ) : (
                      <span className="font-medium">{citation.title || citation.domain}</span>
                    )}
                    <span className="block text-xs text-muted-foreground">
                      {citation.domain}
                      {citation.published_date && ` · ${formatDate(citation.published_date)}`}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
