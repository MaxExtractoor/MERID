import React, { useState, useCallback, useMemo, useEffect } from 'react';
import {
  Briefcase, RefreshCw, DollarSign, Shield, TrendingUp,
  AlertTriangle, Activity, BarChart3, Gauge, Target,
  ArrowDownRight, Filter, X, Download, Trash2, Edit2,
  ToggleLeft, ToggleRight, ShieldOff, Clock,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, API_BASE_URL, DEFAULTS } from '../config/constants';
import type { KalshiBalance, KalshiPosition, KalshiOrder, KalshiFill, KalshiRiskSummary, SizingMetrics } from '../types/kalshi';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiPnlChart from '../components/KalshiPnlChart';
import KalshiRiskFeed from '../components/KalshiRiskFeed';
import OrderGroupPanel from '../components/OrderGroupPanel';
import BatchOrderPanel from '../components/BatchOrderPanel';
import OrderGroupAnalytics from '../components/OrderGroupAnalytics';
import { logUxEvent } from '../utils/uxTelemetry';

const DRAWDOWN_TIER_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  normal: { label: 'Normal', color: 'text-green-400', bg: 'bg-green-500/20' },
  warning: { label: 'Warning', color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
  downsize: { label: 'Downsized', color: 'text-orange-400', bg: 'bg-orange-500/20' },
  halt: { label: 'Halted', color: 'text-red-400', bg: 'bg-red-500/20' },
};

type Tab = 'positions' | 'orders' | 'fills' | 'risk';

interface KalshiPortfolioProps {
  initialTab?: Tab;
}

