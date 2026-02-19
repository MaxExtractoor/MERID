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
  limits: Record<string, number>;
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
