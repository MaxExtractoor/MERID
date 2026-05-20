/**
 * Kalshi Canonical UI State Types
 *
 * Single source of truth for all Kalshi operational state.
 * Derived from backend /api/v1/kalshi/ui-state endpoint.
 */

// ── Core State ────────────────────────────────────────────────────────────────────

export interface KalshiUIState {
  version: string;
  timestamp: string;
  cache_ttl_seconds: number;
  system: SystemStatus;
  capital: CapitalState;
  markets: MarketState;
  risk: RiskState;
  grid: GridState;
}

// ── System Status ────────────────────────────────────────────────────────────────

export interface SystemStatus {
  mode: 'paper' | 'shadow' | 'live';
  is_live_enabled: boolean;
  execution_gate: 'clear' | 'limited' | 'blocked';
  execution_gate_reasons: string[];
  execution_gate_near_limit?: {
    exposure_pct: number;
    daily_loss_pct: number;
  };
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  kill_switch_triggered_at: string | null;
  venue_healthy: boolean;
  venue_latency_ms: number | null;
  venue_last_error: string | null;
  reconciliation_status: 'ok' | 'discrepancy' | 'error';
  reconciliation_last_check: string | null;
  reconciliation_discrepancy_count: number;
}

// ── Capital State ────────────────────────────────────────────────────────────────

export interface CapitalState {
  balance_usd: number;
  portfolio_usd: number;
  total_value_usd: number;
  locked_usd: number;
  daily_pnl_usd: number;
  total_pnl_usd: number;
  daily_pnl_pct: number;
  drawdown_pct: number;
  drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  drawdown_from_peak_usd: number;
  peak_equity_usd: number;
  daily_loss_limit_usd: number;
  daily_loss_remaining_usd: number;
  notional_limit_usd: number;
  notional_used_usd: number;
  notional_utilization_pct: number;
}

// ── Market State ────────────────────────────────────────────────────────────────

export interface MarketState {
  open_position_count: number;
  positions: PositionSummary[];
  open_order_count: number;
  recent_orders: OrderSummary[];
  recent_fills: FillSummary[];
  active_tickers: string[];
  active_market_count: number;
  avg_spread_cents: number | null;
  avg_depth_10c: number | null;
  illiquid_market_count: number;
}

export interface PositionSummary {
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  avg_price_cents: number;
  current_price_cents: number;
  unrealized_pnl_usd: number;
  expiry_time: string;
  seconds_to_expiry: number;
}

export interface OrderSummary {
  order_id: string;
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  contracts: number;
  limit_price_cents: number;
  status: 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected';
  created_at: string;
  seconds_ago: number;
  event_id?: string;  // For deduplication
  sequence?: number;  // For ordering and deduplication
}

export interface FillSummary {
  fill_id: string;
  order_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  fee_cents: number;
  pnl_usd: number;
  filled_at: string;
  seconds_ago: number;
  event_id?: string;  // For deduplication
  sequence?: number;  // For ordering and deduplication
}

// ── Risk State ──────────────────────────────────────────────────────────────────

export interface RiskState {
  daily_loss_usd: number;
  daily_loss_limit_usd: number;
  daily_loss_pct: number;
  total_notional_usd: number;
  notional_limit_usd: number;
  notional_utilization_pct: number;
  gross_exposure_usd: number;
  net_exposure_usd: number;
  max_single_asset_exposure_pct: number;
  breach_count: number;
  active_breaches: BreachSummary[];
  recent_alerts: RiskAlertSummary[];
  unacknowledged_alert_count: number;
}

export interface BreachSummary {
  check: string;
  reason: string;
  severity: 'warning' | 'critical';
  triggered_at: string;
  acknowledged: boolean;
}

export interface RiskAlertSummary {
  id: string;
  level: 'warning' | 'critical' | 'info';
  category: string;
  message: string;
  timestamp: string;
  acknowledged: boolean;
  event_id?: string;  // For deduplication
  sequence?: number;  // For ordering and deduplication
}

// ── Grid State ───────────────────────────────────────────────────────────────────

export interface GridState {
  running: boolean;
  agent_count: number;
  active_agent_count: number;
  last_cycle_at: string | null;
  cycles_run: number;
  cycles_per_minute: number | null;
  total_orders: number;
  total_fills: number;
  fill_rate_pct: number | null;
  active_markets: number;
  coverage_pct: number | null;
  recent_errors: GridErrorSummary[];
  error_count: number;
}

export interface GridErrorSummary {
  agent_id: string;
  error: string;
  timestamp: string;
}

// ── Detail State (Lazy-Loaded) ────────────────────────────────────────────────────

export interface AgentPerformanceDetail {
  agent_id: string;
  total_fills: number;
  total_closes: number;
  total_volume_usd: number;
  win_rate: number;
  avg_pnl_per_trade: number;
  total_pnl: number;
  sharpe_ratio: number | null;
  edge_accuracy: number;
  confidence_calibration_error: number;
  brier_score: number | null;
  last_trade_at: string | null;
  recent_trades: TradeDetail[];
}

export interface TradeDetail {
  trade_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  pnl_usd: number;
  traded_at: string;
}

export interface SentimentDetail {
  asset: string;
  sentiment_value: number; // 0-100
  sentiment_regime: 'extreme_fear' | 'fear' | 'neutral' | 'greed' | 'extreme_greed';
  sentiment_confidence: number;
  sizing_multiplier: number; // 0.0-1.5
  sizing_regime: 'halted' | 'caution' | 'normal' | 'aggressive';
  components: {
    volatility: number;
    volume_heat: number;
    book_imbalance: number;
  };
  timeframe_sentiment: TimeframeSentiment[];
}

export interface TimeframeSentiment {
  timeframe: string;
  sentiment: number;
  regime: string;
  signal_count: number;
}

export interface MarketDetail {
  ticker: string;
  title: string;
  subtitle: string;
  yes_ask: number;
  no_ask: number;
  yes_bid: number;
  no_bid: number;
  spread_cents: number;
  mid_cents: number;
  volume_24h: number;
  open_interest: number;
  seconds_to_expiry: number;
  expiration_time: string;
  orderbook: OrderbookLevel[];
  recent_trades: TradeDetail[];
}

export interface OrderbookLevel {
  price_cents: number;
  yes_qty: number;
  no_qty: number;
}

// ── WebSocket Event Types ─────────────────────────────────────────────────────────

export type UIStateEvent =
  | { type: 'fill'; data: FillSummary }
  | { type: 'order'; data: OrderSummary }
  | { type: 'risk_alert'; data: RiskAlertSummary }
  | { type: 'kill_switch'; data: { active: boolean; reason: string | null } }
  | { type: 'execution_gate'; data: { state: string; reasons: string[] } }
  | { type: 'grid_status'; data: Partial<GridState> }
  | { type: 'capital_update'; data: Partial<CapitalState> }
  | { type: 'ping'; timestamp: string }
  | { type: 'pong'; timestamp: string };
