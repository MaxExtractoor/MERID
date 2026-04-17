/**
 * KalshiTerminalView — Operator-grade live trading terminal for Kalshi.
 *
 * Layout:
 *   Top:    ExecutionGateStrip + account/risk bar (kill-switch, balance, PnL, drawdown, positions, orders)
 *   Left:   Market browser (search/filter/sort) + selected market detail + orderbook
 *   Right:  Trade ticket (live mode) + ALL open orders with cancel + fills + global agent activity
 */

import {
  Search, RefreshCw, X, DollarSign,
  TrendingUp, Shield,
  ShieldAlert, ShieldCheck, Filter,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY} from '../config/constants';
import type { KalshiBalance, KalshiPosition, KalshiOrder, KalshiFill, KalshiRiskSummary, CatalogMarket, SizingMetrics } from '../types/kalshi';
import { useState, useCallback, useMemo, useEffect } from 'react';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
import KalshiOrderbookPanel from '../components/KalshiOrderbookPanel';
import KalshiActivityLog from '../components/KalshiActivityLog';
import KalshiModeBadge from '../components/KalshiModeBadge';
import KalshiBankrollPanel from '../components/KalshiBankrollPanel';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';
import CryptoSpotKalshiPanel from '../components/CryptoSpotKalshiPanel';
import SwarmSentimentGrid from '../components/SwarmSentimentGrid';
import SentimentPnLStrip from '../components/SentimentPnLStrip';
import MarketSwarmConsensusBar from '../components/MarketSwarmConsensusBar';
import { formatFillPriceCentsLabel } from '../utils/kalshiFillPrice';

/* ══════════════════════════════════════════════════════════════════
   Types
   ══════════════════════════════════════════════════════════════════ */

interface TerminalEdgeSignal {
  implied_prob: number;
  model_prob: number;
  ev_cents: number;
  edge_pct: number;
  confidence: number;
  confidence_bucket: 'low' | 'medium' | 'high';
  sizing_tier: 'normal' | 'reduced' | 'boosted' | 'halted';
}

interface TerminalEdgeResponse {
  signals: Record<string, TerminalEdgeSignal>;
  count: number;
  kelly_fraction: number;
  effective_fraction: number;
}

interface CatalogResponse {
  categories: Record<string, number>;
}

interface KillSwitchState {
  kill_switch_active: boolean;  // canonical
  active?: boolean;             // compat alias
  reason: string | null;
  can_trade: boolean;
}

/* ══════════════════════════════════════════════════════════════════
   Constants
   ══════════════════════════════════════════════════════════════════ */

const CAT_COLOR: Record<string, string> = {
  crypto: 'text-orange-400 bg-orange-400/10',
  economics: 'text-blue-400 bg-blue-400/10',
  financials: 'text-emerald-400 bg-emerald-400/10',
  politics: 'text-red-400 bg-red-400/10',
  climate: 'text-teal-400 bg-teal-400/10',
  sports: 'text-green-400 bg-green-400/10',
  tech: 'text-violet-400 bg-violet-400/10',
  culture: 'text-pink-400 bg-pink-400/10',
  science: 'text-cyan-400 bg-cyan-400/10',
  fed: 'text-yellow-400 bg-yellow-400/10',
  inflation: 'text-amber-400 bg-amber-400/10',
  rates: 'text-indigo-400 bg-indigo-400/10',
  weather: 'text-sky-400 bg-sky-400/10',
};

type SortKey = 'volume' | 'expiry' | 'edge' | 'position';
type RightTab = 'orders' | 'fills' | 'agents';

/* ══════════════════════════════════════════════════════════════════
   Component
   ══════════════════════════════════════════════════════════════════ */

