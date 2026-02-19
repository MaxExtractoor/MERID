import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface AlertRule {
  name: string;
  severity: 'info' | 'warning' | 'critical';
  firing: boolean;
  description: string;
  detail?: Record<string, unknown>;
}

export interface HealthSection {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  metrics: Record<string, unknown>;
}

export interface ObservabilityData {
  status: string;
  alerts: AlertRule[];
  firing_count: number;
  total_rules: number;
  health_sections: Record<string, HealthSection>;
  uptime_s: number;
  last_check: string;
}

export function useObservability(pollMs = 15000) {
  const [data, setData] = useState<ObservabilityData | null>(null);
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

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OBSERVABILITY_SUMMARY}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const raw = await res.json();
        const alerts: AlertRule[] = raw.alerts ?? raw.alert_results ?? [];
        setData({
          status: raw.status ?? 'unknown',
          alerts,
          firing_count: alerts.filter((a) => a.firing).length,
          total_rules: alerts.length,
          health_sections: raw.health_sections ?? raw.sections ?? {},
          uptime_s: raw.uptime_s ?? 0,
          last_check: raw.last_check ?? new Date().toISOString(),
        });
        setError(null);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, error, refresh };
}
