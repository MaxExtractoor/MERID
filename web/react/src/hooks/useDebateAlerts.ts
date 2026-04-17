import { useMemo } from 'react';
import { useApiData } from './useApiData';
import { API_ENDPOINTS } from '../config/constants';

export type DebateUtilizationBand = 'low' | 'medium' | 'high';
export type DebateTierFilter = 'gold' | 'silver' | 'bronze' | 'restricted';

// Backend contract types
export interface DebateAlert {
  agent_id: string;
  tier: string;
  utilization_pct: number;
  metric_id: string;
  metric_label: string;
  severity: 'warning' | 'critical';
  message: string;
  triggered_at: string;
  supporting_values: Record<string, any>;
}

export interface DebateAlertsResponse {
  window_days: number;
  generated_at: string;
  alerts: DebateAlert[];
}

export interface UseDebateAlertsOptions {
  timeWindowDays: number;
  tierFilter?: DebateTierFilter | null;
  utilizationFilter?: DebateUtilizationBand | null;
  problemsOnly?: boolean;
}

export interface UseDebateAlertsResult {
  alerts: DebateAlert[];
  loading: boolean;
  error?: Error;
  filteredAgents: string[]; // Agent IDs with alerts
}

export function getUtilizationBand(utilizedPct: number): DebateUtilizationBand {
  if (utilizedPct > 0.9) return 'high';
  if (utilizedPct > 0.6) return 'medium';
  return 'low';
}

export function useDebateAlerts(options: UseDebateAlertsOptions): UseDebateAlertsResult {
  const { timeWindowDays, tierFilter, utilizationFilter, problemsOnly = false } = options;
  
  // Build query parameters
  const queryParams = new URLSearchParams({
    days_back: timeWindowDays.toString(),
    tier: tierFilter ?? 'all',
    utilization_band: utilizationFilter ?? 'all',
    ...(problemsOnly && { problems_only: 'true' }),
  });
  
  const endpoint = `${API_ENDPOINTS.DEBATE_ALERTS}?${queryParams}`;
  
  const { data: alertsResponse, loading, error } = useApiData<DebateAlertsResponse>(endpoint);
  
  const alerts = alertsResponse?.alerts ?? [];
  
  // Extract unique agent IDs from alerts
  const filteredAgents = useMemo(() => {
    const agentIds = new Set(alerts.map(alert => alert.agent_id));
    return Array.from(agentIds);
  }, [alerts]);
  
  return {
    alerts,
    loading,
    error: error ?? undefined,
    filteredAgents,
  };
}
