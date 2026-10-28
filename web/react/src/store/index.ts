/**
 * Kalshi Store — Single Source of Truth for 15m Stack
 * 
 * Architecture:
 * - Single Zustand store with 3 slices: portfolio, risk, system
 * - REST polling only (no WS router exists on the live backend)
 * - All UI state derived from store, no local state duplication
 * - Agent-fleet telemetry is owned by useAgentWall (agents/api.ts) — the
 *   store deliberately does NOT duplicate grid/agent probes.
 *
 * Guardrails:
 * - UI never recomputes PnL, risk, or balances — only renders what backend provides
 * - Interface freeze: PortfolioData, RiskData, SystemData are contracts
 * - Fault isolation: every refreshAll() fetch is independently settled — one
 *   failing endpoint must never zero out the rest of the store
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import {
  AGENT_ENDPOINTS,
  fetchLiveRuntimeState,
  getJson,
} from '../agents/api';

// ── Types (contracts with backend) ─────────────────────────────────────────────

export interface Position {
  ticker: string;
  side: 'yes' | 'no';
  quantity: number;
  avg_entry_price_cents: number;
  unrealized_pnl_cents: number;
  outcome: string;
}

export interface KalshiOrder {
  order_id: string;
  ticker: string;
  side: string;
  size: number;
  price_cents: number;
  filled: number;
  remaining: number | null;
  status: string;
  created_at?: string | null;
}

export interface Fill {
  fill_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  fee_cents: number;
  pnl_cents: number;
  filled_at: string;
  market_question?: string;
}

export interface SliceHealth {
  /** ms epoch of last successful fetch for this slice. */
  lastOk?: number;
  /** Last fetch error for this slice (null when the last fetch succeeded). */
  error?: string | null;
}

export interface PortfolioData extends SliceHealth {
  balance: number;
  cash: number;
  portfolio_value: number;
  daily_pnl: number;
  positions: Position[];
  orders: KalshiOrder[];
  fills: Fill[];
  timestamp: string;
}

export interface SizingMetrics {
  kelly_fraction: number;
  vol_scale: number;
  effective_fraction: number;
  edge_pct: number;
}

export interface RiskAlert {
  id: string;
  type: 'drawdown' | 'notional' | 'daily_loss' | 'position';
  severity: 'warning' | 'critical';
  message: string;
  timestamp: string;
}

export interface RiskLimits {
  max_notional_usd?: number;
  max_open_markets?: number;
  daily_loss_limit?: number;
  max_drawdown_pct?: number;
  max_orders_per_minute?: number;
  max_orders_per_hour?: number;
}

export interface RiskData extends SliceHealth {
  daily_pnl: number;
  drawdown_pct: number;
  total_notional: number;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  sizing_metrics: SizingMetrics;
  limits: RiskLimits;
  open_market_count: number;
  daily_trades: number;
  realized_pnl: number;
  unrealized_pnl: number;
  win_rate_pct: number;
  sharpe_ratio: number;
  profit_factor: number;
  alerts: RiskAlert[];
  timestamp: string;
}

export interface ServiceHealth {
  name: string;
  ok: boolean;
  latency_ms: number;
  error?: string;
}

export interface LiveState {
  state: string;
  entry_halted: boolean;
  reason?: string;
}

export interface SystemData extends SliceHealth {
  health: {
    ok: boolean;
    services: Record<string, ServiceHealth>;
    overall_latency_ms: number;
  };
  /** Venue order mode. 'live' only when the backend reports a LIVE_* runtime
   *  state; 'paper' otherwise (safe default — never lie about paper). */
  mode: 'live' | 'paper';
  /** Canonical live runtime state (live-runtime-state endpoint). */
  live: LiveState | null;
  startup_completed: boolean;
  logs: LogEntry[];
  timestamp: string;
}

export interface LogEntry {
  id: string;
  level: 'info' | 'warning' | 'error';
  component: string;
  message: string;
  timestamp: string;
}

