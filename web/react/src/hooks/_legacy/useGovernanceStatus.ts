import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface GovernanceStatus {
  channels: string[];
  total_dispatches: number;
  recent_dispatches: Array<{
    timestamp: number;
    entity: string;
    status: string;
    source: string;
    results: Array<{ channel: string; success: boolean; error?: string }>;
  }>;
  promotion_enforcement: {
    enabled: boolean;
    eligible_domains: string[];
    blocked_agents: string[];
    report_ts: number;
    sync_age_s: number | null;
    stale: boolean;
  };
}

interface UseGovernanceStatusResult {
  data: GovernanceStatus | null;
  loading: boolean;
  error: string | null;
}

export function useGovernanceStatus(pollingMs = 30000): UseGovernanceStatusResult {
  const [data, setData] = useState<GovernanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.GOVERNANCE_STATUS}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: GovernanceStatus = await res.json();
      setData(json);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch governance status');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, pollingMs);
    return () => clearInterval(id);
  }, [fetchStatus, pollingMs]);

  return { data, loading, error };
}
