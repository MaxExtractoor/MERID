import { useApiData } from './useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface EquityPoint {
  ts: string;
  equity: number;
  drawdown?: number | null;
  realized_only?: boolean;
}

interface EquitySeriesResponse {
  points: EquityPoint[];
  error?: string;
}

export const useKalshiEquitySeries = () => {
  return useApiData<EquitySeriesResponse>(
    API_ENDPOINTS.KALSHI_EQUITY_SERIES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );
};
