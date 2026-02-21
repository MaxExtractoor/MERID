/**
 * Core Swarm Event Types
 * Shared type definitions for event-driven agent communication
 */

export interface EventEnvelope<T = unknown> {
  topic: string;
  ts: number;
  data: T;
}

export interface EventBus {
  subscribe<T>(
    topic: string,
    handler: (evt: EventEnvelope<T>) => Promise<void> | void
  ): Promise<void>;
  publish<T>(topic: string, data: T): Promise<void>;
}

// Kalshi WebSocket Message Types
export interface OrderbookSnapshotMsg {
  type: "orderbook_snapshot";
  sid?: number;
  seq: number;
  msg: {
    market_ticker: string;
    market_id?: string;
    yes: [number, number][]; // [price_int (0-100), quantity]
    no: [number, number][];
    seq: number;
    ts?: string;
  };
}

export interface OrderbookDeltaMsg {
  type: "orderbook_delta";
  sid?: number;
  seq: number;
  msg: {
    market_ticker: string;
    market_id?: string;
    price: number; // int (0–100)
    delta: number; // signed size change
    side: "yes" | "no";
    seq: number;
    ts?: string;
  };
}

export interface TradeMsg {
  type: "trade";
  msg: {
    market_ticker: string;
    market_id?: string;
    price: number; // 0–100 int
    size: number;
    ts: string; // ISO timestamp
    trade_id?: string;
  };
}

export interface TickerMsg {
  type: "ticker";
  msg: {
    market_ticker: string;
    market_id?: string;
    last_price: number;
    volume: number;
    open_interest: number;
    ts: string;
  };
}

export interface FillMsg {
  type: "fill";
  msg: {
    order_id: string;
    market_ticker: string;
    side: "yes" | "no";
    action: "buy" | "sell";
    price: number;
    size: number;
    ts: string;
  };
}

export interface ErrorMsg {
  type: "error";
  msg: {
    code: string;
    message: string;
    details?: any;
  };
}

export type KalshiWSMessage =
  | OrderbookSnapshotMsg
  | OrderbookDeltaMsg
  | TradeMsg
  | TickerMsg
  | FillMsg
  | ErrorMsg;

// Trading Intent Types
export interface OrderIntent {
  session_id: string;
  agent_id: string;
  market_ticker: string;
  side: "buy_yes" | "sell_yes" | "buy_no" | "sell_no";
  qty: number;
  price: number; // 0-1 (decimal probability)
  client_tag: string; // Idempotency key
  confidence?: number; // 0-1
  rationale?: string;
  timestamp: number;
}

export interface RiskDecision {
  intent_id: string;
  approved: boolean;
  adjusted_qty?: number;
  rejection_reason?: string;
  risk_score: number;
  timestamp: number;
}

export interface ExecutionOutcome {
  intent_id: string;
  order_id?: string;
  status: "submitted" | "rejected_risk" | "rejected_rate_limit" | "error";
  error_message?: string;
  timestamp: number;
}

// Market Signal Types
export interface OrderbookFeatures {
  market_ticker: string;
  bestBid: number; // Dollar probability (0-1)
  bestAsk: number;
  mid: number;
  spread: number;
  bidDepth?: number;
  askDepth?: number;
  imbalance?: number;
  ts: number;
}

export interface MicrostructureSignal {
  market_ticker: string;
  mid: number;
  spread: number;
  imbalance: number;
  recentVol: number;
  ts: number;
}

export interface TradeTick {
  market_ticker: string;
  price: number; // Dollar probability (0-1)
  size: number;
  ts: number;
}
