/**
 * useThrottledValue - Hook to throttle value updates
 * Prevents excessive re-renders from rapid data changes
 */

import { useState, useEffect } from 'react';

export function useThrottledValue<T>(value: T, delay: number = 100): T {
  const [throttledValue, setThrottledValue] = useState(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setThrottledValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return throttledValue;
}

export default useThrottledValue;
