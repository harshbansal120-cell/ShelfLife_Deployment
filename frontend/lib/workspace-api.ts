import { API_URL, ApiError, errorMessage } from "@/lib/api";
import type {
  BatchStatus,
  CheckContext,
  CheckSummary,
  Comparison,
  Dashboard,
  AutopilotMode,
  AutopilotStatus,
  DeclaredEdge,
  DemoScenario,
  DocumentKind,
  DocumentView,
  EvaluationData,
  FreshnessPolicy,
  GraphData,
  ImpactReport,
  PoliciesResponse,
  PolicyCategory,
  LinkResult,
  Passport,
  Profile,
  RegressionRun,
  RegressionTest,
  SystemStatus,
} from "@/lib/types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(`Can't reach the ShelfLife API at ${API_URL}. Check that the backend is running.`);
  }
  if (response.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) throw new ApiError(errorMessage(data, response.status), response.status);
  return data as T;
}

const post = <T,>(path: string, body: unknown) =>
  call<T>(path, { method: "POST", body: JSON.stringify(body) });

export const workspaceApi = {
  dashboard: () => call<Dashboard>("/api/dashboard"),
  checks: (limit = 50) => call<{ checks: CheckSummary[] }>(`/api/checks?limit=${limit}`),
  claims: (status?: string, query?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (query) params.set("q", query);
    return call<{ claims: Passport[] }>(`/api/claims?${params}`);
  },
  claim: (id: string) => call<Passport>(`/api/claims/${encodeURIComponent(id)}`),
  evaluation: () => call<EvaluationData>("/api/evaluation"),
  compare: (body: { question?: string; answers: { app: string; answer: string }[]; context?: CheckContext | null }) =>
    post<Comparison>("/api/compare", body),
  comparisons: () => call<{ comparisons: Comparison[] }>("/api/comparisons"),
  tests: () => call<{ tests: RegressionTest[] }>("/api/tests"),
  createTest: (body: { name: string; question: string; model?: string | null; must_include: string[] }) =>
    post<RegressionTest>("/api/tests", body),
  deleteTest: (id: string) => call<void>(`/api/tests/${id}`, { method: "DELETE" }),
  runTest: (id: string) => post<RegressionRun>(`/api/tests/${id}/run`, {}),
  testRuns: (id: string) => call<{ runs: RegressionRun[] }>(`/api/tests/${id}/runs`),
  profiles: () => call<{ profiles: Profile[] }>("/api/profiles"),
  createProfile: (body: { name: string; context: CheckContext }) => post<Profile>("/api/profiles", body),
  updateProfile: (id: string, body: { name: string; context: CheckContext }) =>
    call<Profile>(`/api/profiles/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteProfile: (id: string) => call<void>(`/api/profiles/${id}`, { method: "DELETE" }),
  checkLinks: (body: { check_id?: string; urls?: string[] }) =>
    post<{ results: LinkResult[]; counts: Record<string, number> }>("/api/links/check", body),
  startBatch: (body: { items: { question?: string; answer: string }[]; context?: CheckContext | null }) =>
    post<{ batch_id: string }>("/api/batch", body),
  batch: (id: string) => call<BatchStatus>(`/api/batch/${id}`),
  system: () => call<SystemStatus>("/api/system"),
  enableCache: () => post<SystemStatus["cache_plugin"]>("/api/system/enable-cache", {}),
  demo: () => call<{ active: boolean; scenarios: DemoScenario[] }>("/api/demo"),
  policies: () => call<PoliciesResponse>("/api/policies"),
  createPolicy: (body: PolicyBody) => post<FreshnessPolicy>("/api/policies", body),
  deletePolicy: (id: string) => call<void>(`/api/policies/${id}`, { method: "DELETE" }),
  setDefaultPolicy: (policyId: string) =>
    call<PoliciesResponse>("/api/policies-default", {
      method: "PUT",
      body: JSON.stringify({ policy_id: policyId }),
    }),
  documents: () => call<{ documents: DocumentView[] }>("/api/documents"),
  createDocument: (body: { title: string; kind: DocumentKind; text: string; passport_ids?: string[] }) =>
    post<DocumentView>("/api/documents", body),
  applyDocument: (id: string) => post<DocumentView>(`/api/documents/${id}/apply`, {}),
  deleteDocument: (id: string) => call<void>(`/api/documents/${id}`, { method: "DELETE" }),
  impacts: () => call<{ items: ImpactReport[] }>("/api/impact"),
  impact: (passportId: string) => call<ImpactReport>(`/api/impact/${encodeURIComponent(passportId)}`),
  graph: () => call<GraphData>("/api/graph"),
  edges: () => call<{ edges: DeclaredEdge[] }>("/api/graph/edges"),
  addEdge: (body: { upstream: string; downstream: string; note?: string }) =>
    post<DeclaredEdge>("/api/graph/edges", body),
  deleteEdge: (id: string) => call<void>(`/api/graph/edges/${id}`, { method: "DELETE" }),
  autopilot: () => call<AutopilotStatus>("/api/autopilot"),
  setAutopilot: (body: { mode?: AutopilotMode; interval_seconds?: number; max_checks_per_cycle?: number }) =>
    call<AutopilotStatus>("/api/autopilot", { method: "PUT", body: JSON.stringify(body) }),
  runAutopilot: () => post<AutopilotStatus>("/api/autopilot/run", {}),
};

export interface PolicyBody {
  name: string;
  description?: string;
  half_life_days: Partial<Record<PolicyCategory, number>>;
  recheck_days: Partial<Record<PolicyCategory, number>>;
  withhold_categories: PolicyCategory[];
  withhold_ratio: number;
}


export const COUNTRIES = [
  "australia", "brazil", "canada", "france", "germany", "india", "indonesia", "italy",
  "japan", "mexico", "netherlands", "singapore", "south africa", "south korea", "spain",
  "united arab emirates", "united kingdom", "united states",
];

export function titleCase(text: string): string {
  return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function contextLines(context: CheckContext | null | undefined): string[] {
  if (!context) return [];
  const lines: string[] = [];
  if (context.country) lines.push(titleCase(context.country));
  if (context.edition) lines.push(context.edition);
  if (context.environment) lines.push(context.environment);
  if (context.currency) lines.push(context.currency);
  return lines;
}
