/**
 * agents/api.ts — typed fetchers for the agent-facing backend surface.
 *
 * Every call goes through apiUrl() (same-origin by default, VITE_API_BASE
 * override) with shared auth headers. Each fetcher is fault-isolated by the
 * caller (Promise.allSettled / independent try-catch) — one failing endpoint
 * must never zero out the whole wall.
 */

import { apiUrl } from '../config/apiBase';
import { ensureSession, getSessionId, clearSessionIf, isSessionScopedPath } from './session';
import type {
  AssetAgent, AssetSymbol, AgentState, BalanceInfo, CycleDecision,
  DecisionEvent, GridSummary, LaneInfo, LaneId, LiveRuntimeState,
  MarketState, RejectionWaterfallStage,
} from './types';
import { ASSETS, LANES, MONEYNESS_BANDS } from './types';
import { numOr, parseTsMs } from './format';

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getSessionId();
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
    ...(extra ?? {}),
  };
}

/**
 * Shared fetch. Paths on the session-gated router (/api/v1/kalshi/*) mint an
 * operator session on first call and, on a 401 (e.g. backend restart wiped
 * the in-memory sessions), clear the stale token, re-mint once, and retry.
 * All other routes are unauthenticated and pass straight through.
 */
async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const scoped = isSessionScopedPath(path);
  if (scoped) await ensureSession(false, init.signal ?? undefined);
  const sent = getSessionId();
  let res = await fetch(apiUrl(path), { ...init, headers: authHeaders(init.headers) });
  if (res.status === 401 && scoped) {
    // Only clear if the stored token is still the one that failed — a
    // concurrent retry may have already minted a fresh session.
    clearSessionIf(sent);
    await ensureSession(true, init.signal ?? undefined);
    res = await fetch(apiUrl(path), { ...init, headers: authHeaders(init.headers) });
  }
  return res;
}

async function errorDetail(res: Response, path: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json() as { detail?: unknown };
    // FastAPI returns detail as a string for HTTPException(str) but as an
    // object for structured refusals (e.g. /live-runtime-state/recover
    // returns {status, missing}) — serialize either form.
    if (body?.detail != null) {
      detail = ` — ${typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)}`;
    }
  } catch { /* non-JSON error body */ }
  return new Error(`${res.status} ${res.statusText} @ ${path}${detail}`);
}

