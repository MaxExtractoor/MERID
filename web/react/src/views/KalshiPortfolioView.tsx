import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY} from '../config/constants';
import { log } from '../ui/logger';
import { DRAWDOWN_TIER_CONFIG, getDrawdownTierConfig } from '../shared/config/riskConfig';
import type { KalshiBalance, KalshiPosition, KalshiOrder, KalshiRiskSummary, SizingMetrics } from '../types/kalshi';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiPnlChart from '../components/KalshiPnlChart';
import KalshiRiskFeed from '../components/KalshiRiskFeed';
import OrderGroupPanel from '../components/OrderGroupPanel';
import BatchOrderPanel from '../components/BatchOrderPanel';
import OrderGroupAnalytics from '../components/OrderGroupAnalytics';
import CircuitBreakerPanel from '../components/CircuitBreakerPanel';
import LatencyPanel from '../components/LatencyPanel';
import OrderErrorsPanel from '../components/OrderErrorsPanel';
import ErrorAlert from '../components/ErrorAlert';
import { ConfirmModal } from '../components/ConfirmModal';
import KalshiReconciliationBadge from '../components/KalshiReconciliationBadge';
import RiskAlertFeed from '../components/RiskAlertFeed';
import KalshiBankrollPanel from '../components/KalshiBankrollPanel';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';
import { DataAgeBadge } from '../components/DataAgeBadge';

// Helper to normalize enum-like values to strings (handles .value, .name, or plain strings)
const _normalizeLabel = (value: unknown, defaultValue = 'UNKNOWN'): string => {
  if (value === null || value === undefined) return defaultValue;
  if (typeof value === 'string') return value;
  // Handle enum-like objects with .value or .name
  const obj = value as Record<string, unknown>;
  if (typeof obj.value === 'string') return obj.value;
  if (typeof obj.name === 'string') return obj.name;
  return String(value);
};