// ── Raw server shapes (defensive) ─────────────────────────────────────────────

interface ServerPosition {
  ticker?: string;
  outcome?: string;
  side?: string;
  size?: number | string;
  contracts?: number | string;
  avg_price?: number | string;
  unrealized_pnl?: number | string;
  asset?: string;
}

interface ServerOrder {
  order_id?: string;
  ticker?: string;
  side?: string;
  size?: number | string;
  price?: number | string;
  filled?: number | string;
  remaining?: number | string | null;
  status?: string;
  created_at?: string | null;
}

interface ServerFill {
  fill_id?: string;
  trade_id?: string;
  ticker?: string;
  side?: string;
  size?: number | string;
  contracts?: number | string;
  price_usd?: number | string;
  price_cents?: number | string;
  fee_usd?: number | string;
  pnl_usd?: number | string;
  pnl_cents?: number | string;
  timestamp?: string;
  filled_at?: string;
  market_question?: string;
}

interface ServerTick {
  tick?: number;
  ts?: number;
  duration_ms?: number;
  actions?: string[];
  plans?: { generated?: number; executed?: number; blocked?: number };
  guard?: { kill_switch?: boolean };
  error?: string;
}

// ── Mappers ─────────────────────────────────────────────────────────────────

const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const mapPosition = (p: ServerPosition): Position => {
  const outcome = String(p.outcome ?? p.side ?? 'yes').toLowerCase();
  return {
    ticker: String(p.ticker ?? ''),
    side: outcome === 'no' ? 'no' : 'yes',
    quantity: num(p.size ?? p.contracts),
    avg_entry_price_cents: Math.round(num(p.avg_price) * 100),
    unrealized_pnl_cents: Math.round(num(p.unrealized_pnl) * 100),
    outcome,
  };
};

const mapOrder = (o: ServerOrder): KalshiOrder => ({
  order_id: String(o.order_id ?? ''),
  ticker: String(o.ticker ?? ''),
  side: String(o.side ?? ''),
  size: num(o.size),
  price_cents: Math.round(num(o.price) * 100),
  filled: num(o.filled),
  remaining: o.remaining == null ? null : num(o.remaining),
  status: String(o.status ?? ''),
  created_at: o.created_at ?? null,
});

const mapFill = (f: ServerFill): Fill => ({
  fill_id: String(f.fill_id ?? f.trade_id ?? ''),
  ticker: String(f.ticker ?? ''),
  side: String(f.side ?? 'yes').toLowerCase() === 'no' ? 'no' : 'yes',
  contracts: num(f.size ?? f.contracts),
  price_cents: f.price_cents != null ? num(f.price_cents) : Math.round(num(f.price_usd) * 100),
  fee_cents: Math.round(num(f.fee_usd) * 100),
  pnl_cents: f.pnl_cents != null ? num(f.pnl_cents) : Math.round(num(f.pnl_usd) * 100),
  filled_at: String(f.timestamp ?? f.filled_at ?? ''),
  market_question: f.market_question,
});

const mapTickToLog = (t: ServerTick, idx: number): LogEntry => {
  const kill = t.guard?.kill_switch === true;
  const blocked = num(t.plans?.blocked);
  const level: LogEntry['level'] = t.error ? 'error' : (kill || blocked > 0 ? 'warning' : 'info');
  const parts = [`tick ${t.tick ?? idx}`];
  if (t.actions && t.actions.length > 0) parts.push(t.actions.join(', '));
  if (t.plans) parts.push(`plans +${num(t.plans.generated)}/${num(t.plans.executed)} exec/${blocked} blocked`);
  if (t.duration_ms != null) parts.push(`${t.duration_ms}ms`);
  if (kill) parts.push('KILL SWITCH');
  if (t.error) parts.push(`error: ${t.error}`);
  return {
    id: `tick-${t.tick ?? idx}-${t.ts ?? 0}`,
    level,
    component: 'merid-loop',
    message: parts.join(' · '),
    timestamp: t.ts ? new Date(num(t.ts) * 1000).toISOString() : new Date().toISOString(),
  };
};

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Settle one fetch — never throws. Returns [value, error]. */
async function probe<T>(fn: () => Promise<T>): Promise<[T | null, string | null]> {
  try {
    return [await fn(), null];
  } catch (e) {
    return [null, errMsg(e)];
  }
}