export async function getJson<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await authedFetch(path, { signal: ctrl.signal });
    if (!res.ok) throw await errorDetail(res, path);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export async function postJson<T>(path: string, body?: unknown, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await authedFetch(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw await errorDetail(res, path);
    return (await res.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

export async function delJson<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await authedFetch(path, { method: 'DELETE', signal: ctrl.signal });
    if (!res.ok) throw await errorDetail(res, path);
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
  working_order?: boolean;
  working_orders?: Array<Record<string, unknown>>;
  risk_budget_used?: number;
  risk_budget_cap_usd?: number;
  is_zombie?: boolean;
  has_signal?: boolean;
  rejected_reason?: string;
  /** Gate-level detail behind rejected_reason (e.g. STALE:age>t, NOT-LIVE-SEQUENCE-CONFIRMED). */
  rejected_detail?: string;
  /** Live entry-TTE cutoff (seconds) — new entries vetoed below this. */
  entry_cutoff_secs?: number;
  trend_aligned?: boolean;
  run_id?: string;
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
  RECOVER: '/api/v1/live-runtime-state/recover',
  UNIFIED_HEALTH: '/api/v1/unified-health',
  SPOT_PRICES: '/api/v1/spot/prices',
  CALIBRATION_STATS: '/api/v1/kalshi/calibration/stats',
  CALIBRATION_CELLS: '/api/v1/kalshi/calibration/cell-metrics',
  MARKETS: '/api/v1/kalshi/markets',
  TICK_LOG: '/api/v1/loop/tick-log',
  ORDERBOOK: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook`,
} as const;

/* ------------------------------------------------------------------ */
/* Fetchers                                                           */
/* ------------------------------------------------------------------ */

export const fetchGridAgents = () => getJson<GridAgentsResponse>(AGENT_ENDPOINTS.GRID_AGENTS);
export const fetchLegacyAgents = () => getJson<{ agents?: ServerAgent[] } | ServerAgent[]>(AGENT_ENDPOINTS.LEGACY_AGENTS);

/**
 * GET /api/v1/kalshi-grid/summary returns {available, running, agent_count,
 * agents[], exchange_positions, open_orders, loop{...}} — NOT the legacy
 * {agents_total, agents_running, mode} shape.  Normalize here so consumers
 * read one contract; agents_running stays undefined when the backend omits
 * per-agent running flags (honest '?' in the UI, never a guessed count).
 */
export const fetchGridSummary = async (): Promise<GridSummary> => {
  const raw = await getJson<Record<string, unknown>>(AGENT_ENDPOINTS.GRID_SUMMARY);
  const agents = Array.isArray(raw?.agents)
    ? (raw.agents as GridSummary['agents']) ?? []
    : [];
  const agentCount = numOr(raw?.agent_count) ?? agents.length;
  const anyRunningFlag = agents.some((a) => a && typeof a.running === 'boolean');
  const agentsRunning = anyRunningFlag
    ? agents.filter((a) => a?.running === true).length
    : undefined;
  return {
    ...(raw as unknown as GridSummary),
    agent_count: agentCount,
    agents_total: agentCount,
    agents_running: agentsRunning,
    agents,
  };
};
const FEED_KINDS: ReadonlySet<string> = new Set([
  'enter', 'veto', 'skip', 'order', 'fill', 'guard', 'exit', 'settle', 'state',
]);

/**
 * Normalize backend decision-feed events (verified kalshi_agent_grid_api
 * /decision-feed): rows carry `kind` ∈ {fill,order,veto,skip,exit,settle,
 * state,signal,scan,guard}, `state`, `reason`, `side`, `ticker`,
 * `decision_lane`, `detail` — but no `summary`/`price_c`/`edge_c`. Build
 * the UI fields honestly from what's emitted; unmapped kinds → 'state'.
 */
function toDecisionEvent(e: Record<string, unknown>): DecisionEvent {
  const detail = (e.detail ?? e.meta ?? {}) as Record<string, unknown>;
  const rawKind = String(e.kind ?? 'state');
  const mapped = FEED_KINDS.has(rawKind);
  const kind = (mapped ? rawKind : 'state') as DecisionEvent['kind'];
  const side = e.side ?? detail.selected_side;
  const ticker = e.ticker ?? detail.ticker;
  const label = mapped ? null : rawKind.toUpperCase();
  const summary = typeof e.summary === 'string' && e.summary
    ? e.summary
    : [label, e.state ? String(e.state) : null,
       side ? String(side).toUpperCase() : null,
       ticker ? String(ticker) : null].filter(Boolean).join(' ') || 'n/a';
  return {
    ...(e as unknown as DecisionEvent),
    kind,
    summary,
    side: side === 'yes' || side === 'no' ? side : undefined,
    price_c: numOr(e.price_c ?? detail.entry_price_cents ?? detail.selected_side_best_bid_cents),
    edge_c: numOr(e.edge_c ?? detail.ev_net_cents),
    counterfactual: e.counterfactual === true || detail.counterfactual === true || undefined,
    lane: (e.lane ?? e.decision_lane ?? detail.decision_lane ?? detail.entry_lane) as string | undefined,
    reason: (e.reason as string) ?? undefined,
    meta: detail,
  };
}

export const fetchDecisionFeed = async (limit = 60) => {
  const res = await getJson<{ events?: Array<Record<string, unknown>> }>(
    `${AGENT_ENDPOINTS.DECISION_FEED}?limit=${limit}`);
  return { events: (res?.events ?? []).map(toDecisionEvent) };
};
export const fetchMarketStates = () =>
  getJson<{ markets?: MarketState[] } | MarketState[] | Record<string, MarketState>>(AGENT_ENDPOINTS.MARKET_STATES);
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
export const fetchSpotPrices = () => getJson<Record<string, unknown>>(AGENT_ENDPOINTS.SPOT_PRICES);

/** Emergency halt — blocks new entries. Exits/cancels stay live. */
export const haltEntries = (reason = 'operator_halt') =>
  postJson<Record<string, unknown>>(AGENT_ENDPOINTS.HALT, { reason });
/** Verified release — the backend probes fresh reconciliation, fill
 *  watermark, exits/router availability, and production/live identity, then
 *  commits the canonical RECOVERY_RUNNING -> LIVE_ENTRIES_ENABLED transition.
 *  A 409 means evidence is still missing; the halt stays in place (fail
 *  closed). The manual-token /release endpoint remains for break-glass use. */
export const releaseEntries = () =>
  postJson<Record<string, unknown>>(AGENT_ENDPOINTS.RECOVER, { reason: 'operator_release_ui' });
/** Kill switch takes `activate` as a QUERY param (verified: kalshi_api.py:4548). */
export const setKillSwitch = (active: boolean) =>
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
  // Backend semantics: has_signal is FALSE precisely when rejection_reason
  // exists — requiring it true here would veto-proof the fallback path.
  if (s.rejected_reason || s.cycle_decision?.rejection_reason) return 'VETOED';
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

/**
 * Normalize the raw `_cycle_decision` dict into the UI CycleDecision shape.
 * Live keys (verified agent_grid_15m.py): `selected_side`, `rejection_reason`,
 * `selected_side_best_bid_cents`, `selected_side_best_ask_cents`,
 * `entry_price_cents`, `ev_net_cents`. Raw fields are spread through for
 * drill-downs; only the canonical UI keys are renamed.
 */
function toCycleDecision(cd: CycleDecision | Record<string, unknown> | null | undefined): CycleDecision | null {
  if (!cd || typeof cd !== 'object') return null;
  const raw = cd as Record<string, unknown>;
  const side = raw.side ?? raw.selected_side ?? raw.selected_outcome;
  return {
    ...(raw as CycleDecision),
    side: side === 'yes' || side === 'no' ? side : undefined,
    bid_c: numOr(raw.bid_c ?? raw.selected_side_best_bid_cents ?? raw.entry_price_cents),
    ask_c: numOr(raw.ask_c ?? raw.selected_side_best_ask_cents),
    net_edge_c: numOr(raw.net_edge_c ?? raw.ev_net_cents),
    rejection_reason: (raw.rejection_reason as string) ?? undefined,
    rejection_detail: (raw.rejection_detail ?? raw.entry_ready_reason) as string | undefined,
  };
}

export function toAssetAgent(s: ServerAgent): AssetAgent | null {
  const asset = coerceAsset(s.name, s.asset);
  if (!asset) return null;
  const state = deriveState(s);
  let cd = toCycleDecision(s.cycle_decision);
  // Merge the serializer's resolved veto reason into last_decision: the
  // backend merges cycle → _last_signal_rejection → waterfall.final_reason
  // into top-level `rejected_reason`, but cycle_decision.rejection_reason
  // itself is often empty on gate-path vetoes (e.g. hard_tte_cutoff) —
  // without this, cards render "vetoed - reason n/a" despite a real reason.
  if (cd) {
    if (!cd.rejection_reason && s.rejected_reason) cd.rejection_reason = s.rejected_reason;
    if (!cd.rejection_detail && s.rejected_detail) cd.rejection_detail = s.rejected_detail;
  } else if (s.rejected_reason) {
    cd = { rejection_reason: s.rejected_reason, rejection_detail: s.rejected_detail };
  }
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
    last_decision: cd,
    entry_cutoff_secs: numOr(s.entry_cutoff_secs),
    veto_waterfall: s.rejection_waterfall,
    pnl: s.pnl,
    raw: s as unknown as Record<string, unknown>,
  };
}

/**
 * Map a raw market-state row into the UI MarketState shape.
 * Live row (kalshi_api.py /market-states): emits cents-suffixed BBO
 * (yes_bid_cents/yes_ask_cents/no_bid_cents/no_ask_cents), mid_cents,
 * spread_cents, book_age_ms, book_health, executable, data_source,
 * status, underlying, strike_price/floor_strike, external_spot,
 * last_price_cents, quote_owner, data_quality, seconds_to_expiry,
 * volume_24h, open_interest, last_update_ts.
 */
function toMarketState(r: Record<string, unknown>, ticker?: string): MarketState {
  const lastUpdated = r.last_update_ts ?? r.last_updated;
  let bookAge = numOr(r.book_age_ms);
  if (bookAge == null) {
    const ts = parseTsMs(lastUpdated);
    if (ts != null) bookAge = Math.max(0, Date.now() - ts);
  }
  const depth = numOr(r.depth_contracts ?? r.depth_10c);
  return {
    ticker: String(r.ticker ?? ticker ?? ''),
    initialized: Boolean(r.initialized ?? r.book_initialized ?? false),
    yes_bid_c: numOr(r.yes_bid_c ?? r.yes_bid ?? r.yes_bid_cents ?? r.best_bid_cents),
    yes_ask_c: numOr(r.yes_ask_c ?? r.yes_ask ?? r.yes_ask_cents ?? r.best_ask_cents),
    no_bid_c: numOr(r.no_bid_c ?? r.no_bid_cents ?? r.best_no_bid_cents),
    no_ask_c: numOr(r.no_ask_c ?? r.no_ask_cents ?? r.best_no_ask_cents),
    mid_c: numOr(r.mid_c ?? r.mid_cents),
    spread_c: numOr(r.spread_c ?? r.spread_cents),
    depth_contracts: depth,
    volume: numOr(r.volume ?? r.volume_24h),
    open_interest: numOr(r.open_interest),
    secs_to_expiry: numOr(r.secs_to_expiry ?? r.seconds_to_expiry),
    status: typeof r.status === 'string' ? r.status : undefined,
    underlying: typeof r.underlying === 'string' ? r.underlying : undefined,
    strike: numOr(r.strike ?? r.strike_price ?? r.floor_strike),
    external_spot: numOr(r.external_spot),
    last_price_c: numOr(r.last_price_c ?? r.last_price_cents),
    book_health: typeof r.book_health === 'string' ? r.book_health : undefined,
    executable: typeof r.executable === 'boolean' ? r.executable : undefined,
    data_source: typeof r.data_source === 'string' ? r.data_source : (typeof r.source === 'string' ? r.source : undefined),
    quote_owner: typeof r.quote_owner === 'string' ? r.quote_owner : undefined,
    data_quality: typeof r.data_quality === 'string' ? r.data_quality : undefined,
    last_update_ts: lastUpdated != null ? String(lastUpdated) : undefined,
    book_age_ms: bookAge,
  };
}

/** Normalize a mixed market-states response into a flat list.
 *  Live shape (verified): `{count, states: {TICKER: row, ...}, timestamp}`. */
export function toMarketStateList(raw: unknown): MarketState[] {
  if (Array.isArray(raw)) return raw.map((r) => toMarketState(r as Record<string, unknown>));
  const obj = raw as Record<string, unknown> | null;
  if (!obj || typeof obj !== 'object') return [];
  const states = obj.markets ?? obj.states;
  if (Array.isArray(states)) return states.map((r) => toMarketState(r as Record<string, unknown>));
  if (states && typeof states === 'object') {
    return Object.entries(states as Record<string, unknown>)
      .filter(([, v]) => v && typeof v === 'object')
      .map(([ticker, v]) => toMarketState(v as Record<string, unknown>, ticker));
  }
  return Object.entries(obj)
    .filter(([, v]) => v && typeof v === 'object')
    .map(([ticker, v]) => toMarketState(v as Record<string, unknown>, ticker));
}

/** Compose the wall: prefer the rich grid endpoint, fall back to /api/v1/agents.
 *  Legacy shape (verified): `{agents_by_asset: {BTC: {...}, ...}}`. */
export async function fetchAgentsWall(): Promise<AssetAgent[]> {
  let servers: ServerAgent[] = [];
  try {
    const rich = await fetchGridAgents();
    servers = rich.agents ?? [];
  } catch {
    try {
      const legacy = await fetchLegacyAgents();
      if (Array.isArray(legacy)) {
        servers = legacy;
      } else {
        const l = legacy as { agents?: ServerAgent[]; agents_by_asset?: Record<string, ServerAgent> };
        servers = l.agents ?? (l.agents_by_asset ? Object.values(l.agents_by_asset) : []);
      }
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
