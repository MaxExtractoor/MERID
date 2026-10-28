/**
 * Agent domain types — the canonical contract between the backend's
 * five LeanAgent15m asset agents (BTC/ETH/SOL/XRP/DOGE) and every
 * agent-facing UI surface (Agent Wall, Agent Detail, Mission Control).
 *
 * Sources:
 *   GET /api/v1/kalshi-grid/agents        -> AgentSummary[] (rich)
 *   GET /api/v1/kalshi-grid/summary       -> GridSummary
 *   GET /api/v1/kalshi-grid/decision-feed -> DecisionEvent[]
 *   GET /api/v1/kalshi/market-states      -> MarketState[]
 *   GET /api/v1/kalshi/balance            -> BalanceInfo (incl. shards)
 *   GET /api/v1/live-runtime-state/       -> LiveRuntimeState
 */

export type AssetSymbol = 'BTC' | 'ETH' | 'SOL' | 'XRP' | 'DOGE';

export const ASSETS: AssetSymbol[] = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];

/** Canonical agent states, ordered by operator-attention priority. */
export type AgentState =
  | 'WORKING_ORDER'   // resting entry order live on the book
  | 'IN_POSITION'     // holding an open position
  | 'VETOED'          // evaluated recently, decision was a veto
  | 'STALE_FEED'      // book/feed data too old to trust
  | 'HALTED'          // agent disabled or system halted
  | 'SCANNING';       // enabled, evaluating, no position/order

export const AGENT_ATTENTION_ORDER: AgentState[] = [
  'WORKING_ORDER', 'IN_POSITION', 'VETOED', 'STALE_FEED', 'HALTED', 'SCANNING',
];

export type LaneId = 'settle' | 'pinned_fav' | 'cheap_no' | 'mband';
export const LANES: LaneId[] = ['settle', 'pinned_fav', 'cheap_no', 'mband'];
export const LANE_LABELS: Record<LaneId, string> = {
  settle: 'SETTLE',
  pinned_fav: 'PIN',
  cheap_no: 'CNO',
  mband: 'MBAND',
};

export type LaneStatus = 'active' | 'resting' | 'flat' | 'blocked' | 'suspended' | 'unknown';

/** Per-asset moneyness rules from the audited bands in AGENTS.md. */
export interface MoneynessBand {
  /** Max entry price (cents) for NO side; 1 = hard-blocked. */
  noMaxC: number;
  /** Blocked NO pocket [lo, hi] in cents, if any. */
  noBlockedPocket: [number, number] | null;
  /** Pinned-fav maker floor (cents). */
  pinnedFavFloorC: number;
}

export const MONEYNESS_BANDS: Record<AssetSymbol, MoneynessBand> = {
  BTC:  { noMaxC: 79, noBlockedPocket: [51, 64], pinnedFavFloorC: 90 },
  ETH:  { noMaxC: 89, noBlockedPocket: [51, 64], pinnedFavFloorC: 90 },
  SOL:  { noMaxC: 75, noBlockedPocket: null,     pinnedFavFloorC: 90 },
  XRP:  { noMaxC: 1,  noBlockedPocket: null,     pinnedFavFloorC: 90 },
  DOGE: { noMaxC: 75, noBlockedPocket: null,     pinnedFavFloorC: 90 },
};

/** One gate step in a decision trace. */
export interface GateStep {
  gate: string;          // e.g. 'moneyness_cap', 'tail_lcb', 'ev_gate', 'shard_collateral'
  passed: boolean;
  detail?: string;
}

export interface CycleDecision {
  decision_id?: string;
  ticker?: string;
  side?: 'yes' | 'no';
  action?: string;              // enter | veto | skip | exit
  lane?: LaneId | string;
  net_edge_c?: number;
  edge_threshold_c?: number;
  yes_score?: number;
  no_score?: number;
  confidence?: number;
  model_p?: number;
  market_p?: number;
  bid_c?: number;
  ask_c?: number;
  depth_contracts?: number;
  fee_c?: number;
  ann_vol?: number;
  data_quality?: string;
  regime?: string;
  rejection_reason?: string;
  policy_version?: string;
  ts?: string;
  gates?: GateStep[];
}

export interface RejectionWaterfallStage {
  stage: string;
  rejected: number;
  final_reason?: string;
}

export interface LaneInfo {
  lane: LaneId;
  status: LaneStatus;
  reason?: string;
  last_order_ts?: string;
}

