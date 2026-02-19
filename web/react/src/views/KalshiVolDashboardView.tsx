/**
 * KalshiVolDashboardView — Volatility Targeting Dashboard (3×2 grid).
 *
 * Layout:
 *   Top row:    [Venue & Mode + Toggle] [Vol Targeting] [Risk Limits]
 *   Middle row: [Agent Grid]            [Equity & Vol Chart]
 *   Bottom row: [Live Alerts]           [AI Insights + Consensus Signals]
 */

import React, { useMemo, useState } from 'react';
import {
  Shield, Gauge, Target, TrendingUp,
  AlertTriangle, BarChart3, RefreshCw,
  Wifi, WifiOff, AlertCircle, Activity, Zap,
  ShieldOff, ToggleLeft, ToggleRight, Bot,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiInsightsPanel from '../components/KalshiInsightsPanel';
import PublishPipelinePanel from '../components/PublishPipelinePanel';
import type { SizingMetrics, KalshiRiskSummary } from '../types/kalshi';

// ── Interfaces ──────────────────────────────────────────────────────────────

interface HealthStatus {
  status: string;
  issues: string[];
  catalog: { market_count: number };
  risk: { kill_switch: boolean; daily_pnl: number; drawdown_pct: number };
  ws: { running: boolean; events_forwarded: number; subscribed_tickers: number };
  rate_limits: { orders_this_minute: number; max_per_minute: number; orders_this_hour: number; max_per_hour: number };
}


interface GridAgent {
  name: string;
  asset: string;
  timeframe: string;
  status: string;
  cycles: number;
  pf: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  size_factor: number;
  win_rate?: number;
  errors?: number;
  fills?: number;
  active_tickers?: string[];
}

interface GridStatus {
  agent_count: number;
  agents: GridAgent[];
}

interface LiquidityAlertData {
  market_id: string;
  kind: string;
  severity: string;
  msg: string;
  ts: number;
}

interface VolumeChange {
  ticker: string;
  prev_volume: number;
  curr_volume: number;
  change_pct: number;
  direction: 'up' | 'down';
  ts: string;
}

interface VolumeAnomaly {
  ticker: string;
  z_score: number;
  volume: number;
  baseline_volume: number;
  severity: 'low' | 'medium' | 'high';
  ts: string;
}

interface PnlPoint {
  ts: string;
  equity: number;
  realized_vol: number;
  target_vol: number;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const TIER_COLORS: Record<string, { text: string; bg: string }> = {
  normal: { text: 'text-green-400', bg: 'bg-green-500/20' },
  warning: { text: 'text-yellow-400', bg: 'bg-yellow-500/20' },
  downsize: { text: 'text-orange-400', bg: 'bg-orange-500/20' },
  halt: { text: 'text-red-400', bg: 'bg-red-500/20' },
};

function pctBar(value: number, max: number, color: string) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// ── Component ───────────────────────────────────────────────────────────────

const KalshiVolDashboardView: React.FC = () => {
  const slow = { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW };
  const std  = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };

  // ── Data fetches ──────────────────────────────────────────────────────────
  const healthRes       = useApiData<HealthStatus>(API_ENDPOINTS.KALSHI_HEALTH, std);
  const sizingRes       = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, slow);
  const riskRes         = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, std);
  const gridRes         = useApiData<GridStatus>(API_ENDPOINTS.KALSHI_GRID_STATUS, std);
  const alertsRes       = useApiData<{ alerts: LiquidityAlertData[] }>(API_ENDPOINTS.KALSHI_VOLUME_ALERTS, slow);
  const liqAlertsRes    = useApiData<{ alerts: LiquidityAlertData[] }>(API_ENDPOINTS.KALSHI_LIQUIDITY_ALERTS, slow);
  const pnlRes          = useApiData<{ points: PnlPoint[] }>(API_ENDPOINTS.KALSHI_PNL_HISTORY, slow);
  const volChangesRes   = useApiData<{ changes: VolumeChange[] }>(API_ENDPOINTS.KALSHI_VOLUME_CHANGES, slow);
  const volAnomaliesRes = useApiData<{ anomalies: VolumeAnomaly[] }>(API_ENDPOINTS.KALSHI_VOLUME_ANOMALIES, slow);
  const modeRes         = useApiData<{ mode: string; is_live: boolean; live_enabled: boolean }>(
    API_ENDPOINTS.KALSHI_GRID_MODE, std,
  );
  const consensusRes    = useApiData<{
    signals: Array<{ ticker: string; direction: string; confidence: number; vote_count: number; agents: string[] }>;
    consensus_rate: number;
    engine_running: boolean;
  }>(API_ENDPOINTS.KALSHI_CONSENSUS_SIGNALS, slow);
  const killRes         = useApiData<{ state: string; can_trade: boolean; kill_reason: string | null }>(
    API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, std,
  );

  // ── Local state ───────────────────────────────────────────────────────────
  const [alertTab, setAlertTab]     = useState<'alerts' | 'liq-alerts' | 'changes' | 'anomalies'>('alerts');
  const [modeToggling, setModeToggling] = useState(false);
  const [modeError, setModeError]       = useState<string | null>(null);

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
  const latestPnlPoint = pnlPoints.length > 0 ? pnlPoints[pnlPoints.length - 1] : null;

  const currentMode = modeRes.data?.mode ?? 'paper';
  const isLive      = modeRes.data?.is_live ?? false;
  const liveEnabled = modeRes.data?.live_enabled ?? false;
  const killActive  = killRes.data?.state === 'triggered' || risk?.kill_switch_active;
  const canTrade    = killRes.data?.can_trade ?? !killActive;
  const isConnected = health?.ws?.running ?? false;
  const healthColor = health?.status === 'healthy' ? 'text-green-400'
    : health?.status === 'degraded' ? 'text-yellow-400' : 'text-red-400';

  const assetExposure = useMemo(() => {
    if (!risk) return [];
    return Object.entries(risk.category_notional).map(([asset, notional]) => ({
      asset,
      notional,
      contracts: risk.category_contracts[asset] ?? 0,
      cap: risk.limits?.[`max_${asset}_notional_usd`] ?? risk.limits?.max_total_notional_usd ?? 1000,
    }));
  }, [risk]);

  const tierStyle       = TIER_COLORS[sizing?.drawdown_tier ?? 'normal'] ?? TIER_COLORS.normal;
  const dailyPnlUsd     = typeof risk?.daily_pnl_usd === 'number'
    ? risk.daily_pnl_usd
    : (typeof risk?.daily_total_pnl_usd === 'number' ? risk.daily_total_pnl_usd : 0);
  const drawdownPct     = typeof risk?.drawdown_pct === 'number' ? risk.drawdown_pct : 0;
  const totalNotionalUsd = typeof risk?.total_notional_usd === 'number' ? risk.total_notional_usd : 0;
  const maxDailyLoss    = risk?.limits?.max_daily_loss_usd ?? 500;
  const maxNotional     = risk?.limits?.max_total_notional_usd ?? 10000;
  const drawdownHalt    = (risk?.limits?.drawdown_halt_pct ?? 0.15) * 100;

  // ── Mode toggle ───────────────────────────────────────────────────────────
  const handleModeToggle = async () => {
    const targetMode = isLive ? 'paper' : 'live';
    if (targetMode === 'live' && !liveEnabled) {
      setModeError('Live mode requires MERID_PM_LIVE_ENABLED=true in environment');
      return;
    }
    setModeToggling(true);
    setModeError(null);
    try {
      const res = await fetch(API_ENDPOINTS.KALSHI_GRID_MODE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: targetMode, force: false }),
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
                : 'Live mode requires MERID_PM_LIVE_ENABLED=true'
              }
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium border transition-all disabled:opacity-50 ${
                isLive
                  ? 'bg-green-500/20 border-green-500/40 text-green-400 hover:bg-green-500/30'
                  : liveEnabled
                    ? 'bg-amber-500/20 border-amber-500/40 text-amber-400 hover:bg-amber-500/30'
                    : 'bg-slate-800 border-slate-700 text-slate-500 cursor-not-allowed'
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
            }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* ═══ TOP ROW ═══ */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* 1. Venue & Mode Card */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            {isConnected ? <Wifi className="w-4 h-4 text-green-400" /> : <WifiOff className="w-4 h-4 text-red-400" />}
            <h3 className="text-sm font-medium text-gray-300">Venue Status</h3>
            <span className={`ml-auto text-xs font-bold ${healthColor}`}>
              {health?.status?.toUpperCase() ?? 'UNKNOWN'}
            </span>
          </div>

          {/* Trading gate status */}
          {killActive || !canTrade ? (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/20 border border-red-500/30 text-[10px] text-red-400 font-medium">
              <ShieldOff className="w-3 h-3 shrink-0" />
              Kill switch — {killRes.data?.kill_reason ?? risk?.kill_switch_reason ?? 'manual'}
            </div>
          ) : (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-green-500/10 border border-green-500/20 text-[10px] text-green-400">
              <Shield className="w-3 h-3 shrink-0" />
              Trading enabled — {currentMode.toUpperCase()} mode
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-gray-500">WS Events</span>
              <p className="text-white font-mono">{health?.ws?.events_forwarded?.toLocaleString() ?? 0}</p>
            </div>
            <div>
              <span className="text-gray-500">Tickers</span>
              <p className="text-white font-mono">{health?.ws?.subscribed_tickers ?? 0}</p>
            </div>
            <div>
              <span className="text-gray-500">Rate /min</span>
              <p className={`font-mono ${
                (health?.rate_limits?.orders_this_minute ?? 0) >= 25 ? 'text-red-400' :
                (health?.rate_limits?.orders_this_minute ?? 0) >= 15 ? 'text-yellow-400' : 'text-white'
              }`}>
                {health?.rate_limits?.orders_this_minute ?? 0}/{health?.rate_limits?.max_per_minute ?? 30}
              </p>
            </div>
            <div>
              <span className="text-gray-500">Markets</span>
              <p className="text-white font-mono">{health?.catalog?.market_count ?? 0}</p>
            </div>
            <div>
              <span className="text-gray-500">Agents</span>
              <p className="text-white font-mono">{grid?.agent_count ?? 0} active</p>
            </div>
            <div>
              <span className="text-gray-500">Daily Trades</span>
              <p className="text-white font-mono">{risk?.daily_trades ?? 0}</p>
            </div>
          </div>

          {/* Hourly rate bar */}
          <div className="space-y-0.5">
            <div className="flex justify-between text-[10px] text-gray-500">
              <span>Orders/hr</span>
              <span>{health?.rate_limits?.orders_this_hour ?? 0} / {health?.rate_limits?.max_per_hour ?? 1800}</span>
            </div>
            {pctBar(
              health?.rate_limits?.orders_this_hour ?? 0,
              health?.rate_limits?.max_per_hour ?? 1800,
              (health?.rate_limits?.orders_this_hour ?? 0) >= 1440 ? 'bg-red-500' : 'bg-cyan-500',
            )}
          </div>

          {health?.issues && health.issues.length > 0 && (
            <div className="flex items-start gap-1.5 text-[10px] text-yellow-400">
              <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
              <span>{health.issues.slice(0, 2).join(' · ')}</span>
            </div>
          )}
        </div>

        {/* 2. Volatility Targeting Card */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-purple-400" />
            <h3 className="text-sm font-medium text-gray-300">Vol Targeting</h3>
            {sizing && (
              <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-bold ${tierStyle.text} ${tierStyle.bg}`}>
                {sizing.drawdown_tier.toUpperCase()}
              </span>
            )}
          </div>

          {sizing ? (
            <>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-gray-500">Target Vol</span>
                  <p className="text-white font-mono">{(sizing.target_vol * 100).toFixed(1)}%</p>
                </div>
                <div>
                  <span className="text-gray-500">Realized Vol</span>
                  <p className={`font-mono ${sizing.realized_vol > sizing.target_vol ? 'text-red-400' : 'text-green-400'}`}>
                    {(sizing.realized_vol * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <span className="text-gray-500">Kelly f</span>
                  <p className="text-white font-mono">{sizing.kelly_fraction.toFixed(3)}</p>
                </div>
                <div>
                  <span className="text-gray-500">Kelly Util</span>
                  <p className="text-white font-mono">{sizing.kelly_utilization_pct.toFixed(0)}%</p>
                </div>
                <div>
                  <span className="text-gray-500">Vol Scale</span>
                  <p className="text-white font-mono">{sizing.vol_scale.toFixed(2)}×</p>
                </div>
                <div>
                  <span className="text-gray-500">ATR</span>
                  <p className="text-white font-mono">{sizing.atr_value.toFixed(0)}</p>
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-[10px]">
                  <span className="text-gray-500">Effective Fraction</span>
                  <span className="text-white font-mono">{(sizing.effective_fraction * 100).toFixed(2)}%</span>
                </div>
                {pctBar(sizing.effective_fraction * 100, 5, 'bg-purple-500')}
              </div>
            </>
          ) : (
            <p className="text-xs text-gray-500">Loading sizing data...</p>
          )}
        </div>

        {/* 3. Risk Limits Card */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <Shield className={`w-4 h-4 ${risk?.kill_switch_active ? 'text-red-400' : 'text-green-400'}`} />
            <h3 className="text-sm font-medium text-gray-300">Risk Limits</h3>
          </div>

          {risk ? (
            <>
              {/* Daily PnL gauge */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Daily PnL</span>
                  <span className={`font-mono ${dailyPnlUsd >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${dailyPnlUsd.toFixed(2)}
                    <span className="text-gray-600 ml-1">/ -${maxDailyLoss.toFixed(0)}</span>
                  </span>
                </div>
                {pctBar(
                  Math.abs(dailyPnlUsd),
                  maxDailyLoss,
                  dailyPnlUsd >= 0 ? 'bg-green-500' : 'bg-red-500',
                )}
              </div>

              {/* Drawdown gauge */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Drawdown</span>
                  <span className={`font-mono ${drawdownPct < 5 ? 'text-green-400' : drawdownPct < 10 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {drawdownPct.toFixed(1)}%
                    <span className="text-gray-600 ml-1">/ {drawdownHalt.toFixed(0)}% halt</span>
                  </span>
                </div>
                {pctBar(drawdownPct, drawdownHalt, 'bg-orange-500')}
              </div>

              {/* Notional gauge */}
              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Notional</span>
                  <span className="text-white font-mono">${totalNotionalUsd.toFixed(0)}
                    <span className="text-gray-600 ml-1">/ ${maxNotional.toFixed(0)}</span>
                  </span>
                </div>
                {pctBar(totalNotionalUsd, maxNotional, 'bg-blue-500')}
              </div>

              {/* Per-asset exposure */}
              {assetExposure.length > 0 && (
                <div className="space-y-1.5 pt-1">
                  <span className="text-[10px] text-gray-500 uppercase tracking-wider">Per-Asset Exposure</span>
                  {assetExposure.map(a => (
                    <div key={a.asset} className="flex items-center gap-2 text-[10px]">
                      <span className="text-gray-400 w-14 capitalize">{a.asset}</span>
                      <div className="flex-1">
                        {pctBar(a.notional, a.cap, 'bg-cyan-500')}
                      </div>
                      <span className="text-gray-500 font-mono w-16 text-right">${a.notional.toFixed(0)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-gray-500">Loading risk data...</p>
          )}
        </div>
      </div>

      {/* ═══ MIDDLE ROW ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* 4. Agent Performance Grid */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
            <BarChart3 className="w-4 h-4 text-orange-400" />
            <h3 className="text-sm font-medium text-gray-300">Agent Performance Grid</h3>
            <span className="ml-auto text-[10px] text-gray-500">{grid?.agent_count ?? 0} agents</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-gray-500 text-[10px] uppercase">
                  <th className="text-left p-2 pl-4">Agent</th>
                  <th className="text-right p-2">WR%</th>
                  <th className="text-right p-2">PF</th>
                  <th className="text-right p-2">Sharpe</th>
                  <th className="text-right p-2">Fills</th>
                  <th className="text-right p-2 pr-4">Size f</th>
                </tr>
              </thead>
              <tbody>
                {(!grid?.agents || grid.agents.length === 0) ? (
                  <tr><td colSpan={6} className="text-center py-6 text-gray-500">
                    No agents running — start the grid from Overview
                  </td></tr>
                ) : (
                  grid.agents.map(a => (
                    <tr key={a.name} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-2 pl-4">
                        <div className="flex items-center gap-1.5">
                          <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                            a.status === 'running' ? 'bg-green-400 animate-pulse' :
                            a.status === 'paused' ? 'bg-yellow-400' : 'bg-gray-500'
                          }`} />
                          <div>
                            <div className="text-white font-mono text-[11px]">{a.asset}/{a.timeframe}</div>
                            {a.errors != null && a.errors > 0 && (
                              <div className="text-[9px] text-red-400">{a.errors} err</div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className={`p-2 text-right font-mono ${
                        (a.win_rate ?? 0) >= 55 ? 'text-green-400' :
                        (a.win_rate ?? 0) >= 45 ? 'text-yellow-400' : 'text-red-400'
                      }`}>
                        {((a.win_rate ?? 0)).toFixed(0)}%
                      </td>
                      <td className={`p-2 text-right font-mono ${
                        (a.pf ?? 0) >= 1.5 ? 'text-green-400' :
                        (a.pf ?? 0) >= 1.0 ? 'text-yellow-400' : 'text-red-400'
                      }`}>
                        {(a.pf ?? 0).toFixed(2)}
                      </td>
                      <td className="p-2 text-right font-mono text-blue-400">{(a.sharpe ?? 0).toFixed(2)}</td>
                      <td className="p-2 text-right font-mono text-gray-300">{a.fills ?? a.cycles ?? 0}</td>
                      <td className="p-2 pr-4 text-right font-mono text-white">{(a.size_factor ?? 0).toFixed(2)}×</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {/* Swarm consensus rate footer */}
          {consensusRes.data && (
            <div className="px-4 py-2 border-t border-slate-800 flex items-center gap-3 text-[10px] text-gray-500">
              <Bot className="w-3 h-3" />
              <span>Swarm consensus rate: <span className="text-white font-mono">{(consensusRate * 100).toFixed(0)}%</span></span>
              <span className="ml-auto">{consensusRes.data.engine_running ? (
                <span className="text-green-400">engine running</span>
              ) : (
                <span className="text-gray-600">engine offline</span>
              )}</span>
            </div>
          )}
        </div>

        {/* 5. Equity & Vol Chart */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-green-400" />
            <h3 className="text-sm font-medium text-gray-300">Equity & Vol</h3>
            {sizing && (
              <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-bold ${tierStyle.text} ${tierStyle.bg}`}>
                {sizing.drawdown_tier.toUpperCase()}
              </span>
            )}
          </div>

          {pnlPoints.length > 0 ? (
            <>
              {/* Sparkline with drawdown-tier color shading */}
              <div className="flex items-end gap-px h-20 relative">
                {pnlPoints.slice(-40).map((p, i) => {
                  const slice = pnlPoints.slice(-40);
                  const max = Math.max(...slice.map(pp => pp.equity));
                  const min = Math.min(...slice.map(pp => pp.equity));
                  const range = max - min || 1;
                  const h = ((p.equity - min) / range) * 100;
                  const base = pnlPoints[0]?.equity ?? 0;
                  const tier = sizing?.drawdown_tier ?? 'normal';
                  const barColor =
                    tier === 'halt' ? 'bg-red-500/70' :
                    tier === 'downsize' ? 'bg-orange-500/70' :
                    tier === 'warning' ? 'bg-yellow-500/70' :
                    p.equity >= base ? 'bg-green-500/60' : 'bg-red-500/60';
                  return (
                    <div
                      key={i}
                      className={`flex-1 rounded-sm ${barColor} transition-all`}
                      style={{ height: `${Math.max(4, h)}%` }}
                      title={`${p.ts}: $${p.equity.toFixed(2)} | rvol=${((p.realized_vol ?? 0)*100).toFixed(1)}%`}
                    />
                  );
                })}
              </div>

              {/* Vol overlay bars */}
              <div className="space-y-1">
                <div className="flex justify-between text-[10px] text-gray-500">
                  <span>Realized Vol</span>
                  <span className={`font-mono ${
                    (latestPnlPoint?.realized_vol ?? 0) > (latestPnlPoint?.target_vol ?? 0.15)
                      ? 'text-red-400' : 'text-green-400'
                  }`}>{((latestPnlPoint?.realized_vol ?? 0) * 100).toFixed(1)}%</span>
                </div>
                {pctBar(
                  (latestPnlPoint?.realized_vol ?? 0) * 100,
                  (latestPnlPoint?.target_vol ?? sizing?.target_vol ?? 0.15) * 200,
                  (latestPnlPoint?.realized_vol ?? 0) > (latestPnlPoint?.target_vol ?? 0.15)
                    ? 'bg-red-500' : 'bg-green-500',
                )}
                <div className="flex justify-between text-[10px] text-gray-500">
                  <span>Target Vol</span>
                  <span className="font-mono text-purple-400">{((latestPnlPoint?.target_vol ?? sizing?.target_vol ?? 0) * 100).toFixed(1)}%</span>
                </div>
              </div>

              {/* Summary stats */}
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <span className="text-gray-500">Equity</span>
                  <p className={`font-mono ${
                    (latestPnlPoint?.equity ?? 0) >= (pnlPoints[0]?.equity ?? 0)
                      ? 'text-green-400' : 'text-red-400'
                  }`}>${(latestPnlPoint?.equity ?? 0).toFixed(2)}</p>
                </div>
                <div>
                  <span className="text-gray-500">Vol Scale</span>
                  <p className="text-white font-mono">{(sizing?.vol_scale ?? 1).toFixed(2)}×</p>
                </div>
                <div>
                  <span className="text-gray-500">Kelly Util</span>
                  <p className="text-white font-mono">{(sizing?.kelly_utilization_pct ?? 0).toFixed(0)}%</p>
                </div>
              </div>

              {/* Risk-adj metrics */}
              {sizing && (
                <div className="flex items-center gap-3 text-[10px] pt-1 border-t border-slate-800 flex-wrap">
                  <span className="text-gray-500">Risk-Adj:</span>
                  <span>Sharpe <span className="font-mono text-blue-400">{sizing.sharpe_ratio.toFixed(2)}</span></span>
                  <span>Sortino <span className="font-mono text-purple-400">{sizing.sortino_ratio.toFixed(2)}</span></span>
                  <span>Calmar <span className="font-mono text-teal-400">{sizing.calmar_ratio.toFixed(2)}</span></span>
                  <span>WR <span className="font-mono text-white">{sizing.win_rate_pct.toFixed(0)}%</span></span>
                  <span>PF <span className="font-mono text-white">{sizing.profit_factor.toFixed(2)}</span></span>
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-24 gap-2 text-xs text-gray-500">
              <TrendingUp className="w-6 h-6 opacity-30" />
              No PnL history yet — trades will populate this chart
            </div>
          )}
        </div>
      </div>

      {/* ═══ BOTTOM ROW ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* 6. Volume & Alerts Panel */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          {/* Tab bar */}
          <div className="flex items-center gap-0 border-b border-slate-800">
            {([
              { id: 'alerts',     label: 'Vol Alerts',  icon: AlertCircle,   count: alerts.length },
              { id: 'liq-alerts', label: 'Liq Alerts',  icon: AlertTriangle, count: liqAlerts.length },
              { id: 'changes',    label: 'Changes',     icon: Activity,      count: volChanges.length },
              { id: 'anomalies',  label: 'Anomalies',   icon: Zap,           count: volAnomalies.length },
            ] as const).map(t => (
              <button
                key={t.id}
                type="button"
                onClick={() => setAlertTab(t.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                  alertTab === t.id
                    ? 'border-orange-400 text-orange-400'
                    : 'border-transparent text-gray-500 hover:text-gray-300'
                }`}
              >
                <t.icon className="w-3 h-3" />
                {t.label}
                {t.count > 0 && (
                  <span className="px-1 py-0.5 rounded text-[9px] bg-slate-700 text-gray-400">{t.count}</span>
                )}
              </button>
            ))}
          </div>

          <div className="max-h-[240px] overflow-y-auto divide-y divide-slate-800/50">
            {/* Liquidity Alerts tab */}
            {alertTab === 'alerts' && (
              alerts.length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-gray-500">No liquidity alerts. Book health is good.</div>
              ) : (
                alerts.slice(-30).reverse().map((a, i) => (
                  <div key={i} className="px-4 py-2 flex items-start gap-2">
                    <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${a.severity === 'critical' ? 'text-red-400' : 'text-yellow-400'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono text-gray-400">{a.market_id}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          a.kind === 'wide_spread' ? 'bg-orange-500/20 text-orange-400' :
                          a.kind === 'thin_book' ? 'bg-red-500/20 text-red-400' :
                          a.kind === 'spread_spike' ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-blue-500/20 text-blue-400'
                        }`}>{a.kind.replace('_', ' ')}</span>
                      </div>
                      <p className="text-[11px] text-gray-400 mt-0.5">{a.msg}</p>
                    </div>
                    <span className="text-[10px] text-gray-600 shrink-0">{new Date(a.ts * 1000).toLocaleTimeString()}</span>
                  </div>
                ))
              )
            )}

            {/* Liquidity Alerts tab */}
            {alertTab === 'liq-alerts' && (
              liqAlerts.length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-gray-500">No liquidity alerts active.</div>
              ) : (
                liqAlerts.slice(-30).reverse().map((a, i) => (
                  <div key={i} className="px-4 py-2 flex items-start gap-2">
                    <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${a.severity === 'critical' ? 'text-red-400' : 'text-yellow-400'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono text-gray-400">{a.market_id}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          a.severity === 'critical' ? 'bg-red-500/20 text-red-400' :
                          'bg-yellow-500/20 text-yellow-400'
                        }`}>{a.kind.replace(/_/g, ' ')}</span>
                      </div>
                      <p className="text-[11px] text-gray-400 mt-0.5">{a.msg}</p>
                    </div>
                    <span className="text-[10px] text-gray-600 shrink-0">{new Date(a.ts * 1000).toLocaleTimeString()}</span>
                  </div>
                ))
              )
            )}

            {/* Volume Changes tab */}
            {alertTab === 'changes' && (
              volChanges.length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-gray-500">No volume changes detected.</div>
              ) : (
                volChanges.slice(0, 30).map((c, i) => (
                  <div key={i} className="px-4 py-2 flex items-center gap-3">
                    <Activity className={`w-3 h-3 shrink-0 ${c.direction === 'up' ? 'text-green-400' : 'text-red-400'}`} />
                    <span className="text-[10px] font-mono text-white w-28 truncate">{c.ticker}</span>
                    <span className={`text-[10px] font-mono font-bold ${
                      c.direction === 'up' ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {c.direction === 'up' ? '+' : ''}{c.change_pct.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-gray-500 ml-auto">
                      {c.curr_volume.toLocaleString()} ct
                    </span>
                    <span className="text-[10px] text-gray-600">{new Date(c.ts).toLocaleTimeString()}</span>
                  </div>
                ))
              )
            )}

            {/* Volume Anomalies tab */}
            {alertTab === 'anomalies' && (
              volAnomalies.length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-gray-500">No volume anomalies detected.</div>
              ) : (
                volAnomalies.slice(0, 30).map((a, i) => (
                  <div key={i} className="px-4 py-2 flex items-center gap-3">
                    <Zap className={`w-3 h-3 shrink-0 ${
                      a.severity === 'high' ? 'text-red-400' :
                      a.severity === 'medium' ? 'text-yellow-400' : 'text-blue-400'
                    }`} />
                    <span className="text-[10px] font-mono text-white w-28 truncate">{a.ticker}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      a.severity === 'high' ? 'bg-red-500/20 text-red-400' :
                      a.severity === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-blue-500/20 text-blue-400'
                    }`}>{a.severity}</span>
                    <span className="text-[10px] text-gray-400 font-mono">z={a.z_score.toFixed(1)}</span>
                    <span className="text-[10px] text-gray-500 ml-auto">{a.volume.toLocaleString()} ct</span>
                    <span className="text-[10px] text-gray-600">{new Date(a.ts).toLocaleTimeString()}</span>
                  </div>
                ))
              )
            )}
          </div>
        </div>

        {/* 7. AI Insights + Consensus Signals */}
        <div className="space-y-4">
          <KalshiInsightsPanel />

          {/* Consensus Signals from swarm */}
          {consensusSigs.length > 0 && (
            <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
                <Bot className="w-4 h-4 text-violet-400" />
                <h3 className="text-sm font-medium text-gray-300">Swarm Consensus Signals</h3>
                <span className="ml-auto text-[10px] text-gray-500">
                  {consensusSigs.length} active · {(consensusRate * 100).toFixed(0)}% rate
                </span>
              </div>
              <div className="divide-y divide-slate-800/50 max-h-[200px] overflow-y-auto">
                {consensusSigs.slice(0, 10).map((sig, i) => (
                  <div key={i} className="px-4 py-2 flex items-center gap-3">
                    <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      sig.direction === 'bullish' ? 'bg-green-400' :
                      sig.direction === 'bearish' ? 'bg-red-400' : 'bg-gray-500'
                    }`} />
                    <span className="text-[11px] font-mono text-white truncate flex-1">{sig.ticker}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      sig.direction === 'bullish' ? 'bg-green-500/20 text-green-400' :
                      sig.direction === 'bearish' ? 'bg-red-500/20 text-red-400' :
                      'bg-slate-700 text-gray-400'
                    }`}>{sig.direction}</span>
                    <span className="text-[10px] text-gray-500 font-mono w-12 text-right">
                      {(sig.confidence * 100).toFixed(0)}%
                    </span>
                    <span className="text-[10px] text-gray-600 w-14 text-right">
                      {sig.vote_count} vote{sig.vote_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══ PIPELINE ROW ═══ */}
      <PublishPipelinePanel />
    </div>
  );
};

export default KalshiVolDashboardView;
