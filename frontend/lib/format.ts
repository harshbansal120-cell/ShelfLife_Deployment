const DAY_MS = 86_400_000;

function utcTime(isoDate: string): number {
  return Date.parse(`${isoDate}T00:00:00Z`);
}

export function formatDate(isoDate: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(utcTime(isoDate));
}

export function formatAge(isoDate: string, checkDate: string): string {
  const days = Math.round((utcTime(checkDate) - utcTime(isoDate)) / DAY_MS);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 60) return `${days} days ago`;
  if (days < 730) return `${Math.round(days / 30.44)} months ago`;
  return `${Math.round(days / 365.25)} years ago`;
}

export function confidenceLabel(confidence: number): "Low" | "Medium" | "High" {
  if (confidence >= 0.7) return "High";
  if (confidence >= 0.4) return "Medium";
  return "Low";
}

export function formatCost(costUsd: number, unpricedCalls: number): string {
  const cost = `$${costUsd.toFixed(4)}`;
  if (unpricedCalls === 0) return cost;
  return costUsd > 0 ? `${cost} + ${unpricedCalls} unpriced` : "Not reported";
}

export function formatDuration(milliseconds: number): string {
  return milliseconds < 1000
    ? `${milliseconds} ms`
    : `${(milliseconds / 1000).toFixed(1)} s`;
}

const RESET_PERIODS: Record<string, string> = {
  "1h": "hour",
  "1d": "day",
  "1w": "week",
  "1M": "month",
  "1Q": "quarter",
  "1Y": "year",
};

export function formatResetPeriod(duration: string | null): string | null {
  if (!duration) return null;
  return RESET_PERIODS[duration] ?? duration;
}

/** Links come from the web, so only ordinary web addresses become clickable. */
export function safeHref(url: string): string | null {
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:" ? url : null;
  } catch {
    return null;
  }
}
