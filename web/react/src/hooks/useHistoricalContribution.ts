import { useApiData } from './useApiData';
import { API_ENDPOINTS } from '../config/constants';

// Backend contract types
export interface HistoricalPoint {
  timestamp: string;
  debate_contribution_pct: number;
  win_rate: number;
  utilization_pct: number;
}

export interface HistoricalResponse {
  agent_id: string;
  window_days: number;
  points: HistoricalPoint[];
}

export interface UseHistoricalContributionOptions {
  agentId: string;
  timeWindowDays: number;
  points?: number; // Optional number of points to return
}

export interface UseHistoricalContributionResult {
  points: HistoricalPoint[];
  loading: boolean;
  error?: Error;
}

export function useHistoricalContribution(options: UseHistoricalContributionOptions): UseHistoricalContributionResult {
  const { agentId, timeWindowDays, points } = options;
  
  // Build query parameters
  const queryParams = new URLSearchParams({
    agent_id: agentId,
    days_back: timeWindowDays.toString(),
    ...(points && { points: points.toString() }),
  });
  
  const endpoint = `${API_ENDPOINTS.DEBATE_HISTORICAL_CONTRIBUTION}?${queryParams}`;
  
  const { data: historicalResponse, loading, error } = useApiData<HistoricalResponse>(endpoint);
  
  const pointsData = historicalResponse?.points ?? [];
  
  return {
    points: pointsData,
    loading,
    error: error ?? undefined,
  };
}