const KalshiPortfolioView: React.FC<KalshiPortfolioProps> = ({ initialTab }) => {
  const [tab, setTab] = useState<Tab>(initialTab ?? 'positions');
  const [assetFilter, setAssetFilter] = useState<string>('');

  const pollOpts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const posResult = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, pollOpts);
  const ordResult = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, pollOpts);
  const fillResult = useApiData<{ fills: KalshiFill[] }>(API_ENDPOINTS.KALSHI_FILLS, pollOpts);
  const balResult = useApiData<KalshiBalance>(API_ENDPOINTS.KALSHI_BALANCE, pollOpts);
  const riskResult = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, pollOpts);
  const sizingResult = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW });
  const ksResult = useApiData<{ global_kill: boolean; can_trade: boolean; kill_reason: string | null }>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH });
  const modeResult = useApiData<{ mode: string; is_live: boolean; live_enabled: boolean }>(API_ENDPOINTS.KALSHI_GRID_MODE, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });
  const sessionResult = useApiData<{ trading_allowed: boolean; block_reason: string | null; current_et: string; maintenance_day: boolean; maintenance_window: string }>(API_ENDPOINTS.KALSHI_GRID_SESSION, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });
  const gridPortfolioResult = useApiData<{ equity_usd: number; daily_pnl_usd: number; open_interest: number; position_count: number; kill_switch_active: boolean; margin_utilization: number }>(API_ENDPOINTS.KALSHI_GRID_PORTFOLIO, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });
  const orderGroupsResult = useApiData<{
    groups: Array<{
      order_group_id: string;
      name: string;
      status: 'active' | 'triggered' | 'canceled' | 'pending';
      contracts_limit: number;
      used_contracts: number;
      utilization_pct: number;
    }>;
  }>(API_ENDPOINTS.KALSHI_ORDER_GROUPS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });

  const allPositions = useMemo(() => posResult.data?.positions ?? [], [posResult.data]);
  const allOrders = useMemo(() => ordResult.data?.orders ?? [], [ordResult.data]);
  const allFills = useMemo(() => fillResult.data?.fills ?? [], [fillResult.data]);

  // Per-asset filtering
  const positionAssets = useMemo(() => {
    const assets = new Set<string>();
    for (const p of allPositions) {
      const asset = p.ticker.split('-')[0]?.toUpperCase() || p.ticker;
      assets.add(asset);
    }
    return Array.from(assets).sort();
  }, [allPositions]);

  const positions = useMemo(() => {
    if (!assetFilter) return allPositions;
    return allPositions.filter(p => p.ticker.toUpperCase().startsWith(assetFilter));
  }, [allPositions, assetFilter]);

  const orders = useMemo(() => {
    if (!assetFilter) return allOrders;
    return allOrders.filter(o => o.ticker.toUpperCase().startsWith(assetFilter));
  }, [allOrders, assetFilter]);

  const fills = useMemo(() => {
    if (!assetFilter) return allFills;
    return allFills.filter(f => f.ticker.toUpperCase().startsWith(assetFilter));
  }, [allFills, assetFilter]);
  const balance = balResult.data;
  const risk = riskResult.data;
  const loading = posResult.loading || ordResult.loading || fillResult.loading || balResult.loading || riskResult.loading;

  const [killSwitchError, setKillSwitchError] = useState<string | null>(null);
  const [modeToggling, setModeToggling] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [downsizing, setDownsizing] = useState(false);
  const [downsizeResult, setDownsizeResult] = useState<string | null>(null);
  const [amendOrderId, setAmendOrderId] = useState<string | null>(null);
  const [amendPrice, setAmendPrice] = useState<string>('');
  const [orderError, setOrderError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [operatorOverride, setOperatorOverride] = useState(false);

  const isLive = modeResult.data?.is_live ?? false;
  const liveEnabled = modeResult.data?.live_enabled ?? false;
  const currentMode = modeResult.data?.mode ?? 'paper';
  const sessionOpen = sessionResult.data?.trading_allowed ?? false;
  const sessionBlockReason = sessionResult.data?.block_reason ?? null;
  const maintenanceDay = sessionResult.data?.maintenance_day ?? false;
  const killSwitchActive = ksResult.data?.global_kill ?? false;
  const gridKillActive = gridPortfolioResult.data?.kill_switch_active ?? false;
  const executeBlocked = killSwitchActive || gridKillActive || !sessionOpen;
  const executeBlockReason = killSwitchActive
    ? (ksResult.data?.kill_reason ?? 'Kill switch active')
    : gridKillActive
      ? 'Grid portfolio kill switch active'
      : !sessionOpen
        ? (sessionBlockReason ?? 'Session closed')
        : null;

  useEffect(() => {
    if (executeBlocked) {
      setOperatorOverride(false);
    }
  }, [executeBlocked]);
  const canExecute = !executeBlocked || operatorOverride;

  const ensureExecutable = useCallback((action: string) => {
    if (!executeBlocked) return true;
    if (!operatorOverride) {
      setOrderError(executeBlockReason ? `Trading blocked: ${executeBlockReason}` : 'Trading blocked by session/kill switch');
      return false;
    }
    logUxEvent('portfolio_override', action, { reason: executeBlockReason ?? 'manual override' });
    return true;
  }, [executeBlocked, operatorOverride, executeBlockReason]);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const balanceUsd = useMemo(() => {
    if (!balance) return null;
    if (typeof balance.usd === 'number') {
      return Math.abs(balance.usd) > 100000 ? balance.usd / 100 : balance.usd;
    }
    return (balance.available ?? 0) + (balance.locked ?? 0);
  }, [balance]);

  const handleDownsize = useCallback(async () => {
    if (!ensureExecutable('downsize')) {
      setDownsizeResult('Blocked: session closed or kill switch active.');
      return;
    }
    if (!window.confirm('Trigger manual position downsize? This will reduce position sizes according to current risk parameters.')) return;
    setDownsizing(true);
    setDownsizeResult(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_RISK_DOWNSIZE}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      const json = res.ok ? await res.json().catch(() => ({})) : {};
      setDownsizeResult(json.message ?? (res.ok ? 'Downsize triggered.' : 'Downsize failed.'));
      if (res.ok) { posResult.refetch(); riskResult.refetch(); }
    } catch { setDownsizeResult('Request failed.'); }
    setDownsizing(false);
  }, [authHeaders, posResult, riskResult, ensureExecutable]);
  const [cancellingOrder, setCancellingOrder] = useState<string | null>(null);
  const [cancellingAll, setCancellingAll] = useState(false);

  const handleCancelOrder = useCallback(async (orderId: string) => {
    if (!ensureExecutable('cancel_order')) {
      return;
    }
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
      ordResult.refetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : `Cancel order ${orderId} failed`);
    }
    setCancellingOrder(null);
  }, [authHeaders, ordResult, ensureExecutable]);

  const handleAmendOpen = useCallback((orderId: string, currentPrice: number | null) => {
    setAmendOrderId(orderId);
    setAmendPrice(currentPrice != null ? String(Math.round(currentPrice * 100)) : '');
  }, []);

  const handleAmendSubmit = useCallback(async () => {
    if (!amendOrderId) return;
    const newPriceCents = parseInt(amendPrice, 10);
    if (isNaN(newPriceCents) || newPriceCents < 1 || newPriceCents > 99) return;
    if (!ensureExecutable('amend_order')) {
      return;
    }
    setOrderError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_AMEND(amendOrderId)}?price_cents=${newPriceCents}`, {
        method: 'PATCH',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`Amend failed: HTTP ${res.status}`);
      ordResult.refetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : `Amend order failed`);
    }
    setAmendOrderId(null);
    setAmendPrice('');
  }, [amendOrderId, amendPrice, authHeaders, ordResult, ensureExecutable]);

  const handleCancelAllOrders = useCallback(async () => {
    if (!ensureExecutable('cancel_all_orders')) {
      return;
    }
    const totalOpen = allOrders.length;
    const filteredView = assetFilter && orders.length !== totalOpen;
    const baseMsg = `Cancel ALL ${totalOpen} open orders across all assets?`;
    const filteredMsg = filteredView ? `${baseMsg}\nFilters are active (${orders.length} showing).` : baseMsg;
    if (!window.confirm(filteredMsg)) return;
    if (filteredView && !window.confirm('Filters are active; confirm global cancel across assets.')) return;
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
      ordResult.refetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : 'Batch cancel failed');
    }
    setCancellingAll(false);
  }, [authHeaders, orders.length, ordResult, allOrders.length, assetFilter, ensureExecutable]);

  const handleExportFills = useCallback(async () => {
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_EXPORT}`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `kalshi-fills-${Date.now()}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      setOrderError('Export failed — please try again');
    }
    setExporting(false);
  }, [authHeaders]);

  const fetchData = useCallback(() => {
    posResult.refetch();
    ordResult.refetch();
    fillResult.refetch();
    balResult.refetch();
    riskResult.refetch();
  }, [posResult, ordResult, fillResult, balResult, riskResult]);

  const handleModeToggle = useCallback(async () => {
    const targetMode = isLive ? 'paper' : 'live';
    if (targetMode === 'live' && !liveEnabled) {
      setModeError('Live mode requires MERID_PM_LIVE_ENABLED=true');
      return;
    }
    setModeToggling(true);
    setModeError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ mode: targetMode, force: false }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setModeError((err as { detail?: string }).detail ?? `Switch to ${targetMode} failed`);
      } else {
        modeResult.refetch();
        sessionResult.refetch();
      }
    } catch {
      setModeError('Network error during mode switch');
    } finally {
      setModeToggling(false);
    }
  }, [isLive, liveEnabled, authHeaders, modeResult, sessionResult]);

  const handleKillSwitch = useCallback(async (activate: boolean) => {
    setKillSwitchError(null);
    if (activate && !window.confirm('⚠️ Activate kill switch? This will immediately halt ALL trading.')) return;
    if (!activate && !window.confirm('Reset kill switch and re-enable trading? Ensure all issues are resolved first.')) return;
    try {
      const endpoint = activate ? API_ENDPOINTS.OPERATOR_EMERGENCY_STOP : API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH;
      const body = activate
        ? JSON.stringify({ reason: 'Manual operator activation from Portfolio view' })
        : JSON.stringify({ confirm: true });
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: authHeaders(),
        body,
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      await Promise.all([riskResult.refetch(), ksResult.refetch()]);
    } catch (err) {
      setKillSwitchError(err instanceof Error ? err.message : 'Kill switch action failed');
    }
  }, [authHeaders, riskResult, ksResult]);

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'positions', label: 'Positions', count: positions.length },
    { id: 'orders', label: 'Orders', count: orders.length },
    { id: 'fills', label: 'Fills', count: fills.length },
    { id: 'risk', label: 'Risk', count: risk?.recent_breaches?.length ?? 0 },
  ];

  const gridPortfolio = gridPortfolioResult.data;

  return (
    <div className="space-y-6">
      {/* Execution Gate — always visible */}
      <ExecutionGateStrip />

      {/* Kill switch error banner */}
      {killSwitchError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Kill switch failed: {killSwitchError}</span>
          <button type="button" onClick={() => setKillSwitchError(null)} className="ml-auto text-red-400 hover:text-red-300" title="Dismiss" aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Order action error banner */}
      {orderError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{orderError}</span>
          <button type="button" onClick={() => setOrderError(null)} className="ml-auto text-red-400 hover:text-red-300" title="Dismiss" aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Mode error banner */}
      {modeError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{modeError}</span>
          <button type="button" onClick={() => setModeError(null)} className="ml-auto" aria-label="Dismiss">×</button>
        </div>
      )}

      {executeBlocked && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Trading blocked: {executeBlockReason ?? 'session closed or kill switch active'}.</span>
          <label className="ml-auto flex items-center gap-2 text-xs text-amber-200">
            <input
              type="checkbox"
              checked={operatorOverride}
              onChange={(e) => {
                setOperatorOverride(e.target.checked);
                if (e.target.checked) {
                  logUxEvent('portfolio_override_ack', executeBlockReason ?? 'unknown');
                }
              }}
            />
            <span>Override once (I understand the risk)</span>
          </label>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Briefcase className="w-7 h-7 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Kalshi Portfolio
              <KalshiModeBadge />
            </h1>
            <div className="flex items-center gap-3 mt-0.5">
              <p className="text-sm text-gray-400">
                {positions.length} positions · {orders.length} open orders
              </p>
              {/* Session status */}
              <span className={`flex items-center gap-1 text-xs ${
                sessionOpen ? 'text-green-400' : 'text-gray-500'
              }`}>
                <Clock className="w-3 h-3" />
                {sessionOpen ? 'Session open' : 'Session closed'}
              </span>
              {/* Maintenance indicator */}
              {maintenanceDay && (
                <span className="flex items-center gap-1 text-xs text-amber-400">
                  <AlertTriangle className="w-3 h-3" />
                  Maintenance window
                </span>
              )}
              {sessionBlockReason && (
                <span className="flex items-center gap-1 text-xs text-red-400">
                  <AlertTriangle className="w-3 h-3" />
                  {sessionBlockReason}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Kill switch quick indicator */}
          {ksResult.data?.global_kill && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-bold animate-pulse">
              <ShieldOff className="w-3.5 h-3.5" />
              KILL ACTIVE
            </span>
          )}

          {/* Paper / Live toggle */}
          <button
            type="button"
            onClick={() => void handleModeToggle()}
            disabled={modeToggling || ksResult.data?.global_kill}
            title={isLive ? 'Switch to Paper mode' : liveEnabled ? 'Switch to Live mode' : 'Live mode disabled (set MERID_PM_LIVE_ENABLED=true)'}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium transition-all disabled:opacity-50 ${
              isLive
                ? 'bg-green-500/20 border-green-500/40 text-green-300 hover:bg-green-500/30'
                : 'bg-slate-800 border-slate-700 text-gray-400 hover:text-white hover:bg-slate-700'
            }`}
          >
            {isLive
              ? <ToggleRight className="w-4 h-4" />
              : <ToggleLeft className="w-4 h-4" />}
            {modeToggling ? 'Switching…' : currentMode.toUpperCase()}
          </button>

          <button
            type="button"
            onClick={fetchData}
            aria-label="Refresh all portfolio data"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className={`rounded-xl p-4 border ${
          isLive ? 'bg-green-500/5 border-green-500/20' : 'bg-slate-900 border-slate-800'
        }`}>
          <div className="flex items-center gap-2 mb-1">
            <DollarSign className="w-4 h-4 text-green-400" />
            <span className="text-xs text-gray-400">Equity</span>
            {isLive && <span className="ml-auto text-[9px] font-bold text-green-400 bg-green-500/20 px-1 rounded">LIVE</span>}
          </div>
          <p className="text-lg font-bold text-white">
            {gridPortfolio?.equity_usd != null
              ? `$${gridPortfolio.equity_usd.toFixed(2)}`
              : balanceUsd != null ? `$${balanceUsd.toFixed(2)}` : '—'}
          </p>
          <p className="text-xs text-gray-500">Avail: ${balance?.available?.toFixed(2) ?? '—'}</p>
        </div>
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            <span className="text-xs text-gray-400">Unrealized</span>
          </div>
          <p className={`text-lg font-bold ${(risk?.total_unrealized_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${(risk?.total_unrealized_pnl_usd ?? 0).toFixed(2)}
          </p>
        </div>
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 className="w-4 h-4 text-purple-400" />
            <span className="text-xs text-gray-400">Realized PnL</span>
          </div>
          <p className={`text-lg font-bold ${
            (gridPortfolio?.daily_pnl_usd ?? risk?.daily_realized_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
          }`}>
            ${(gridPortfolio?.daily_pnl_usd ?? risk?.daily_realized_pnl_usd ?? 0).toFixed(2)}
          </p>
          <p className="text-xs text-gray-500">{risk?.daily_trades ?? 0} trades today</p>
        </div>
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-1">
            <Activity className="w-4 h-4 text-yellow-400" />
            <span className="text-xs text-gray-400">Notional</span>
          </div>
          <p className="text-lg font-bold text-white">${(risk?.total_notional_usd ?? 0).toFixed(2)}</p>
          <p className="text-xs text-gray-500">
            OI: {gridPortfolio?.open_interest ?? risk?.open_market_count ?? 0} · {risk?.open_market_count ?? 0} markets
          </p>
        </div>
        <div className={`rounded-xl p-4 border ${ksResult.data?.global_kill ? 'bg-red-500/5 border-red-500/30' : 'bg-slate-900 border-slate-800'}`}>
          <div className="flex items-center gap-2 mb-1">
            <Shield className={`w-4 h-4 ${ksResult.data?.global_kill ? 'text-red-400' : 'text-green-400'}`} />
            <span className="text-xs text-gray-400">Kill Switch</span>
          </div>
          <p className={`text-lg font-bold ${ksResult.data?.global_kill ? 'text-red-400' : 'text-green-400'}`}>
            {ksResult.data?.global_kill ? 'ACTIVE' : 'OFF'}
          </p>
          {ksResult.data?.kill_reason && (
            <p className="text-[10px] text-red-300 truncate mt-0.5" title={ksResult.data.kill_reason}>{ksResult.data.kill_reason}</p>
          )}
          <button
            type="button"
            onClick={() => handleKillSwitch(!(ksResult.data?.global_kill ?? false))}
            className={`mt-1 text-xs px-2 py-0.5 rounded ${
              ksResult.data?.global_kill
                ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
            }`}
          >
            {ksResult.data?.global_kill ? 'Reset' : 'Activate'}
          </button>
        </div>
      </div>

      {/* PnL Equity Curve */}
      <KalshiPnlChart />

      {/* Per-Asset Filter */}
      {positionAssets.length > 1 && (
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-3.5 h-3.5 text-gray-500" />
          <button
            type="button"
            onClick={() => setAssetFilter('')}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
              !assetFilter ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500' : 'text-gray-400 bg-slate-800 hover:text-white'
            }`}
          >
            All
          </button>
          {positionAssets.map(asset => (
            <button
              type="button"
              key={asset}
              onClick={() => setAssetFilter(assetFilter === asset ? '' : asset)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
                assetFilter === asset ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500' : 'text-gray-400 bg-slate-800 hover:text-white'
              }`}
            >
              {asset}
            </button>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-900 rounded-xl p-1 border border-slate-800">
        {tabs.map((t) => (
          <button
            type="button"
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t.id
                ? 'bg-orange-500/20 text-orange-300'
                : 'text-gray-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            {t.label} {t.count > 0 && <span className="ml-1 text-xs opacity-70">({t.count})</span>}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading...</div>
      ) : (
        <>
          {/* Positions Tab */}
          {tab === 'positions' && (
            <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-gray-400 text-xs">
                    <th className="text-left p-3">Ticker</th>
                    <th className="text-left p-3">Side</th>
                    <th className="text-right p-3">Size</th>
                    <th className="text-right p-3">Avg Price</th>
                    <th className="text-right p-3">Unrealized</th>
                    <th className="text-right p-3">Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <tr><td colSpan={6} className="text-center py-8 text-gray-500">No positions</td></tr>
                  ) : (
                    positions.map((p, i) => (
                      <tr key={`${p.ticker}-${i}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="p-3 font-mono text-white">{p.ticker}</td>
                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-xs ${
                            p.outcome === 'yes' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                          }`}>
                            {p.outcome.toUpperCase()}
                          </span>
                        </td>
                        <td className="p-3 text-right text-white">{p.size}</td>
                        <td className="p-3 text-right text-gray-300">{((p.avg_price ?? 0) * 100).toFixed(1)}¢</td>
                        <td className={`p-3 text-right font-medium ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${(p.unrealized_pnl ?? 0).toFixed(2)}
                        </td>
                        <td className={`p-3 text-right ${p.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          ${(p.realized_pnl ?? 0).toFixed(2)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Orders Tab */}
          {tab === 'orders' && (
            <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
              {orders.length > 0 && (
                <div className="flex items-center justify-end px-3 py-2 border-b border-slate-800">
                  <button
                    type="button"
                    onClick={handleCancelAllOrders}
                    disabled={cancellingAll || !canExecute}
                    title={canExecute ? 'Cancel all open orders' : (executeBlockReason ?? 'Trading blocked')}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 transition-colors disabled:opacity-50"
                  >
                    <Trash2 className="w-3 h-3" />
                    {cancellingAll ? 'Cancelling…' : `Cancel All (${allOrders.length})`}
                  </button>
                </div>
              )}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-gray-400 text-xs">
                    <th className="text-left p-3">Order ID</th>
                    <th className="text-left p-3">Ticker</th>
                    <th className="text-left p-3">Side</th>
                    <th className="text-right p-3">Size</th>
                    <th className="text-right p-3">Price</th>
                    <th className="text-right p-3">Filled</th>
                    <th className="text-left p-3">Status</th>
                    <th className="p-3" />
                  </tr>
                </thead>
                <tbody>
                  {orders.length === 0 ? (
                    <tr><td colSpan={8} className="text-center py-8 text-gray-500">No open orders</td></tr>
                  ) : (
                    orders.map((o) => (
                      <React.Fragment key={o.order_id}>
                        <tr className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-3 font-mono text-gray-400 text-xs">{o.order_id.slice(0, 12)}…</td>
                          <td className="p-3 font-mono text-white">{o.ticker}</td>
                          <td className="p-3">
                            <span className={`px-2 py-0.5 rounded text-xs ${
                              o.side === 'buy' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                            }`}>
                              {o.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="p-3 text-right text-white">{o.size}</td>
                          <td className="p-3 text-right text-gray-300">{o.price != null ? `${(o.price * 100).toFixed(0)}¢` : 'MKT'}</td>
                          <td className="p-3 text-right text-gray-300">{o.filled}/{o.size}</td>
                          <td className="p-3">
                            <span className="px-2 py-0.5 rounded text-xs text-yellow-400 bg-yellow-400/10">{o.status}</span>
                          </td>
                          <td className="p-3 text-right">
                            {o.status === 'resting' && (
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => handleAmendOpen(o.order_id, o.price)}
                                  disabled={!canExecute}
                                  className="p-1 rounded hover:bg-blue-500/20 text-gray-600 hover:text-blue-400 transition-colors disabled:opacity-40"
                                  title="Amend price"
                                >
                                  <Edit2 className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleCancelOrder(o.order_id)}
                                  disabled={cancellingOrder === o.order_id || !canExecute}
                                  className="p-1 rounded hover:bg-red-500/20 text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
                                  title="Cancel order"
                                >
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                        {amendOrderId === o.order_id && (
                          <tr className="bg-blue-500/5 border-b border-slate-800">
                            <td colSpan={8} className="px-3 py-2">
                              <div className="flex items-center gap-2">
                                <span className="text-xs text-gray-400">New price (1–99¢):</span>
                                <input
                                  type="number"
                                  min={1}
                                  max={99}
                                  value={amendPrice}
                                  onChange={e => setAmendPrice(e.target.value)}
                                  className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-400 focus:outline-none"
                                  aria-label="New limit price in cents"
                                  onKeyDown={e => { if (e.key === 'Enter') void handleAmendSubmit(); if (e.key === 'Escape') { setAmendOrderId(null); setAmendPrice(''); } }}
                                />
                                <span className="text-xs text-gray-500">¢</span>
                                <button type="button" onClick={() => void handleAmendSubmit()}
                                  className="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 border border-blue-500/30">
                                  Amend
                                </button>
                                <button type="button" onClick={() => { setAmendOrderId(null); setAmendPrice(''); }}
                                  className="px-2 py-1 rounded text-xs bg-slate-700 text-gray-400 hover:text-white">
                                  Cancel
                                </button>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Fills Tab */}
          {tab === 'fills' && (
            <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
              <div className="flex items-center justify-end px-3 py-2 border-b border-slate-800">
                <button
                  type="button"
                  onClick={handleExportFills}
                  disabled={exporting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors disabled:opacity-50"
                >
                  <Download className="w-3 h-3" />
                  Export CSV
                </button>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-gray-400 text-xs">
                    <th className="text-left p-3">Time</th>
                    <th className="text-left p-3">Ticker</th>
                    <th className="text-left p-3">Side</th>
                    <th className="text-right p-3">Size</th>
                    <th className="text-right p-3">Price</th>
                    <th className="text-right p-3">Fee</th>
                    <th className="text-right p-3">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {fills.length === 0 ? (
                    <tr><td colSpan={7} className="text-center py-8 text-gray-500">No recent fills</td></tr>
                  ) : (
                    fills.map((f) => {
                      const net = f.size * f.price - f.fee;
                      return (
                        <tr key={f.trade_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-3 text-gray-400 text-xs">
                            {new Date(f.timestamp).toLocaleTimeString()}
                          </td>
                          <td className="p-3 font-mono text-white">{f.ticker}</td>
                          <td className="p-3">
                            <span className={`px-2 py-0.5 rounded text-xs ${
                              f.side === 'yes' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                            }`}>
                              {f.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="p-3 text-right text-white">{f.size}</td>
                          <td className="p-3 text-right text-gray-300">{((f.price ?? 0) * 100).toFixed(1)}¢</td>
                          <td className="p-3 text-right text-yellow-400">${(f.fee ?? 0).toFixed(2)}</td>
                          <td className="p-3 text-right text-gray-300">${net.toFixed(2)}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* Risk Tab */}
          {tab === 'risk' && risk && (
            <div className="space-y-4">
              {/* Risk Overview */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-gray-400 mb-1">Daily PnL</p>
                  <p className={`text-lg font-bold ${(risk.daily_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${(risk.daily_pnl_usd ?? 0).toFixed(2)}
                  </p>
                  <p className="text-xs text-gray-500">Max: ${risk.limits?.max_daily_loss_usd ?? '—'}</p>
                </div>
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-gray-400 mb-1">Drawdown</p>
                  <p className={`text-lg font-bold ${(risk.drawdown_pct ?? 0) < 5 ? 'text-green-400' : (risk.drawdown_pct ?? 0) < 10 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {(risk.drawdown_pct ?? 0).toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-500">Halt: {((risk.limits?.drawdown_halt_pct ?? 0) * 100).toFixed(0)}%</p>
                </div>
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-gray-400 mb-1">Total Notional</p>
                  <p className="text-lg font-bold text-white">${(risk.total_notional_usd ?? 0).toFixed(2)}</p>
                  <p className="text-xs text-gray-500">Max: ${risk.limits?.max_total_notional_usd ?? '—'}</p>
                </div>
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <p className="text-xs text-gray-400 mb-1">Rate Limits</p>
                  <p className="text-lg font-bold text-white">{risk.daily_trades}/day</p>
                  <p className="text-xs text-gray-500">Fees: ${(risk.daily_fees_usd ?? 0).toFixed(2)}</p>
                </div>
              </div>

              {/* Category Exposure */}
              {Object.keys(risk.category_notional).length > 0 && (
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <h3 className="text-sm font-medium text-gray-300 mb-3">Category Exposure</h3>
                  <div className="space-y-2">
                    {Object.entries(risk.category_notional ?? {}).map(([cat, notional]) => (
                      <div key={cat} className="flex items-center justify-between">
                        <span className="text-sm text-gray-400 capitalize">{cat}</span>
                        <div className="flex items-center gap-4">
                          <span className="text-sm text-white">${(notional ?? 0).toFixed(2)}</span>
                          <span className="text-xs text-gray-500">
                            {risk.category_contracts[cat] ?? 0} contracts
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Sizing & Performance Metrics */}
              {sizingResult.data && (() => {
                const s = sizingResult.data;
                const tier = DRAWDOWN_TIER_CONFIG[s.drawdown_tier] ?? DRAWDOWN_TIER_CONFIG.normal;
                const canDownsize = s.drawdown_tier === 'downsize' || s.drawdown_tier === 'halt';
                return (
                  <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium text-gray-300">Sizing & Performance</h3>
                      {canDownsize && (
                        <button
                          type="button"
                          onClick={handleDownsize}
                          disabled={downsizing || !canExecute}
                          title={canExecute ? 'Force downsize' : (executeBlockReason ?? 'Trading blocked')}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 border border-orange-500/20 transition-colors disabled:opacity-50"
                        >
                          <ArrowDownRight className="w-3 h-3" />
                          {downsizing ? 'Downsizing…' : 'Force Downsize'}
                        </button>
                      )}
                    </div>
                    {downsizeResult && (
                      <p className="text-xs text-orange-300 bg-orange-900/20 px-3 py-1.5 rounded">{downsizeResult}</p>
                    )}

                    {/* Drawdown Tier */}
                    <div className="flex items-center gap-3">
                      <ArrowDownRight className="w-4 h-4 text-gray-400" />
                      <span className="text-xs text-gray-400">Drawdown Tier:</span>
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${tier.color} ${tier.bg}`}>
                        {tier.label}
                      </span>
                      <span className="text-xs text-gray-500 ml-auto">
                        {(s.drawdown_pct ?? 0).toFixed(1)}% / W:{s.drawdown_thresholds?.warning ?? '—'}% D:{s.drawdown_thresholds?.downsize ?? '—'}% H:{s.drawdown_thresholds?.halt ?? '—'}%
                      </span>
                    </div>

                    {/* Kelly & Vol Sizing */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="flex items-center gap-1.5 mb-1">
                          <Gauge className="w-3.5 h-3.5 text-blue-400" />
                          <span className="text-[10px] text-gray-500">Kelly Util</span>
                        </div>
                        <p className="text-sm font-bold text-white">{(s.kelly_utilization_pct ?? 0).toFixed(0)}%</p>
                        <p className="text-[10px] text-gray-600">f={(s.kelly_fraction ?? 0).toFixed(3)}</p>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="flex items-center gap-1.5 mb-1">
                          <Target className="w-3.5 h-3.5 text-purple-400" />
                          <span className="text-[10px] text-gray-500">Vol Scale</span>
                        </div>
                        <p className="text-sm font-bold text-white">{(s.vol_scale ?? 0).toFixed(2)}x</p>
                        <p className="text-[10px] text-gray-600">
                          {((s.realized_vol ?? 0) * 100).toFixed(1)}% / {((s.target_vol ?? 0) * 100).toFixed(1)}% target
                        </p>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <span className="text-[10px] text-gray-500">Effective Fraction</span>
                        <p className="text-sm font-bold text-white">{((s.effective_fraction ?? 0) * 100).toFixed(2)}%</p>
                        <p className="text-[10px] text-gray-600">ATR: {(s.atr_value ?? 0).toFixed(0)}</p>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <span className="text-[10px] text-gray-500">Trades Today</span>
                        <p className="text-sm font-bold text-white">{s.trades_today ?? 0}</p>
                        <p className="text-[10px] text-gray-600">WR: {(s.win_rate_pct ?? 0).toFixed(0)}% PF: {(s.profit_factor ?? 0).toFixed(2)}</p>
                      </div>
                    </div>

                    {/* Risk-Adjusted Metrics */}
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-gray-500">Risk-Adjusted:</span>
                      <span className="text-gray-300">Sharpe <span className="font-mono text-blue-400">{(s.sharpe_ratio ?? 0).toFixed(2)}</span></span>
                      <span className="text-gray-300">Sortino <span className="font-mono text-purple-400">{(s.sortino_ratio ?? 0).toFixed(2)}</span></span>
                      <span className="text-gray-300">Calmar <span className="font-mono text-teal-400">{(s.calmar_ratio ?? 0).toFixed(2)}</span></span>
                    </div>
                  </div>
                );
              })()}

              {/* Live Risk Feed */}
              <KalshiRiskFeed maxItems={30} />

              {/* Recent Breaches */}
              {risk.recent_breaches.length > 0 && (
                <div className="bg-slate-900 rounded-xl p-4 border border-red-900/30">
                  <div className="flex items-center gap-2 mb-3">
                    <AlertTriangle className="w-4 h-4 text-red-400" />
                    <h3 className="text-sm font-medium text-red-300">Recent Breaches ({risk.recent_breaches.length})</h3>
                  </div>
                  <div className="space-y-2">
                    {risk.recent_breaches.map((b, i) => (
                      <div key={i} className="flex items-start gap-3 text-xs">
                        <span className="text-gray-500 whitespace-nowrap">
                          {new Date(b.ts).toLocaleTimeString()}
                        </span>
                        <span className="text-yellow-400 font-mono">{b.check}</span>
                        <span className="text-gray-400">{b.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Order Groups Panel */}
              <BatchOrderPanel
                onOrdersPlaced={() => posResult.refetch()}
                availableGroups={orderGroupsResult.data?.groups || []}
                compact={true}
              />
              <OrderGroupPanel
                compact={false}
                onGroupTriggered={(groupId) => {
                  console.log('Portfolio: Group triggered:', groupId);
                }}
              />
              {/* Order Group Analytics */}
              <OrderGroupAnalytics
                histories={(orderGroupsResult.data?.groups || []).map(g => ({
                  order_group_id: g.order_group_id,
                  name: g.name,
                  status: g.status,
                  history: [
                    {
                      timestamp: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
                      utilization_pct: Math.max(0, g.utilization_pct - 10),
                      contracts_used: Math.max(0, g.used_contracts - 5),
                      contracts_limit: g.contracts_limit,
                    },
                    {
                      timestamp: new Date().toISOString(),
                      utilization_pct: g.utilization_pct,
                      contracts_used: g.used_contracts,
                      contracts_limit: g.contracts_limit,
                    },
                  ],
                  trigger_events: g.status === 'triggered' ? [{ timestamp: new Date().toISOString(), matched_contracts: g.used_contracts }] : [],
                }))}
                hours={24}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default KalshiPortfolioView;
