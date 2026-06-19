/**
 * KalshiGridView — Dedicated Kalshi agent grid dashboard.
 *
 * Shows:
 *   - Header strip: session guard, grid running/stopped, kill switch
 *   - Agent grid matrix: 5 rows (assets) × 6 columns (timeframes)
 *   - Portfolio risk card
 *   - Controls: Start/Stop, Pause/Resume, Kill switch reset
 *   - Recent fills table
 *   - Drill-down to KalshiAgentDetail on cell click
 */

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { TRADABLE_TIMEFRAMES, TRADABLE_TIMEFRAME_LABELS, sortTimeframes } from '../config/timeframes';
import PaperLadderCard from '../components/PaperLadderCard';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import {
  BarChart3, Play, Square, Pause, RotateCcw, RefreshCw,
  Shield, AlertTriangle, Clock, ChevronRight,
  Activity, X, Zap, Radio, Wifi, WifiOff, Target,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════ */

interface AgentSummary {
  name: string;
  enabled: boolean;
  running: boolean;
  last_cycle_at: string | null;
  cycles_run: number;
  orders_placed: number;
  orders_this_window: number;
  active_tickers: string[];
  last_error: string | null;
  signal_count: number;
  order_count: number;
  fill_count: number;
  config: {
    assets: string[];
    timeframes: string[];
    risk_limits: {
      max_yes_position: number;
      max_no_position: number;
      max_orders_per_window: number;
      max_notional_usd: string;
    };
    entry_window: {
      minutes_before_expiry: number;
      cutoff_minutes_before_expiry: number;
    };
  };
}

interface VenueMode {
  mode: 'paper' | 'live' | 'mock';
  is_live: boolean;
  live_enabled: boolean;
}

interface GridStatus {
  running: boolean;
  agent_count: number;
  agents: AgentSummary[];
  venue_mode?: VenueMode;
  venue_health: {
    connected: boolean;
    circuit: {
      state: string;
      failure_count: number;
      last_failure: string | null;
    };
    rate_limits: {
      read: number;
      write: number;
    };
    error_rate: number;
  };
  metrics: {
    active_markets: number;
    covered_markets: number;
    coverage_pct: number;
    total_orders: number;
    total_fills: number;
    pnl_by_category: Record<string, number>;
  };
  portfolio_risk: {
    kill_switch_active: boolean;
    daily_pnl_usd: number;
    total_notional_usd: number;
    margin_utilization: number;
    paused_agents: string[];
  };
  session: {
    trading_allowed: boolean;
    block_reason: string | null;
    maintenance_day: boolean;
    maintenance_window: string;
  };
}

interface GridHealth {
  status: string;
  issues: string[];
  catalog: { market_count: number; last_refresh: string | null; categories: number };
  risk: { kill_switch: boolean; daily_pnl: number; drawdown_pct: number };
  ws: { running: boolean; events_forwarded: number; subscribed_tickers: number };
  rate_limits: { orders_this_minute: number; max_per_minute: number; orders_this_hour: number; max_per_hour: number };
}

interface SignalEntry {
  ts: string;
  market_id: string;
  question: string;
  action: string;
  contracts: number;
  limit_price_cents: number | null;
  edge: number | null;
  confidence: number | null;
  implied_yes: number | null;
  implied_no: number | null;
}

interface OrderEntry {
  ts: string;
  market_id: string;
  question: string;
  side: string;
  action: string;
  price_cents: number;
  contracts: number;
  ref_bid: number | null;
  ref_ask: number | null;
  ref_mid: number | null;
  success: boolean;
  simulated: boolean | null;
  error: string | null;
}

interface FillEntry {
  ts: string;
  market_id: string;
  side: string;
  action: string;
  price_cents: number;
  contracts: number;
  agent: string;
  simulated: boolean;
}

/* ═══════════════════════════════════════════════════════
   Constants
   ═══════════════════════════════════════════════════════ */

const ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
// Fallback timeframe list when matrix data is unavailable.
// Includes '15m', '1h', 'daily', 'pre-market' as the core set.
const TIMEFRAMES = ['15m', '1h', 'daily', 'pre-market', ...TRADABLE_TIMEFRAMES].filter(
  (v, i, arr) => arr.indexOf(v) === i  // deduplicate
);
const TF_LABELS: Record<string, string> = {
  ...TRADABLE_TIMEFRAME_LABELS,
  'pre-market': 'Pre-Mkt',
};

/* ═══════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════ */

interface GridMatrixCell {
  agent: string;
  enabled: boolean;
  running: boolean;
  cycles: number;
  orders: number;
  active_tickers: string[];
  status: 'active' | 'covering';
}

interface GridMatrixData {
  matrix: Record<string, Record<string, GridMatrixCell>>;
  assets: string[];
  timeframes: string[];
}

type GridTab = 'grid' | 'health';

function UtilBar({ value, max, warn = 75, danger = 90 }: { value: number; max: number; warn?: number; danger?: number }) {
  const p = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const color = p >= danger ? 'bg-red-500' : p >= warn ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div className="w-full bg-slate-700 rounded-full h-1.5 mt-0.5">
      <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${p}%` }} />
    </div>
  );
}

export default function KalshiGridView() {
  const [activeTab, setActiveTab] = useState<GridTab>('grid');
  const [status, setStatus] = useState<GridStatus | null>(null);
  const [gridHealth, setGridHealth] = useState<GridHealth | null>(null);
  const [matrixData, setMatrixData] = useState<GridMatrixData | null>(null);
  const [fills, setFills] = useState<FillEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentSignals, setAgentSignals] = useState<SignalEntry[]>([]);
  const [agentOrders, setAgentOrders] = useState<OrderEntry[]>([]);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [modeLoading, setModeLoading] = useState(false);
  const [startMode, setStartMode] = useState<'paper' | 'live'>('paper');

  const withAuthHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const fetchJson = useCallback(async <T,>(endpoint: string, init?: RequestInit): Promise<T> => {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...init,
      headers: withAuthHeaders(init?.headers),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json() as Promise<T>;
  }, [withAuthHeaders]);

  // ── Fetch ────────────────────────────────────────────

  const fetchStatus = useCallback(async () => {
    try {
      const [statusRes, matrixRes, fillsRes, healthRes] = await Promise.allSettled([
        fetchJson<GridStatus>(API_ENDPOINTS.KALSHI_GRID_STATUS),
        fetchJson<GridMatrixData>(API_ENDPOINTS.KALSHI_GRID_MATRIX),
        fetchJson<{ fills?: FillEntry[] } | FillEntry[]>(API_ENDPOINTS.KALSHI_GRID_FILLS),
        fetchJson<GridHealth>(API_ENDPOINTS.KALSHI_GRID_HEALTH),
      ]);

      if (statusRes.status === 'fulfilled') {
        setStatus(statusRes.value);
      }
      if (matrixRes.status === 'fulfilled') {
        setMatrixData(matrixRes.value);
      }
      if (fillsRes.status === 'fulfilled') {
        const payload = fillsRes.value;
        setFills(Array.isArray(payload) ? payload : (payload.fills ?? []));
      }
      if (healthRes.status === 'fulfilled') {
        setGridHealth(healthRes.value);
      }
    } catch {
      // keep stale data on network/parse errors
    } finally {
      setLoading(false);
    }
  }, [fetchJson]);

  const fetchAgentDetail = useCallback(async (name: string) => {
    try {
      const [sigRes, ordRes] = await Promise.allSettled([
        fetchJson<{ signals?: SignalEntry[] }>(API_ENDPOINTS.KALSHI_GRID_AGENT_SIGNALS(name)),
        fetchJson<{ orders?: OrderEntry[] }>(API_ENDPOINTS.KALSHI_GRID_AGENT_ORDERS(name)),
      ]);
      if (sigRes.status === 'fulfilled') {
        setAgentSignals(sigRes.value.signals ?? []);
      }
      if (ordRes.status === 'fulfilled') {
        setAgentOrders(ordRes.value.orders ?? []);
      }
    } catch {
      // keep stale
    }
  }, [fetchJson]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, DEFAULTS.POLLING_INTERVALS.STANDARD);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Sync startMode with actual server mode when status arrives
  useEffect(() => {
    if (status?.venue_mode?.mode && status.venue_mode.mode !== 'mock') {
      setStartMode(status.venue_mode.mode as 'paper' | 'live');
    }
  }, [status?.venue_mode?.mode]);

  useEffect(() => {
    if (selectedAgent) {
      fetchAgentDetail(selectedAgent);
      const interval = setInterval(() => fetchAgentDetail(selectedAgent), DEFAULTS.POLLING_INTERVALS.STANDARD);
      return () => clearInterval(interval);
    }
  }, [selectedAgent, fetchAgentDetail]);

  // ── Actions ──────────────────────────────────────────

  const postAction = async (url: string) => {
    setActionLoading(true);
    setActionError(null);
    try {
      await fetchJson(url, { method: 'POST' });
      await fetchStatus();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setActionLoading(false);
    }
  };

  const switchMode = async (mode: 'paper' | 'live') => {
    if (mode === 'live') {
      const confirmed = window.confirm(
        '⚠️ Switch to LIVE trading with real money?\n\n' +
        'This will route all agent orders to Kalshi with real funds.\n' +
        'Make sure MERID_PM_LIVE_ENABLED=true is set in your .env.\n\n' +
        'Continue?'
      );
      if (!confirmed) return;
    }
    setModeLoading(true);
    setActionError(null);
    try {
      await fetchJson(API_ENDPOINTS.KALSHI_GRID_MODE, {
        method: 'POST',
        body: JSON.stringify({ mode, force: false }),
      });
      setStartMode(mode);
      await fetchStatus();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Mode switch failed');
    } finally {
      setModeLoading(false);
    }
  };

  // ── Helpers ──────────────────────────────────────────

  const findAgent = (asset: string, tf: string): GridMatrixCell | undefined => {
    if (!matrixData?.matrix) return undefined;
    return matrixData.matrix[asset]?.[tf];
  };

  const agentStatusColor = (cell: GridMatrixCell) => {
    if (!cell.enabled) return 'bg-gray-500/20 text-gray-400';
    if (cell.running && cell.status === 'active') return 'bg-green-500/20 text-green-400';
    if (cell.status === 'covering') return 'bg-blue-500/20 text-blue-400';
    return 'bg-gray-500/20 text-gray-400';
  };

  const agentStatusLabel = (cell: GridMatrixCell) => {
    if (!cell.enabled) return 'Paused';
    if (cell.status === 'active') return 'Active';
    if (cell.status === 'covering') return 'Watching';
    return 'Idle';
  };

  // ── Loading ──────────────────────────────────────────

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading Kalshi agent grid...</span>
        </div>
      </div>
    );
  }

  const gridRunning = status?.running ?? false;
  const portfolio = status?.portfolio_risk;
  const session = status?.session;
  const venueMode = status?.venue_mode;
  const isLive = venueMode?.is_live ?? false;

  const activeAssets = matrixData?.assets || ASSETS;
  const activeTimeframes = sortTimeframes(matrixData?.timeframes || TIMEFRAMES);

  return (
    <div className="space-y-6">
      <ExecutionGateStrip />

      {/* ── Header ──────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-6 h-6 text-orange-400" />
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">Kalshi Agent Grid <KalshiModeBadge /></h2>
            <p className="text-sm text-gray-400">
              {status?.agent_count ?? 0} agents &middot; {activeAssets.length} assets &middot; {activeTimeframes.length} timeframes
            </p>
          </div>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* Trading mode badge */}
          <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-semibold ${
            isLive ? 'bg-red-500/30 text-red-300 border border-red-500/50' : 'bg-amber-500/20 text-amber-400'
          }`}>
            <Zap className="w-3 h-3" />
            {isLive ? '🔴 LIVE' : '📄 PAPER'}
          </span>

          {/* Session */}
          <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${
            session?.trading_allowed ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
          }`}>
            <Clock className="w-3 h-3" />
            {session?.trading_allowed ? 'Trading Open' : session?.block_reason || 'Closed'}
          </span>

          {/* Grid status */}
          <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${
            gridRunning ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'
          }`}>
            <Activity className="w-3 h-3" />
            Grid: {gridRunning ? 'Running' : 'Stopped'}
          </span>

          {/* Venue Health */}
          {status?.venue_health && (
            <>
              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${
                status.venue_health.connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
              }`}>
                <Activity className="w-3 h-3" />
                Kalshi: {status.venue_health.connected ? 'Connected' : 'Offline'}
              </span>
              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${
                status?.venue_health?.circuit?.state === 'closed' ? 'bg-blue-500/20 text-blue-400' : 'bg-amber-500/20 text-amber-400'
              }`}>
                <Shield className="w-3 h-3" />
                Breaker: {(status?.venue_health?.circuit?.state ?? 'unknown').toUpperCase()}
              </span>
            </>
          )}

          {/* Kill switch */}
          {portfolio?.kill_switch_active && (
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-red-500/20 text-red-400">
              <AlertTriangle className="w-3 h-3" />
              Kill Switch Active
            </span>
          )}
        </div>
      </div>

      {/* ── Controls ────────────────────────────────────── */}
      {actionError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="ml-auto text-red-300 hover:text-red-200"
            aria-label="Dismiss action error"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {/* Mode toggle — always visible */}
        <div className="flex items-center rounded-lg overflow-hidden border border-slate-700">
          <button
            type="button"
            onClick={() => switchMode('paper')}
            disabled={modeLoading || !isLive}
            className={`px-3 py-1.5 text-xs font-medium transition-colors ${
              !isLive ? 'bg-amber-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-white'
            } disabled:opacity-50`}
            title={!isLive ? 'Already in paper mode' : 'Switch to paper mode'}
          >
            Paper
          </button>
          <button
            type="button"
            onClick={() => switchMode('live')}
            disabled={modeLoading || isLive}
            className={`px-3 py-1.5 text-xs font-medium transition-colors ${
              isLive ? 'bg-red-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-red-400'
            } disabled:opacity-50`}
            title={isLive ? 'Already in live mode' : 'Switch to live mode (real money)'}
          >
            Live
          </button>
        </div>

        {!gridRunning ? (
          <button
            type="button"
            onClick={() => postAction(`${API_ENDPOINTS.KALSHI_GRID_START}?mode=${startMode}`)}
            disabled={actionLoading}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-sm text-white rounded-lg transition-colors disabled:opacity-50 ${
              startMode === 'live' ? 'bg-red-700 hover:bg-red-600' : 'bg-green-600 hover:bg-green-500'
            }`}
          >
            <Play className="w-3.5 h-3.5" /> Start Grid {startMode === 'live' ? '(LIVE)' : ''}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => postAction(API_ENDPOINTS.KALSHI_GRID_STOP)}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Square className="w-3.5 h-3.5" /> Stop Grid
          </button>
        )}
        <button
          type="button"
          onClick={() => postAction(API_ENDPOINTS.KALSHI_GRID_PAUSE)}
          disabled={actionLoading || !gridRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-amber-600 hover:bg-amber-500 text-white rounded-lg transition-colors disabled:opacity-50"
        >
          <Pause className="w-3.5 h-3.5" /> Pause All
        </button>
        <button
          type="button"
          onClick={() => postAction(API_ENDPOINTS.KALSHI_GRID_RESUME)}
          disabled={actionLoading || !gridRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors disabled:opacity-50"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Resume All
        </button>
        {portfolio?.kill_switch_active && (
          <button
            type="button"
            onClick={() => { if (window.confirm('Reset Kalshi kill switch and resume trading?')) postAction(API_ENDPOINTS.KALSHI_GRID_KILL_SWITCH_RESET); }}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-red-700 hover:bg-red-600 text-white rounded-lg transition-colors disabled:opacity-50"
            aria-label="Reset Kalshi kill switch"
          >
            <Shield className="w-3.5 h-3.5" /> Reset Kill Switch
          </button>
        )}
        <button
          type="button"
          onClick={fetchStatus}
          className="ml-auto p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh"
          aria-label="Refresh grid status"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* ── Tabs ────────────────────────────────────────── */}
      <div className="flex gap-1 border-b border-slate-800">
        {(['grid', 'health'] as GridTab[]).map(tab => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? 'border-orange-500 text-orange-400'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab === 'health' ? 'Health & Diagnostics' : 'Agent Grid'}
          </button>
        ))}
      </div>

      {/* ── Health Tab ──────────────────────────────────── */}
      {activeTab === 'health' && (
        <div className="space-y-5">
          {/* Issues banner */}
          {gridHealth && gridHealth.issues.length > 0 && (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <h2 className="text-sm font-semibold text-amber-300">Health Issues ({gridHealth.issues.length})</h2>
              </div>
              <ul className="space-y-1">
                {gridHealth.issues.map((issue, i) => (
                  <li key={`${issue}-${i}`} className="text-xs text-amber-300/80 flex items-start gap-2">
                    <span className="text-amber-500 mt-0.5">•</span>{issue}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {gridHealth && gridHealth.issues.length === 0 && (
            <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              <span className="text-sm text-emerald-300 font-medium">All systems healthy</span>
            </div>
          )}

          {/* Catalog + WS + Rate limits */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-4 h-4 text-orange-400" />
                <h3 className="text-sm font-semibold text-white">Market Catalog</h3>
              </div>
              {gridHealth ? (
                <>
                  <p className="text-2xl font-bold text-orange-400 font-mono">{gridHealth.catalog.market_count}</p>
                  <p className="text-xs text-slate-500 mt-1">markets · {gridHealth.catalog.categories} categories</p>
                  {gridHealth.catalog.last_refresh && (
                    <p className="text-[10px] text-slate-600 mt-1">Refreshed {new Date(gridHealth.catalog.last_refresh).toLocaleTimeString()}</p>
                  )}
                </>
              ) : <p className="text-sm text-slate-600">—</p>}
            </div>

            <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Radio className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-semibold text-white">WebSocket Feed</h3>
              </div>
              {gridHealth ? (
                <>
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`w-2 h-2 rounded-full ${gridHealth.ws.running ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
                    <span className={`text-sm font-bold ${gridHealth.ws.running ? 'text-green-400' : 'text-red-400'}`}>
                      {gridHealth.ws.running ? 'LIVE' : 'DOWN'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{gridHealth.ws.subscribed_tickers} tickers subscribed</p>
                  <p className="text-xs text-slate-500 mt-0.5">{(gridHealth.ws.events_forwarded ?? 0).toLocaleString()} events forwarded</p>
                </>
              ) : <p className="text-sm text-slate-600">—</p>}
            </div>

            <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Activity className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-white">Rate Limits</h3>
              </div>
              {gridHealth ? (
                <div className="space-y-2">
                  <div>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-slate-400">Orders/min</span>
                      <span className="text-slate-300 font-mono">{gridHealth.rate_limits.orders_this_minute} / {gridHealth.rate_limits.max_per_minute}</span>
                    </div>
                    <UtilBar value={gridHealth.rate_limits.orders_this_minute} max={gridHealth.rate_limits.max_per_minute} />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-slate-400">Orders/hr</span>
                      <span className="text-slate-300 font-mono">{gridHealth.rate_limits.orders_this_hour} / {gridHealth.rate_limits.max_per_hour}</span>
                    </div>
                    <UtilBar value={gridHealth.rate_limits.orders_this_hour} max={gridHealth.rate_limits.max_per_hour} />
                  </div>
                </div>
              ) : <p className="text-sm text-slate-600">—</p>}
            </div>
          </div>

          {/* Venue connection detail */}
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
            <div className="flex items-center gap-2 mb-3">
              {status?.venue_health?.connected
                ? <Wifi className="w-4 h-4 text-green-400" />
                : <WifiOff className="w-4 h-4 text-red-400" />}
              <h3 className="text-sm font-semibold text-white">Venue Connection</h3>
            </div>
            {status?.venue_health ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                <div>
                  <p className="text-slate-500 mb-1">Status</p>
                  <p className={`font-semibold ${status.venue_health.connected ? 'text-green-400' : 'text-red-400'}`}>
                    {status.venue_health.connected ? 'Connected' : 'Disconnected'}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 mb-1">Circuit Breaker</p>
                  <p className={`font-semibold ${status?.venue_health?.circuit?.state === 'closed' ? 'text-green-400' : 'text-red-400'}`}>
                    {(status?.venue_health?.circuit?.state ?? 'unknown').toUpperCase()}
                  </p>
                  {(status.venue_health?.circuit?.failure_count ?? 0) > 0 && (
                    <p className="text-slate-600">{status.venue_health.circuit.failure_count} failures</p>
                  )}
                </div>
                <div>
                  <p className="text-slate-500 mb-1">Error Rate</p>
                  <p className={`font-semibold font-mono ${(status.venue_health?.error_rate ?? 0) > 0.05 ? 'text-red-400' : 'text-slate-300'}`}>
                    {((status.venue_health?.error_rate ?? 0) * 100).toFixed(2)}%
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 mb-1">Rate Tokens</p>
                  <p className="font-semibold font-mono text-slate-300">
                    R:{(status.venue_health?.rate_limits?.read ?? 0).toFixed(0)} W:{(status.venue_health?.rate_limits?.write ?? 0).toFixed(0)}
                  </p>
                </div>
              </div>
            ) : <p className="text-sm text-slate-600">No venue data</p>}
          </div>

          {/* Per-agent status table */}
          {status?.agents && status.agents.length > 0 && (
            <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
              <div className="p-4 border-b border-slate-800">
                <h3 className="text-sm font-semibold text-white">Agent Status</h3>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500">
                    <th className="text-left px-4 py-2">Agent</th>
                    <th className="text-left px-4 py-2">Status</th>
                    <th className="text-left px-4 py-2">Assets</th>
                    <th className="text-right px-4 py-2">Cycles</th>
                    <th className="text-right px-4 py-2">Orders</th>
                    <th className="text-right px-4 py-2">Fills</th>
                    <th className="text-right px-4 py-2">Last Cycle</th>
                  </tr>
                </thead>
                <tbody>
                  {status.agents.map(agent => {
                    const hasError = !!agent.last_error;
                    const isPaused = status.portfolio_risk?.paused_agents?.includes(agent.name);
                    return (
                      <tr key={agent.name} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                        <td className="px-4 py-2">
                          <div className="flex items-center gap-2">
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              hasError ? 'bg-red-400' : agent.running ? 'bg-green-400 animate-pulse' : !agent.enabled ? 'bg-slate-700' : 'bg-slate-500'
                            }`} />
                            <span className="text-slate-200 font-medium">{agent.name}</span>
                            {isPaused && <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-400 font-bold">PAUSED</span>}
                          </div>
                        </td>
                        <td className="px-4 py-2">
                          <span className={`font-medium ${
                            hasError ? 'text-red-400' : agent.running ? 'text-green-400' : !agent.enabled ? 'text-slate-600' : 'text-slate-400'
                          }`}>
                            {hasError ? 'Error' : agent.running ? 'Running' : !agent.enabled ? 'Disabled' : 'Idle'}
                          </span>
                          {hasError && <p className="text-red-400/70 text-[10px] truncate max-w-[200px]" title={agent.last_error ?? ''}>{agent.last_error}</p>}
                        </td>
                        <td className="px-4 py-2 text-slate-400 font-mono">{agent.config.assets.join(', ')}</td>
                        <td className="px-4 py-2 text-right font-mono text-slate-300">{(agent.cycles_run ?? 0).toLocaleString()}</td>
                        <td className="px-4 py-2 text-right font-mono text-slate-300">{agent.orders_placed}</td>
                        <td className="px-4 py-2 text-right font-mono text-slate-300">{agent.fill_count}</td>
                        <td className="px-4 py-2 text-right text-slate-500">
                          {agent.last_cycle_at ? new Date(agent.last_cycle_at).toLocaleTimeString() : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Grid Tab content (existing) ──────────────────── */}
      {activeTab === 'grid' && <>

      {/* ── Grid Metrics ── */}
      {status?.metrics && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Market Coverage</span>
            <p className="text-xl font-bold text-white mt-1">{(status.metrics?.coverage_pct ?? 0).toFixed(1)}%</p>
            <p className="text-[10px] text-gray-500">{status.metrics.covered_markets} / {status.metrics.active_markets} markets</p>
          </div>
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Total Orders</span>
            <p className="text-xl font-bold text-white mt-1">{status.metrics.total_orders}</p>
            <p className="text-[10px] text-gray-500">{((status.venue_health?.error_rate ?? 0) * 100).toFixed(2)}% error rate</p>
          </div>
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Total Fills</span>
            <p className="text-xl font-bold text-white mt-1">{status.metrics.total_fills}</p>
          </div>
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Rate Limit</span>
            <p className="text-xl font-bold text-white mt-1">{(status.venue_health?.rate_limits?.write ?? 0).toFixed(0)}</p>
            <p className="text-[10px] text-gray-500">Write tokens available</p>
          </div>
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Health Score</span>
            <p className={`text-xl font-bold mt-1 ${status.venue_health?.connected ? 'text-emerald-400' : 'text-rose-400'}`}>
              {status.venue_health?.connected ? '100%' : '0%'}
            </p>
          </div>
        </div>
      )}

      {/* ── Portfolio Risk Card ─────────────────────────── */}
      {portfolio && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Daily P&L</span>
            <p className={`text-xl font-bold mt-1 ${
              (portfolio.daily_pnl_usd ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}>
              {(portfolio.daily_pnl_usd ?? 0) >= 0 ? '+' : ''}${(portfolio.daily_pnl_usd ?? 0).toFixed(2)}
            </p>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Total Notional</span>
            <p className="text-xl font-bold text-white mt-1">${(portfolio.total_notional_usd ?? 0).toFixed(2)}</p>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Margin Util</span>
            <p className="text-xl font-bold text-white mt-1">{((portfolio.margin_utilization ?? 0) * 100).toFixed(1)}%</p>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <span className="text-xs text-gray-400 uppercase tracking-wider">Paused Agents</span>
            <p className="text-xl font-bold text-white mt-1">{(portfolio.paused_agents ?? []).length}</p>
          </div>
        </div>
      )}

      {/* ── Agent Grid Matrix ───────────────────────────── */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700">
              <th className="text-left text-xs text-gray-400 uppercase tracking-wider p-3 w-20">Asset</th>
              {activeTimeframes.map(tf => (
                <th key={tf} className="text-center text-xs text-gray-400 uppercase tracking-wider p-3">
                  {TF_LABELS[tf as keyof typeof TF_LABELS] || tf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activeAssets.map(asset => (
              <tr key={asset} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                <td className="p-3 font-semibold text-white">{asset}</td>
                {activeTimeframes.map(tf => {
                  const cell = findAgent(asset, tf);
                  if (!cell) {
                    return (
                      <td key={tf} className="p-3 text-center">
                        <span className="text-xs text-gray-600">—</span>
                      </td>
                    );
                  }
                  return (
                    <td key={tf} className="p-2">
                      <button
                        type="button"
                        onClick={() => setSelectedAgent(cell.agent)}
                        className={`w-full p-2 rounded-lg border transition-colors text-left ${
                          selectedAgent === cell.agent
                            ? 'bg-blue-600/20 border-blue-500/50'
                            : 'bg-slate-800/50 border-slate-700/50 hover:border-slate-600'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${agentStatusColor(cell)}`}>
                            {agentStatusLabel(cell)}
                          </span>
                          <ChevronRight className="w-3 h-3 text-gray-500" />
                        </div>
                        <div className="flex items-center gap-2 text-xs text-gray-400">
                          <span>{cell.cycles}c</span>
                          <span>{cell.orders}o</span>
                        </div>
                        {cell.active_tickers && cell.active_tickers.length > 0 && (
                          <div className="text-[10px] text-gray-500 mt-1 truncate">
                            {cell.active_tickers[0]}
                          </div>
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Agent Detail Panel ──────────────────────────── */}
      {selectedAgent && (() => {
        const agent = status?.agents?.find(a => a.name === selectedAgent);
        if (!agent) return null;
        return (
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white">{agent.name}</h3>
                <p className="text-sm text-gray-400">
                  {agent.config.assets.join(', ')} &middot; {agent.config.timeframes.join(', ')}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => postAction(
                    agent.enabled
                      ? API_ENDPOINTS.KALSHI_GRID_AGENT_PAUSE(agent.name)
                      : API_ENDPOINTS.KALSHI_GRID_AGENT_RESUME(agent.name)
                  )}
                  className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg transition-colors ${
                    agent.enabled
                      ? 'bg-amber-600/20 text-amber-400 hover:bg-amber-600/30'
                      : 'bg-green-600/20 text-green-400 hover:bg-green-600/30'
                  }`}
                >
                  {agent.enabled ? <><Pause className="w-3 h-3" /> Pause</> : <><Play className="w-3 h-3" /> Resume</>}
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedAgent(null)}
                  className="p-1 rounded hover:bg-slate-700 text-gray-400"
                  aria-label="Close agent detail"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Agent stats */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div className="text-center">
                <span className="text-xs text-gray-400">Cycles</span>
                <p className="text-sm font-semibold text-white">{agent.cycles_run}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Orders</span>
                <p className="text-sm font-semibold text-white">{agent.orders_placed}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Fills</span>
                <p className="text-sm font-semibold text-white">{agent.fill_count}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Signals</span>
                <p className="text-sm font-semibold text-white">{agent.signal_count}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Max Notional</span>
                <p className="text-sm font-semibold text-white">${agent.config.risk_limits.max_notional_usd}</p>
              </div>
            </div>

            {/* Active tickers */}
            {agent.active_tickers.length > 0 && (
              <div>
                <h4 className="text-xs text-gray-400 uppercase tracking-wider mb-2">Active Tickers</h4>
                <div className="flex flex-wrap gap-1.5">
                  {agent.active_tickers.map(t => (
                    <span key={t} className="text-xs px-2 py-0.5 bg-slate-800 text-gray-300 rounded">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Last error */}
            {agent.last_error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                <span className="text-xs text-red-400">{agent.last_error}</span>
              </div>
            )}

            {/* Recent Signals */}
            {agentSignals.length > 0 && (
              <div>
                <h4 className="text-xs text-gray-400 uppercase tracking-wider mb-2">Recent Signals</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-slate-700">
                        <th className="text-left p-2">Time</th>
                        <th className="text-left p-2">Market</th>
                        <th className="text-left p-2">Action</th>
                        <th className="text-right p-2">Edge</th>
                        <th className="text-right p-2">Conf</th>
                        <th className="text-right p-2">Contracts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agentSignals.slice(-10).reverse().map((s) => (
                        <tr key={`${s.ts}-${s.market_id}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-2 text-gray-400">{new Date(s.ts).toLocaleTimeString()}</td>
                          <td className="p-2 text-gray-300 truncate max-w-[200px]" title={s.market_id}>{s.market_id}</td>
                          <td className="p-2">
                            <span className={`px-1.5 py-0.5 rounded ${
                              s.action.includes('BUY') ? 'bg-green-500/20 text-green-400' :
                              s.action.includes('SELL') ? 'bg-red-500/20 text-red-400' :
                              'bg-gray-500/20 text-gray-400'
                            }`}>
                              {s.action}
                            </span>
                          </td>
                          <td className={`p-2 text-right font-mono ${
                            (s.edge ?? 0) > 0 ? 'text-green-400' : (s.edge ?? 0) < 0 ? 'text-red-400' : 'text-gray-400'
                          }`}>
                            {s.edge != null ? `${s.edge > 0 ? '+' : ''}${(s.edge * 100).toFixed(1)}%` : '—'}
                          </td>
                          <td className="p-2 text-right font-mono text-gray-300">
                            {s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : '—'}
                          </td>
                          <td className="p-2 text-right text-gray-300">{s.contracts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Recent Orders */}
            {agentOrders.length > 0 && (
              <div>
                <h4 className="text-xs text-gray-400 uppercase tracking-wider mb-2">Recent Orders</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-slate-700">
                        <th className="text-left p-2">Time</th>
                        <th className="text-left p-2">Market</th>
                        <th className="text-left p-2">Side</th>
                        <th className="text-right p-2">Price</th>
                        <th className="text-right p-2">Qty</th>
                        <th className="text-right p-2">Ref Mid</th>
                        <th className="text-center p-2">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agentOrders.slice(-10).reverse().map((o) => (
                        <tr key={`${o.ts}-${o.market_id}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-2 text-gray-400">{new Date(o.ts).toLocaleTimeString()}</td>
                          <td className="p-2 text-gray-300 truncate max-w-[200px]" title={o.market_id}>{o.market_id}</td>
                          <td className="p-2">
                            <span className={`px-1.5 py-0.5 rounded ${
                              o.action === 'buy' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                            }`}>
                              {o.action.toUpperCase()} {o.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="p-2 text-right font-mono text-gray-300">{o.price_cents}¢</td>
                          <td className="p-2 text-right text-gray-300">{o.contracts}</td>
                          <td className="p-2 text-right font-mono text-gray-400">
                            {o.ref_mid != null ? `${o.ref_mid.toFixed(1)}¢` : '—'}
                          </td>
                          <td className="p-2 text-center">
                            {o.success ? (
                              <span className="text-green-400">{o.simulated ? 'SIM' : 'FILLED'}</span>
                            ) : (
                              <span className="text-red-400" title={o.error || ''}>FAILED</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── Paper Trading Ladder ─────────────────────────── */}
      <PaperLadderCard />

      {/* ── Recent Fills (all agents) ───────────────────── */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Recent Fills</h3>
          <span className="text-xs text-gray-500">{fills.length} fills</span>
        </div>
        {fills.length === 0 ? (
          <p className="text-sm text-gray-500 text-center py-4">No fills yet — start the grid to begin paper trading</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-slate-700">
                  <th className="text-left p-2">Time</th>
                  <th className="text-left p-2">Agent</th>
                  <th className="text-left p-2">Market</th>
                  <th className="text-left p-2">Side</th>
                  <th className="text-right p-2">Price</th>
                  <th className="text-right p-2">Qty</th>
                  <th className="text-center p-2">Mode</th>
                </tr>
              </thead>
              <tbody>
                {fills.slice(0, 20).map((f) => (
                  <tr key={`${f.ts}-${f.agent}-${f.market_id}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-2 text-gray-400">{new Date(f.ts).toLocaleTimeString()}</td>
                    <td className="p-2 text-gray-300">{f.agent}</td>
                    <td className="p-2 text-gray-300 truncate max-w-[200px]" title={f.market_id}>{f.market_id}</td>
                    <td className="p-2">
                      <span className={`px-1.5 py-0.5 rounded ${
                        f.action === 'buy' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                      }`}>
                        {f.action.toUpperCase()} {f.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono text-gray-300">{f.price_cents}¢</td>
                    <td className="p-2 text-right text-gray-300">{f.contracts}</td>
                    <td className="p-2 text-center">
                      <span className={f.simulated ? 'text-amber-400' : 'text-green-400'}>
                        {f.simulated ? 'SIM' : 'PAPER'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      </> }
    </div>
  );
}