// ── Store Interface ───────────────────────────────────────────────────────────

interface KalshiStore {
  // Slices
  portfolio: PortfolioData;
  risk: RiskData;
  system: SystemData;

  // Connection state
  connected: boolean;
  lastUpdate: number;

  // Actions
  updatePortfolio: (data: Partial<PortfolioData>) => void;
  updateRisk: (data: Partial<RiskData>) => void;
  updateSystem: (data: Partial<SystemData>) => void;
  setConnected: (connected: boolean) => void;
  refreshAll: () => Promise<void>;
}

// ── Initial State ─────────────────────────────────────────────────────────────

const initialPortfolio: PortfolioData = {
  balance: 0,
  cash: 0,
  portfolio_value: 0,
  daily_pnl: 0,
  positions: [],
  orders: [],
  fills: [],
  timestamp: new Date().toISOString(),
};

const initialRisk: RiskData = {
  daily_pnl: 0,
  drawdown_pct: 0,
  total_notional: 0,
  kill_switch_active: false,
  kill_switch_reason: '',
  sizing_metrics: {
    kelly_fraction: 0,
    vol_scale: 0,
    effective_fraction: 0,
    edge_pct: 0,
  },
  limits: {},
  open_market_count: 0,
  daily_trades: 0,
  realized_pnl: 0,
  unrealized_pnl: 0,
  win_rate_pct: 0,
  sharpe_ratio: 0,
  profit_factor: 0,
  alerts: [],
  timestamp: new Date().toISOString(),
};

const initialSystem: SystemData = {
  health: {
    ok: false,
    services: {},
    overall_latency_ms: 0,
  },
  mode: 'paper',
  live: null,
  startup_completed: false,
  logs: [],
  timestamp: new Date().toISOString(),
};

// ── Store Creation ───────────────────────────────────────────────────────────

