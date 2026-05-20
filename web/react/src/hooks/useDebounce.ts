/**
 * useDebounce - Debounce hook for input throttling
 * 
 * Delays the update of a value until after a specified delay has passed
 * since the last time the value changed. Useful for search inputs, form fields,
 * and other scenarios where you want to reduce the frequency of updates.
 * 
 * Tier 3: Unified Hooks Implementation
 */

import { useState, useEffect } from 'react';

export interface UseDebounceOptions {
  /**
   * Delay in milliseconds
   */
  delay: number;
  
  /**
   * Whether debouncing is enabled
   */
  enabled?: boolean;
}

/**
 * useDebounce hook
 * 
 * @param value - The value to debounce
 * @param options - Configuration options
 * @returns The debounced value
 */
export function useDebounce<T>(value: T, options: UseDebounceOptions): T {
  const { delay, enabled = true } = options;
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    if (!enabled) {
      setDebouncedValue(value);
      return;
    }

    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay, enabled]);

  return debouncedValue;
}

/**
 * Convenience hook with default delay of 300ms
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  return useDebounce(value, { delay });
}
