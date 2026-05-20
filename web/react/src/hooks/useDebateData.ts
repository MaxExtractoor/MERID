/**
 * useDebateData - Unified debate data fetching hook
 * 
 * Consolidates multiple debate-specific hooks into one configurable primitive:
 * - useDebateStats (debate statistics)
 * - useDebateRollups (debate rollups by team/strategy/configuration)
 * - useDebateAlerts (debate alerts with filtering)
 * 
 * Uses useApiData for REST API and integrates with useVisibility for intelligent polling.
 * 
 * Tier 3: Debate Hooks Consolidation
 */

import { useMemo } from 'react';
import { useApiData } from './useApiData';
import { useVisibility } from './useVisibility';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

export interface UseDebateDataOptions {
  /**
   * Data source type
   */
  source: 'stats' | 'rollups' | 'alerts' | 'custom';
  
  /**
   * Custom endpoint (for 'custom' source)
   */
  endpoint?: string;
  
  /**
   * Polling interval in milliseconds
   */
  pollingInterval?: number;
  
  /**
   * Whether polling is enabled
   */
  enabled?: boolean;
  
  /**
   * Data transformation function
   */
  transform?: (data: any) => any;
  
  /**
   * Query parameters for rollups/alerts
   */
  queryParams?: Record<string, string | number | boolean | null | undefined>;
}

/**
 * useDebateData hook - Unified debate data fetching
 */
export function useDebateData<T>(options: UseDebateDataOptions) {
  const {
    source,
    endpoint,
    pollingInterval = DEFAULTS.POLLING_INTERVALS.SLOW,
    enabled = true,
    transform,
    queryParams = {},
  } = options;
  
  const isVisible = useVisibility();
  
  // Resolve endpoint based on source type
  const resolveEndpoint = (): string => {
    if (endpoint) return endpoint;
    
    switch (source) {
      case 'stats':
        return API_ENDPOINTS.KALSHI_DEBATE_STATS;
      case 'rollups':
        const rollupParams = new URLSearchParams(
          Object.entries(queryParams)
            .filter(([_, v]) => v !== null && v !== undefined)
            .map(([k, v]) => [k, String(v)])
        );
        return `${API_ENDPOINTS.DEBATE_ROLLUPS}?${rollupParams}`;
      case 'alerts':
        const alertParams = new URLSearchParams(
          Object.entries(queryParams)
            .filter(([_, v]) => v !== null && v !== undefined)
            .map(([k, v]) => [k, String(v)])
        );
        return `${API_ENDPOINTS.DEBATE_ALERTS}?${alertParams}`;
      default:
        return endpoint || '';
    }
  };
  
  // REST API data fetching (useApiData)
  const apiData = useApiData<T>(
    resolveEndpoint(),
    {
      enabled,
      pollingInterval: isVisible ? pollingInterval : undefined, // Only poll when visible
      transform,
    }
  );
  
  return apiData;
}

// =============================================================================
// TYPE DEFINITIONS
// =============================================================================

export interface DebateStats {
  debate_count: number;
  win_rate: number;
  recent_snippets: string[];
}

export interface DebateStatsResponse {
  agents: Record<string, DebateStats>;
  error?: string;
}

export interface RollupRow {
  id: string;
  label: string;
  debate_contribution_pct: number;
  sharpe_delta: number;
  drawdown_delta: number;
  agents: string[];
  utilization_pct: number;
}

export interface RollupsResponse {
  group_by: 'team' | 'strategy' | 'configuration';
  window_days: number;
  rows: RollupRow[];
}

export type DebateUtilizationBand = 'low' | 'medium' | 'high';
export type DebateTierFilter = 'gold' | 'silver' | 'bronze' | 'restricted';

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

// =============================================================================
// CONVENIENCE HOOKS
// =============================================================================

/**
 * useDebateStats - Fetch debate statistics
 */
export function useDebateStats() {
  return useDebateData<DebateStatsResponse>({
    source: 'stats',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
}

/**
 * useDebateRollups - Fetch debate rollups with grouping
 */
export function useDebateRollups(groupBy: 'team' | 'strategy' | 'configuration', timeWindowDays: number) {
  const { data: rollupsResponse, loading, error } = useDebateData<RollupsResponse>({
    source: 'rollups',
    queryParams: {
      group_by: groupBy,
      days_back: timeWindowDays,
    },
  });
  
  const rows = rollupsResponse?.rows ?? [];
  
  return {
    rows,
    loading,
    error,
  };
}

/**
 * getUtilizationBand - Helper to categorize utilization
 */
export function getUtilizationBand(utilizedPct: number): DebateUtilizationBand {
  if (utilizedPct > 0.9) return 'high';
  if (utilizedPct > 0.6) return 'medium';
  return 'low';
}

/**
 * useDebateAlerts - Fetch debate alerts with filtering
 */
export function useDebateAlerts(options: {
  timeWindowDays: number;
  tierFilter?: DebateTierFilter | null;
  utilizationFilter?: DebateUtilizationBand | null;
  problemsOnly?: boolean;
}) {
  const { timeWindowDays, tierFilter, utilizationFilter, problemsOnly = false } = options;
  
  const { data: alertsResponse, loading, error } = useDebateData<DebateAlertsResponse>({
    source: 'alerts',
    queryParams: {
      days_back: timeWindowDays,
      tier: tierFilter ?? 'all',
      utilization_band: utilizationFilter ?? 'all',
      ...(problemsOnly && { problems_only: 'true' }),
    },
  });
  
  const alerts = alertsResponse?.alerts ?? [];
  
  // Extract unique agent IDs from alerts
  const filteredAgents = useMemo(() => {
    const agentIds = new Set(alerts.map(alert => alert.agent_id));
    return Array.from(agentIds);
  }, [alerts]);
  
  return {
    alerts,
    loading,
    error,
    filteredAgents,
  };
}
