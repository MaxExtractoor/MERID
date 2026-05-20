import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, AUTH_TOKEN_KEY } from "../config/constants";

export interface UseApiDataOptions<T> {
  pollingInterval?: number;
  initialData?: T;
  transform?: (data: unknown) => T;
  enabled?: boolean;
  query?: Record<string, string | undefined>;
}

export interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  /** Alias for `loading` — matches react-query convention. */
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
  /** The raw JSON response before any transform — useful for stub detection. */
  rawResponse: unknown;
  /** True when the backend returned fallback/offline data (has _stub flag). */
  isStub: boolean;
  /** Reason string from the backend when data is a stub. */
  stubMessage: string;
  /** True when backend is unreachable (network error or down). */
  backendOffline: boolean;
}

export function useApiData<T>(
  endpoint: string,
  options: UseApiDataOptions<T> = {}
): UseApiDataResult<T> {
  const {
    pollingInterval,
    initialData,
    transform,
    enabled = true,
    query,  // stored in queryRef to avoid re-render on inline object identity changes
  } = options;

  const [data, setData] = useState<T | null>(initialData || null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [rawResponse, setRawResponse] = useState<unknown>(null);

  // Stable refs — prevent identity changes from re-triggering the effect
  const transformRef = useRef(transform);
  transformRef.current = transform;

  const queryRef = useRef(query);
  queryRef.current = query;

  const abortControllerRef = useRef<AbortController | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const generationRef = useRef(0);
  const consecutiveErrorsRef = useRef(0);
  const backoffTimerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || !endpoint) {
      setLoading(false);
      return;
    }

    // Bump generation so stale responses are discarded (no aggressive abort)
    const gen = ++generationRef.current;

    const controller = new AbortController();
    abortControllerRef.current = controller;
    // T-070: Auto-abort after 10s to prevent indefinite hangs
    const timeout = setTimeout(() => controller.abort(), 10_000);
    setLoading(true);
    setError(null);

    try {
      // Prepend API_BASE_URL unless endpoint is already absolute or empty
      let url =
        endpoint && !endpoint.startsWith("http")
          ? `${API_BASE_URL}${endpoint}`
          : endpoint;

      // Append query params if provided — filter out undefined values
      const currentQuery = queryRef.current;
      if (currentQuery) {
        const params = new URLSearchParams(
          Object.entries(currentQuery).filter((kv): kv is [string, string] => kv[1] !== undefined)
        );
        if (params.toString()) {
          url = `${url}${url.includes('?') ? '&' : '?'}${params.toString()}`;
        }
      }

      const response = await fetch(url, {
        signal: controller.signal,
        headers: (() => {
          const h: Record<string, string> = { "Content-Type": "application/json" };
          const token = localStorage.getItem(AUTH_TOKEN_KEY);
          if (token) {
            h["Authorization"] = `Bearer ${token}`;
            h["X-Session-ID"] = token;
          }
          return h;
        })(),
      });
      clearTimeout(timeout);

      // Discard if a newer request has been issued
      if (gen !== generationRef.current) return;

      // T-050: Handle 401 by attempting token refresh before failing
      if (response.status === 401) {
        const refreshToken = localStorage.getItem(`${AUTH_TOKEN_KEY}-refresh`);
        if (refreshToken) {
          try {
            const refreshRes = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (refreshRes.ok) {
              const tokens = await refreshRes.json();
              localStorage.setItem(AUTH_TOKEN_KEY, tokens.access_token);
              if (tokens.refresh_token) localStorage.setItem(`${AUTH_TOKEN_KEY}-refresh`, tokens.refresh_token);
              // Retry the original request with new token
              const retryRes = await fetch(url, {
                signal: controller.signal,
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${tokens.access_token}`,
                  'X-Session-ID': tokens.access_token,
                },
              });
              if (retryRes.ok) {
                const retryData = await retryRes.json();
                if (gen === generationRef.current) {
                  setRawResponse(retryData);
                  const xform = transformRef.current;
                  setData(xform ? xform(retryData) : retryData);
                  setLastUpdated(new Date());
                  consecutiveErrorsRef.current = 0;
                }
                return;
              }
            } else {
              // Refresh failed — clear tokens
              localStorage.removeItem(AUTH_TOKEN_KEY);
              localStorage.removeItem(`${AUTH_TOKEN_KEY}-refresh`);
            }
          } catch { /* refresh attempt failed — fall through to error */ }
        }
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const rawData = await response.json();

      // Discard stale after JSON parse
      if (gen !== generationRef.current) return;

      setRawResponse(rawData);
      const xform = transformRef.current;
      const transformedData = xform ? xform(rawData) : rawData;
      
      setData(transformedData);
      setLastUpdated(new Date());
      consecutiveErrorsRef.current = 0;
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        if (gen === generationRef.current) {
          // Cap error count to prevent unbounded growth (backoff already capped at 8x)
          consecutiveErrorsRef.current = Math.min(consecutiveErrorsRef.current + 1, 20);
          setError(err);
        }
      }
    } finally {
      if (gen === generationRef.current) {
        setLoading(false);
      }
    }
  }, [endpoint, enabled]);

  const refetch = useCallback(async () => {
    await fetchData();
  }, [fetchData]);

  // Set up polling with exponential backoff on error
  useEffect(() => {
    if (!enabled || !endpoint) {
      setLoading(false);
      return;
    }

    if (pollingInterval && pollingInterval > 0) {
      // Cancel any prior polling chain before starting a new one (BUG-007 fix)
      if (pollingIntervalRef.current) {
        clearTimeout(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }

      let mounted = true;

      // Initial fetch
      fetchData();

      // Adaptive polling: back off up to 4x base interval after consecutive errors.
      // M02 fix: always null the ref before setting a new timer so there is
      // never more than one live timer per hook instance, even if fetchData
      // completes synchronously and triggers a dependency-change re-run.
      const scheduleNext = () => {
        if (!mounted) return;
        pollingIntervalRef.current = null;
        const errors = consecutiveErrorsRef.current;
        const backoffMultiplier = errors === 0 ? 1 : Math.min(Math.pow(2, errors - 1), 8);
        const interval = pollingInterval * backoffMultiplier;
        pollingIntervalRef.current = setTimeout(async () => {
          pollingIntervalRef.current = null;
          await fetchData();
          if (mounted && pollingIntervalRef.current === null) {
            scheduleNext();
          }
        }, interval);
      };
      scheduleNext();

      return () => {
        mounted = false;
        if (pollingIntervalRef.current) {
          clearTimeout(pollingIntervalRef.current);
        }
        if (backoffTimerRef.current) {
          clearTimeout(backoffTimerRef.current);
        }
      };
    } else {
      // Single fetch if no polling
      fetchData();
    }
  }, [fetchData, pollingInterval, enabled, endpoint]);

  // Cleanup on unmount — only place we abort
  useEffect(() => {
    const generationRefCurrent = generationRef;
    const abortRefCurrent = abortControllerRef;
    const pollingRefCurrent = pollingIntervalRef;
    const backoffRefCurrent = backoffTimerRef;
    return () => {
      generationRefCurrent.current++;
      if (abortRefCurrent.current) {
        abortRefCurrent.current.abort();
      }
      if (pollingRefCurrent.current) {
        clearTimeout(pollingRefCurrent.current);
      }
      if (backoffRefCurrent.current) {
        clearTimeout(backoffRefCurrent.current);
      }
    };
  }, []);

  const rawObject = rawResponse && typeof rawResponse === 'object'
    ? (rawResponse as Record<string, unknown>)
    : null;
  const isStub = !!rawObject?._stub;
  const stubMessage = isStub ? String(rawObject?._stub_message ?? 'Offline data') : '';

  return {
    data,
    loading,
    isLoading: loading,
    error,
    refetch,
    lastUpdated,
    rawResponse,
    isStub,
    stubMessage,
    backendOffline: !!error && (error.message?.includes('fetch') || error.message?.includes('network') || false),
  };
}
