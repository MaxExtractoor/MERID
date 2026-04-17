import { useEffect, useRef, useCallback } from 'react';

interface DedupRequest {
  endpoint: string;
  timestamp: number;
  promise: Promise<unknown>;
}

// Global request deduplication registry
const globalRequestRegistry = new Map<string, DedupRequest>();
const DEDUP_WINDOW_MS = 1000; // 1 second deduplication window

/**
 * Hook for request deduplication to prevent duplicate API calls
 * when multiple components poll the same endpoint simultaneously.
 * 
 * Usage:
 * const dedup = useRequestDedup();
 * const data = await dedup.fetch('/api/data', () => fetch('/api/data'));
 */
export function useRequestDedup() {
  const activeRequests = useRef<Set<string>>(new Set());

  const fetchWithDedup = useCallback(<T>(
    endpoint: string,
    fetchFn: () => Promise<T>,
    options: { windowMs?: number } = {}
  ): Promise<T> => {
    const windowMs = options.windowMs ?? DEDUP_WINDOW_MS;
    const now = Date.now();

    // Check for existing active request to same endpoint
    const existing = globalRequestRegistry.get(endpoint);
    if (existing) {
      const age = now - existing.timestamp;
      if (age < windowMs) {
        // Return existing promise (deduplication)
        return existing.promise as Promise<T>;
      }
      // Expired, remove it
      globalRequestRegistry.delete(endpoint);
    }

    // Check if this component has an active request
    if (activeRequests.current.has(endpoint)) {
      // Wait a bit and check again
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          fetchWithDedup(endpoint, fetchFn, options).then(resolve).catch(reject);
        }, 50);
      });
    }

    // Create new request
    activeRequests.current.add(endpoint);
    const promise = fetchFn().finally(() => {
      activeRequests.current.delete(endpoint);
      // Keep in global registry briefly for cross-component dedup
      setTimeout(() => {
        globalRequestRegistry.delete(endpoint);
      }, windowMs);
    });

    // Register globally
    globalRequestRegistry.set(endpoint, {
      endpoint,
      timestamp: now,
      promise,
    });

    return promise;
  }, []);

  const clearDedup = useCallback((endpoint?: string) => {
    if (endpoint) {
      globalRequestRegistry.delete(endpoint);
      activeRequests.current.delete(endpoint);
    } else {
      // Clear all active requests for this component
      activeRequests.current.forEach((ep) => {
        globalRequestRegistry.delete(ep);
      });
      activeRequests.current.clear();
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearDedup();
    };
  }, [clearDedup]);

  return {
    fetch: fetchWithDedup,
    clear: clearDedup,
  };
}

/**
 * Shared poll registry for coordinating polling across components
 */
interface PollEntry {
  endpoint: string;
  interval: number;
  callbacks: Set<(data: unknown) => void>;
  intervalId: ReturnType<typeof setInterval> | null;
  lastData: unknown | null;
  lastFetch: number;
}

const pollRegistry = new Map<string, PollEntry>();

/**
 * Hook for shared polling - multiple components can subscribe to the same endpoint
 * and only one actual poll request will be made.
 */
export function useSharedPoll() {
  const subscribe = useCallback(<T>(
    endpoint: string,
    callback: (data: T) => void,
    options: {
      interval?: number;
      fetchFn?: () => Promise<T>;
    } = {}
  ): () => void => {
    const interval = options.interval ?? 5000;
    const fetchFn = options.fetchFn;

    let entry = pollRegistry.get(endpoint);

    if (!entry) {
      // Create new poll entry
      entry = {
        endpoint,
        interval,
        callbacks: new Set(),
        intervalId: null,
        lastData: null,
        lastFetch: 0,
      };
      pollRegistry.set(endpoint, entry);

      // Start polling
      const poll = async () => {
        if (!fetchFn) return;
        
        // Skip if already fetching (simple lock)
        if (Date.now() - entry!.lastFetch < 1000) return;
        
        entry!.lastFetch = Date.now();
        
        try {
          const data = await fetchFn();
          entry!.lastData = data;
          entry!.callbacks.forEach((cb) => cb(data));
        } catch (err) {
          console.error(`Poll failed for ${endpoint}:`, err);
        }
      };

      // Initial poll
      poll();

      // Set up interval
      entry.intervalId = setInterval(poll, interval);
    }

    // Add callback
    entry.callbacks.add(callback as (data: unknown) => void);

    // Return unsubscribe function
    return () => {
      const current = pollRegistry.get(endpoint);
      if (current) {
        current.callbacks.delete(callback as (data: unknown) => void);
        
        // Clean up if no more subscribers
        if (current.callbacks.size === 0 && current.intervalId) {
          clearInterval(current.intervalId);
          pollRegistry.delete(endpoint);
        }
      }
    };
  }, []);

  const getLastData = useCallback(<T>(endpoint: string): T | null => {
    const entry = pollRegistry.get(endpoint);
    return entry?.lastData as T | null;
  }, []);

  return {
    subscribe,
    getLastData,
  };
}
