/**
 * Shared Kalshi data types used across multiple views and components.
 *
 * Import from here instead of re-defining in each view file.
 */

export interface KalshiBalance {
  usd: number;
  locked: number;
  available: number;
}

export interface KalshiPosition {
  ticker: string;
  outcome: string;
  size: number;
  avg_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface KalshiOrder {
  order_id: string;
  ticker: string;
  side: string;
  size: number;
  price: number | null;
  filled: number;
  remaining: number | null;
  status: string;
  created_at: string | null;
  /** GAP-E1: agent/source that placed the order (agent ID or client_order_id prefix) */
  source?: string;
}

export interface KalshiFill {
  trade_id: string;
  ticker: string;
  order_id: string;
  side: string;
  size: number;
  price: number;
  fee: number;
  timestamp: string;
}

export interface KalshiRiskSummary {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  /** Canonical daily PnL in USD — single source of truth for daily PnL display. */
  daily_pnl_usd: number;
  total_notional_usd: number;
  total_unrealized_pnl_usd: number;
  /** Realized PnL for the day (USD). Same source as daily_pnl_usd for consistency. */
  daily_realized_pnl_usd: number;
  /** Total PnL = realized + unrealized (USD). */
  daily_total_pnl_usd: number;
  daily_trades: number;
  daily_fees_usd: number;
  drawdown_pct: number;
  category_notional: Record<string, number>;
  category_contracts: Record<string, number>;
  open_market_count: number;
  recent_breaches: Array<{ ts: string; check: string; reason: string }>;
  limits: Record<string, number>;
  // ExecutionGateStrip alias fields (set by /api/v1/kalshi/risk endpoint)
  daily_pnl?: number;
  max_daily_loss?: number;
  total_exposure?: number;
  max_exposure?: number;
  position_count?: number;
  max_positions?: number;
}

export interface ContinuousTraderSnapshot {
  total_trades: number;
  total_fills: number;
  system_win_rate: number;
  agent_count: number;
}

export interface SizingMetrics {
  kelly_fraction: number;
  kelly_utilization_pct: number;
  vol_scale: number;
  target_vol: number;
  realized_vol: number;
  atr_fraction: number;
  atr_value: number;
  effective_fraction: number;
  drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  drawdown_pct: number;
  drawdown_thresholds: { warning: number; downsize: number; halt: number };
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
  trades_today: number;
  /** Continuous trader performance snapshot — authoritative source for trade counts. */
  continuous_trader?: ContinuousTraderSnapshot;
}

/** Agent summary as returned by /api/v1/kalshi-grid/status agent_cards[]. */
export interface GridAgent {
  name: string;
  asset: string;
  timeframe: string;
  status: string;
  cycles: number;
  pf: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  size_factor: number;
  /** Win rate as percentage (0–100). Null when perf tracker data is unavailable. */
  win_rate: number | null;
  /** Error count for this agent session. Null when unavailable. */
  errors: number | null;
  /** Total fills for this agent session. Null when unavailable. */
  fills: number | null;
  /** Tickers this agent is currently active on. */
  active_tickers: string[] | null;
  /** Combined effective size multiplier: DD zone × profit-lock × size_factor. */
  effective_size_multiplier?: number | null;
  /** Drawdown zone multiplier component. */
  dd_zone_multiplier?: number | null;
  /** Profit-lock multiplier component. */
  profit_lock_multiplier?: number | null;
  /** Reason this agent/market is not trading, if applicable. */
  reason_not_trading?: string | null;
}

/** Aggregated global risk snapshot returned by /api/v1/kalshi/global-risk-status. */
export interface GlobalRiskStatus {
  ts: string;
  /** Portfolio drawdown as a percentage (e.g. 12.3). */
  drawdown_pct: number;
  /** Current drawdown zone: green | yellow | orange | red. */
  zone: 'green' | 'yellow' | 'orange' | 'red';
  /** Size multiplier for the current zone (e.g. 0.625 for yellow). */
  zone_multiplier: number;
  /** Profit-lock state: safe | caution | frozen. */
  profit_lock_state: 'safe' | 'caution' | 'frozen';
  /** Profit-lock size multiplier (1.0 / 0.5 / 0.0). */
  profit_lock_multiplier: number;
  /** Locked profit in USD. */
  locked_profit_usd: number;
  /** Remaining give-back headroom in USD before FROZEN triggers. */
  giveback_remaining_usd: number;
  /** Session realized P&L high-water mark in USD. */
  session_high_usd: number;
  /** Combined effective size multiplier (zone × profit-lock). */
  effective_multiplier: number;
  /** Number of errors counted toward budget in the current window. */
  error_budget_used: number;
  /** Error budget threshold (default 50). */
  error_budget_threshold: number;
  /** Error budget utilization percentage. */
  error_budget_pct: number;
  /** True when drawdown halt is active (≥20% DD). Does NOT consume error budget. */
  drawdown_halt_active: boolean;
  /** True when an operator manual halt is active. */
  manual_halt_active: boolean;
  /** True when the kill switch is fired (error budget exceeded). */
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
}

/** A single risk state transition event from /api/v1/kalshi/risk/state-transitions. */
export interface StateTransition {
  ts: string;
  event_type: string;
  detail: string;
  [key: string]: unknown;
}

/** Effective live risk configuration from /api/v1/kalshi/risk/effective-config. */
export interface EffectiveRiskConfig {
  drawdown: {
    green_pct: number;
    soft_pct: number;
    hard_pct: number;
    halt_pct: number;
    multipliers: { green: number; yellow: number; orange: number; red: number };
  };
  profit_lock: {
    lock_fraction: number;
    max_giveback_fraction: number;
    caution_threshold: number;
    states: Record<string, { multiplier: number; description: string }>;
  };
  kill_switch: {
    error_budget_threshold: number;
    dedup_window_secs: number;
    warn_pct: number;
    limit_pct: number;
    exempt_classes: string[];
    note: string;
  };
  ct_timebox: {
    taper_start_minutes_before_expiry: number;
    expired_skip: boolean;
    description: string;
  };
}

export interface MarketOutcome {
  id: string;
  name: string;
  price: number;
  bid: number | null;
  ask: number | null;
}

export interface CatalogMarket {
  ticker: string;
  question: string;
  category: string;
  asset: string | null;
  market_type: string;
  volume: number;
  outcomes: MarketOutcome[];
  active: boolean;
  minutes_to_expiry: number | null;
  expires_at: string | null;
  timeframe: string | null;
}
