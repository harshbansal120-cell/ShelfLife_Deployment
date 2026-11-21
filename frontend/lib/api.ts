import type {
  AffectedAnswer,
  BudgetStatus,
  CheckFailure,
  CheckTimeline,
  WatchItem,
  CheckRequest,
  CheckResult,
  CheckStreamEvent,
  GeneratedAnswer,
  Health,
} from "@/lib/types";

export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const UNREACHABLE = `Can't reach the ShelfLife API at ${API_URL}. Check that the backend is running.`;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn an error response body into a sentence a person can act on. */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (status === 422) return "That input isn't valid. Check its length and try again.";
  return `The server returned an error (HTTP ${status}).`;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(UNREACHABLE);
  }
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await send(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readJson(response);
  if (!response.ok) {
    throw new ApiError(errorMessage(data, response.status), response.status);
  }
  return data as T;
}

export async function createCheck(request: CheckRequest): Promise<string> {
  const { check_id } = await postJson<{ check_id: string }>("/api/checks", request);
  return check_id;
}

export function generateStaleAnswer(question: string): Promise<GeneratedAnswer> {
  return postJson<GeneratedAnswer>("/api/generate-stale", { question });
}

export async function getHealth(): Promise<Health> {
  const response = await send("/api/health", { cache: "no-store" });
  // The endpoint answers 503 with the same body when a service is down.
  const data = await readJson(response);
  if (!data) throw new ApiError(UNREACHABLE, response.status);
  return data as Health;
}

export async function getBudget(): Promise<BudgetStatus> {
  const response = await send("/api/budget", { cache: "no-store" });
  const data = await readJson(response);
  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);
  return data as BudgetStatus;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await send(path, { cache: "no-store" });
  const data = await readJson(response);
  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);
  return data as T;
}

export function getHistory(checkId: string): Promise<CheckTimeline> {
  return getJson<CheckTimeline>(`/api/checks/${checkId}/history`);
}

export async function getAffected(checkId: string): Promise<Record<string, AffectedAnswer[]>> {
  return (await getJson<{ claims: Record<string, AffectedAnswer[]> }>(`/api/checks/${checkId}/affected`))
    .claims;
}

export async function getWatchlist(days = 7): Promise<WatchItem[]> {
  return (await getJson<{ items: WatchItem[] }>(`/api/watchlist?days=${days}`)).items;
}

export function exportUrl(checkId: string, format: "md" | "json"): string {
  return `${API_URL}/api/checks/${checkId}/export?format=${format}`;
}

export type CheckOutcome =
  | { status: "done"; result: CheckResult }
  | { status: "running" }
  | { status: "failed"; error: CheckFailure };

export async function getCheckOutcome(checkId: string): Promise<CheckOutcome> {
  const response = await send(`/api/checks/${checkId}`, { cache: "no-store" });
  const data = await readJson(response);
  if (response.status === 200) return { status: "done", result: data as CheckResult };
  if (response.status === 202) return { status: "running" };
  const failure = (data as { error?: CheckFailure } | null)?.error;
  return {
    status: "failed",
    error: failure ?? {
      code: "unavailable",
      message: "This check is no longer available.",
    },
  };
}

const STREAM_EVENTS = [
  "claims_extracted",
  "claim_evidence",
  "claim_scored",
  "metrics",
  "rewrite_ready",
  "done",
] as const;

/** Follow a check's progress. Returns a function that stops listening. */
export function subscribeToCheck(
  checkId: string,
  onEvent: (event: CheckStreamEvent) => void,
  onConnectionLost: () => void,
): () => void {
  const source = new EventSource(`${API_URL}/api/checks/${checkId}/events`);

  for (const type of STREAM_EVENTS) {
    source.addEventListener(type, (event) => {
      onEvent({ type, data: JSON.parse(event.data) } as CheckStreamEvent);
      if (type === "done") source.close();
    });
  }

  // "error" is both our event name and the browser's connection failure event.
  // Only ours carries data. The browser retries dropped connections by itself.
  source.addEventListener("error", (event) => {
    if (event instanceof MessageEvent) {
      onEvent({ type: "error", data: JSON.parse(event.data) });
      source.close();
    } else if (source.readyState === EventSource.CLOSED) {
      onConnectionLost();
    }
  });

  return () => source.close();
}
