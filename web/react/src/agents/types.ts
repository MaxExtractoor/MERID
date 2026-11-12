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
  // pinnedFavFloorC mirrors MERID_PINNED_FAV_MAKER_LO=92 (2026-10-28): the
  // 90-91c floor pocket itself was falsified at maker fills — keep this in
  // sync with the live env value or the gauge lies about the maker zone.
  BTC:  { noMaxC: 79, noBlockedPocket: [51, 64], pinnedFavFloorC: 92 },
  ETH:  { noMaxC: 89, noBlockedPocket: [51, 64], pinnedFavFloorC: 92 },
  SOL:  { noMaxC: 75, noBlockedPocket: null,     pinnedFavFloorC: 92 },
  XRP:  { noMaxC: 1,  noBlockedPocket: null,     pinnedFavFloorC: 92 },
  DOGE: { noMaxC: 75, noBlockedPocket: null,     pinnedFavFloorC: 92 },
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
  /** Gate-level detail behind rejection_reason (e.g. STALE:age>t, NOT-LIVE-SEQUENCE-CONFIRMED). */
  rejection_detail?: string;
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
  watermark_ms?: number;    // age (ms) of the last WS orderbook event applied to the agent's market state
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
    no_bid_c?: number;
    no_ask_c?: number;
    mid_c?: number;
    spread_c?: number;
    secs_to_close?: number;    // seconds to 15m window close
    status?: string;           // venue market status (open/closed/paused)
    underlying?: string;       // BTC/ETH/SOL/... settlement asset
    book_fresh?: boolean;
    book_age_ms?: number;      // ms since last book update
    book_health?: string;      // NO_SNAPSHOT|LIVE|DEGRADED|... state-machine label
    executable?: boolean;      // book healthy enough to trade against
    data_quality?: string;
    data_source?: string;      // WS_LIVE | REST_BOOTSTRAP | STALE_WS | ...
    external_spot?: number;    // CF Benchmarks RTI / external reference
    model_fair_prob?: number;  // model fair probability (0-1) when published
    annualized_vol?: number;
    last_price_c?: number;     // last trade price, cents
    ws_last_event_age_ms?: number;
    last_update_ts?: number;
    window_low_c?: number;
    window_high_c?: number;
    depth_10c_yes?: number;
    depth_10c_no?: number;
    min_depth_yes?: number;
    min_depth_no?: number;
    exchange_index?: number;   // Kalshi collateral shard for this market
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
  /** Live entry-TTE cutoff (seconds): new entries vetoed when secs_to_close < this. */
  entry_cutoff_secs?: number;
  veto_waterfall?: RejectionWaterfallStage[];
  pnl?: {
    realized_c?: number;
    session_c?: number;
    fills_24h?: number;
  };
  /** Raw server payload kept for drill-downs. */
  raw?: Record<string, unknown>;
}

export interface GridSummaryAgent {
  name?: string;
  asset?: string;
  enabled?: boolean;
  running?: boolean;
  rejection_reason?: string | null;
}

/** Loop telemetry echoed by GET /api/v1/kalshi-grid/summary. */
export interface GridLoopSummary {
  running?: boolean | null;
  tick?: number | null;
  cycle_count?: number | null;
  error_count?: number | null;
  cadence_seconds?: number | null;
  last_cycle_at?: string | null;
  started_at?: string | null;
  halted_due_to_drawdown?: boolean | null;
}

/**
 * GET /api/v1/kalshi-grid/summary — verified shape:
 *   {available, running, agent_count, agents[], executed_candidates[],
 *    exchange_positions, open_orders, loop{...}}
 * agents_total / agents_running are normalized client-side aliases.
 */
export interface GridSummary {
  available?: boolean;
  reason?: string;
  running?: boolean;
  agent_count?: number;
  agents_total?: number;       // alias of agent_count
  agents_running?: number;     // count of agents with running===true; undefined when backend omits the flag
  agents?: GridSummaryAgent[];
  exchange_positions?: number;
  open_orders?: number;
  executed_candidates?: string[];
  loop?: GridLoopSummary;
}

export type DecisionEventKind =
  | 'enter' | 'veto' | 'skip' | 'order' | 'fill' | 'guard' | 'exit' | 'settle'
  | 'state'; // lifecycle/signal/scan rows from the backend feed

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
  no_bid_c?: number;
  no_ask_c?: number;
  mid_c?: number;
  spread_c?: number;
  depth_contracts?: number;
  volume?: number;
  open_interest?: number;
  secs_to_expiry?: number;
  status?: string;
  underlying?: string;
  strike?: number;
  external_spot?: number;
  last_price_c?: number;
  book_health?: string;
  executable?: boolean;
  data_source?: string;
  quote_owner?: string;
  data_quality?: string;
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
  reason_codes?: string[];
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
