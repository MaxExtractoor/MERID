import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '../config/constants';

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
  pauseSwarm: () => Promise<boolean>;
  resumeSwarm: () => Promise<boolean>;
  switchMode: (mode: string, reason: string) => Promise<boolean>;
  toggleKillSwitch: (activate: boolean, reason?: string) => Promise<boolean>;
}

export function useOperatorSummary(pollingMs = 5000): UseOperatorSummaryResult {
  const [data, setData] = useState<OperatorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/operator/summary`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (e: any) {
      setError(e.message || 'Failed to fetch operator summary');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
    const id = setInterval(fetchSummary, pollingMs);
    return () => clearInterval(id);
  }, [fetchSummary, pollingMs]);

  const pauseSwarm = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/dev-swarm/pause`, { method: 'POST' });
      if (!res.ok) return false;
      const json = await res.json();
      await fetchSummary();
      return json.changed;
    } catch {
      return false;
    }
  }, [fetchSummary]);

  const resumeSwarm = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/dev-swarm/resume`, { method: 'POST' });
      if (!res.ok) return false;
      const json = await res.json();
      await fetchSummary();
      return json.changed;
    } catch {
      return false;
    }
  }, [fetchSummary]);

  const switchMode = useCallback(async (mode: string, reason: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/trading-mode/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, reason }),
      });
      if (!res.ok) return false;
      await fetchSummary();
      return true;
    } catch {
      return false;
    }
  }, [fetchSummary]);

  const toggleKillSwitch = useCallback(async (activate: boolean, reason = 'operator'): Promise<boolean> => {
    try {
      const endpoint = activate ? '/api/v1/loop/guard/kill' : '/api/v1/loop/guard/unkill';
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) return false;
      await fetchSummary();
      return true;
    } catch {
      return false;
    }
  }, [fetchSummary]);

  return { data, loading, error, refetch: fetchSummary, lastUpdated, pauseSwarm, resumeSwarm, switchMode, toggleKillSwitch };
}