const KalshiPortfolioView: React.FC = () => {

  const pollOpts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const { error: healthError } = useApiData<{ ok: boolean }>(API_ENDPOINTS.KALSHI_HEALTH, pollOpts);
  const posResult = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, pollOpts);
  const ordResult = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, pollOpts);
  const balResult = useApiData<KalshiBalance>(API_ENDPOINTS.KALSHI_BALANCE, pollOpts);
  const riskResult = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, pollOpts);
  const sizingResult = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW });
  const ksResult = useApiData<{ kill_switch_active: boolean; global_kill?: boolean; can_trade: boolean; kill_reason: string | null }>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH });
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
  const { summary, summaryReceivedAt, alerts: wsAlerts, clearAlerts: clearWsAlerts } = useKalshiRiskStream();

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

  // Real-time updates: refetch when WebSocket summary changes
  // UI-002 fix: extract stable refetch refs to prevent infinite re-render loop
  // NOTE: stable refs are defined below (posRefetchCb, ordRefetchCb) and reused here

  const allPositions = useMemo(() => posResult.data?.positions ?? [], [posResult.data]);
  const allOrders = useMemo(() => ordResult.data?.orders ?? [], [ordResult.data]);

  const balance = balResult.data;
  const risk = riskResult.data;
  const loading = posResult.loading || balResult.loading || riskResult.loading;

  const [killSwitchError, setKillSwitchError] = useState<string | null>(null);
  const [modeToggling, setModeToggling] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [downsizing, setDownsizing] = useState(false);
  const [downsizeResult, setDownsizeResult] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    confirmVariant?: 'primary' | 'danger' | 'warning';
  }>({ isOpen: false, title: '', message: '', onConfirm: () => { /* no-op */ } });

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const balanceUsd = useMemo(() => {
    if (!balance) return null;
    // Backend now normalizes balance to dollars - use directly
    // API returns units: "dollars" to confirm
    const usd = typeof balance.usd === 'number'
      ? balance.usd
      : (balance.available ?? 0) + (balance.locked ?? 0);
    if (usd > 10_000) {
      // Sanity check: suspiciously large balanceUsd may still be in cents
      console.error('[KalshiPortfolioView] suspiciously large balanceUsd — verify backend is not returning cents', usd);
    }
    return usd;
  }, [balance]);

  // UI-009 fix: extract stable refetch refs for Portfolio callbacks
  const posRefetchCb = posResult.refetch;
  const riskRefetchCb = riskResult.refetch;
  const ordRefetchCb = ordResult.refetch;
  const balRefetchCb = balResult.refetch;
  const modeRefetchCb = modeResult.refetch;
  const sessionRefetchCb = sessionResult.refetch;
  const ksRefetchCb = ksResult.refetch;

  // MED-004 fix: debounce WS-triggered refetches to prevent REST storm on rapid messages
  const wsRefetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!summary) return;
    if (wsRefetchTimerRef.current) clearTimeout(wsRefetchTimerRef.current);
    wsRefetchTimerRef.current = setTimeout(() => {
      posRefetchCb();
      ordRefetchCb();
    }, 500);
    return () => {
      if (wsRefetchTimerRef.current) clearTimeout(wsRefetchTimerRef.current);
    };
  }, [summary, posRefetchCb, ordRefetchCb]);

  const handleDownsize = useCallback(async () => {
    setConfirmModal({
      isOpen: true,
      title: 'Confirm Downsize',
      message: 'Trigger manual position downsize? This will reduce position sizes according to current risk parameters.',
      confirmVariant: 'warning',
      onConfirm: async () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
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
          const json = await res.json().catch(() => ({}));
          setDownsizeResult(json.message ?? 'Downsize triggered.');
          posRefetchCb(); riskRefetchCb();
        } catch (err) { setDownsizeResult(`Request failed: ${err instanceof Error ? err.message : 'Unknown error'}`); }
        setDownsizing(false);
      },
    });
  }, [authHeaders, posRefetchCb, riskRefetchCb]);

  const fetchData = useCallback(() => {
    posRefetchCb();
    ordRefetchCb();
    balRefetchCb();
    riskRefetchCb();
  }, [posRefetchCb, ordRefetchCb, balRefetchCb, riskRefetchCb]);

  const isLive = modeResult.data?.is_live ?? false;
  const liveEnabled = modeResult.data?.live_enabled ?? false;
  const currentMode = modeResult.data?.mode ?? 'paper';
  const sessionOpen = sessionResult.data?.trading_allowed ?? false;
  const sessionBlockReason = sessionResult.data?.block_reason ?? null;
  const maintenanceDay = sessionResult.data?.maintenance_day ?? false;

  const handleModeToggle = useCallback(async () => {
    const targetMode = isLive ? 'paper' : 'live';
    
    if (targetMode === 'live' && !liveEnabled) {
      // First confirmation for force override
      setConfirmModal({
        isOpen: true,
        title: 'Force Live Mode Override',
        message: 'MERID_PM_LIVE_ENABLED is not set.\n\nForce switch to LIVE mode anyway? This will route real orders to Kalshi.',
        confirmVariant: 'warning',
        onConfirm: () => {
          // Second confirmation for live trading
          setConfirmModal({
            isOpen: true,
            title: 'Switch to LIVE Trading',
            message: '⚠️ Switch to LIVE trading?\n\nReal orders will be placed on Kalshi with real funds.\nConfirm all risk parameters are correct.\n\nContinue?',
            confirmVariant: 'danger',
            onConfirm: async () => {
              setConfirmModal(prev => ({ ...prev, isOpen: false }));
              setModeToggling(true);
              setModeError(null);
              try {
                const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
                  method: 'POST',
                  headers: authHeaders(),
                  body: JSON.stringify({ mode: targetMode, force: true }),
                });
                if (!res.ok) {
                  const err = await res.json().catch(() => ({}));
                  setModeError((err as { detail?: string }).detail ?? `Switch to ${targetMode} failed`);
                } else {
                  modeRefetchCb();
                  sessionRefetchCb();
                }
              } catch (err) {
                log.error('Mode switch failed', err, 'KalshiPortfolioView');
                setModeError('Network error during mode switch');
              } finally {
                setModeToggling(false);
              }
            },
          });
        },
      });
      return;
    }
    
    if (targetMode === 'live') {
      setConfirmModal({
        isOpen: true,
        title: 'Switch to LIVE Trading',
        message: '⚠️ Switch to LIVE trading?\n\nReal orders will be placed on Kalshi with real funds.\nConfirm all risk parameters are correct.\n\nContinue?',
        confirmVariant: 'danger',
        onConfirm: async () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          setModeToggling(true);
          setModeError(null);
          try {
            const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
              method: 'POST',
              headers: authHeaders(),
              body: JSON.stringify({ mode: targetMode }),
            });
            if (!res.ok) {
              const err = await res.json().catch(() => ({}));
              setModeError((err as { detail?: string }).detail ?? `Switch to ${targetMode} failed`);
            } else {
              modeRefetchCb();
              sessionRefetchCb();
            }
          } catch (err) {
            log.error('Mode switch failed', err, 'KalshiPortfolioView');
            setModeError('Network error during mode switch');
          } finally {
            setModeToggling(false);
          }
        },
      });
      return;
    }
    
    // Switch to paper (no confirmation needed)
    setModeToggling(true);
    setModeError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ mode: targetMode }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setModeError((err as { detail?: string }).detail ?? `Switch to ${targetMode} failed`);
      } else {
        modeRefetchCb();
        sessionRefetchCb();
      }
    } catch (err) {
      log.error('Mode switch failed', err, 'KalshiPortfolioView');
      setModeError('Network error during mode switch');
    } finally {
      setModeToggling(false);
    }
  }, [isLive, liveEnabled, authHeaders, modeRefetchCb, sessionRefetchCb]);

  const executeKillSwitch = useCallback(async (activate: boolean) => {
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
      await Promise.all([riskRefetchCb(), ksRefetchCb()]);
    } catch (err) {
      setKillSwitchError(err instanceof Error ? err.message : 'Kill switch action failed');
    }
  }, [authHeaders, riskRefetchCb, ksRefetchCb]);

  const handleKillSwitch = useCallback(async (activate: boolean) => {
    setKillSwitchError(null);
    if (activate) {
      setConfirmModal({
        isOpen: true,
        title: 'Activate Kill Switch',
        message: '⚠️ Activate kill switch? This will immediately halt ALL trading.',
        confirmVariant: 'danger',
        onConfirm: async () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          await executeKillSwitch(activate);
        },
      });
    } else {
      setConfirmModal({
        isOpen: true,
        title: 'Reset Kill Switch',
        message: 'Reset kill switch and re-enable trading? Ensure all issues are resolved first.',
        confirmVariant: 'warning',
        onConfirm: async () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          await executeKillSwitch(activate);
        },
      });
    }
  }, [executeKillSwitch]);

  const gridPortfolio = gridPortfolioResult.data;

  if (loading && !balance && !allPositions.length) {
    return (
      <div className="p-6 flex items-center gap-2 text-slate-400">
        <Icon name="loader" size={16} className="animate-spin" />
        Loading KalshiPortfolio...
      </div>
    );
  }

  if (healthError && !balance) {
    return <ErrorAlert message={healthError.message ?? 'Failed to load KalshiPortfolio data'} />;
  }

  return (
    <div className="space-y-6">
      {/* Execution Gate — always visible */}
      <ExecutionGateStrip />

      {/* Continuous trader bankroll */}
      <KalshiBankrollPanel />

      {/* Reconciliation Warning Banner */}
      {reconciliationResult.data?.status && reconciliationResult.data.status !== 'ok' && (
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm ${
          reconciliationResult.data.status === 'broken' 
            ? 'bg-red-500/10 border-red-500/30 text-red-400' 
            : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
        }`}>
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>
            <strong>Reconciliation {_normalizeLabel(reconciliationResult.data?.status).toUpperCase()}:</strong>{' '}
            {reconciliationResult.data.message || 'Positions may not match fills ledger'}
          </span>
          {reconciliationResult.data.ledger && (
            <span className="ml-auto text-xs opacity-75">
              {reconciliationResult.data.ledger.total_fills} fills tracked
            </span>
          )}
        </div>
      )}

      {/* Risk Discrepancies Warning */}
      {riskResult.data?.has_discrepancies && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-orange-500/10 border border-orange-500/30 text-orange-400 text-sm">
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>
            <strong>Risk Data Discrepancy:</strong>{' '}
            {riskResult.data.risk_discrepancies?.map((d) => `${d.field}: $${d.diff_usd} diff`).join(', ')}
          </span>
        </div>
      )}
      {killSwitchError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>Kill switch failed: {killSwitchError}</span>
          <button type="button" onClick={() => setKillSwitchError(null)} className="ml-auto text-red-400 hover:text-red-300" title="Dismiss" aria-label="Dismiss error">×</button>
        </div>
      )}

      {/* Mode error banner */}
      {modeError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-sm">
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>{modeError}</span>
          <button type="button" onClick={() => setModeError(null)} className="ml-auto" aria-label="Dismiss">×</button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Icon name="briefcase" size={28} className="w-7 h-7 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Kalshi Portfolio
              <KalshiModeBadge />
            </h1>
            <div className="flex items-center gap-3 mt-0.5">
              <p className="text-sm text-gray-400">
                {allPositions.length} positions · {allOrders.length} open orders
              </p>
              {/* Session status */}
              <span className={`flex items-center gap-1 text-xs ${
                sessionOpen ? 'text-green-400' : 'text-gray-500'
              }`}>
                <Icon name="clock" size={12} className="w-3 h-3" />
                {sessionOpen ? 'Session open' : 'Session closed'}
              </span>
              {/* Maintenance indicator */}
              {maintenanceDay && (
                <span className="flex items-center gap-1 text-xs text-amber-400">
                  <Icon name="alert" size={12} className="w-3 h-3" />
                  Maintenance window
                </span>
              )}
              {sessionBlockReason && (
                <span className="flex items-center gap-1 text-xs text-red-400">
                  <Icon name="alert" size={12} className="w-3 h-3" />
                  {sessionBlockReason}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Kill switch quick indicator */}
          {(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-bold animate-pulse">
              <Icon name="shieldOff" size={14} className="w-3.5 h-3.5" />
              KILL ACTIVE
            </span>
          )}

          {/* Paper / Live toggle */}
          <button
            type="button"
            onClick={() => void handleModeToggle()}
            disabled={modeToggling || (ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill)}
            title={isLive ? 'Switch to Paper mode' : liveEnabled ? 'Switch to Live mode' : 'Switch to Live mode (force override available)'}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium transition-all disabled:opacity-50 ${
              isLive
                ? 'bg-green-500/20 border-green-500/40 text-green-300 hover:bg-green-500/30'
                : 'bg-slate-800 border-slate-700 text-gray-400 hover:text-white hover:bg-slate-700'
            }`}
          >
            {isLive
              ? <Icon name="toggleRight" size={16} className="w-4 h-4" />
              : <Icon name="toggleLeft" size={16} className="w-4 h-4" />
            }
            {modeToggling ? 'Switching…' : (currentMode ?? 'UNKNOWN').toUpperCase()}
          </button>

          <button
            type="button"
            onClick={fetchData}
            aria-label="Refresh all portfolio data"
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <Icon name="refresh" size={16} className="w-4 h-4" />
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
            <Icon name="dollarSign" size={16} className="w-4 h-4 text-green-400" />
            <span className="text-xs text-gray-400">Equity</span>
            {isLive && <span className="ml-auto text-[9px] font-bold text-green-400 bg-green-500/20 px-1 rounded">LIVE</span>}
          </div>
          <p className="text-lg font-bold text-white">
            {gridPortfolio?.equity_usd != null
              ? `$${gridPortfolio.equity_usd.toFixed(2)}`
              : balanceUsd != null
                ? `$${balanceUsd.toFixed(2)}`
                : '—'}
          </p>
          <p className="text-xs text-gray-500">Avail: ${balance?.available?.toFixed(2) ?? '—'}</p>
          {balance?.mock && (
            <p className="text-[9px] font-bold text-amber-400 mt-0.5">⚠ MOCK — auth unavailable</p>
          )}
          {summaryReceivedAt != null && (
            <DataAgeBadge
              lastUpdated={new Date(summaryReceivedAt)}
              warningMs={15_000}
              criticalMs={35_000}
              className="mt-0.5 block"
            />
          )}
        </div>
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="trendingUp" size={16} className="w-4 h-4 text-blue-400" />
            <span className="text-xs text-gray-400">Unrealized</span>
          </div>
          <p className={`text-lg font-bold ${(risk?.total_unrealized_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${(risk?.total_unrealized_pnl_usd ?? 0).toFixed(2)}
          </p>
        </div>
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="barChart" size={16} className="w-4 h-4 text-purple-400" />
            <span className="text-xs text-gray-400">Realized PnL</span>
            {gridPortfolio?.daily_pnl_usd != null && risk?.daily_pnl_usd != null &&
              Math.abs(gridPortfolio.daily_pnl_usd - risk.daily_pnl_usd) > 0.01 && (
              <span
                className="ml-auto text-[9px] font-bold text-amber-400 bg-amber-400/10 px-1 rounded"
                title={`Sources differ: grid=$${gridPortfolio.daily_pnl_usd.toFixed(2)} vs risk=$${risk.daily_pnl_usd.toFixed(2)}`}
              >
                ≠ sources
              </span>
            )}
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
            <Icon name="activity" size={16} className="w-4 h-4 text-yellow-400" />
            <span className="text-xs text-gray-400">Notional</span>
          </div>
          <p className="text-lg font-bold text-white">${(risk?.total_notional_usd ?? 0).toFixed(2)}</p>
          <p className="text-xs text-gray-500">
            OI: {gridPortfolio?.open_interest ?? risk?.open_market_count ?? 0} · {risk?.open_market_count ?? 0} markets
          </p>
        </div>
        <div className={`rounded-xl p-4 border ${(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ? 'bg-red-500/5 border-red-500/30' : 'bg-slate-900 border-slate-800'}`}>
          <div className="flex items-center gap-2 mb-1">
            <Icon name="shield" size={16} className={`w-4 h-4 ${(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ? 'text-red-400' : 'text-green-400'}`} />
            <span className="text-xs text-gray-400">Kill Switch</span>
          </div>
          <p className={`text-lg font-bold ${(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ? 'text-red-400' : 'text-green-400'}`}>
            {(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ? 'ACTIVE' : 'OFF'}
          </p>
          {ksResult.data?.kill_reason && (
            <p className="text-[10px] text-red-300 truncate mt-0.5" title={ksResult.data.kill_reason}>{ksResult.data.kill_reason}</p>
          )}
          <button
            type="button"
            onClick={() => handleKillSwitch(!((ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ?? false))}
            className={`mt-1 text-xs px-2 py-0.5 rounded ${
              (ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill)
                ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
            }`}
          >
            {(ksResult.data?.kill_switch_active ?? ksResult.data?.global_kill) ? 'Reset' : 'Activate'}
          </button>
        </div>
      </div>

      {/* Header with Reconciliation Badge */}
      <div className="flex items-center justify-between flex-wrap gap-4 mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold text-white flex items-center gap-2">Kalshi Portfolio <KalshiModeBadge /></h2>
        </div>
        <KalshiReconciliationBadge />
      </div>

      {/* PnL Equity Curve */}
      <KalshiPnlChart />

      {/* Risk & Performance */}
      {riskResult.loading && !risk ? (
        <div className="text-center py-8 text-gray-500">Loading risk data...</div>
      ) : risk ? (
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
              <p className="text-lg font-bold text-white">{risk.daily_trades ?? 0}/day</p>
              <p className="text-xs text-gray-500">Fees: ${(risk.daily_fees_usd ?? 0).toFixed(2)}</p>
            </div>
          </div>

          {/* Circuit Breaker Status */}
          <CircuitBreakerPanel />

          {/* Latency Metrics */}
          <LatencyPanel />

          {/* Order Error Breakdown */}
          <OrderErrorsPanel />

          {/* Category Exposure */}
          {Object.keys(risk.category_notional ?? {}).length > 0 && (
            <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Category Exposure</h3>
              <div className="space-y-2">
                {Object.entries(risk.category_notional ?? {}).map(([cat, notional]) => (
                  <div key={cat} className="flex items-center justify-between">
                    <span className="text-sm text-gray-400 capitalize">{cat}</span>
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-white">${(notional ?? 0).toFixed(2)}</span>
                      <span className="text-xs text-gray-500">
                        {(risk.category_contracts ?? {})[cat] ?? 0} contracts
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
                      disabled={downsizing}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 border border-orange-500/20 transition-colors disabled:opacity-50"
                    >
                      <Icon name="arrowDownRight" size={12} className="w-3 h-3" />
                      {downsizing ? 'Downsizing…' : 'Force Downsize'}
                    </button>
                  )}
                </div>
                {downsizeResult && (
                  <div className="flex items-center gap-2 text-xs text-orange-300 bg-orange-900/20 px-3 py-1.5 rounded">
                    <span>{downsizeResult}</span>
                    <button type="button" onClick={() => setDownsizeResult(null)} className="ml-auto text-orange-400 hover:text-orange-200" aria-label="Dismiss">×</button>
                  </div>
                )}

                {/* Drawdown Tier */}
                <div className="flex items-center gap-3">
                  <Icon name="arrowDownRight" size={16} className="w-4 h-4 text-gray-400" />
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
                      <Icon name="gauge" size={14} className="w-3.5 h-3.5 text-blue-400" />
                      <span className="text-[10px] text-gray-500">Kelly Util</span>
                    </div>
                    <p className="text-sm font-bold text-white">{(s.kelly_utilization_pct ?? 0).toFixed(0)}%</p>
                    <p className="text-[10px] text-gray-600">f={(s.kelly_fraction ?? 0).toFixed(3)}</p>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Icon name="target" size={14} className="w-3.5 h-3.5 text-purple-400" />
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

          {/* Risk Alert Feed */}
          <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
            <h3 className="text-sm font-medium text-gray-300 mb-3">Live Risk Alerts</h3>
            <RiskAlertFeed alerts={wsAlerts} maxVisible={10} onDismiss={() => {
              clearWsAlerts();
            }} />
          </div>

          {/* Recent Breaches */}
          {(risk.recent_breaches ?? []).length > 0 && (
            <div className="bg-slate-900 rounded-xl p-4 border border-red-900/30">
              <div className="flex items-center gap-2 mb-3">
                <Icon name="alert" size={16} className="w-4 h-4 text-red-400" />
                <h3 className="text-sm font-medium text-red-300">Recent Breaches ({(risk.recent_breaches ?? []).length})</h3>
              </div>
              <div className="space-y-2">
                {(risk.recent_breaches ?? []).map((b, i) => (
                  <div key={`${b.ts}-${b.check}-${i}`} className="flex items-start gap-3 text-xs">
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
            onGroupTriggered={() => {
              posResult.refetch();
            }}
          />
          {/* Order Group Analytics */}
          <OrderGroupAnalytics
            histories={(orderGroupsResult.data?.groups || []).map(g => ({
              order_group_id: g.order_group_id,
              name: g.name,
              status: g.status,
              history: [],
              trigger_events: [],
            }))}
            hours={24}
          />
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <Icon name="shield" size={32} className="w-8 h-8 mx-auto mb-2 opacity-50" />
          Risk data unavailable
        </div>
      )}

      {/* Confirm Modal */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        confirmVariant={confirmModal.confirmVariant}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};

export default KalshiPortfolioView;
