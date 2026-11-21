import type { ClaimView } from "@/lib/check-state";
import type { Category, ClaimKind, TimeFrame, Verdict } from "@/lib/types";

export type Tone = "fresh" | "uncertain" | "stale" | "unknown" | "pending";

export const VERDICT_INFO: Record<Verdict, { label: string; tone: Tone }> = {
  fresh: { label: "Fresh", tone: "fresh" },
  uncertain: { label: "Uncertain", tone: "uncertain" },
  stale: { label: "Stale", tone: "stale" },
  unverified: { label: "Unverified", tone: "unknown" },
  error: { label: "Couldn't check", tone: "unknown" },
  not_time_sensitive: { label: "Doesn't change", tone: "unknown" },
};

/** A past claim is right or wrong for its time; "fresh" and "stale" describe today. */
const HISTORICAL_LABELS: Partial<Record<Verdict, string>> = {
  fresh: "Correct for its time",
  uncertain: "Unclear for its time",
  stale: "Wrong for its time",
};

export function verdictLabel(verdict: Verdict, timeFrame?: TimeFrame | null): string {
  return (timeFrame === "past" && HISTORICAL_LABELS[verdict]) || VERDICT_INFO[verdict].label;
}

/** "As of June 2025" for a past claim, "Planned for 2026" for a future one, else null. */
export function timeFrameLabel(claim: { time_frame?: TimeFrame; as_of?: string | null }): string | null {
  if (claim.time_frame === "past") return claim.as_of ? `As of ${claim.as_of}` : "About the past";
  if (claim.time_frame === "future") return claim.as_of ? `Planned: ${claim.as_of}` : "Planned or expected";
  return null;
}

export const CATEGORY_LABELS: Record<Category, string> = {
  pricing: "Pricing",
  version_api: "Version or API",
  product_status: "Product status",
  statistic: "Statistic",
  leadership_role: "Leadership",
  law_regulation: "Law or regulation",
  event_status: "Current event",
  static: "Background fact",
};

export const TONE_CLASSES: Record<Tone, { badge: string; text: string; mark: string }> = {
  fresh: {
    badge: "bg-fresh-soft text-fresh",
    text: "text-fresh",
    mark: "bg-fresh-soft decoration-fresh-line decoration-solid decoration-[1.5px]",
  },
  uncertain: {
    badge: "bg-uncertain-soft text-uncertain",
    text: "text-uncertain",
    mark: "bg-uncertain-soft decoration-uncertain-line decoration-dashed decoration-2",
  },
  stale: {
    badge: "bg-stale-soft text-stale",
    text: "text-stale",
    mark: "bg-stale-soft decoration-stale-line decoration-solid decoration-[3px]",
  },
  unknown: {
    badge: "bg-unknown-soft text-unknown",
    text: "text-unknown",
    mark: "bg-unknown-soft decoration-unknown-line decoration-dotted decoration-2",
  },
  pending: {
    badge: "bg-muted text-muted-foreground",
    text: "text-muted-foreground",
    mark: "bg-muted decoration-border decoration-dotted decoration-2 motion-safe:animate-pulse",
  },
};

export function toneForScore(score: number): Tone {
  if (score >= 70) return "fresh";
  if (score >= 40) return "uncertain";
  return "stale";
}

export function toneForClaim(view: ClaimView): Tone {
  return view.result ? VERDICT_INFO[view.result.verdict].tone : "pending";
}

const TONE_PRIORITY: Tone[] = ["stale", "uncertain", "pending", "unknown", "fresh"];

/** Where claims overlap, show the one the reader most needs to notice. */
export function strongestTone(tones: Tone[]): Tone {
  return TONE_PRIORITY.find((tone) => tones.includes(tone)) ?? "unknown";
}

export const KIND_LABELS: Record<ClaimKind, string> = {
  fact: "Fact",
  assumption: "Hidden assumption",
  calculation: "Calculation",
  recommendation: "Recommendation",
  api_usage: "Code",
  availability: "Availability",
};
