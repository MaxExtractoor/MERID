import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface RingResult {
  name: string;
  passed: boolean;
  checks_passed: number;
  checks_total: number;
  pass_rate: number;
  failures: string[];
  warnings: string[];
  elapsed_s: number;
}

export interface DomainDetail {
  domain: string;
  eligible: boolean;
  mode: string;
  blockers: string[];
  instruments: number;
  reconciliation_venue: string | null;
}

export interface AgentDetail {
  agent_id: string;
  category: string;
  promoted: boolean;
  slo_pass_rate: number;
  failed_slos: string[];
}

export interface PromotionReport {
  timestamp: number;
  overall_eligible: boolean;
  all_rings_pass: boolean;
  rings: RingResult[];
  domains: {
    eligible: string[];
    blocked: string[];
    detail: DomainDetail[];
  };
  agents: {
    promoted: string[];
    blocked: string[];
    detail: AgentDetail[];
  };
  elapsed_s: number;
  error?: string;
}

interface UsePromotionReportResult {
  data: PromotionReport | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  lastUpdated: Date | null;
}

export function usePromotionReport(pollingMs = 60000): UsePromotionReportResult {
  const [data, setData] = useState<PromotionReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const fetchReport = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.PROMOTION_REPORT}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: PromotionReport = await res.json();
      setData(json);
      setError(json.error || null);
      setLastUpdated(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch promotion report');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.PROMOTION_REPORT_REFRESH}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: PromotionReport = await res.json();
      setData(json);
      setError(json.error || null);
      setLastUpdated(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to refresh promotion report');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    fetchReport();
    const id = setInterval(fetchReport, pollingMs);
    return () => clearInterval(id);
  }, [fetchReport, pollingMs]);

  return { data, loading, error, refresh, lastUpdated };
}
