/**
 * KalshiVolDashboardView — Volatility Targeting Dashboard (3×2 grid).
 *
 * Layout:
 *   Top row:    [Venue & Mode + Toggle] [Vol Targeting] [Risk Limits]
 *   Middle row: [Agent Grid]            [Equity & Vol Chart]
 *   Bottom row: [Live Alerts]           [AI Insights + Consensus Signals]
 * 
 * Tier 4: KalshiVolDashboardView.tsx Split (929→4 files)
 */

import React, { useMemo, useState } from 'react';
import {
  Gauge, RefreshCw, ToggleLeft, ToggleRight, ArrowRight, ShieldOff,
} from '../ui/icons';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import type { SizingMetrics, KalshiRiskSummary } from '../types/kalshi';
import { ConfirmModal } from '../components/ConfirmModal';
import KalshiBankrollPanel from '../components/KalshiBankrollPanel';
import { TopRowCards } from './KalshiVolDashboard/TopRowCards';
import { MiddleRowPanels } from './KalshiVolDashboard/MiddleRowPanels';
import { BottomRowPanels } from './KalshiVolDashboard/BottomRowPanels';
import type { VolDashHealthStatus, VolDashGridStatus, PnlPoint, LiquidityAlertData, VolumeChange, VolumeAnomaly } from './KalshiVolDashboard/types';

// ── Component ───────────────────────────────────────────────────────────────

