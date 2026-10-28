/**
 * React hooks for ViewMagnet API
 */

import { useState, useCallback } from "react";
import {
  analyzeVideo,
  type AnalyzeRequest,
  type AnalyzeResponse,
  type ApiError,
} from "@/lib/api";

interface UseAnalyzeVideoResult {
  analyze: (request: AnalyzeRequest) => Promise<AnalyzeResponse | null>;
  data: AnalyzeResponse | null;
  loading: boolean;
  error: string | null;
  reset: () => void;
}

export function useAnalyzeVideo(): UseAnalyzeVideoResult {
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async (request: AnalyzeRequest) => {
    setLoading(true);
    setError(null);

    try {
      const result = await analyzeVideo(request);
      setData(result);
      return result;
    } catch (err) {
      const apiError = err as ApiError;
      setError(apiError.detail || "Analysis failed");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setData(null);
    setError(null);
  }, []);

  return { analyze, data, loading, error, reset };
}

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useAsyncFn<T, Args extends unknown[]>(
  fn: (...args: Args) => Promise<T>
): [AsyncState<T>, (...args: Args) => Promise<T | null>] {
  const [state, setState] = useState<AsyncState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const execute = useCallback(
    async (...args: Args) => {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      try {
        const result = await fn(...args);
        setState({ data: result, loading: false, error: null });
        return result;
      } catch (err) {
        const apiError = err as ApiError;
        setState((prev) => ({
          ...prev,
          loading: false,
          error: apiError.detail || "An error occurred",
        }));
        return null;
      }
    },
    [fn]
  );

  return [state, execute];
}