export const useKalshiStore = create<KalshiStore>()(
  subscribeWithSelector((set, get) => ({
    // Initial state
    portfolio: initialPortfolio,
    risk: initialRisk,
    system: initialSystem,
    connected: false,
    lastUpdate: 0,

    // Actions
    updatePortfolio: (data) => set((state) => ({
      portfolio: { ...state.portfolio, ...data },
      lastUpdate: Date.now(),
    })),

    updateRisk: (data) => set((state) => ({
      risk: { ...state.risk, ...data },
      lastUpdate: Date.now(),
    })),

    updateSystem: (data) => set((state) => ({
      system: { ...state.system, ...data },
      lastUpdate: Date.now(),
    })),
    
    setConnected: (connected) => set({ connected }),
    
    /**
     * Refresh every slice from the live backend.
     *
     * Fault-isolated: each endpoint is probed independently — a 404/500 on one
     * endpoint degrades only its own slice (error field set, prior data kept).
     * `connected` is true when ANY core fetch succeeds.
     */
    refreshAll: async () => {
      const now = Date.now();

      const [
        [balance, balanceErr],
        [pnl, pnlErr],
        [positionsRes, posErr],
        [ordersRes, ordErr],
        [fillsRes, fillsErr],
        [riskRes, riskErr],
        [killRes, killErr],
        [healthRes, healthErr],
        [liveRes, liveErr],
        [tickRes, tickErr],
      ] = await Promise.all([
        probe(() => getJson<Record<string, any>>(AGENT_ENDPOINTS.BALANCE)),
        probe(() => getJson<Record<string, any>>(AGENT_ENDPOINTS.PNL)),
        probe(() => getJson<{ positions?: ServerPosition[] }>(AGENT_ENDPOINTS.POSITIONS)),
        probe(() => getJson<{ orders?: ServerOrder[] }>(AGENT_ENDPOINTS.ORDERS)),
        probe(() => getJson<{ fills?: ServerFill[] }>(`${AGENT_ENDPOINTS.FILLS}?since_hours=24&limit=100`)),
        probe(() => getJson<Record<string, any>>(AGENT_ENDPOINTS.RISK)),
        probe(() => getJson<{ kill_switch?: boolean; status?: string }>(AGENT_ENDPOINTS.KILL_SWITCH)),
        probe(() => getJson<Record<string, any>>(AGENT_ENDPOINTS.UNIFIED_HEALTH)),
        probe(() => fetchLiveRuntimeState()),
        probe(() => getJson<{ ticks?: ServerTick[] }>(`${AGENT_ENDPOINTS.TICK_LOG}?limit=50`)),
      ]);

      const portfolioErr = balanceErr ?? pnlErr ?? posErr ?? ordErr ?? fillsErr;

      // ── Portfolio slice (balance + pnl + positions + orders + fills) ──
      if (balance || pnl || positionsRes || ordersRes || fillsRes) {
        get().updatePortfolio({
          balance: balance ? num(balance.total_value_cents ?? balance.balance_cents) / 100 : get().portfolio.balance,
          cash: balance ? num(balance.balance_cents ?? balance.usd) / 100 : get().portfolio.cash,
          portfolio_value: balance ? num(balance.portfolio_cents) / 100 : get().portfolio.portfolio_value,
          daily_pnl: pnl ? num(pnl.daily_pnl_usd) : get().portfolio.daily_pnl,
          positions: positionsRes?.positions ? positionsRes.positions.map(mapPosition) : get().portfolio.positions,
          orders: ordersRes?.orders ? ordersRes.orders.map(mapOrder) : get().portfolio.orders,
          fills: fillsRes?.fills ? fillsRes.fills.map(mapFill) : get().portfolio.fills,
          timestamp: new Date().toISOString(),
          lastOk: now,
          error: portfolioErr,
        });
      } else if (portfolioErr) {
        get().updatePortfolio({ error: portfolioErr });
      }

      // ── Risk slice (/kalshi/risk + authoritative kill-switch GET) ──
      if (riskRes || killRes) {
        const breachesRaw: unknown = riskRes?.recent_breaches;
        const breaches = Array.isArray(breachesRaw) ? breachesRaw : [];
        const alerts: RiskAlert[] = breaches.map((b: Record<string, any>, i: number) => {
          const check = String(b?.check ?? b?.type ?? '');
          const reason = String(b?.reason ?? b?.message ?? check ?? 'risk breach');
          const lc = `${check} ${reason}`.toLowerCase();
          const type: RiskAlert['type'] = lc.includes('drawdown')
            ? 'drawdown'
            : lc.includes('notional') || lc.includes('exposure')
              ? 'notional'
              : lc.includes('daily') ? 'daily_loss' : 'position';
          return {
            id: `${b?.ts ?? i}-${check}`,
            type,
            severity: (b?.severity === 'critical' ? 'critical' : 'warning') as RiskAlert['severity'],
            message: reason,
            timestamp: String(b?.ts ?? riskRes?.timestamp ?? new Date().toISOString()),
          };
        });
        get().updateRisk({
          daily_pnl: riskRes ? num(riskRes.daily_pnl_usd) : get().risk.daily_pnl,
          drawdown_pct: riskRes ? num(riskRes.drawdown_pct) : get().risk.drawdown_pct,
          total_notional: riskRes ? num(riskRes.total_notional_usd) : get().risk.total_notional,
          // Dedicated kill-switch GET is authoritative for the toggle state;
          // /risk carries the risk_controller view of the same flag.
          kill_switch_active: killRes?.kill_switch ?? riskRes?.kill_switch_active ?? get().risk.kill_switch_active,
          kill_switch_reason: killRes?.kill_switch
            ? (riskRes?.kill_switch_reason ?? '')
            : (riskRes?.kill_switch_reason ?? get().risk.kill_switch_reason),
          limits: riskRes?.limits ?? get().risk.limits,
          open_market_count: riskRes ? num(riskRes.open_market_count) : get().risk.open_market_count,
          daily_trades: riskRes ? num(riskRes.daily_trades) : get().risk.daily_trades,
          realized_pnl: riskRes ? num(riskRes.realized_pnl_usd) : get().risk.realized_pnl,
          unrealized_pnl: riskRes ? num(riskRes.unrealized_pnl_usd) : get().risk.unrealized_pnl,
          win_rate_pct: riskRes ? num(riskRes.win_rate_pct) : get().risk.win_rate_pct,
          sharpe_ratio: riskRes ? num(riskRes.sharpe_ratio) : get().risk.sharpe_ratio,
          profit_factor: riskRes ? num(riskRes.profit_factor) : get().risk.profit_factor,
          alerts: riskRes ? alerts : get().risk.alerts,
          timestamp: riskRes?.timestamp ?? new Date().toISOString(),
          lastOk: now,
          error: riskErr ?? killErr,
        });
      } else if (riskErr ?? killErr) {
        get().updateRisk({ error: riskErr ?? killErr });
      }

      // ── System slice (unified-health + live-runtime-state + tick log) ──
      if (healthRes || liveRes || tickRes) {
        const services: Record<string, ServiceHealth> = {};
        const svcObj = healthRes?.services as Record<string, any> | undefined;
        if (svcObj) {
          Object.entries(svcObj).forEach(([name, svc]) => {
            const ready = svc?.ready === true;
            services[name] = {
              name,
              ok: ready,
              latency_ms: 0,
              error: ready ? undefined : (svc?.error ?? svc?.status ?? 'not ready'),
            };
          });
        }
        const live: LiveState | null = liveRes?.state
          ? {
              state: String(liveRes.state),
              entry_halted: liveRes.entry_halted === true,
              reason: liveRes.reason ?? liveRes.reason_code,
            }
          : get().system.live;
        const ticksRaw: unknown = tickRes?.ticks;
        const ticks = Array.isArray(ticksRaw) ? ticksRaw : null;
        get().updateSystem({
          health: {
            ok: healthRes?.overall_status === 'ok',
            services,
            overall_latency_ms: 0,
          },
          // 'live' only on positive LIVE_* evidence from the runtime-state
          // endpoint; anything else keeps the safe 'paper' default.
          mode: String(liveRes?.state ?? '').startsWith('LIVE_') ? 'live' : get().system.mode,
          live,
          startup_completed: healthRes?.startup_completed === true || get().system.startup_completed,
          logs: ticks ? ticks.map(mapTickToLog) : get().system.logs,
          timestamp: new Date().toISOString(),
          lastOk: now,
          error: healthErr ?? liveErr ?? tickErr,
        });
      } else if (healthErr ?? liveErr ?? tickErr) {
        get().updateSystem({ error: healthErr ?? liveErr ?? tickErr });
      }

      // ── Connection: ANY core fetch succeeding means the backend is up ──
      const anyOk = [
        balance, pnl, positionsRes, ordersRes, fillsRes,
        riskRes, killRes, healthRes, liveRes, tickRes,
      ].some(v => v !== null);
      get().setConnected(anyOk);
    },
  }))
);

// ── Selectors (for optimized subscriptions) ───────────────────────────────────

export const selectPortfolio = (state: KalshiStore) => state.portfolio;
export const selectRisk = (state: KalshiStore) => state.risk;
export const selectSystem = (state: KalshiStore) => state.system;
export const selectConnected = (state: KalshiStore) => state.connected;
export const selectMode = (state: KalshiStore) => state.system.mode;
