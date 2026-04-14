/**
 * useGlobalRiskStatus — polling hook for the aggregated global risk snapshot.
 *
 * Fetches /api/v1/kalshi/global-risk-status at a configurable interval and
 * returns the parsed GlobalRiskStatus plus loading/error state.
 */
import { useApiData } from './useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { GlobalRiskStatus } from '../types/kalshi';

export function useGlobalRiskStatus(pollingInterval?: number) {
  return useApiData<GlobalRiskStatus>(API_ENDPOINTS.KALSHI_GLOBAL_RISK_STATUS, {
    pollingInterval: pollingInterval ?? DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
}
