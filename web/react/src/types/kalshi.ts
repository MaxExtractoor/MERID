/**
 * Shared Kalshi data types used across multiple views and components.
 *
 * Import from here instead of re-defining in each view file.
 */

export interface KalshiBalance {
  usd: number;
  locked: number;
  available: number;
  mock?: boolean;
}

export interface KalshiPosition {
  ticker: string;
  outcome: string;
  size: number;
  avg_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  /** Canonical crypto asset from ``kalshi_ticker_to_asset`` (BTC, ETH, …) */
  asset?: string | null;
  initiated_by?: string | null;
  agent_name?: string | null;
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
  initiated_by?: string | null;
  agent_name?: string | null;
}

export interface KalshiFill {
  fill_id?: string;
  venue_fill_id?: string;
  trade_id: string;
  ticker: string;
  order_id?: string;
  /** Canonical asset code from backend */
  asset?: string | null;
  side: string;
  /** buy/sell (Kalshi action) */
  action?: string;
  size: number;
  price: number;
  price_usd?: number;
  price_cents?: number;
  fee: number;
  fee_usd?: number;
  timestamp: string;
  executed_at?: string;
  agent_id?: string;
  incomplete?: boolean;
  reconciled?: boolean;
  ingestion_source?: string;
  initiated_by?: string | null;
  agent_name?: string | null;
}

export interface KalshiRiskSummary {
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  daily_pnl_usd: number;
  total_notional_usd: number;
  total_unrealized_pnl_usd: number;
  daily_realized_pnl_usd: number;
  daily_total_pnl_usd: number;
  daily_trades: number;
  daily_fees_usd: number;
  drawdown_pct: number;
  category_notional: Record<string, number>;
  category_contracts: Record<string, number>;
  open_market_count: number;
  recent_breaches: Array<{ ts: string; check: string; reason: string }>;
  has_discrepancies?: boolean;
  risk_discrepancies?: Array<{ field: string; diff_usd: number }>;
  limits: Record<string, number>;
  win_rate_pct: number;
  profit_factor: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  total_exposure: number;
  max_exposure: number;
  daily_pnl: number;
  max_daily_loss: number;
  position_count: number;
  max_positions: number;
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
  continuous_trader?: {
    running: boolean;
    cycle: number;
    balance_cents: number;
    peak_balance_cents: number;
    drawdown_pct: number;
    halted: boolean;
    total_trades: number;
    total_pnl_cents: number;
    fee_drag_pct: number;
    fee_drag_tightening: boolean;
    vol_band: string;
    annualized_vol_pct: number;
    key_error: string | null;
    [key: string]: unknown;
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