const KalshiVolDashboardView: React.FC = () => {
  const slow = { refetchInterval: DEFAULTS.POLLING_INTERVALS.SLOW };
  const verySlow = { refetchInterval: DEFAULTS.POLLING_INTERVALS.SLOW * 2 }; // Reduce polling frequency
  const std  = { refetchInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };

  // ── Data fetches ──────────────────────────────────────────────────────────
  // Critical data - standard polling
  const healthRes   = useApiQuery<VolDashHealthStatus>(API_ENDPOINTS.KALSHI_HEALTH, std);
  const riskRes         = useApiQuery<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, std);
  const modeRes         = useApiQuery<{ mode: string; is_live: boolean; live_enabled: boolean }>(
    API_ENDPOINTS.KALSHI_GRID_MODE, std,
  );
  const killRes         = useApiQuery<{ active: boolean; can_trade: boolean; kill_reason: string | null }>(
    API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, std,
  );

  // Less critical data - slow polling
  const sizingRes       = useApiQuery<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, slow);
  const gridRes         = useApiQuery<VolDashGridStatus>(API_ENDPOINTS.KALSHI_GRID_STATUS, verySlow);
  const consensusRes    = useApiQuery<{
    signals: Array<{ ticker: string; direction: string; confidence: number; vote_count: number; agents: string[] }>;
    consensus_rate: number;
    engine_running: boolean;
  }>(API_ENDPOINTS.KALSHI_CONSENSUS_SIGNALS, verySlow);

  // Alert/volume data - very slow polling (tab-based, not always visible)
  const alertsRes       = useApiQuery<{ alerts: LiquidityAlertData[] }>(API_ENDPOINTS.KALSHI_VOLUME_ALERTS, verySlow);
  const liqAlertsRes    = useApiQuery<{ alerts: LiquidityAlertData[] }>(API_ENDPOINTS.KALSHI_LIQUIDITY_ALERTS, verySlow);
  const volChangesRes   = useApiQuery<{ changes: VolumeChange[] }>(API_ENDPOINTS.KALSHI_VOLUME_CHANGES, verySlow);
  const volAnomaliesRes = useApiQuery<{ anomalies: VolumeAnomaly[] }>(API_ENDPOINTS.KALSHI_VOLUME_ANOMALIES, verySlow);

  // PNL history - very slow polling (chart data)
  const pnlRes          = useApiQuery<{ points: PnlPoint[] }>(API_ENDPOINTS.KALSHI_PNL_HISTORY, verySlow);

  // Sentiment/Vol context - slow polling
  const sentimentVolRes = useApiQuery<{
    assets: Record<string, {
      sentiment: { value: number; regime: string; confidence: number } | null;
      sizing_multiplier: { value: number; regime_label: string; reasoning: string };
    }>;
  }>(API_ENDPOINTS.SENTIMENT_VOL_ASSETS, slow);
  const sentimentVolData = sentimentVolRes.data?.assets ?? {};
  const primarySentiment = sentimentVolData['BTC'] ?? Object.values(sentimentVolData)[0];

  // ── Local state ───────────────────────────────────────────────────────────
  const [alertTab, setAlertTab]     = useState<'alerts' | 'liq-alerts' | 'changes' | 'anomalies'>('alerts');
  const [modeToggling, setModeToggling] = useState(false);
  const [modeError, setModeError]       = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    confirmVariant?: 'primary' | 'danger' | 'warning';
  }>({ isOpen: false, title: '', message: '', onConfirm: () => undefined });

  // ── Derived values ────────────────────────────────────────────────────────
  const health        = healthRes.data;
  const sizing        = sizingRes.data;
  const risk          = riskRes.data;
  const grid          = gridRes.data;
  const alerts        = alertsRes.data?.alerts ?? [];
  const liqAlerts     = liqAlertsRes.data?.alerts ?? [];
  const pnlPoints     = pnlRes.data?.points ?? [];
  const volChanges    = volChangesRes.data?.changes ?? [];
  const volAnomalies  = volAnomaliesRes.data?.anomalies ?? [];
  const consensusSigs = consensusRes.data?.signals ?? [];
  const consensusRate = consensusRes.data?.consensus_rate ?? 0;

  const currentMode = modeRes.data?.mode ?? 'paper';
  const isLive      = modeRes.data?.is_live ?? false;
  const liveEnabled = modeRes.data?.live_enabled ?? false;
  const killActive  = killRes.data?.active === true || risk?.kill_switch_active;
  const canTrade    = killRes.data?.can_trade ?? !killActive;
  const isConnected = health?.ws?.running ?? false;
  const healthColor = health?.status === 'healthy' ? 'text-green-400'
    : health?.status === 'degraded' ? 'text-yellow-400' : 'text-red-400';

  const assetExposure = useMemo(() => {
    if (!risk) return [];
    return Object.entries(risk.category_notional ?? {}).map(([asset, notional]) => ({
      asset,
      notional: notional as number,
      cap: risk.limits?.[`max_${asset}_notional_usd`] ?? risk.limits?.max_notional_usd ?? 1000,
    }));
  }, [risk]);

  // ── Mode toggle ───────────────────────────────────────────────────────────
  const handleModeToggle = async () => {
    const targetMode = isLive ? 'paper' : 'live';
    const needForce = targetMode === 'live' && !liveEnabled;
    
    if (needForce) {
      setConfirmModal({
        isOpen: true,
        title: 'Force Live Mode Override',
        message: 'MERID_PM_LIVE_ENABLED is not set.\n\nForce switch to LIVE mode anyway? Real orders will be placed on Kalshi.',
        confirmVariant: 'warning',
        onConfirm: () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          // Second confirmation
          setConfirmModal({
            isOpen: true,
            title: 'Switch to LIVE Trading',
            message: '⚠️ Switch to LIVE trading?\n\nReal orders with real funds. Confirm risk parameters are correct.\n\nContinue?',
            confirmVariant: 'danger',
            onConfirm: async () => {
              setConfirmModal(prev => ({ ...prev, isOpen: false }));
              await executeModeSwitch(targetMode, true);
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
        message: '⚠️ Switch to LIVE trading?\n\nReal orders with real funds. Confirm risk parameters are correct.\n\nContinue?',
        confirmVariant: 'danger',
        onConfirm: async () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          await executeModeSwitch(targetMode, false);
        },
      });
      return;
    }
    
    // Switch to paper (no confirmation needed)
    await executeModeSwitch(targetMode, false);
  };

  const executeModeSwitch = async (targetMode: string, force: boolean) => {
    setModeToggling(true);
    setModeError(null);
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
        body: JSON.stringify({ mode: targetMode, force }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setModeError((err as { detail?: string }).detail ?? `Switch to ${targetMode} failed`);
      } else {
        modeRes.refetch();
        healthRes.refetch();
      }
    } catch {
      setModeError('Network error during mode switch');
    } finally {
      setModeToggling(false);
    }
  };

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />

      {/* Continuous trader bankroll */}
      <KalshiBankrollPanel />

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Gauge className="w-7 h-7 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Kalshi Vol Dashboard <KalshiModeBadge />
            </h1>
            <p className="text-sm text-gray-400">
              Volatility targeting, risk limits & AI insights
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Kill switch indicator */}
          {killActive && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 text-xs font-bold animate-pulse">
              <ShieldOff className="w-4 h-4" />
              KILL SWITCH ACTIVE
            </div>
          )}

          {/* Paper ↔ Live toggle */}
          <div className="flex flex-col items-end gap-0.5">
            <button
              type="button"
              onClick={handleModeToggle}
              disabled={modeToggling || !!killActive}
              title={
                isLive ? 'Switch to Paper mode'
                : liveEnabled ? 'Switch to Live mode'
                : 'Switch to Live mode (force override — MERID_PM_LIVE_ENABLED not set)'
              }
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium border transition-all disabled:opacity-50 ${
                isLive
                  ? 'bg-green-500/20 border-green-500/40 text-green-400 hover:bg-green-500/30'
                  : 'bg-amber-500/20 border-amber-500/40 text-amber-400 hover:bg-amber-500/30'
              }`}
            >
              {isLive ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
              {modeToggling ? 'Switching…' : isLive ? 'LIVE — click for Paper' : 'PAPER — click for Live'}
            </button>
            {modeError && (
              <span className="text-[10px] text-red-400 max-w-[240px] text-right">{modeError}</span>
            )}
          </div>

          <button
            type="button"
            onClick={() => {
              healthRes.refetch(); sizingRes.refetch(); riskRes.refetch();
              gridRes.refetch(); modeRes.refetch(); consensusRes.refetch();
              sentimentVolRes.refetch();
            }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* ═══ SENTIMENT CONTEXT STRIP ═══ */}
      {primarySentiment && (
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-800 flex items-center gap-4 flex-wrap">
          {/* FGI Mini Gauge */}
          <div className="flex items-center gap-2">
            {primarySentiment.sentiment && (
              <>
                <div className={`w-2 h-2 rounded-full ${
                  primarySentiment.sentiment.value <= 25 ? 'bg-red-500' :
                  primarySentiment.sentiment.value <= 45 ? 'bg-orange-500' :
                  primarySentiment.sentiment.value <= 55 ? 'bg-slate-400' :
                  primarySentiment.sentiment.value <= 80 ? 'bg-green-500' :
                  'bg-emerald-500'
                }`} />
                <span className="text-sm font-bold text-white">{(primarySentiment.sentiment.value ?? 0).toFixed(0)}</span>
                <span className={`text-xs ${
                  primarySentiment.sentiment.regime.includes('FEAR') ? 'text-red-400' :
                  primarySentiment.sentiment.regime.includes('GREED') ? 'text-green-400' :
                  'text-slate-400'
                }`}>
                  {primarySentiment.sentiment.regime.replace('_', ' ')}
                </span>
              </>
            )}
          </div>

          {/* Divider */}
          <div className="h-6 w-px bg-slate-700" />

          {/* Sizing Multiplier */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Sizing:</span>
            <span className={`text-sm font-bold ${
              primarySentiment.sizing_multiplier.value < 0.5 ? 'text-red-400' :
              primarySentiment.sizing_multiplier.value < 0.8 ? 'text-amber-400' :
              'text-green-400'
            }`}>
              {(primarySentiment.sizing_multiplier.value ?? 0).toFixed(2)}×
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
              primarySentiment.sizing_multiplier.regime_label === 'HALTED' ? 'bg-red-500/20 text-red-400' :
              primarySentiment.sizing_multiplier.regime_label === 'CAUTION' ? 'bg-amber-500/20 text-amber-400' :
              'bg-green-500/20 text-green-400'
            }`}>
              {primarySentiment.sizing_multiplier.regime_label}
            </span>
          </div>

          {/* Reasoning */}
          <span className="text-xs text-slate-400 flex-1 truncate">
            {primarySentiment.sizing_multiplier.reasoning}
          </span>

          {/* Links */}
          <div className="flex items-center gap-2 ml-auto">
            <a href="#/kalshi-sentiment" className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
              Sentiment <ArrowRight className="w-3 h-3" />
            </a>
            <a href="#/kalshi-risk-context" className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1">
              Risk Context <ArrowRight className="w-3 h-3" />
            </a>
          </div>
        </div>
      )}

      {/* ═══ TOP ROW ═══ */}
      <TopRowCards
        health={health ?? undefined}
        risk={risk ?? undefined}
        sizing={sizing ?? undefined}
        killActive={killActive ?? false}
        canTrade={canTrade ?? true}
        killReason={killRes.data?.kill_reason ?? risk?.kill_switch_reason ?? null}
        currentMode={currentMode}
        isConnected={isConnected}
        healthColor={healthColor}
        gridAgentCount={grid?.agent_count ?? 0}
        assetExposure={assetExposure}
      />

      {/* ═══ MIDDLE ROW ═══ */}
      <MiddleRowPanels
        grid={grid ?? undefined}
        sizing={sizing ?? undefined}
        pnlPoints={pnlPoints}
        consensusRate={consensusRate}
        engineRunning={consensusRes.data?.engine_running ?? false}
      />

      {/* ═══ BOTTOM ROW ═══ */}
      <BottomRowPanels
        alertTab={alertTab}
        setAlertTab={setAlertTab}
        alerts={alerts}
        liqAlerts={liqAlerts}
        volChanges={volChanges}
        volAnomalies={volAnomalies}
        consensusSigs={consensusSigs}
        consensusRate={consensusRate}
      />

      {/* ═══ PIPELINE ROW ═══ */}
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

export default KalshiVolDashboardView;
