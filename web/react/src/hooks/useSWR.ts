/**
 * Lightweight SWR (stale-while-revalidate) implementation for server state management.
 * Provides caching, deduplication, and background revalidation without external dependencies.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  expiresAt: number;
}

interface SWROptions<T> {
  endpoint: string;
  fetcher?: () => Promise<T>;
  refreshInterval?: number;
  dedupingInterval?: number;
  shouldRetryOnError?: boolean;
  errorRetryCount?: number;
  errorRetryInterval?: number;
  onError?: (error: Error) => void;
  onSuccess?: (data: T) => void;
}

interface SWRResult<T> {
  data: T | undefined;
  error: Error | null;
  isLoading: boolean;
  isValidating: boolean;
  mutate: () => Promise<void>;
}

// Global cache
const globalCache = new Map<string, CacheEntry<unknown>>();

// In-flight requests for deduplication
const inFlightRequests = new Map<string, Promise<unknown>>();

/**
 * SWR hook for server state management
 */
export function useSWR<T>(options: SWROptions<T>): SWRResult<T> {
  const {
    endpoint,
    fetcher,
    refreshInterval = 0,
    dedupingInterval = 2000,
    shouldRetryOnError = true,
    errorRetryCount = 3,
    errorRetryInterval = 5000,
    onError,
    onSuccess,
  } = options;

  const [data, setData] = useState<T | undefined>(() => {
    const cached = globalCache.get(endpoint);
    return cached?.data as T | undefined;
  });
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(!globalCache.has(endpoint));
  const [isValidating, setIsValidating] = useState(false);

  const retryCountRef = useRef(0);
  const mountedRef = useRef(true);

  const fetchData = useCallback(async (): Promise<void> => {
    if (!fetcher) return;

    // Check for cached data
    const cached = globalCache.get(endpoint);
    const now = Date.now();
    
    if (cached && now - cached.timestamp < dedupingInterval) {
      // Use cached data
      setData(cached.data as T);
      setIsLoading(false);
      return;
    }

    // Check for in-flight request
    const inFlight = inFlightRequests.get(endpoint);
    if (inFlight) {
      setIsValidating(true);
      try {
        const result = await inFlight as T;
        if (mountedRef.current) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (mountedRef.current) {
          setError(err as Error);
        }
      } finally {
        if (mountedRef.current) {
          setIsValidating(false);
          setIsLoading(false);
        }
      }
      return;
    }

    // Create new request
    setIsValidating(true);
    const request = fetcher();
    inFlightRequests.set(endpoint, request);

    try {
      const result = await request;
      
      if (mountedRef.current) {
        // Update cache
        globalCache.set(endpoint, {
          data: result,
          timestamp: Date.now(),
          expiresAt: Date.now() + (refreshInterval || 60000),
        });
        
        setData(result);
        setError(null);
        retryCountRef.current = 0;
        onSuccess?.(result);
      }
    } catch (err) {
      if (mountedRef.current) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        onError?.(error);

        // Retry logic
        if (shouldRetryOnError && retryCountRef.current < errorRetryCount) {
          retryCountRef.current++;
          setTimeout(() => {
            if (mountedRef.current) {
              fetchData();
            }
          }, errorRetryInterval * retryCountRef.current);
        }
      }
    } finally {
      inFlightRequests.delete(endpoint);
      if (mountedRef.current) {
        setIsValidating(false);
        setIsLoading(false);
      }
    }
  }, [endpoint, fetcher, dedupingInterval, refreshInterval, shouldRetryOnError, errorRetryCount, errorRetryInterval, onError, onSuccess]);

  // Initial fetch
  useEffect(() => {
    mountedRef.current = true;
    fetchData();

    return () => {
      mountedRef.current = false;
    };
  }, [fetchData]);

  // Polling
  useEffect(() => {
    if (!refreshInterval || refreshInterval <= 0) return;

    const interval = setInterval(() => {
      fetchData();
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [fetchData, refreshInterval]);

  const mutate = useCallback(async () => {
    globalCache.delete(endpoint);
    await fetchData();
  }, [endpoint, fetchData]);

  return {
    data,
    error,
    isLoading,
    isValidating,
    mutate,
  };
}

/**
 * Preload data into SWR cache
 */
export function preloadSWR<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const existing = globalCache.get(key);
  if (existing) {
    return Promise.resolve(existing.data as T);
  }

  const request = fetcher().then((data) => {
    globalCache.set(key, {
      data,
      timestamp: Date.now(),
      expiresAt: Date.now() + 60000,
    });
    return data;
  });

  inFlightRequests.set(key, request);
  return request;
}

/**
 * Clear SWR cache
 */
export function clearSWRCache(key?: string): void {
  if (key) {
    globalCache.delete(key);
  } else {
    globalCache.clear();
  }
}

/**
 * Mutate SWR cache programmatically
 */
export function mutateSWR<T>(key: string, data: T): void {
  globalCache.set(key, {
    data,
    timestamp: Date.now(),
    expiresAt: Date.now() + 60000,
  });
}
