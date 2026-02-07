import { useState, useEffect, useCallback } from 'react';
import { CircuitBreakerState } from '../types/risk';

export interface CircuitBreakerStatus {
  state: CircuitBreakerState;
  state_color: 'green' | 'red' | 'yellow';
  error_count: number;
  window_seconds: number;
  threshold: number;
  last_error_at: string | null;
  opened_at: string | null;
  cooldown_seconds: number;
  half_open_successes: number;
}

export interface LockdownStatus {
  trading_suite_enabled: boolean;
  global_mode: string;
  spectator_mode: boolean;
  lockdown_reason: string | null;
}

export interface RiskLimitsStatus {
  max_daily_loss_usd: number;
  current_daily_pnl: number;
  daily_loss_utilization_pct: number;
  max_per_symbol_exposure_usd: number;
  max_open_orders: number;
  current_open_orders: number;
}

export interface RiskEvent {
  timestamp: string;
  type: string;
  details: Record<string, unknown>;
}

export interface RiskProtectionsData {
  timestamp: string;
  circuit_breaker: CircuitBreakerStatus;
  lockdown: LockdownStatus;
  risk_limits: RiskLimitsStatus;
  recent_events: RiskEvent[];
}

export interface UseRiskProtectionsReturn {
  data: RiskProtectionsData | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  resetCircuit: () => Promise<boolean>;
  toggleKillSwitch: (action: 'enable' | 'disable') => Promise<boolean>;
}

const POLL_INTERVAL = 5000; // 5 seconds

export function useRiskProtections(pollingInterval = POLL_INTERVAL): UseRiskProtectionsReturn {
  const [data, setData] = useState<RiskProtectionsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProtections = useCallback(async () => {
    try {
      const response = await fetch('/api/risk/protections');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const json = await response.json();
      setData(json);
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch risk protections';
      setError(message);
      console.error('Risk protections fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const refetch = useCallback(async () => {
    setLoading(true);
    await fetchProtections();
  }, [fetchProtections]);

  const resetCircuit = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch('/api/risk/circuit-breaker/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      await fetchProtections(); // Refresh data
      return true;
    } catch (err) {
      console.error('Circuit reset failed:', err);
      return false;
    }
  }, [fetchProtections]);

  const toggleKillSwitch = useCallback(async (action: 'enable' | 'disable'): Promise<boolean> => {
    try {
      const response = await fetch(`/api/risk/kill-switch/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      await fetchProtections(); // Refresh data
      return true;
    } catch (err) {
      console.error('Kill switch toggle failed:', err);
      return false;
    }
  }, [fetchProtections]);

  useEffect(() => {
    fetchProtections();
    const interval = setInterval(fetchProtections, pollingInterval);
    return () => clearInterval(interval);
  }, [fetchProtections, pollingInterval]);

  return {
    data,
    loading,
    error,
    refetch,
    resetCircuit,
    toggleKillSwitch,
  };
}

// Helper to get human-readable status text
export function getCircuitStatusText(state: CircuitBreakerState): string {
  switch (state) {
    case 'CLOSED':
      return 'System Operational';
    case 'OPEN':
      return 'Circuit Open - Orders Blocked';
    case 'HALF_OPEN':
      return 'Circuit Half-Open - Testing';
    default:
      return 'Unknown';
  }
}

// Helper to check if trading is blocked
export function isTradingBlocked(data: RiskProtectionsData | null): boolean {
  if (!data || !data.circuit_breaker || !data.lockdown) return false;
  
  return (
    data.circuit_breaker.state === 'OPEN' ||
    !data.lockdown.trading_suite_enabled
  );
}

// Helper to get overall status for UI
export function getOverallRiskStatus(data: RiskProtectionsData | null): {
  status: 'good' | 'warning' | 'critical';
  message: string;
} {
  if (!data || !data.lockdown || !data.circuit_breaker) {
    return { status: 'warning', message: 'Risk data unavailable' };
  }

  if (!data.lockdown.trading_suite_enabled) {
    return { status: 'critical', message: 'Lockdown Active' };
  }

  if (data.circuit_breaker.state === 'OPEN') {
    return { status: 'critical', message: 'Circuit Breaker Open' };
  }

  if (data.circuit_breaker.state === 'HALF_OPEN') {
    return { status: 'warning', message: 'Circuit Half-Open' };
  }

  // Check risk limits
  if (data.risk_limits.daily_loss_utilization_pct > 90) {
    return { status: 'warning', message: 'Daily Loss Near Limit' };
  }

  return { status: 'good', message: 'All Protections Active' };
}
