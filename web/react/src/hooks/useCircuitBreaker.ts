import { useState, useEffect, useCallback, useRef } from 'react';
import { CircuitBreakerState } from '../types/risk';
export type { CircuitBreakerState };
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUiError } from '../utils/logger';

export interface CircuitBreakerDetail {
  name: string;
  state: CircuitBreakerState;
  failure_count: number;
  success_count: number;
  total_calls: number;
  blocked_calls: number;
  last_failure_time: string | null;
  last_success_time: string | null;
  last_transition_time: string | null;
  recovery_timeout_seconds: number;
  failure_threshold: number;
  success_threshold: number;
}

export interface CircuitBreakerSummary {
  overall_status: 'healthy' | 'degraded' | 'critical';
  total_breakers: number;
  open_count: number;
  half_open_count: number;
  closed_count: number;
  last_updated: string;
}

export interface CircuitBreakerData {
  summary: CircuitBreakerSummary;
  breakers: CircuitBreakerDetail[];
  kalshi_specific: {
    rest_client: CircuitBreakerDetail;
    websocket: CircuitBreakerDetail;
    order_placement: CircuitBreakerDetail;
  };
}

export interface UseCircuitBreakerReturn {
  data: CircuitBreakerData | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  resetBreaker: (name: string) => Promise<boolean>;
}

const POLL_INTERVAL = 30000; // 30 seconds

export function useCircuitBreaker(pollingInterval = POLL_INTERVAL): UseCircuitBreakerReturn {
  const [data, setData] = useState<CircuitBreakerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const consecutiveFailures = useRef(0);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      'merid-access': 'O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8',
      ...(headers ?? {}),
    };
  }, []);

  const fetchCircuitBreaker = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CIRCUIT_BREAKER}`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const json = await response.json();
      setData(json);
      setError(null);
      consecutiveFailures.current = 0;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch circuit breaker status';
      setError(message);
      if (consecutiveFailures.current === 0) {
        logUiError('useCircuitBreaker', 'Circuit breaker fetch error', err);
      }
      consecutiveFailures.current += 1;
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  const refetch = useCallback(async () => {
    setLoading(true);
    await fetchCircuitBreaker();
  }, [fetchCircuitBreaker]);

  const resetBreaker = useCallback(async (name: string): Promise<boolean> => {
    try {
      const response = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_CIRCUIT_BREAKER}/${encodeURIComponent(name)}/reset`,
        {
          method: 'POST',
          headers: authHeaders(),
        }
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      await fetchCircuitBreaker(); // Refresh data after reset
      return true;
    } catch (err) {
      logUiError('useCircuitBreaker', `Failed to reset breaker ${name}`, err);
      return false;
    }
  }, [authHeaders, fetchCircuitBreaker]);

  useEffect(() => {
    fetchCircuitBreaker();
    
    const interval = setInterval(() => {
      if (consecutiveFailures.current > 1) return; // back off: skip ticks while backend is down
      fetchCircuitBreaker();
    }, pollingInterval);
    return () => clearInterval(interval);
  }, [fetchCircuitBreaker, pollingInterval]);

  return {
    data,
    loading,
    error,
    refetch,
    resetBreaker,
  };
}

// Helper to get color for circuit breaker state
export function getCircuitBreakerColor(state: CircuitBreakerState): string {
  switch (state) {
    case 'CLOSED':
      return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
    case 'HALF_OPEN':
      return 'text-amber-400 bg-amber-400/10 border-amber-400/20';
    case 'OPEN':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    default:
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
  }
}

// Helper to get icon name for circuit breaker state
export function getCircuitBreakerIcon(state: CircuitBreakerState): string {
  switch (state) {
    case 'CLOSED':
      return 'CheckCircle';
    case 'HALF_OPEN':
      return 'AlertTriangle';
    case 'OPEN':
      return 'XCircle';
    default:
      return 'HelpCircle';
  }
}

// Helper to format state for display
export function formatCircuitBreakerState(state: CircuitBreakerState): string {
  switch (state) {
    case 'CLOSED':
      return 'Healthy';
    case 'HALF_OPEN':
      return 'Testing';
    case 'OPEN':
      return 'Open / Blocking';
    default:
      return state;
  }
}
