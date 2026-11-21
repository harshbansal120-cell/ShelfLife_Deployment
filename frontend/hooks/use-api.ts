"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";

interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** Load data from the API, with a reload function for after changes. */
export function useApi<T>(loader: () => Promise<T>, key = "") {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    loader()
      .then((data) => {
        if (active) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (!active) return;
        const message = error instanceof ApiError ? error.message : "Something went wrong.";
        setState((previous) => ({ ...previous, error: message, loading: false }));
      });
    return () => {
      active = false;
    };
    // The loader is recreated every render; the key and version say when to reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  return { ...state, reload };
}
