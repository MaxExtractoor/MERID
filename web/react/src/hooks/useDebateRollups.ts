import { useApiData } from './useApiData';
import { API_ENDPOINTS } from '../config/constants';

// Backend contract types
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

export interface UseDebateRollupsOptions {
  groupBy: 'team' | 'strategy' | 'configuration';
  timeWindowDays: number;
}

export interface UseDebateRollupsResult {
  rows: RollupRow[];
  loading: boolean;
  error?: Error;
}

export function useDebateRollups(options: UseDebateRollupsOptions): UseDebateRollupsResult {
  const { groupBy, timeWindowDays } = options;
  
  // Build query parameters
  const queryParams = new URLSearchParams({
    group_by: groupBy,
    days_back: timeWindowDays.toString(),
  });
  
  const endpoint = `${API_ENDPOINTS.DEBATE_ROLLUPS}?${queryParams}`;
  
  const { data: rollupsResponse, loading, error } = useApiData<RollupsResponse>(endpoint);
  
  const rows = rollupsResponse?.rows ?? [];
  
  return {
    rows,
    loading,
    error: error ?? undefined,
  };
}
