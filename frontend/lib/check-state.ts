import type {
  Claim,
  ClaimResult,
  CheckResult,
  CheckStreamEvent,
  Metrics,
  Rewrite,
} from "@/lib/types";

export type CheckPhase = "editing" | "starting" | "running" | "done" | "failed";
export type ClaimStage = "searching" | "judging" | "finished";

export interface ClaimView {
  claim: Claim;
  stage: ClaimStage;
  sourceCount: number | null;
  result: ClaimResult | null;
}

export interface CheckState {
  phase: CheckPhase;
  checkId: string | null;
  answer: string;
  deep: boolean;
  useCache: boolean;
  claims: ClaimView[];
  claimsReady: boolean;
  result: CheckResult | null;
  rewrite: Rewrite | null;
  // Updated during the run, so the metrics panel can fill in live.
  liveMetrics: Metrics | null;
  // The last run of the same answer, for the before-and-after comparison.
  previousMetrics: Metrics | null;
  error: string | null;
  selectedClaimId: string | null;
}

export type CheckAction =
  | { type: "start"; answer: string; deep: boolean; useCache: boolean }
  | { type: "started"; checkId: string }
  | { type: "event"; event: CheckStreamEvent }
  | { type: "failed"; message: string }
  | { type: "select"; claimId: string }
  | { type: "loaded"; result: CheckResult }
  | { type: "reset" };

export const initialCheckState: CheckState = {
  phase: "editing",
  checkId: null,
  answer: "",
  deep: false,
  useCache: true,
  claims: [],
  claimsReady: false,
  result: null,
  rewrite: null,
  liveMetrics: null,
  previousMetrics: null,
  error: null,
  selectedClaimId: null,
};

function finishedView(result: ClaimResult): ClaimView {
  return {
    claim: result.claim,
    stage: "finished",
    sourceCount: result.evidence.length,
    result,
  };
}

function isChecked(view: ClaimView): boolean {
  return view.result
    ? view.result.verdict !== "not_time_sensitive"
    : view.claim.time_sensitive && view.claim.category !== "static";
}

/** The claim most worth showing first: stale, then uncertain, then any checked one. */
export function preferredClaimId(claims: ClaimView[]): string | null {
  const finished = claims.filter((view) => view.result && isChecked(view));
  const pick =
    finished.find((view) => view.result?.verdict === "stale") ??
    finished.find((view) => view.result?.verdict === "uncertain") ??
    finished[0];
  return pick?.claim.id ?? null;
}

export function checkProgress(state: CheckState): { finished: number; total: number } {
  const checked = state.claims.filter(isChecked);
  return {
    finished: checked.filter((view) => view.stage === "finished").length,
    total: checked.length,
  };
}

function applyEvent(state: CheckState, event: CheckStreamEvent): CheckState {
  switch (event.type) {
    case "claims_extracted": {
      // A reconnect can replay events, so keep what is already known.
      const known = new Map(state.claims.map((view) => [view.claim.id, view]));
      return {
        ...state,
        claimsReady: true,
        claims: event.data.claims.map(
          (claim) =>
            known.get(claim.id) ?? {
              claim,
              stage: "searching",
              sourceCount: null,
              result: null,
            },
        ),
      };
    }
    case "claim_evidence":
      return {
        ...state,
        claims: state.claims.map((view) =>
          view.claim.id === event.data.claim_id && view.stage !== "finished"
            ? { ...view, stage: "judging", sourceCount: event.data.sources.length }
            : view,
        ),
      };
    case "claim_scored": {
      const result = event.data;
      const selectStale = !state.selectedClaimId && result.verdict === "stale";
      return {
        ...state,
        selectedClaimId: selectStale ? result.claim.id : state.selectedClaimId,
        claims: state.claims.map((view) =>
          view.claim.id === result.claim.id ? finishedView(result) : view,
        ),
      };
    }
    case "metrics":
      return { ...state, liveMetrics: event.data };
    case "rewrite_ready":
      return { ...state, rewrite: event.data };
    case "done": {
      const claims = event.data.claims.map(finishedView);
      return {
        ...state,
        phase: "done",
        claimsReady: true,
        result: event.data,
        rewrite: {
          corrected_answer: event.data.corrected_answer ?? event.data.answer,
          edits: event.data.edits,
          citations: event.data.citations,
        },
        liveMetrics: event.data.metrics,
        claims,
        selectedClaimId: state.selectedClaimId ?? preferredClaimId(claims),
      };
    }
    case "error":
      return { ...state, phase: "failed", error: event.data.message };
  }
}

export function checkReducer(state: CheckState, action: CheckAction): CheckState {
  switch (action.type) {
    case "start":
      return {
        ...initialCheckState,
        phase: "starting",
        answer: action.answer,
        deep: action.deep,
        useCache: action.useCache,
        previousMetrics:
          action.answer === state.answer && state.result ? state.result.metrics : null,
      };
    case "started":
      return { ...state, phase: "running", checkId: action.checkId };
    case "event":
      return applyEvent(state, action.event);
    case "failed":
      return { ...state, phase: "failed", error: action.message };
    case "select":
      return { ...state, selectedClaimId: action.claimId };
    case "loaded": {
      // A saved check, opened from history: no live events, straight to the result.
      const loaded = applyEvent(
        { ...initialCheckState, phase: "running", answer: action.result.answer },
        { type: "done", data: action.result },
      );
      return { ...loaded, checkId: action.result.id };
    }
    case "reset":
      return initialCheckState;
  }
}
