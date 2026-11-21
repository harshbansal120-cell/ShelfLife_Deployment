import {
  CircleCheck,
  CircleDashed,
  CircleSlash,
  LoaderCircle,
  Minus,
  OctagonAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

import type { ClaimView } from "@/lib/check-state";
import type { TimeFrame, Verdict } from "@/lib/types";
import { TONE_CLASSES, VERDICT_INFO, verdictLabel } from "@/lib/verdicts";

const VERDICT_ICONS: Record<Verdict, LucideIcon> = {
  fresh: CircleCheck,
  uncertain: TriangleAlert,
  stale: OctagonAlert,
  unverified: CircleDashed,
  error: CircleSlash,
  not_time_sensitive: Minus,
};

const badgeBase =
  "inline-flex h-6 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs font-medium";

export function VerdictBadge({
  verdict,
  timeFrame,
  className,
}: {
  verdict: Verdict;
  /** A past claim's verdict says whether it was right for its time. */
  timeFrame?: TimeFrame | null;
  className?: string;
}) {
  const info = VERDICT_INFO[verdict];
  const Icon = VERDICT_ICONS[verdict];
  return (
    <span className={cn(badgeBase, TONE_CLASSES[info.tone].badge, className)}>
      <Icon className="size-3.5" aria-hidden />
      {verdictLabel(verdict, timeFrame)}
    </span>
  );
}

export function stageLabel(view: ClaimView): string {
  if (view.stage === "judging") {
    return view.sourceCount === 1
      ? "Reading 1 source"
      : `Reading ${view.sourceCount ?? 0} sources`;
  }
  return "Searching the web";
}

export function PendingBadge({ view }: { view: ClaimView }) {
  return (
    <span className={cn(badgeBase, TONE_CLASSES.pending.badge)}>
      <LoaderCircle className="size-3.5 motion-safe:animate-spin" aria-hidden />
      {stageLabel(view)}
    </span>
  );
}
