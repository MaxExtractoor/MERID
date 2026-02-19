/**
 * Order types for the Open Orders panel
 * 
 * Aligned with backend contract:
 * - REST: GET /api/v1/orders/open
 * - WS: order:created, order:updated, order:canceled, order:completed
 */

export type OrderStatus = 'PENDING' | 'PARTIALLY_FILLED' | 'FILLED' | 'CANCELED' | 'REJECTED';
export type OrderSide = 'BUY' | 'SELL';
export type OrderType = 'MARKET' | 'LIMIT' | 'STOP' | 'STOP_LIMIT';

export interface OrderRow {
  id: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  status: OrderStatus;
  price: number | null;
  size: number;
  filledSize: number;
  remainingSize: number;
  notional: number;
  leverage: number;
  venue: string;
  strategyId: string;
  agentId: string;
  createdAt: string;
  expiresAt: string | null;
}

export interface OpenOrdersResponse {
  orders: OrderRow[];
  meta: {
    total: number;
    pending: number;
    partiallyFilled: number;
    totalNotional: number;
  };
}

// WebSocket payload types
export type OrderCreatedPayload = OrderRow;

export interface OrderUpdatedPayload {
  id: string;
  status: OrderStatus;
  filledSize: number;
  remainingSize: number;
  price?: number | null;
}

export interface OrderCanceledPayload {
  id: string;
  canceledAt: string;
  status: 'CANCELED';
}

export interface OrderCompletedPayload {
  id: string;
  filledSize: number;
  avgFillPrice: number;
  completedAt: string;
  status: 'FILLED';
}
