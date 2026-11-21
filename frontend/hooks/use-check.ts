"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError, createCheck, getCheckOutcome, subscribeToCheck } from "@/lib/api";
import { checkReducer, initialCheckState } from "@/lib/check-state";
import type { CheckRequest, CheckResult } from "@/lib/types";

const CONNECTION_LOST = "The connection to the server was lost before the check finished.";

export function useCheck() {
  const [state, dispatch] = useReducer(checkReducer, initialCheckState);
  const stopListening = useRef<(() => void) | null>(null);
  // Guards against a slow response from a check the user has already left.
  const runId = useRef(0);

  useEffect(() => () => stopListening.current?.(), []);

  const start = useCallback(async (request: CheckRequest) => {
    stopListening.current?.();
    runId.current += 1;
    const thisRun = runId.current;
    dispatch({
      type: "start",
      answer: request.answer,
      deep: Boolean(request.deep),
      useCache: request.use_cache !== false,
    });

    let checkId: string;
    try {
      checkId = await createCheck(request);
    } catch (error) {
      if (thisRun === runId.current) {
        const message =
          error instanceof ApiError ? error.message : "The check couldn't be started.";
        dispatch({ type: "failed", message });
      }
      return;
    }
    if (thisRun !== runId.current) return;

    dispatch({ type: "started", checkId });
    stopListening.current = subscribeToCheck(
      checkId,
      (event) => dispatch({ type: "event", event }),
      async () => {
        // The stream can close just as a check ends, so ask for the final state.
        try {
          const outcome = await getCheckOutcome(checkId);
          if (thisRun !== runId.current) return;
          if (outcome.status === "done") {
            dispatch({ type: "event", event: { type: "done", data: outcome.result } });
          } else if (outcome.status === "failed") {
            dispatch({ type: "failed", message: outcome.error.message });
          } else {
            dispatch({ type: "failed", message: CONNECTION_LOST });
          }
        } catch {
          if (thisRun === runId.current) {
            dispatch({ type: "failed", message: CONNECTION_LOST });
          }
        }
      },
    );
  }, []);

  const reset = useCallback(() => {
    stopListening.current?.();
    runId.current += 1;
    dispatch({ type: "reset" });
  }, []);

  const select = useCallback((claimId: string) => {
    dispatch({ type: "select", claimId });
  }, []);

  const load = useCallback((result: CheckResult) => {
    stopListening.current?.();
    runId.current += 1;
    dispatch({ type: "loaded", result });
  }, []);

  return { state, start, reset, select, load };
}
