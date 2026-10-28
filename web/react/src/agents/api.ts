/**
 * agents/api.ts — typed fetchers for the agent-facing backend surface.
 *
 * Every call goes through apiUrl() (same-origin by default, VITE_API_BASE
 * override) with shared auth headers. Each fetcher is fault-isolated by the
 * caller (Promise.allSettled / independent try-catch) — one failing endpoint
 * must never zero out the whole wall.
 */

import { apiUrl } from '../config/apiBase';
import type {
  AssetAgent, AssetSymbol, AgentState, BalanceInfo, CycleDecision,
  DecisionEvent, GridSummary, LaneInfo, LaneId, LiveRuntimeState,
  MarketState, RejectionWaterfallStage,
} from './types';
import { ASSETS, LANES, MONEYNESS_BANDS } from './types';

const TOKEN_KEY = 'merid-access';

export function authHeaders(extra?: HeadersInit): HeadersInit {
  let token: string | null = null;
  try { token = localStorage.getItem(TOKEN_KEY); } catch { /* noop */ }
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
    ...(extra ?? {}),
  };
}

export async function getJson<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl(path), { headers: authHeaders(), signal: ctrl.signal });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} @ ${path}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export async function postJson<T>(path: string, body?: unknown, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl(path), {
      method: 'POST',
      headers: authHeaders(),
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} @ ${path}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export async function delJson<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl(path), {
      method: 'DELETE',
      headers: authHeaders(),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      let detail = '';
      try {
        const body = await res.json() as { detail?: string };
        detail = body?.detail ? ` — ${body.detail}` : '';
      } catch { /* non-JSON error body */ }
      throw new Error(`${res.status} ${res.statusText} @ ${path}${detail}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

/* ------------------------------------------------------------------ */
/* Raw server shapes (defensive — backend may omit fields)             */
/* ------------------------------------------------------------------ */

export interface ServerAgent {
  name?: string;
  asset?: string;
  enabled?: boolean;
  running?: boolean;
  state?: string;
  current_task?: string;
  last_signal_ts?: string | number;
  last_signal_age_s?: number;
  position_count?: number;
  risk_budget_used?: number;
  is_zombie?: boolean;
  has_signal?: boolean;
  rejected_reason?: string;
  trend_aligned?: boolean;
  heartbeat?: { last_eval_ms?: number; book_age_ms?: number; watermark_ms?: number; spot_age_ms?: number };
  market?: AssetAgent['market'];
  position?: AssetAgent['position'];
  lanes?: Array<{ lane?: string; status?: string; reason?: string; last_order_ts?: string }>;
  edge?: AssetAgent['edge'];
  cycle_decision?: CycleDecision | null;
  rejection_waterfall?: RejectionWaterfallStage[];
  pnl?: AssetAgent['pnl'];
}

export interface GridAgentsResponse {
  running?: boolean;
  mode?: string;
  agents?: ServerAgent[];
}

/* ------------------------------------------------------------------ */
/* Endpoint paths                                                     */
/* ------------------------------------------------------------------ */

export const AGENT_ENDPOINTS = {
  GRID_AGENTS: '/api/v1/kalshi-grid/agents',
  GRID_SUMMARY: '/api/v1/kalshi-grid/summary',
  DECISION_FEED: '/api/v1/kalshi-grid/decision-feed',
  LEGACY_AGENTS: '/api/v1/agents',                        // basic per-asset fallback
  MARKET_STATES: '/api/v1/kalshi/market-states',
  INTERNAL_KALSHI_HEALTH: '/api/v1/kalshi/internal/kalshi_health',
  BALANCE: '/api/v1/kalshi/balance',
  POSITIONS: '/api/v1/kalshi/positions',
  ORDERS: '/api/v1/kalshi/orders',
  FILLS: '/api/v1/kalshi/fills',
  PNL: '/api/v1/kalshi/pnl',
  PNL_HISTORY: '/api/v1/kalshi/pnl-history',
  RISK: '/api/v1/kalshi/risk',
  KILL_SWITCH: '/api/v1/kalshi/kill-switch',
  ORDER_ERRORS: '/api/v1/kalshi/order-errors',
  GUARD_VERDICTS: '/api/v1/loop/guard/verdicts',
  LIVE_RUNTIME_STATE: '/api/v1/live-runtime-state/',
  HALT: '/api/v1/live-runtime-state/halt',
  RELEASE: '/api/v1/live-runtime-state/release',
  LOOP_STATUS: '/api/v1/loop-status',
  UNIFIED_HEALTH: '/api/v1/unified-health',
  SPOT_PRICES: '/api/v1/spot/prices',
  CALIBRATION_STATS: '/api/v1/kalshi/calibration/stats',
  CALIBRATION_CELLS: '/api/v1/kalshi/calibration/cell-metrics',
  MARKETS: '/api/v1/kalshi/markets',
  TICK_LOG: '/api/v1/loop/tick-log',
  ORDERBOOK: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook`,
  ORDERBOOK_STREAM: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook/stream`,
  MARKET_STATE: (ticker: string) => `/api/internal/v1/market-state/${ticker}`,
} as const;

/* ------------------------------------------------------------------ */
/* Fetchers                                                           */
/* ------------------------------------------------------------------ */

export const fetchGridAgents = () => getJson<GridAgentsResponse>(AGENT_ENDPOINTS.GRID_AGENTS);
export const fetchLegacyAgents = () => getJson<{ agents?: ServerAgent[] } | ServerAgent[]>(AGENT_ENDPOINTS.LEGACY_AGENTS);
export const fetchGridSummary = () => getJson<GridSummary>(AGENT_ENDPOINTS.GRID_SUMMARY);
export const fetchDecisionFeed = (limit = 60) =>
  getJson<{ events?: DecisionEvent[] }>(`${AGENT_ENDPOINTS.DECISION_FEED}?limit=${limit}`);
export const fetchMarketStates = () =>
  getJson<{ markets?: MarketState[] } | MarketState[] | Record<string, MarketState>>(AGENT_ENDPOINTS.MARKET_STATES);
export const fetchKalshiHealth = () => getJson<Record<string, unknown>>(AGENT_ENDPOINTS.INTERNAL_KALSHI_HEALTH);
/** Balance: normalize shard_balances_usd (USD dict) into shards[] (cents). */
export const fetchBalance = async (): Promise<BalanceInfo> => {
  const raw = await getJson<BalanceInfo>(AGENT_ENDPOINTS.BALANCE);
  if (!raw.shards && raw.shard_balances_usd) {
    raw.shards = Object.entries(raw.shard_balances_usd)
      .map(([k, usd]) => ({
        shard: Number(k),
        balance_cents: Math.round(Number(usd) * 100),
        available_cents: Math.round(Number(usd) * 100),
      }))
      .filter((s) => Number.isFinite(s.shard));
  }
  return raw;
};
export const fetchLiveRuntimeState = () => getJson<LiveRuntimeState>(AGENT_ENDPOINTS.LIVE_RUNTIME_STATE);
export const fetchLoopStatus = () => getJson<Record<string, unknown>>(AGENT_ENDPOINTS.LOOP_STATUS);
export const fetchUnifiedHealth = () => getJson<Record<string, unknown>>(AGENT_ENDPOINTS.UNIFIED_HEALTH);
export const fetchSpotPrices = () => getJson<Record<string, unknown>>(AGENT_ENDPOINTS.SPOT_PRICES);

/** Emergency halt — blocks new entries. Exits/cancels stay live. */
export const haltEntries = (reason = 'operator_halt') =>
  postJson<Record<string, unknown>>(AGENT_ENDPOINTS.HALT, { reason });
/** Release halt — requires the backend's release assertion to pass. */
export const releaseEntries = () => postJson<Record<string, unknown>>(AGENT_ENDPOINTS.RELEASE, {});
/** Kill switch takes `activate` as a QUERY param (verified: kalshi_api.py:4548). */
export const setKillSwitch = (active: boolean, _reason?: string) =>
  postJson<Record<string, unknown>>(`${AGENT_ENDPOINTS.KILL_SWITCH}?activate=${active}`);

/* ------------------------------------------------------------------ */
/* Normalizer: ServerAgent -> AssetAgent                              */
/* ------------------------------------------------------------------ */

const VALID_STATES: AgentState[] = ['WORKING_ORDER', 'IN_POSITION', 'VETOED', 'STALE_FEED', 'HALTED', 'SCANNING'];

function coerceAsset(name?: string, asset?: string): AssetSymbol | null {
  const raw = (asset ?? name ?? '').toUpperCase();
  for (const a of ASSETS) if (raw.includes(a)) return a;
  return null;
}

function deriveState(s: ServerAgent): AgentState {
  if (s.state && VALID_STATES.includes(s.state as AgentState)) return s.state as AgentState;
  if (s.enabled === false) return 'HALTED';
  const bookAge = s.heartbeat?.book_age_ms ?? s.market?.book_age_ms;
  if (bookAge != null && bookAge > 60_000) return 'STALE_FEED';
  if (s.position || (s.position_count ?? 0) > 0) return 'IN_POSITION';
  if (s.has_signal && s.rejected_reason) return 'VETOED';
  return 'SCANNING';
}

function deriveTask(s: ServerAgent, state: AgentState): string {
  if (s.current_task) return s.current_task;
  const cd = s.cycle_decision;
  switch (state) {
    case 'IN_POSITION':
      return s.position ? `Holding ${s.position.side.toUpperCase()} ${s.position.qty_centi}cc @${s.position.avg_price_c}c` : 'In position';
    case 'WORKING_ORDER':
      return cd ? `Resting ${String(cd.side ?? '').toUpperCase()} @${cd.bid_c ?? cd.ask_c ?? '?'}c` : 'Working order';
    case 'VETOED':
      return `Veto: ${s.rejected_reason ?? cd?.rejection_reason ?? 'unknown'}`;
    case 'STALE_FEED':
      return 'Feed stale — not evaluating';
    case 'HALTED':
      return 'Halted';
    default:
      return cd?.rejection_reason ? `Scanning — last: ${cd.rejection_reason}` : 'Scanning for entries';
  }
}

function normalizeLanes(s: ServerAgent): LaneInfo[] {
  const byLane = new Map<string, LaneInfo>();
  for (const l of s.lanes ?? []) {
    const id = String(l.lane ?? '') as LaneId;
    if (!LANES.includes(id)) continue;
    byLane.set(id, {
      lane: id,
      status: (l.status as LaneInfo['status']) ?? 'unknown',
      reason: l.reason,
      last_order_ts: l.last_order_ts,
    });
  }
  return LANES.map((lane) => byLane.get(lane) ?? { lane, status: 'unknown' as const });
}

export function toAssetAgent(s: ServerAgent): AssetAgent | null {
  const asset = coerceAsset(s.name, s.asset);
  if (!asset) return null;
  const state = deriveState(s);
  return {
    asset,
    name: s.name ?? asset,
    state,
    current_task: deriveTask(s, state),
    enabled: s.enabled !== false,
    heartbeat: s.heartbeat ?? {},
    market: s.market,
    position: s.position ?? null,
    lanes: normalizeLanes(s),
    edge: s.edge,
    last_decision: s.cycle_decision ?? null,
    veto_waterfall: s.rejection_waterfall,
    pnl: s.pnl,
    raw: s as unknown as Record<string, unknown>,
  };
}

/** Normalize a mixed market-states response into a flat list. */
export function toMarketStateList(raw: unknown): MarketState[] {
  if (Array.isArray(raw)) return raw as MarketState[];
  const obj = raw as Record<string, unknown> | null;
  if (obj && Array.isArray(obj.markets)) return obj.markets as MarketState[];
  if (obj && typeof obj === 'object') {
    return Object.entries(obj)
      .filter(([, v]) => v && typeof v === 'object')
      .map(([k, v]) => ({ ticker: k, ...(v as object) })) as MarketState[];
  }
  return [];
}

/** Compose the wall: prefer the rich grid endpoint, fall back to /api/v1/agents. */
export async function fetchAgentsWall(): Promise<AssetAgent[]> {
  let servers: ServerAgent[] = [];
  try {
    const rich = await fetchGridAgents();
    servers = rich.agents ?? [];
  } catch {
    try {
      const legacy = await fetchLegacyAgents();
      servers = Array.isArray(legacy) ? legacy : legacy.agents ?? [];
    } catch {
      servers = [];
    }
  }
  const agents = servers.map(toAssetAgent).filter((a): a is AssetAgent => a !== null);
  // Guarantee one card per configured asset, even if the backend omits it.
  const have = new Set(agents.map((a) => a.asset));
  for (const asset of ASSETS) {
    if (!have.has(asset)) {
      agents.push({
        asset, name: asset, state: 'HALTED', current_task: 'No agent data',
        enabled: false, heartbeat: {}, position: null, lanes: LANES.map((lane) => ({ lane, status: 'unknown' as const })),
      });
    }
  }
  return agents;
}

export { MONEYNESS_BANDS, ASSETS, LANES };
