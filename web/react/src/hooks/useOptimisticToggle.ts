import { useState, useCallback, useRef } from 'react';

interface ToggleState {
  value: boolean;
  isPending: boolean;
  error: Error | null;
}

interface UseOptimisticToggleOptions {
  onToggle: (value: boolean) => Promise<void>;
  onError?: (error: Error, revertedValue: boolean) => void;
  onSuccess?: (value: boolean) => void;
  debounceMs?: number;
}

/**
 * useOptimisticToggle — Optimistic toggle with rollback on failure.
 * 
 * Features:
 * - Immediately reflects new state in UI (optimistic)
 * - Rolls back to previous state if server returns error
 * - Prevents double-toggling while request is in flight
 * - Handles rapid toggles with debouncing
 * - Surfaces errors appropriately
 * 
 * Use for: Favorite/bookmark toggles, switches, checkboxes
 */
export function useOptimisticToggle(
  initialValue: boolean,
  options: UseOptimisticToggleOptions
) {
  const { onToggle, onError, onSuccess, debounceMs = 100 } = options;
  
  const [state, setState] = useState<ToggleState>({
    value: initialValue,
    isPending: false,
    error: null,
  });
  
  // Track pending requests to handle race conditions
  const pendingRef = useRef<Promise<void> | null>(null);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const lastToggleTime = useRef<number>(0);

  const toggle = useCallback(async () => {
    // Prevent rapid toggles
    const now = Date.now();
    if (now - lastToggleTime.current < debounceMs) {
      return;
    }
    lastToggleTime.current = now;

    // Clear any pending debounce
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    const previousValue = state.value;
    const newValue = !previousValue;

    // Optimistically update UI
    setState(prev => ({
      ...prev,
      value: newValue,
      isPending: true,
      error: null,
    }));

    // Debounce the actual request
    debounceRef.current = setTimeout(async () => {
      try {
        // Wait for any previous request to complete
        if (pendingRef.current) {
          await pendingRef.current;
        }

        // Create new request
        const request = onToggle(newValue);
        pendingRef.current = request;
        
        await request;
        
        // Success - keep the optimistic state
        setState(prev => ({
          ...prev,
          isPending: false,
          error: null,
        }));
        
        onSuccess?.(newValue);
      } catch (error) {
        // Rollback on error
        const err = error instanceof Error ? error : new Error(String(error));
        
        setState({
          value: previousValue, // Revert to previous value
          isPending: false,
          error: err,
        });
        
        onError?.(err, previousValue);
      } finally {
        pendingRef.current = null;
      }
    }, debounceMs);
  }, [state.value, onToggle, onError, onSuccess, debounceMs]);

  const reset = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    setState({
      value: initialValue,
      isPending: false,
      error: null,
    });
  }, [initialValue]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  return {
    value: state.value,
    isPending: state.isPending,
    error: state.error,
    toggle,
    reset,
    clearError,
  };
}

export default useOptimisticToggle;
