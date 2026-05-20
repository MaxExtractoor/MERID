/**
 * Volatility Dashboard Types
 * 
 * Shared type definitions for KalshiVolDashboardView components.
 * 
 * Tier 4: KalshiVolDashboardView.tsx Split (929→4 files)
 */

export interface VolDashHealthStatus {
  status: string;
  issues: string[];
  catalog: { market_count: number };
  risk: { kill_switch: boolean; daily_pnl: number; drawdown_pct: number };
  ws: { running: boolean; events_forwarded: number; subscribed_tickers: number };
  rate_limits: { orders_this_minute: number; max_per_minute: number; orders_this_hour: number; max_per_hour: number };
}

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
  win_rate?: number;
  errors?: number;
  fills?: number;
  active_tickers?: string[];
}

export interface VolDashGridStatus {
  agent_count: number;
  agents: GridAgent[];
}

export interface LiquidityAlertData {
  market_id: string;
  kind: string;
  severity: string;
  msg: string;
  ts: number;
}

export interface VolumeChange {
  ticker: string;
  prev_volume: number;
  curr_volume: number;
  change_pct: number;
  direction: 'up' | 'down';
  ts: string;
}

export interface VolumeAnomaly {
  ticker: string;
  z_score: number;
  volume: number;
  baseline_volume: number;
  severity: 'low' | 'medium' | 'high';
  ts: string;
}

export interface PnlPoint {
  ts: string;
  equity: number;
  realized_vol: number;
  target_vol: number;
}

export const TIER_COLORS: Record<string, { text: string; bg: string }> = {
  normal: { text: 'text-green-400', bg: 'bg-green-500/20' },
  warning: { text: 'text-yellow-400', bg: 'bg-yellow-500/20' },
  downsize: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
  halt: { text: 'text-red-400', bg: 'bg-red-500/20' },
};
