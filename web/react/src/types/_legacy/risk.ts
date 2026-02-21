export type RiskStatus = 'GOOD' | 'WARNING' | 'BAD' | 'UNKNOWN';

export type LowercaseRiskStatus = 'good' | 'warning' | 'bad' | 'unknown';

export type CircuitBreakerState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

/**
 * Risk types for the Live Risk Strip
 *
 * Aligned with backend contract:
 * - REST: GET /api/v1/risk/metrics
 * - WS: risk:threshold_breached, risk:exposure_changed, risk:pnl_updated
 */

export type RiskAlertSeverity = 'INFO' | 'WARNING' | 'CRITICAL';

export interface RiskAlert {
  id: string;
  metric: string; // "dailyDrawdown", "marginUsed", etc.
  value: number;
  threshold: number;
  severity: RiskAlertSeverity;
  createdAt: string;
}

export interface ExposureSide {
  long: number;
  short: number;
}

export interface RiskMetricsResponse {
  totalPnL: number;
  dailyDrawdown: number;
  maxDrawdown: number;
  marginUsed: number;
  marginAvailable: number;
  exposure: Record<string, ExposureSide>; // key = symbol, e.g. "BTC-USD"
  alerts: RiskAlert[];
}

// WebSocket payload types
export interface RiskThresholdBreachedPayload {
  type: 'risk:threshold_breached';
  metric: string;
  value: number;
  threshold: number;
  severity: RiskAlertSeverity;
}

export interface RiskExposureChangedPayload {
  type: 'risk:exposure_changed';
  symbol: string;
  side: 'LONG' | 'SHORT';
  newExposure: number;
}

export interface RiskPnlUpdatedPayload {
  type: 'risk:pnl_updated';
  realized: number;
  unrealized: number;
  total: number;
}

export type RiskEvent =
  | RiskThresholdBreachedPayload
  | RiskExposureChangedPayload
  | RiskPnlUpdatedPayload;