export default function KalshiTerminalView() {
  // ── State ──
  const [selectedMarket, setSelectedMarket] = useState<CatalogMarket | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('volume');
  const [rightTab, setRightTab] = useState<RightTab>('orders');
  const [posOnly, setPosOnly] = useState(false);
  const [cancellingAll, setCancellingAll] = useState(false);
  const [cancellingOrder, setCancellingOrder] = useState<string | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);

  // ── API Hooks ──
  const fast = { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH };
  const std  = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const slow = { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW };

  const ksResult    = useApiData<KillSwitchState>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, fast);
  const { alerts } = useKalshiRiskStream();
  const killSwitchAlert = alerts.find(a => a.type === 'kill_switch' && a.level === 'critical');
  const hasKillSwitch = !!killSwitchAlert;
  const [, setToast] = useState<{ message: string; level: string } | null>(null);
  const venueModeResult = useApiData<{ mode: string; is_live: boolean }>(API_ENDPOINTS.KALSHI_GRID_MODE, std);
  const venueMode: 'paper' | 'live' = (venueModeResult.data?.mode ?? 'paper').toLowerCase().includes('paper') ? 'paper' : 'live';
  const mktsResult  = useApiData<{ markets: CatalogMarket[]; count: number }>(API_ENDPOINTS.KALSHI_MARKETS, slow);
  const orderErrorsResult = useApiData<{ errors: Array<{ id: string; message: string; severity: string; timestamp: string }> }>(API_ENDPOINTS.KALSHI_ORDER_ERRORS, std);

  // ── Grouped Alerts ──
  const groupedAlerts = useMemo(() => {
    const groups: Record<string, { message: string; level: string; count: number; lastAt: string }> = {};
    alerts.forEach(a => {
      const key = `${a.level}:${a.message}`;
      if (!groups[key]) {
        groups[key] = { message: a.message, level: a.level, count: 0, lastAt: a.timestamp ?? new Date().toISOString() };
      }
      groups[key].count++;
      if (a.timestamp && a.timestamp > groups[key].lastAt) {
        groups[key].lastAt = a.timestamp;
      }
    });
    return Object.values(groups).sort((a, b) => {
      // Sort by severity then by count
      const levelOrder = { critical: 0, warning: 1, info: 2 };
      const aLevel = levelOrder[a.level as keyof typeof levelOrder] ?? 3;
      const bLevel = levelOrder[b.level as keyof typeof levelOrder] ?? 3;
      if (aLevel !== bLevel) return aLevel - bLevel;
      return b.count - a.count;
    });
  }, [alerts]);

  useEffect(() => {
    const criticalAlerts = alerts.filter(a => a.level === 'critical');
    if (criticalAlerts.length > 0) {
      const latest = criticalAlerts[criticalAlerts.length - 1];
      setToast({ message: latest.message, level: latest.level });
      const timer = setTimeout(() => setToast(null), 5000); // Hide after 5s
      return () => clearTimeout(timer);
    } else {
      setToast(null);
    }
  }, [alerts]);

  // ── Kill Switch Handler ──
  const handleKillSwitch = useCallback(async () => {
    const ks = ksResult?.data;
    const ksActive = ks?.kill_switch_active ?? ks?.active ?? false;
    
    if (!ksActive) {
      const confirmed = window.confirm('⚠️ EMERGENCY KILL SWITCH\n\nThis will immediately halt all trading activity and cancel all orders.\n\nAre you sure you want to continue?');
      if (!confirmed) return;
      
      try {
        const token = localStorage.getItem(AUTH_TOKEN_KEY);
        const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_KILL_SWITCH('enable')}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
          },
          body: JSON.stringify({ reason: 'Manual operator kill switch from Terminal view' }),
        });
        if (!response.ok) throw new Error('Failed to activate kill switch');
        // Refetch will happen automatically via polling
      } catch (err) {
        setOrderError(err instanceof Error ? err.message : 'Failed to activate kill switch');
      }
    } else {
      try {
        const token = localStorage.getItem(AUTH_TOKEN_KEY);
        const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_KILL_SWITCH('disable')}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
          },
          body: JSON.stringify({ reason: 'Manual operator reset from Terminal view' }),
        });
        if (!response.ok) throw new Error('Failed to deactivate kill switch');
        // Refetch will happen automatically via polling
      } catch (err) {
        setOrderError(err instanceof Error ? err.message : 'Failed to deactivate kill switch');
      }
    }
  }, [ksResult?.data]);

  // ── Keyboard Shortcut ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+K for emergency kill switch
      if (e.ctrlKey && e.shiftKey && e.key === 'K') {
        e.preventDefault();
        handleKillSwitch();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKillSwitch]);

  // ── Data ──
  const catResult   = useApiData<CatalogResponse>(API_ENDPOINTS.KALSHI_CATALOG, slow);
  const balResult   = useApiData<KalshiBalance>(API_ENDPOINTS.KALSHI_BALANCE, std);
  const riskResult  = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, std);
  const posResult   = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, std);
  const ordResult   = useApiData<{ orders: KalshiOrder[]; venue_order_ids?: string[] }>(API_ENDPOINTS.KALSHI_ORDERS, std);
  const fillResult  = useApiData<{ fills: KalshiFill[]; meta?: { response_at?: string; source?: string } }>(API_ENDPOINTS.KALSHI_FILLS, std);
  const edgeResult  = useApiData<TerminalEdgeResponse>(API_ENDPOINTS.KALSHI_EDGE, slow);
  const sizingResult = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, slow);
  // Add reconciliation status fetch
  const reconciliationResult = useApiData<{
    status: 'ok' | 'degraded' | 'broken' | 'unknown';
    last_run: string | null;
    message?: string | null;
    divergence_count?: number;
    divergences?: unknown[];
    ghost_trade_candidates?: unknown[];
    ledger?: { total_fills: number; total_contracts: number };
    timestamp?: string;
  }>(API_ENDPOINTS.KALSHI_HEALTH + '/reconciliation', { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW });

  // Derive event ticker from selected market (e.g. "KXBTC-25JAN1234" -> "KXBTC")
  const eventTicker = useMemo(() => {
    if (!selectedMarket) return '';
    return selectedMarket.ticker.split('-')[0] ?? '';
  }, [selectedMarket]);
  const eventResult = useApiData<{ event_ticker: string; market_count: number; markets: { ticker: string; question: string; category: string; asset: string; volume: number; active: boolean }[] }>(
    eventTicker ? API_ENDPOINTS.KALSHI_EVENT(eventTicker) : '',
    { pollingInterval: eventTicker ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 }
  );

  // ── Derived ──
  const ks        = ksResult.data;
  const markets   = useMemo(() => mktsResult.data?.markets ?? [], [mktsResult.data]);
  const categories = useMemo(() => catResult.data?.categories ? Object.keys(catResult.data.categories) : [], [catResult.data]);
  const balance   = balResult.data;
  const risk      = riskResult.data;
  const positions = useMemo(() => posResult.data?.positions ?? [], [posResult.data]);
  const orders    = useMemo(() => ordResult.data?.orders ?? [], [ordResult.data]);
  const fills     = useMemo(() => fillResult.data?.fills ?? [], [fillResult.data]);
  const fillsStale = useMemo(() => {
    if (!fillResult.lastUpdated) return false;
    return Date.now() - fillResult.lastUpdated.getTime() > 90_000;
  }, [fillResult.lastUpdated]);
  const sizing    = sizingResult.data;
  const orderErrorCount = orderErrorsResult.data?.errors?.length ?? 0;

  const posTickerSet = useMemo(() => new Set(positions.map(p => p.ticker)), [positions]);

  const filteredMarkets = useMemo(() => {
    let result = markets;
    if (posOnly) result = result.filter(m => posTickerSet.has(m.ticker));
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(m =>
        m.ticker.toLowerCase().includes(q) ||
        m.question.toLowerCase().includes(q) ||
        (m.asset && m.asset.toLowerCase().includes(q))
      );
    }
    if (filterCategory) result = result.filter(m => m.category === filterCategory);
    if (sortKey === 'volume') {
      result = [...result].sort((a, b) => b.volume - a.volume);
    } else if (sortKey === 'expiry') {
      result = [...result].sort((a, b) => (a.minutes_to_expiry ?? 99999) - (b.minutes_to_expiry ?? 99999));
    } else if (sortKey === 'edge') {
      const sigs = edgeResult.data?.signals ?? {};
      result = [...result].sort((a, b) => Math.abs(sigs[b.ticker]?.ev_cents ?? 0) - Math.abs(sigs[a.ticker]?.ev_cents ?? 0));
    } else if (sortKey === 'position') {
      result = [...result].sort((a, b) => (posTickerSet.has(b.ticker) ? 1 : 0) - (posTickerSet.has(a.ticker) ? 1 : 0));
    }
    return result;
  }, [markets, posOnly, searchQuery, filterCategory, sortKey, edgeResult.data, posTickerSet]);

  const selectedPosition = useMemo(() =>
    selectedMarket ? (positions.find(p => p.ticker === selectedMarket.ticker) ?? null) : null
  , [selectedMarket, positions]);

  const selectedEdge = useMemo(() =>
    selectedMarket ? (edgeResult.data?.signals?.[selectedMarket.ticker] ?? null) : null
  , [selectedMarket, edgeResult.data]);

  const kellySuggestion = useMemo(() => {
    if (!selectedEdge || !sizing || !selectedMarket) return null;
    if (selectedEdge.ev_cents <= 0 || selectedEdge.confidence < 0.3) return null;
    const bankroll = balance?.available ?? 100;
    const kellyBet = sizing.effective_fraction * selectedEdge.confidence * bankroll;
    const priceCents = (selectedMarket.outcomes[0]?.price ?? 0.5) * 100;
    const suggestedSide: 'yes' | 'no' = selectedEdge.model_prob > selectedEdge.implied_prob ? 'yes' : 'no';
    return { contracts: Math.max(1, Math.floor(kellyBet / (priceCents / 100))), side: suggestedSide };
  }, [selectedEdge, sizing, selectedMarket, balance]);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  // ── Handlers ──
  // UI-009 fix: extract stable refetch refs for useCallback deps
  const ordRefetch = ordResult.refetch;
  const mktsRefetch = mktsResult.refetch;
  const balRefetch = balResult.refetch;
  const riskRefetch = riskResult.refetch;
  const posRefetch = posResult.refetch;
  const fillRefetch = fillResult.refetch;

  const handleCancelOrder = useCallback(async (orderId: string) => {
    setCancellingOrder(orderId);
    setOrderError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_CANCEL(orderId)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Cancel failed: HTTP ${res.status}`);
      }
      ordRefetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : `Cancel order ${orderId} failed`);
    }
    setCancellingOrder(null);
  }, [authHeaders, ordRefetch]);

  const handleCancelAll = useCallback(async () => {
    if (!window.confirm(`Cancel ALL ${orders.length} open orders?`)) return;
    setCancellingAll(true);
    setOrderError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS_BATCH_CANCEL}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Batch cancel failed: HTTP ${res.status}`);
      }
      ordRefetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : 'Batch cancel failed');
    }
    setCancellingAll(false);
  }, [authHeaders, orders.length, ordRefetch]);

  const refreshAll = useCallback(() => {
    mktsRefetch(); balRefetch(); riskRefetch();
    posRefetch(); ordRefetch(); fillRefetch();
  }, [mktsRefetch, balRefetch, riskRefetch, posRefetch, ordRefetch, fillRefetch]);

  const handleReconcileNow = useCallback(async () => {
    setReconcileBusy(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FILLS}/reconcile-now`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`reconcile-now HTTP ${res.status}`);
      await fillRefetch();
      await posRefetch();
    } catch (e) {
      console.warn('[KalshiTerminal] reconcile-now failed', e);
    } finally {
      setReconcileBusy(false);
    }
  }, [authHeaders, fillRefetch, posRefetch]);

  /* ════════════════════════════════════════════════════════════════
     Render
     ════════════════════════════════════════════════════════════════ */

  const ksActive     = ks?.kill_switch_active ?? ks?.active ?? false;
  const drawdownHalt = sizing?.drawdown_tier === 'halt';

  return (
    <div className="flex flex-col h-full gap-2">

      {/* ── CONTINUOUS TRADER BANKROLL ── */}
      <div className="shrink-0">
        <KalshiBankrollPanel />
      </div>

      {/* ── EXECUTION GATE + RISK BANNER ── */}
      <div className="shrink-0 space-y-2">
        <ExecutionGateStrip />

        {/* ── RECONCILIATION STATUS ── */}
        {reconciliationResult.data?.status && reconciliationResult.data.status !== 'ok' && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${
            reconciliationResult.data.status === 'broken' 
              ? 'bg-red-500/10 border border-red-500/30 text-red-400' 
              : 'bg-yellow-500/10 border border-yellow-500/30 text-yellow-400'
          }`}>
            <ShieldAlert className="w-4 h-4 shrink-0" />
            <span>Reconciliation {reconciliationResult.data.status} — {reconciliationResult.data.message || 'Positions may not match fills'}</span>
          </div>
        )}

        {/* ── GROUPED ALERTS ── */}
        {groupedAlerts.length > 0 && (
          <div className="space-y-1">
            {groupedAlerts.slice(0, 5).map((alert, i) => (
              <div key={i} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs ${
                alert.level === 'critical' ? 'bg-red-500/10 border border-red-500/30 text-red-400' :
                alert.level === 'warning' ? 'bg-yellow-500/10 border border-yellow-500/30 text-yellow-400' :
                'bg-slate-800 border border-slate-700 text-gray-400'
              }`}>
                {alert.level === 'critical' ? <ShieldAlert className="w-3 h-3 shrink-0" /> : <Shield className="w-3 h-3 shrink-0" />}
                <span className="flex-1">{alert.message}</span>
                {alert.count > 1 && (
                  <span className="px-1.5 py-0.5 rounded bg-slate-700 text-[10px] font-mono">×{alert.count}</span>
                )}
              </div>
            ))}
            {groupedAlerts.length > 5 && (
              <div className="text-[10px] text-gray-500 pl-2">+{groupedAlerts.length - 5} more alerts</div>
            )}
          </div>
        )}

        {orderError && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
            <ShieldAlert className="w-4 h-4 shrink-0" />
            <span>{orderError}</span>
            <button type="button" onClick={() => setOrderError(null)} className="ml-auto text-red-400 hover:text-red-300" title="Dismiss" aria-label="Dismiss error">×</button>
          </div>
        )}

        {(ksActive || drawdownHalt) && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border bg-red-950/40 border-red-500/50 text-red-400">
            <ShieldAlert className="w-4 h-4 shrink-0 animate-pulse" />
            <span className="text-sm font-bold uppercase tracking-wide">
              {ksActive
                ? `TRADING HALTED — Kill switch active${ks?.reason ? ': ' + ks.reason : ''}`
                : 'TRADING HALTED — Drawdown limit reached'}
            </span>
          </div>
        )}

        {hasKillSwitch && killSwitchAlert && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border bg-red-950/40 border-red-500/50 text-red-400 animate-pulse">
            <ShieldAlert className="w-4 h-4 shrink-0" />
            <span className="text-sm font-bold uppercase tracking-wide">
              LIVE ALERT: {killSwitchAlert.message}
            </span>
          </div>
        )}

        {/* ── SPOT vs KALSHI ── */}
        <CryptoSpotKalshiPanel />

        <SwarmSentimentGrid />

        <SentimentPnLStrip />

        {/* ── ACCOUNT BAR ── */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-2 bg-slate-900 rounded-xl border border-slate-800 text-xs">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-bold text-white">Terminal</h1>
            <KalshiModeBadge />
          </div>
          <div className="w-px h-4 bg-slate-700" />

          <button
            type="button"
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full font-semibold cursor-pointer transition-colors ${
              ksActive
                ? 'bg-red-500/20 text-red-400 border border-red-500/40 hover:bg-red-500/30'
                : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20'
            }`}
            onClick={handleKillSwitch}
            title={`Kill Switch (Ctrl+Shift+K) - Currently ${ksActive ? 'ACTIVE' : 'INACTIVE'}. Click to ${ksActive ? 'deactivate' : 'activate'}.`}
          >
            {ksActive ? <ShieldAlert className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
            <span>{ksActive ? 'HALTED' : 'LIVE'}</span>
          </button>
          {/* Sizing Context — intentionally outside kill switch click target (UI-001 fix) */}
          <div className="bg-slate-900/60 rounded-lg p-3 space-y-2">
            <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Sizing Context</h4>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Kelly:</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono text-slate-200">{(sizing?.kelly_fraction ?? 0).toFixed(3)}</span>
                  {sizing && sizing.effective_fraction < sizing.kelly_fraction && (
                    <span className="px-1 py-0.5 bg-red-500/20 text-red-400 text-[9px] font-bold rounded">CLAMPED</span>
                  )}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Eff Risk:</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono text-slate-200">{(sizing?.effective_fraction ?? 0).toFixed(3)}</span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Vol Scale:</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono text-slate-200">{(sizing?.vol_scale ?? 1.0).toFixed(2)}</span>
                  {sizing && sizing.vol_scale < 1.0 && (
                    <span className="px-1 py-0.5 bg-orange-500/20 text-orange-400 text-[9px] font-bold rounded">VOL CLAMP</span>
                  )}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">ATR Scale:</span>
                <div className="flex items-center gap-1">
                  <span className="font-mono text-slate-200">{(sizing?.atr_fraction ?? 0).toFixed(3)}</span>
                  {sizing && sizing.atr_fraction < 1.0 && sizing.atr_fraction > 0 && (
                    <span className="px-1 py-0.5 bg-yellow-500/20 text-yellow-400 text-[9px] font-bold rounded">ATR CLAMP</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-700">
              <span className="text-slate-400">DD Tier:</span>
              <div className="flex items-center gap-1">
                <span className={`font-semibold ${
                  sizing?.drawdown_tier === 'halt' ? 'text-red-400' :
                  sizing?.drawdown_tier === 'downsize' ? 'text-orange-400' :
                  sizing?.drawdown_tier === 'warning' ? 'text-yellow-400' : 'text-green-400'
                }`}>
                  {sizing?.drawdown_tier?.toUpperCase() ?? 'NORMAL'}
                </span>
                {sizing && sizing.drawdown_tier !== 'normal' && (
                  <span className="px-1 py-0.5 bg-red-500/20 text-red-400 text-[9px] font-bold rounded">DD CLAMP</span>
                )}
              </div>
            </div>
          </div>
          <div className="w-px h-4 bg-slate-700" />

          {orderErrorCount > 0 && (
            <>
              <div className="flex items-center gap-1 text-xs text-red-400">
                <ShieldAlert className="w-3 h-3" />
                <span>{orderErrorCount} order error{orderErrorCount !== 1 ? 's' : ''}</span>
              </div>
              <div className="w-px h-4 bg-slate-700" />
            </>
          )}

          <div className="flex items-center gap-1">
            <DollarSign className="w-3 h-3 text-green-400" />
            <span className="text-gray-400">Avail:</span>
            <span className="font-mono text-white">${balance?.available?.toFixed(2) ?? '—'}</span>
          </div>
          {(balance?.locked ?? 0) > 0 && (
            <span className="text-gray-500 font-mono">Locked: ${(balance?.locked ?? 0).toFixed(2)}</span>
          )}
          <div className="w-px h-4 bg-slate-700" />

          <div className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-blue-400" />
            <span className={`font-mono font-semibold ${(risk?.daily_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {(risk?.daily_pnl_usd ?? 0) >= 0 ? '+' : ''}${(risk?.daily_pnl_usd ?? 0).toFixed(2)}
            </span>
          </div>
          {risk && (
            <span className={`font-mono ${risk.drawdown_pct > 5 ? 'text-orange-400' : 'text-gray-500'}`}>
              DD:{(risk.drawdown_pct ?? 0).toFixed(1)}%
            </span>
          )}
          <div className="w-px h-4 bg-slate-700" />

          <span className="font-mono text-white">{positions.length}<span className="text-gray-500"> pos</span></span>
          <span className="font-mono text-white">{orders.length}<span className="text-gray-500"> ord</span></span>
          <span className="font-mono text-white">{fills.length}<span className="text-gray-500"> fills</span></span>
          {sizing && (
            <span className={`font-mono ${sizing.kelly_utilization_pct > 80 ? 'text-amber-400' : 'text-gray-400'}`}>
              Kelly:{(sizing.kelly_fraction ?? 0).toFixed(2)}
            </span>
          )}

          <button type="button" onClick={refreshAll} className="ml-auto p-1 rounded hover:bg-slate-800 text-gray-500 hover:text-white" aria-label="Refresh">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── MAIN AREA ── */}
      <div className="flex flex-1 gap-3 min-h-0">

        {/* ══ LEFT: Market Browser ══ */}
        <div className="flex flex-col w-[55%] min-h-0 gap-2">

          {/* Controls */}
          <div className="flex items-center gap-1.5 shrink-0">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-500" />
              <input
                aria-label="Search markets"
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Ticker / keyword…"
                className="w-full pl-8 pr-7 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-white placeholder-gray-600 focus:border-orange-500 focus:outline-none"
              />
              {searchQuery && (
                <button type="button" onClick={() => setSearchQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white" aria-label="Clear">
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
            <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-gray-300 focus:border-orange-500 focus:outline-none" aria-label="Category">
              <option value="">All</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={sortKey} onChange={e => setSortKey(e.target.value as SortKey)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-gray-300 focus:border-orange-500 focus:outline-none" aria-label="Sort">
              <option value="volume">Vol</option>
              <option value="expiry">Expiry</option>
              <option value="edge">Edge</option>
              <option value="position">My Pos</option>
            </select>
            <button type="button" onClick={() => setPosOnly(v => !v)}
              className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs border transition-colors ${posOnly ? 'bg-purple-500/20 border-purple-500/40 text-purple-300' : 'bg-slate-800 border-slate-700 text-gray-500 hover:text-gray-300'}`}
              title="My positions only">
              <Filter className="w-3 h-3" />{posOnly && <span>Pos</span>}
            </button>
          </div>

          {/* Market list */}
          <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
            {filteredMarkets.length === 0 ? (
              <div className="flex items-center justify-center h-24 text-xs text-gray-600">
                {mktsResult.loading ? 'Loading…' : posOnly ? 'No positions' : 'No markets'}
              </div>
            ) : filteredMarkets.map(m => {
              const isSelected = selectedMarket?.ticker === m.ticker;
              const sig        = edgeResult.data?.signals?.[m.ticker];
              const pos        = positions.find(p => p.ticker === m.ticker);
              const yesPrice   = m.outcomes[0]?.price;
              const hasPosOrders = orders.some(o => o.ticker === m.ticker);

              return (
                <button type="button" key={m.ticker} onClick={() => setSelectedMarket(m)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg transition-all ${
                    isSelected ? 'bg-orange-500/10 border border-orange-500/40'
                      : 'bg-slate-900/60 border border-slate-800 hover:border-slate-600'
                  }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className={`text-xs font-medium truncate ${isSelected ? 'text-white' : 'text-gray-300'}`}>
                        {m.question}
                      </p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[10px] font-mono text-gray-600">{m.ticker}</span>
                        {m.category && (
                          <span className={`text-[10px] px-1 py-0.5 rounded ${CAT_COLOR[m.category] ?? 'text-gray-400 bg-slate-800'}`}>
                            {m.category}
                          </span>
                        )}
                        {pos && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-purple-500/15 text-purple-300 font-semibold">
                            {pos.asset ? `${pos.asset} · ` : ''}{pos.size} {pos.outcome}
                          </span>
                        )}
                        {hasPosOrders && !pos && (
                          <span className="text-[10px] text-blue-400">ord</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      {yesPrice != null && (
                        <span className={`text-sm font-bold font-mono ${yesPrice >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                          {((yesPrice ?? 0) * 100).toFixed(0)}¢
                        </span>
                      )}
                      <div className="flex items-center justify-end gap-1 mt-0.5">
                        <span className="text-[10px] text-gray-600">{(m.volume ?? 0).toLocaleString()}</span>
                        {sig && sig.ev_cents > 0 && (
                          <span className="text-[10px] font-mono font-semibold text-emerald-400">+{sig.ev_cents}¢</span>
                        )}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Selected market detail + orderbook */}
          {selectedMarket && (
            <div className="shrink-0 max-h-[38%] overflow-y-auto border-t border-slate-800 pt-2 space-y-2">
              <div className="bg-slate-800/80 rounded-xl p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-white truncate">{selectedMarket.question}</p>
                    <p className="text-[10px] font-mono text-gray-500">{selectedMarket.ticker}</p>
                  </div>
                  <button type="button" onClick={() => setSelectedMarket(null)} className="p-1 rounded hover:bg-slate-700 text-gray-500 shrink-0" aria-label="Close">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-1.5">
                  {(selectedMarket.outcomes ?? []).map(o => (
                    <div key={o.id} className="bg-slate-900 rounded-lg px-2.5 py-1.5">
                      <p className="text-[10px] text-gray-500">{o.name}</p>
                      <p className={`text-sm font-bold font-mono ${o.price >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                        {((o.price ?? 0) * 100).toFixed(0)}¢
                      </p>
                      {o.bid != null && o.ask != null && (
                        <p className="text-[10px] text-gray-600">{((o.bid ?? 0) * 100).toFixed(0)}–{((o.ask ?? 0) * 100).toFixed(0)}</p>
                      )}
                    </div>
                  ))}
                </div>

                {eventResult.data && (
                  <div className="flex items-center gap-2 text-[10px] bg-slate-900/60 rounded px-2 py-1">
                    <span className="text-gray-500">Event:</span>
                    <span className="font-mono text-orange-300">{eventResult.data.event_ticker}</span>
                    <span className="ml-auto text-gray-600">{eventResult.data.market_count} mkts</span>
                    {eventResult.data.markets[0]?.category && (
                      <span className={`px-1 py-0.5 rounded ${CAT_COLOR[eventResult.data.markets[0].category] ?? 'text-gray-400 bg-slate-800'}`}>
                        {eventResult.data.markets[0].category}
                      </span>
                    )}
                  </div>
                )}

                {selectedMarket.category === 'crypto' && selectedMarket.asset && selectedMarket.timeframe && (
                  <MarketSwarmConsensusBar asset={selectedMarket.asset} timeframe={selectedMarket.timeframe} />
                )}

                <div className="flex items-center gap-3 text-[10px] text-gray-500">
                  <span>Vol: <span className="text-gray-300">{(selectedMarket.volume ?? 0).toLocaleString()}</span></span>
                  {selectedMarket.minutes_to_expiry != null && (
                    <span>Exp: <span className="text-gray-300">
                      {selectedMarket.minutes_to_expiry < 60 ? `${(selectedMarket.minutes_to_expiry ?? 0).toFixed(0)}m`
                        : selectedMarket.minutes_to_expiry < 1440 ? `${((selectedMarket.minutes_to_expiry / 60) ?? 0).toFixed(1)}h`
                        : `${((selectedMarket.minutes_to_expiry / 1440) ?? 0).toFixed(1)}d`}
                    </span></span>
                  )}
                  {selectedEdge && (
                    <>
                      <span>EV: <span className={`font-mono ${selectedEdge.ev_cents > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {selectedEdge.ev_cents > 0 ? '+' : ''}{selectedEdge.ev_cents}¢
                      </span></span>
                      <span>Conf: <span className="text-gray-300">{((selectedEdge.confidence ?? 0) * 100).toFixed(0)}%</span></span>
                    </>
                  )}
                </div>

                {selectedPosition && (
                  <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-purple-500/5 border border-purple-500/20 text-xs">
                    <Shield className="w-3 h-3 text-purple-400" />
                    <span className="font-mono text-white">{selectedPosition.size} {selectedPosition.outcome}</span>
                    <span className="text-gray-500">@{((selectedPosition.avg_price ?? 0) * 100).toFixed(0)}¢</span>
                    <span className={`font-mono ml-auto ${selectedPosition.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(selectedPosition.unrealized_pnl ?? 0) >= 0 ? '+' : ''}${(selectedPosition.unrealized_pnl ?? 0).toFixed(2)}
                    </span>
                  </div>
                )}
              </div>
              <KalshiOrderbookPanel ticker={selectedMarket.ticker} depth={5} />
            </div>
          )}
        </div>

        {/* ══ RIGHT: Trade + Operations ══ */}
        <div className="flex flex-col w-[45%] min-h-0 gap-2">

          {/* Trade ticket */}
          {selectedMarket ? (
            <div className="shrink-0">
              <KalshiTradeTicket
                key={selectedMarket.ticker}
                ticker={selectedMarket.ticker}
                question={selectedMarket.question}
                outcomes={selectedMarket.outcomes}
                mode={venueMode}
                onOrderPlaced={() => { ordRefetch(); fillRefetch(); posRefetch(); balRefetch(); }}
                suggestedSize={kellySuggestion?.contracts}
                suggestedSide={kellySuggestion?.side}
                kellyFraction={sizing?.effective_fraction}
              />
            </div>
          ) : (
            <div className="bg-slate-800/60 rounded-xl p-5 text-center border border-slate-700/50">
              <Search className="w-6 h-6 text-gray-600 mx-auto mb-1.5" />
              <p className="text-xs text-gray-500">Select a market to place an order</p>
            </div>
          )}

          {/* Orders / Fills / Agents tabs */}
          <div className="flex-1 min-h-0 flex flex-col bg-slate-900 rounded-xl border border-slate-800">
            {/* Tab bar */}
            <div className="flex items-center border-b border-slate-800 shrink-0">
              {(['orders', 'fills', 'agents'] as RightTab[]).map(tab => (
                <button type="button" key={tab} onClick={() => setRightTab(tab)}
                  className={`flex-1 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                    rightTab === tab ? 'text-orange-400 border-b-2 border-orange-400' : 'text-gray-500 hover:text-gray-300'
                  }`}>
                  {tab === 'orders' ? `Orders (${orders.length})` : tab === 'fills' ? `Fills (${fills.length})` : 'Agents'}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto min-h-0">
              {rightTab === 'orders' && (
                <>
                  {orders.length > 1 && (
                    <div className="px-2 pt-2 pb-1">
                      <button type="button" onClick={handleCancelAll} disabled={cancellingAll}
                        className="w-full py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50">
                        {cancellingAll ? 'Cancelling…' : `Cancel All ${orders.length} Orders`}
                      </button>
                    </div>
                  )}
                  <div className="p-1.5 space-y-0.5">
                    {orders.length === 0 ? (
                      <p className="text-center text-[10px] text-gray-600 py-6">No open orders</p>
                    ) : orders.map(o => {
                      const isForSelected = selectedMarket?.ticker === o.ticker;
                      return (
                        <div key={o.order_id} className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-[10px] ${
                          isForSelected ? 'bg-orange-500/5 border border-orange-500/20' : 'bg-slate-800'
                        }`}>
                          <span className={`font-bold ${o.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                            {o.side?.toUpperCase?.() ?? '?'}
                          </span>
                          <span className="font-mono text-gray-500 truncate max-w-[80px]">{o.ticker}</span>
                          <span className="font-mono text-white whitespace-nowrap">
                            {o.size}×{o.price != null ? `${((o.price ?? 0) * 100).toFixed(0)}¢` : 'MKT'}
                          </span>
                          <span className={`px-1 py-0.5 rounded ${
                            o.status === 'resting' ? 'bg-blue-500/10 text-blue-400'
                              : o.status === 'filled' ? 'bg-green-500/10 text-green-400'
                              : 'bg-slate-700 text-gray-400'
                          }`}>{o.status}</span>
                          <button type="button" onClick={() => handleCancelOrder(o.order_id)}
                            disabled={cancellingOrder === o.order_id || cancellingAll}
                            className="ml-auto text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed" aria-label="Cancel">
                            <X className={`w-3 h-3 ${cancellingOrder === o.order_id ? 'animate-spin' : ''}`} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}

              {rightTab === 'fills' && (
                <div className="flex flex-col min-h-0">
                  <div className="flex items-center justify-between gap-2 px-2 pt-1.5 pb-1 border-b border-slate-800/80 shrink-0">
                    <div className="text-[9px] text-gray-500">
                      <span className={fillsStale ? 'text-amber-500/90' : ''}>
                        Last fetch {fillResult.lastUpdated ? fillResult.lastUpdated.toLocaleTimeString() : '—'}
                        {fillsStale ? ' · stale' : ''}
                      </span>
                      {fillResult.data?.meta?.response_at && (
                        <span className="text-gray-600 ml-2">
                          server {new Date(fillResult.data.meta.response_at).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleReconcileNow()}
                      disabled={reconcileBusy}
                      className="text-[9px] px-2 py-0.5 rounded border border-slate-600 text-gray-400 hover:text-orange-300 hover:border-orange-500/40 disabled:opacity-50"
                      title="POST /kalshi/fills/reconcile-now — poll fills + reconcile positions"
                    >
                      {reconcileBusy ? '…' : 'Reconcile'}
                    </button>
                  </div>
                  <div className="p-1.5 space-y-0.5 flex-1 overflow-y-auto min-h-0">
                    {fills.length === 0 ? (
                      <p className="text-center text-[10px] text-gray-600 py-6">No fills in window — ledger empty or still syncing</p>
                    ) : fills.slice(0, 50).map(f => (
                      <div
                        key={f.fill_id || f.trade_id}
                        className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 px-2 py-1.5 rounded-lg bg-slate-800 text-[10px]"
                      >
                        {f.asset && (
                          <span className="text-[9px] font-semibold text-orange-400/90 shrink-0">{f.asset}</span>
                        )}
                        <span className={`font-bold shrink-0 ${f.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                          {f.side?.toUpperCase?.() ?? '?'}
                        </span>
                        {f.action && (
                          <span className="text-[9px] text-gray-400 uppercase shrink-0">{f.action}</span>
                        )}
                        <span className="font-mono text-gray-500 truncate max-w-[90px]">{f.ticker}</span>
                        {f.incomplete ? (
                          <span className="text-amber-500/90 text-[9px]">pending reconciliation</span>
                        ) : (
                          <span className="font-mono text-white">
                            {f.size}×{formatFillPriceCentsLabel(f)}
                          </span>
                        )}
                        <span className="text-gray-600 ml-auto">${(f.fee ?? f.fee_usd ?? 0).toFixed(2)} fee</span>
                        <span className="text-gray-600 whitespace-nowrap shrink-0 w-full sm:w-auto sm:ml-0">
                          {new Date(f.timestamp || f.executed_at || 0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {rightTab === 'agents' && (
                <div className="p-1.5">
                  <KalshiActivityLog ticker={selectedMarket?.ticker ?? null} maxItems={30} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
