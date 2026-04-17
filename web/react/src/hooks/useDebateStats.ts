import { useApiData } from './useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface DebateStats {
  debate_count: number;
  win_rate: number;
  recent_snippets: string[];
}

interface DebateStatsResponse {
  agents: Record<string, DebateStats>;
  error?: string;
}

export const useDebateStats = () => {
  return useApiData<DebateStatsResponse>(
    API_ENDPOINTS.KALSHI_DEBATE_STATS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );
};
