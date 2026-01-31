import { useState, useEffect, useRef, useCallback } from "react";
import { API_BASE_URL } from "../config/constants";

interface UseApiDataOptions<T> {
  pollingInterval?: number;
  initialData?: T;
  transform?: (data: any) => T;
  enabled?: boolean;
}

interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
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

  const abortControllerRef = useRef<AbortController | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;

    // Cancel any ongoing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    abortControllerRef.current = new AbortController();
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        signal: abortControllerRef.current.signal,
        headers: {
          "Content-Type": "application/json",
          // Add auth token if available
          ...(localStorage.getItem("merid-access") && {
            Authorization: `Bearer ${localStorage.getItem("merid-access")}`,
          }),
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const rawData = await response.json();
      const transformedData = transform ? transform(rawData) : rawData;
      
      setData(transformedData);
      setLastUpdated(new Date());
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err);
      }
    } finally {
      setLoading(false);
    }
  }, [endpoint, transform, enabled]);

  const refetch = useCallback(async () => {
    await fetchData();
  }, [fetchData]);

  // Set up polling
  useEffect(() => {
    if (enabled && pollingInterval && pollingInterval > 0) {
      // Initial fetch
      fetchData();

      // Set up polling
      pollingIntervalRef.current = setInterval(fetchData, pollingInterval);

      return () => {
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
        }
      };
    } else if (enabled) {
      // Single fetch if no polling
      fetchData();
    }
  }, [fetchData, pollingInterval, enabled]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
      }
    };
  }, []);

  return {
    data,
    loading,
    error,
    refetch,
    lastUpdated,
  };
}
