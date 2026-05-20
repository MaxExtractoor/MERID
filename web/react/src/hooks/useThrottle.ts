/**
 * useThrottle - Throttle hook for rate limiting
 * 
 * Limits the frequency of function calls to at most once every specified delay.
 * Useful for scroll handlers, resize events, and other high-frequency events.
 * 
 * Tier 3: Unified Hooks Implementation
 */

import { useCallback, useRef } from 'react';

export interface UseThrottleOptions {
  /**
   * Delay in milliseconds
   */
  delay: number;
  
  /**
   * Whether throttling is enabled
   */
  enabled?: boolean;
}

/**
 * useThrottle hook
 * 
 * @param fn - The function to throttle
 * @param options - Configuration options
 * @returns The throttled function
 */
export function useThrottle<T extends (...args: any[]) => any>(
  fn: T,
  options: UseThrottleOptions
): T {
  const { delay, enabled = true } = options;
  const lastCallRef = useRef<number>(0);

  return useCallback(
    (...args: Parameters<T>) => {
      if (!enabled) {
        return fn(...args);
      }

      const now = Date.now();
      if (now - lastCallRef.current >= delay) {
        lastCallRef.current = now;
        return fn(...args);
      }
    },
    [fn, delay, enabled]
  ) as T;
}

/**
 * Convenience hook with default delay of 100ms
 */
export function useThrottledCallback<T extends (...args: any[]) => any>(
  fn: T,
  delay = 100
): T {
  return useThrottle(fn, { delay });
}
