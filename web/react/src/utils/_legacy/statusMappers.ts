// Status mapping utilities for MERID dashboard
import { STATUS_TYPES } from '../config/constants';
import { AgentStatus } from '../types/agents';
import { OrderStatus } from '../types/orders';
import { RiskAlertSeverity } from '../types/risk';
import { PredictionMarketStatus } from '../types/predictions';

/**
 * Maps AgentStatus to STATUS_TYPES for UI components
 */
export function agentStatusToStatusType(status: AgentStatus): keyof typeof STATUS_TYPES {
  switch (status) {
    case 'ONLINE':
      return 'GOOD';
    case 'DEGRADED':
      return 'WARNING';
    case 'OFFLINE':
      return 'BAD';
    default:
      return 'OFFLINE';
  }
}

/**
 * Maps OrderStatus to STATUS_TYPES for UI components
 */
export function orderStatusToStatusType(status: OrderStatus): keyof typeof STATUS_TYPES {
  switch (status) {
    case 'PENDING':
      return 'ONLINE'; // Active/working state
    case 'PARTIALLY_FILLED':
      return 'WARNING';
    case 'FILLED':
      return 'GOOD';
    case 'CANCELED':
    case 'REJECTED':
      return 'BAD';
    default:
      return 'OFFLINE';
  }
}

/**
 * Maps RiskAlertSeverity to STATUS_TYPES for UI components
 */
export function riskSeverityToStatusType(severity: RiskAlertSeverity): keyof typeof STATUS_TYPES {
  switch (severity) {
    case 'INFO':
      return 'ONLINE';
    case 'WARNING':
      return 'WARNING';
    case 'CRITICAL':
      return 'BAD';
    default:
      return 'OFFLINE';
  }
}

/**
 * Maps PredictionMarketStatus to STATUS_TYPES for UI components
 * Optionally considers PnL for resolved markets
 */
export function marketStatusToStatusType(
  status: PredictionMarketStatus,
  ourPnl?: number
): keyof typeof STATUS_TYPES {
  switch (status) {
    case 'OPEN':
      return 'ONLINE';
    case 'CLOSED':
      return 'WARNING';
    case 'RESOLVED':
      if (ourPnl === undefined) return 'OFFLINE';
      if (ourPnl > 0) return 'GOOD';
      if (ourPnl < 0) return 'BAD';
      return 'ONLINE';
    default:
      return 'OFFLINE';
  }
}

/**
 * Maps model confidence to STATUS_TYPES for UI components
 */
export function confidenceToStatusType(confidence: number): keyof typeof STATUS_TYPES {
  if (confidence > 0.7) return 'GOOD';
  if (confidence >= 0.4) return 'WARNING';
  return 'BAD';
}