export interface AgentPosition {
  side: 'yes' | 'no';
  qty_centi: number;       // centi-contracts (0.01 units)
  avg_price_c: number;
  unrealized_pnl_c?: number;
  exits_armed?: boolean;
}

export interface AgentHeartbeat {
  last_eval_ms?: number;    // ms since last evaluation cycle
  book_age_ms?: number;     // ms since last book update for its market
  watermark_ms?: number;    // ms since trusted fill watermark advanced
  spot_age_ms?: number;     // ms since spot/RTI update
}

/** The canonical per-asset agent object powering the UI. */
export interface AssetAgent {
  asset: AssetSymbol;
  name: string;
  state: AgentState;
  current_task: string;        // one-line human description of what it's doing
  enabled: boolean;
  heartbeat: AgentHeartbeat;
  market?: {
    ticker?: string;
    strike?: number;
    yes_bid_c?: number;
    yes_ask_c?: number;
    mid_c?: number;
    spread_c?: number;
    secs_to_close?: number;    // seconds to 15m window close
    book_fresh?: boolean;
    book_age_ms?: number;      // ms since last book update
    window_low_c?: number;
    window_high_c?: number;
    last_price_c?: number;
  };
  position?: AgentPosition | null;
  lanes: LaneInfo[];
  edge?: {
    net_ev_c?: number;
    threshold_c?: number;
    model_p?: number;
    market_p?: number;
    calibrated?: boolean;
  };
  last_decision?: CycleDecision | null;
  veto_waterfall?: RejectionWaterfallStage[];
  pnl?: {
    realized_c?: number;
    session_c?: number;
    fills_24h?: number;
  };
  /** Raw server payload kept for drill-downs. */
  raw?: Record<string, unknown>;
}

export interface GridSummary {
  running: boolean;
  agents_total: number;
  agents_running: number;
  mode?: string;
  uptime_s?: number;
  last_cycle_ts?: string;
}

export type DecisionEventKind =
  | 'enter' | 'veto' | 'skip' | 'order' | 'fill' | 'guard' | 'exit' | 'settle';

export interface DecisionEvent {
  ts: string;
  asset?: AssetSymbol | string;
  kind: DecisionEventKind;
  summary: string;             // "ENTER pinned-fav YES@93c +2.3c"
  lane?: string;
  reason?: string;             // veto/guard reason code
  ticker?: string;
  side?: 'yes' | 'no';
  price_c?: number;
  edge_c?: number;
  counterfactual?: boolean;    // would-have-traded-if-not-vetoed
  meta?: Record<string, unknown>;
}

export interface MarketState {
  ticker: string;
  initialized?: boolean;
  yes_bid_c?: number;
  yes_ask_c?: number;
  mid_c?: number;
  spread_c?: number;
  depth_contracts?: number;
  volume?: number;
  open_interest?: number;
  secs_to_expiry?: number;
  last_update_ts?: string;
  book_age_ms?: number;
}

export interface ShardBalance {
  shard: number;
  balance_cents: number;
  available_cents?: number;
}

export interface BalanceInfo {
  state?: string;                    // OK | STALE | ERROR | UNKNOWN
  usd?: number | null;               // available cash, dollars
  balance_cents?: number;
  portfolio_cents?: number;
  total_value_cents?: number;
  max_position_usd?: number | null;
  as_of?: string;
  source?: string;
  error?: string;
  warning?: string;
  /** Resolved trading shard (crypto 15m markets: shard 2). */
  trading_shard?: number | null;
  /** Raw per-shard balances in USD keyed by shard id ("0", "2", ...). */
  shard_balances_usd?: Record<string, number> | null;
  trading_shard_balance_usd?: number | null;
  /** Normalized cent-based view populated client-side. */
  shards?: ShardBalance[];
}

export interface LiveRuntimeState {
  state: 'LIVE_ENTRIES_ENABLED' | 'LIVE_ENTRIES_HALTED' | string;
  entry_halted?: boolean;
  reason?: string;
  reason_code?: string;
  updated_ts?: string;
  history?: Array<{ ts: string; state: string; reason?: string }>;
}

/** Fleet-level attention sort comparator. */
export function agentAttentionRank(a: AssetAgent): number {
  const idx = AGENT_ATTENTION_ORDER.indexOf(a.state);
  return idx === -1 ? AGENT_ATTENTION_ORDER.length : idx;
}

export function freshnessClass(ageMs?: number): 'live' | 'stale' | 'dead' {
  if (ageMs == null) return 'dead';
  if (ageMs < 10_000) return 'live';
  if (ageMs < 60_000) return 'stale';
  return 'dead';
}
