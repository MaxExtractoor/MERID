import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUiError } from '../utils/logger';

export interface LatencyPercentiles {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  min_ms: number;
  max_ms: number;
  avg_ms: number;
}

export interface LatencyThresholds {
  warning_p95_ms: number;
  critical_p95_ms: number;
  warning_p99_ms: number;
  critical_p99_ms: number;
}

export interface LatencyAlert {
  severity: 'warning' | 'critical';
  metric: 'p95' | 'p99';
  value: number;
  threshold: number;
  message: string;
}

export interface LatencySloCompliance {
  target_p99_ms: number;
  current_p99_ms: number;
  compliant: boolean;
}

export interface LatencyData {
  percentiles: LatencyPercentiles;
  sample_count: number;
  thresholds: LatencyThresholds;
  alert: LatencyAlert | null;
  slo_compliance: LatencySloCompliance;
  last_updated: string;
}

export interface UseLatencyReturn {
  data: LatencyData | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

const POLL_INTERVAL = 30000; // 30 seconds

export function useLatency(pollingInterval = POLL_INTERVAL): UseLatencyReturn {
  const [data, setData] = useState<LatencyData | null>(null);
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

  const fetchLatency = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_LATENCY}`, {
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
      const message = err instanceof Error ? err.message : 'Failed to fetch latency metrics';
      setError(message);
      if (consecutiveFailures.current === 0) {
        logUiError('useLatency', 'Latency fetch error', err);
      }
      consecutiveFailures.current += 1;
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  const refetch = useCallback(async () => {
    setLoading(true);
    await fetchLatency();
  }, [fetchLatency]);

  useEffect(() => {
    fetchLatency();
    
    const interval = setInterval(() => {
      if (consecutiveFailures.current > 1) return; // back off: skip ticks while backend is down
      fetchLatency();
    }, pollingInterval);
    return () => clearInterval(interval);
  }, [fetchLatency, pollingInterval]);

  return {
    data,
    loading,
    error,
    refetch,
  };
}

// Helper to get color for latency value against threshold
export function getLatencyColor(value: number, warning: number, critical: number): string {
  if (value >= critical) {
    return 'text-red-400';
  }
  if (value >= warning) {
    return 'text-amber-400';
  }
  return 'text-emerald-400';
}

// Helper to get background color for latency bar
export function getLatencyBarColor(value: number, warning: number, critical: number): string {
  if (value >= critical) {
    return 'bg-red-400';
  }
  if (value >= warning) {
    return 'bg-amber-400';
  }
  return 'bg-emerald-400';
}

// Format latency for display
export function formatLatency(ms: number): string {
  if (ms < 1) {
    return `${(ms * 1000).toFixed(0)}μs`;
  }
  if (ms < 1000) {
    return `${ms.toFixed(1)}ms`;
  }
  return `${(ms / 1000).toFixed(2)}s`;
}

// Get status text for SLO compliance
export function getSloStatus(compliant: boolean): { text: string; color: string } {
  return compliant
    ? { text: 'Compliant', color: 'text-emerald-400' }
    : { text: 'Breached', color: 'text-red-400' };
}
