import { useCallback } from 'react';
import { useApiData } from './useApiData';
import { API_ENDPOINTS, API_BASE_URL, AUTH_TOKEN_KEY } from '../config/constants';

export interface OperatorSummary {
  mode: {
    name: string;
    is_paper: boolean;
    is_live: boolean;
  };
  portfolio: {
    total_value: number;
    unrealized_pnl: number;
    position_count: number;
  };
  swarm: {
    agents: number;
    active_tasks: number;
    total_tasks: number;
    completed: number;
    failed: number;
    paused: boolean;
    success_rate: number;
  };
  system: {
    cpu_percent: number;
    memory_percent: number;
  };
  guard?: {
    kill_switch_active: boolean;
    last_cqi: Record<string, number>;
    domain_caps: Record<string, { remaining_usd: number; kill: boolean }>;
    recent_verdicts_count: number;
  };
  loop?: {
    running: boolean;
    total_ticks: number;
    total_errors: number;
    plans_executed: number;
    last_tick_duration_ms: number;
  };
}

interface UseOperatorSummaryResult {
  data: OperatorSummary | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  lastUpdated: Date | null;
  isStub: boolean;
  stubMessage: string;
  pauseSwarm: () => Promise<boolean>;
  resumeSwarm: () => Promise<boolean>;
  switchMode: (mode: string, reason: string) => Promise<boolean>;
  toggleKillSwitch: (activate: boolean, reason?: string) => Promise<boolean>;
}

export function useOperatorSummary(pollingMs = 5000): UseOperatorSummaryResult {
  // Always fetch operator summary — kill switch, risk state, and agent grid
  // status are critical regardless of kalshiOnly mode.
  const {
    data,
    loading,
    error,
    refetch,
    lastUpdated,
    isStub,
    stubMessage,
  } = useApiData<OperatorSummary>(
    API_ENDPOINTS.OPERATOR_SUMMARY,
    {
      pollingInterval: pollingMs,
    }
  );

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const pauseSwarm = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.DEV_SWARM_PAUSE}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) return false;
      const json = await res.json();
      await refetch();
      return json.changed;
    } catch {
      return false;
    }
  }, [authHeaders, refetch]);

  const resumeSwarm = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.DEV_SWARM_RESUME}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) return false;
      const json = await res.json();
      await refetch();
      return json.changed;
    } catch {
      return false;
    }
  }, [authHeaders, refetch]);

  const switchMode = useCallback(async (mode: string, reason: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.TRADING_MODE_SET}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ mode, reason }),
      });
      if (!res.ok) return false;
      await refetch();
      return true;
    } catch {
      return false;
    }
  }, [authHeaders, refetch]);

  const toggleKillSwitch = useCallback(async (activate: boolean, reason = 'operator'): Promise<boolean> => {
    try {
      const endpoint = activate ? API_ENDPOINTS.GUARD_KILL : API_ENDPOINTS.GUARD_UNKILL;
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) return false;
      await refetch();
      return true;
    } catch {
      return false;
    }
  }, [authHeaders, refetch]);

  return {
    data,
    loading,
    error: error?.message ?? null,
    refetch,
    lastUpdated,
    isStub,
    stubMessage,
    pauseSwarm,
    resumeSwarm,
    switchMode,
    toggleKillSwitch,
  };
}
