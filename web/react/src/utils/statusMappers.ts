// Status mapping utilities for MERID dashboard
import { STATUS_TYPES } from '../config/constants';
import { AgentStatus } from '../types/agents';
import { OrderStatus } from '../types/orders';

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
