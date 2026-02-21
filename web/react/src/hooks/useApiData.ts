import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "../config/constants";
import { useStubRegistry } from "./useStubRegistry";

interface UseApiDataOptions<T> {
  pollingInterval?: number;
  initialData?: T;
  transform?: (data: unknown) => T;
  enabled?: boolean;
}

interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
  /** The raw JSON response before any transform — useful for stub detection. */
  rawResponse: unknown;
  /** True when the backend returned fallback/offline data (has _stub flag). */
  isStub: boolean;
  /** Reason string from the backend when data is a stub. */
  stubMessage: string;
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
  } = options;

  const [data, setData] = useState<T | null>(initialData || null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [rawResponse, setRawResponse] = useState<unknown>(null);

  // Stable refs — prevent identity changes from re-triggering the effect
  const transformRef = useRef(transform);
  transformRef.current = transform;

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
    setLoading(true);
    setError(null);

    try {
      // Prepend API_BASE_URL unless endpoint is already absolute or empty
      const url =
        endpoint && !endpoint.startsWith("http")
          ? `${API_BASE_URL}${endpoint}`
          : endpoint;

      const response = await fetch(url, {
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          // Add auth token if available
          ...(localStorage.getItem("merid-access") && {
            Authorization: `Bearer ${localStorage.getItem("merid-access")}`,
          }),
        },
      });

      // Discard if a newer request has been issued
      if (gen !== generationRef.current) return;

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
          consecutiveErrorsRef.current += 1;
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
      // Initial fetch
      fetchData();

      // Adaptive polling: back off up to 4x base interval after consecutive errors
      const scheduleNext = () => {
        const errors = consecutiveErrorsRef.current;
        const backoffMultiplier = errors === 0 ? 1 : Math.min(Math.pow(2, errors - 1), 8);
        const interval = pollingInterval * backoffMultiplier;
        pollingIntervalRef.current = setTimeout(() => {
          fetchData();
          scheduleNext();
        }, interval);
      };
      scheduleNext();

      return () => {
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

  // Report stub status to the global banner registry
  const stubRegistry = useStubRegistry();
  useEffect(() => {
    stubRegistry.register(endpoint, isStub);
    return () => { stubRegistry.register(endpoint, false); };
  }, [endpoint, isStub, stubRegistry]);

  return {
    data,
    loading,
    error,
    refetch,
    lastUpdated,
    rawResponse,
    isStub,
    stubMessage,
  };
}
