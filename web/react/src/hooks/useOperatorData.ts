/**
 * useOperatorData - Unified operator data fetching hook
 * 
 * Consolidates multiple operator-specific hooks into one configurable primitive:
 * - useOperatorSummary (operator summary with actions)
 * - useSystemHealth (system health status)
 * - usePnLSummary (P&L analytics)
 * - useAgentsSummary (agent status)
 * - useTradingSummary (trading operations)
 * 
 * Uses useApiData for REST API and integrates with useVisibility for intelligent polling.
 * 
 * Tier 3: Operator Hooks Consolidation
 */

import { useCallback } from 'react';
import { useApiData } from './useApiData';
import { useVisibility } from './useVisibility';
import { API_ENDPOINTS, API_BASE_URL, AUTH_TOKEN_KEY, DEFAULTS } from '../config/constants';

export interface UseOperatorDataOptions {
  /**
   * Data source type
   */
  source: 'summary' | 'health' | 'pnl' | 'agents' | 'trading' | 'custom';
  
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
   * Error handler
   */
  onError?: (error: Error) => void;
}

/**
 * useOperatorData hook - Unified operator data fetching
 */
export function useOperatorData<T>(options: UseOperatorDataOptions) {
  const {
    source,
    endpoint,
    pollingInterval = DEFAULTS.POLLING_INTERVALS.PORTFOLIO,
    enabled = true,
    transform,
  } = options;
  
  const isVisible = useVisibility();
  
  // Resolve endpoint based on source type
  const resolveEndpoint = useCallback((): string => {
    if (endpoint) return endpoint;
    
    switch (source) {
      case 'summary':
        return API_ENDPOINTS.OPERATOR_SUMMARY;
      case 'health':
        return API_ENDPOINTS.SYSTEM_HEALTH;
      case 'pnl':
        return '/api/v1/operator/pnl-summary';
      case 'agents':
        return '/api/v1/operator/agents';
      case 'trading':
        return '/api/v1/operator/trading-summary';
      default:
        return endpoint || '';
    }
  }, [source, endpoint]);
  
  // REST API data fetching (useApiData)
  const apiData = useApiData<T>(
    resolveEndpoint(),
    {
      enabled,
      pollingInterval: isVisible ? pollingInterval : undefined, // Only poll when visible
      transform,
    }
  );
  
  // Operator actions (only for 'summary' source)
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
      await apiData.refetch();
      return json.changed;
    } catch {
      return false;
    }
  }, [authHeaders, apiData]);
  
  const resumeSwarm = useCallback(async (): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.DEV_SWARM_RESUME}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) return false;
      const json = await res.json();
      await apiData.refetch();
      return json.changed;
    } catch {
      return false;
    }
  }, [authHeaders, apiData]);
  
  const switchMode = useCallback(async (mode: string, reason: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.TRADING_MODE_SET}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ mode, reason }),
      });
      if (!res.ok) return false;
      await apiData.refetch();
      return true;
    } catch {
      return false;
    }
  }, [authHeaders, apiData]);
  
  const toggleKillSwitch = useCallback(async (activate: boolean, reason = 'operator'): Promise<boolean> => {
    try {
      const endpoint = activate ? API_ENDPOINTS.GUARD_KILL : API_ENDPOINTS.GUARD_UNKILL;
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) return false;
      await apiData.refetch();
      return true;
    } catch {
      return false;
    }
  }, [authHeaders, apiData]);
  
  // Return appropriate data based on source type
  if (source === 'summary') {
    return {
      ...apiData,
      pauseSwarm,
      resumeSwarm,
      switchMode,
      toggleKillSwitch,
    };
  }
  
  return apiData;
}

/**
 * Convenience hooks for common operator data sources
 */
export function useOperatorSummary(pollingMs = 5000) {
  return useOperatorData({
    source: 'summary',
    pollingInterval: pollingMs,
  });
}

export function useSystemHealth() {
  return useOperatorData({
    source: 'health',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
}

export function usePnLSummary() {
  return useOperatorData({
    source: 'pnl',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
}

export function useAgentsSummary() {
  return useOperatorData({
    source: 'agents',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
}

export function useTradingSummary() {
  return useOperatorData({
    source: 'trading',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
}
