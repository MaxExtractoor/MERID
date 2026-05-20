import { useEffect, useRef, useCallback } from 'react';
import { useVisibility } from './useVisibility';

export interface UsePollingOptions {
  interval: number; // Polling interval in milliseconds
  enabled?: boolean; // Whether polling is enabled
  onPoll: () => void | Promise<void>; // Function to call on each poll
  onError?: (error: Error) => void; // Error handler
}

/**
 * usePolling - Intelligent polling hook with visibility detection and exponential backoff
 * Used to reduce network requests by only polling when tab is visible (Tier 1 optimization)
 * 
 * Features:
 * - Only polls when tab is visible (uses useVisibility hook)
 * - Exponential backoff on errors (1s, 2s, 4s, 8s, 15s max)
 * - Automatic cleanup on unmount
 * - Configurable polling interval
 * 
 * Usage:
 * usePolling({
 *   interval: 5000, // Poll every 5 seconds
 *   enabled: true,
 *   onPoll: async () => {
 *     await fetchData();
 *   },
 *   onError: (error) => {
 *     console.error('Polling error:', error);
 *   },
 * });
 */
export function usePolling(options: UsePollingOptions): void {
  const { interval, enabled = true, onPoll, onError } = options;
  const isVisible = useVisibility();
  
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const backoffTimerRef = useRef<NodeJS.Timeout | null>(null);
  const consecutiveErrorsRef = useRef(0);
  const mountedRef = useRef(true);

  // Calculate backoff interval based on consecutive errors
  const getBackoffInterval = useCallback((): number => {
    const errors = consecutiveErrorsRef.current;
    if (errors === 0) return interval;
    // Exponential backoff: 1s, 2s, 4s, 8s, 15s max
    return Math.min(Math.pow(2, errors - 1) * 1000, 15000);
  }, [interval]);

  // Execute polling function
  const executePoll = useCallback(async () => {
    if (!mountedRef.current || !enabled || !isVisible) return;

    try {
      await onPoll();
      // Reset error count on success
      consecutiveErrorsRef.current = 0;
    } catch (error) {
      consecutiveErrorsRef.current = Math.min(consecutiveErrorsRef.current + 1, 10);
      onError?.(error as Error);
    }
  }, [enabled, isVisible, onPoll, onError]);

  // Schedule next poll
  const scheduleNextPoll = useCallback(() => {
    if (!mountedRef.current || !enabled || !isVisible) return;

    // Clear any existing timer
    if (pollingTimerRef.current) {
      clearTimeout(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }

    // Calculate interval with backoff
    const nextInterval = getBackoffInterval();

    // Schedule next poll
    pollingTimerRef.current = setTimeout(() => {
      pollingTimerRef.current = null;
      executePoll().then(() => {
        if (mountedRef.current && enabled && isVisible) {
          scheduleNextPoll();
        }
      });
    }, nextInterval);
  }, [enabled, isVisible, getBackoffInterval, executePoll]);

  // Start/stop polling based on enabled and visibility state
  useEffect(() => {
    if (enabled && isVisible) {
      // Start polling
      executePoll().then(() => {
        if (mountedRef.current && enabled && isVisible) {
          scheduleNextPoll();
        }
      });
    } else {
      // Stop polling
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
      if (backoffTimerRef.current) {
        clearTimeout(backoffTimerRef.current);
        backoffTimerRef.current = null;
      }
    }

    return () => {
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
      }
      if (backoffTimerRef.current) {
        clearTimeout(backoffTimerRef.current);
      }
    };
  }, [enabled, isVisible, executePoll, scheduleNextPoll]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
      }
      if (backoffTimerRef.current) {
        clearTimeout(backoffTimerRef.current);
      }
    };
  }, []);
}
