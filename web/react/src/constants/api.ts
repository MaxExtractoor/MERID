// web/react/src/constants/api.ts
export const KALSHI_PERF_ENDPOINTS = {
  BTC_15M: "/api/v1/kalshi-grid/performance/btc-15m",
  ETH_15M: "/api/v1/kalshi-grid/performance/eth-15m",
  SOL_15M: "/api/v1/kalshi-grid/performance/sol-15m",
  XRP_15M: "/api/v1/kalshi-grid/performance/xrp-15m",
  BTC_1H: "/api/v1/kalshi-grid/performance/btc-1h",
  BLOCKED_REASONS: (agent: string, days = 7) =>
    `/api/v1/kalshi-grid/performance/blocked-reasons/${agent}?days=${days}`,
  SUMMARY: "/api/v1/kalshi-grid/performance/summary",
  TOP: "/api/v1/kalshi-grid/performance/top",
  CALIBRATION: "/api/v1/kalshi-grid/performance/calibration",
};
