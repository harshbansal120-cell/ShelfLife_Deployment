"use client";

import { GitBranch } from "lucide-react";

import { PendingBadge, VerdictBadge } from "@/components/verdict-badge";
import { EmptyState } from "@/components/ui-kit";
import type { ClaimView } from "@/lib/check-state";
import { KIND_LABELS } from "@/lib/verdicts";

function Node({
  id,
  views,
  onSelect,
  depth,
  seen,
}: {
  id: string;
  views: Map<string, ClaimView>;
  onSelect: (claimId: string) => void;
  depth: number;
  seen: Set<string>;
}) {
  const view = views.get(id);
  if (!view || seen.has(id) || depth > 6) return null;
  const next = new Set(seen).add(id);
  return (
    <li className="flex flex-col">
      <button
        type="button"
        onClick={() => onSelect(id)}
        className="flex items-start gap-2 rounded-md px-1.5 py-1 text-left text-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      >
        {view.result ? <VerdictBadge verdict={view.result.verdict} /> : <PendingBadge view={view} />}
        <span className="min-w-0 leading-6">
          {view.claim.text}
          <span className="text-xs text-muted-foreground"> · {KIND_LABELS[view.claim.kind]}</span>
          {view.claim.formula && (
            <span className="ml-1 font-mono text-xs text-muted-foreground">= {view.claim.formula}</span>
          )}
        </span>
      </button>
      {view.claim.depends_on.length > 0 && (
        <ul className="ml-4 flex flex-col border-l pl-2">
          {view.claim.depends_on.map((dep) => (
            <Node key={dep} id={dep} views={views} onSelect={onSelect} depth={depth + 1} seen={next} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Recommendations and calculations, with everything they rely on beneath them. */
export function DependencyView({
  claims,
  onSelect,
}: {
  claims: ClaimView[];
  onSelect: (claimId: string) => void;
}) {
  const views = new Map(claims.map((view) => [view.claim.id, view]));
  const usedBy = new Set(claims.flatMap((view) => view.claim.depends_on));
  // Roots: claims with dependencies that nothing else depends on.
  const roots = claims.filter((view) => view.claim.depends_on.length > 0 && !usedBy.has(view.claim.id));
  if (roots.length === 0) {
    return (
      <EmptyState>
        This answer has no recommendations or calculations that rely on other claims.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <GitBranch className="size-4" aria-hidden />
        When a claim goes stale, everything above it in the tree is affected.
      </p>
      <ul className="-mx-1.5 flex flex-col gap-3">
        {roots.map((root) => (
          <Node key={root.claim.id} id={root.claim.id} views={views} onSelect={onSelect} depth={0} seen={new Set()} />
        ))}
      </ul>
    </div>
  );
}
