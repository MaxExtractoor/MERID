import { useState, useEffect, useCallback, useRef } from 'react';
import { useAdvancedCache, globalCaches } from './useAdvancedCache';
export { globalCaches };
import { API_BASE_URL, API_ENDPOINTS, RETRY_DEFAULTS, CACHE_TTL, AUTH_TOKEN_KEY } from '../config/constants';
import { authHeaders } from '../api/auth';

interface OptimizedDataOptions {
  endpoint: string;
  pollingInterval?: number;
  cacheKey?: string;
  cacheTTL?: number;
  useWebSocket?: boolean;
  wsUrl?: string;
  enableCache?: boolean;
  staleWhileRevalidate?: boolean;
  retryCount?: number;
  retryDelay?: number;
}

interface OptimizedDataResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  lastUpdated: number | null;
  isStale: boolean;
  refetch: () => Promise<void>;
  invalidate: () => void;
  stats: {
    cacheHits: number;
    cacheMisses: number;
    wsMessages: number;
    apiCalls: number;
  };
}

export const useOptimizedData = <T = any>(options: OptimizedDataOptions): OptimizedDataResult<T> => {
  const {
    endpoint,
    pollingInterval = 0,
    cacheKey,
    cacheTTL = CACHE_TTL.DEFAULT, // Use centralized default
    useWebSocket: _useWebSocket = false,
    wsUrl: _wsUrl,
    enableCache = true,
    staleWhileRevalidate = true,
    retryCount = RETRY_DEFAULTS.MAX_RETRIES, // Use centralized default
    retryDelay = RETRY_DEFAULTS.BASE_DELAY // Use centralized default
  } = options;

  // State
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [isStale, setIsStale] = useState(false);

  // Refs for tracking
  const statsRef = useRef({
    cacheHits: 0,
    cacheMisses: 0,
    wsMessages: 0,
    apiCalls: 0
  });

  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const consecutiveErrorsRef = useRef(0);

  // Cache instance
  const cache = useAdvancedCache<T>({ ttl: cacheTTL, maxSize: 100, strategy: 'lru' });

  // Generate cache key if not provided
  const effectiveCacheKey = cacheKey || endpoint;

  // Fetch data with retry logic
  const fetchData = useCallback(async (useCacheFirst = true): Promise<void> => {
    // Cancel any ongoing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    abortControllerRef.current = new AbortController();

    try {
      setLoading(true);
      setError(null);

      // Try cache first if enabled and requested
      if (enableCache && useCacheFirst) {
        const cachedData = cache.get(effectiveCacheKey);
        if (cachedData) {
          statsRef.current.cacheHits++;
          setData(cachedData);
          setLastUpdated(Date.now());
          
          // Check if cache is stale
          const cacheEntry = cache.cache.get(effectiveCacheKey) as any;
          if (cacheEntry && Date.now() - cacheEntry.timestamp > cacheTTL) {
            setIsStale(true);
          }
          
          setLoading(false);
          return;
        }
      }

      statsRef.current.cacheMisses++;
      statsRef.current.apiCalls++;

      // Fetch from API
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        signal: abortControllerRef.current.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
      });

      if (!response.ok) {
        throw new Error(`API request failed: ${response.status} ${response.statusText}`);
      }

      const result = await response.json();

      // Track mounted state before all state updates
      if (!mountedRef.current) return;

      consecutiveErrorsRef.current = 0;
      // Update state
      setData(result);
      setLastUpdated(Date.now());
      setIsStale(false);
      
      // Update cache
      if (enableCache) {
        cache.set(effectiveCacheKey, result);
      }

    } catch (err) {
      if (err instanceof Error && err.name !== 'AbortError') {
        // Check mounted state before setting error
        if (!mountedRef.current) return;
        consecutiveErrorsRef.current += 1;
        setError(err);

        // Retry with exponential backoff — stop after retryCount consecutive failures
        if (consecutiveErrorsRef.current <= retryCount && mountedRef.current) {
          const backoff = retryDelay * Math.pow(2, consecutiveErrorsRef.current - 1);
          retryTimeoutRef.current = setTimeout(() => {
            if (mountedRef.current) fetchData(false);
          }, Math.min(backoff, 30000));
        }
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [endpoint, enableCache, effectiveCacheKey, cache, cacheTTL, retryCount, retryDelay]);

  // Refetch function
  const refetch = useCallback(async (): Promise<void> => {
    await fetchData(false);
  }, [fetchData]);

  // Invalidate cache
  const invalidate = useCallback(() => {
    cache.remove(effectiveCacheKey);
    setData(null);
    setLastUpdated(null);
    setIsStale(false);
  }, [cache, effectiveCacheKey]);

  // Initial data fetch
  useEffect(() => {
    mountedRef.current = true;
    fetchData(true);

    return () => {
      mountedRef.current = false;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchData]);

  // Polling
  useEffect(() => {
    if (pollingInterval > 0) {
      const interval = setInterval(() => {
        fetchData(true);
      }, pollingInterval);

      return () => clearInterval(interval);
    }
  }, [pollingInterval, fetchData]);

  // Stale-while-revalidate — only revalidate if no recent consecutive errors
  useEffect(() => {
    if (staleWhileRevalidate && isStale && !loading && consecutiveErrorsRef.current === 0) {
      const timeout = setTimeout(() => {
        if (mountedRef.current) fetchData(false);
      }, 1000); // Revalidate after 1 second

      return () => clearTimeout(timeout);
    }
  }, [staleWhileRevalidate, isStale, loading, fetchData]);

  return {
    data,
    loading,
    error,
    lastUpdated,
    isStale,
    refetch,
    invalidate,
    stats: statsRef.current
  };
};

// Specialized hooks for different data types
export const useReconciliationData = (timeRange?: string) => {
  return useOptimizedData({
    endpoint: API_ENDPOINTS.RECONCILIATION_STATUS,
    pollingInterval: 10000, // 10 seconds
    cacheKey: `reconciliation_${timeRange || 'default'}`,
    cacheTTL: 2 * 60 * 1000, // 2 minutes
    useWebSocket: true,
    wsUrl: `${API_BASE_URL.replace('http', 'ws')}/ws/reconciliation`,
    enableCache: true,
    staleWhileRevalidate: true
  });
};

export const useDecisionData = (filters?: Record<string, string>) => {
  const filterString = JSON.stringify(filters || {});
  return useOptimizedData({
    endpoint: API_ENDPOINTS.EXPLAINABILITY_DECISIONS,
    pollingInterval: 30000, // 30 seconds
    cacheKey: `decisions_${filterString}`,
    cacheTTL: 10 * 60 * 1000, // 10 minutes
    useWebSocket: true,
    wsUrl: `${API_BASE_URL.replace('http', 'ws')}/ws/decisions`,
    enableCache: true,
    staleWhileRevalidate: true
  });
};

export const useAuditData = (timeRange?: string, filters?: Record<string, string>) => {
  const filterString = JSON.stringify(filters || {});
  return useOptimizedData({
    endpoint: API_ENDPOINTS.AUDIT_TRAIL_ENTRIES,
    pollingInterval: 15000, // 15 seconds
    cacheKey: `audit_${timeRange || 'default'}_${filterString}`,
    cacheTTL: 30 * 60 * 1000, // 30 minutes
    useWebSocket: true,
    wsUrl: `${API_BASE_URL.replace('http', 'ws')}/ws/audit`,
    enableCache: true,
    staleWhileRevalidate: true
  });
};

// Performance monitoring hook
export const usePerformanceMonitor = () => {
  const [performance, setPerformance] = useState(() => ({
    cacheStats: Object.entries(globalCaches).map(([name, cache]) => ({
      name,
      ...cache.getStats()
    })),
    networkStats: {
      totalRequests: 0,
      failedRequests: 0,
      avgResponseTime: 0
    }
  }));

  useEffect(() => {
    const interval = setInterval(() => {
      setPerformance(prev => ({
        ...prev,
        cacheStats: Object.entries(globalCaches).map(([name, cache]) => ({
          name,
          ...cache.getStats()
        }))
      }));
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return performance;
};

// Bundle optimization utilities
export const preloadCriticalData = async () => {
  const criticalEndpoints = [
    API_ENDPOINTS.RECONCILIATION_STATUS,
    API_ENDPOINTS.EXPLAINABILITY_DECISIONS,
    API_ENDPOINTS.AUDIT_TRAIL_ENTRIES
  ];

  const promises = criticalEndpoints.map(async (endpoint) => {
    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, { headers: authHeaders() });
      if (response.ok) {
        const data = await response.json();
        const cacheKey = endpoint.replace('/api/v1/', '');
        globalCaches[cacheKey as keyof typeof globalCaches]?.set('default', data);
      }
    } catch (error) {
      console.warn(`Failed to preload ${endpoint}:`, error);
    }
  });

  await Promise.all(promises);
};

// Memory management utilities
export const cleanupExpiredCache = () => {
  Object.values(globalCaches).forEach(cache => {
    const keys = cache.keys();
    keys.forEach(key => {
      const entry = cache.getEntry(key);
      if (entry && Date.now() - entry.timestamp > entry.ttl) {
        cache.delete(key);
      }
    });
  });
};
