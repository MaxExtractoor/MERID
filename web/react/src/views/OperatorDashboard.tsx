import { useOperatorSummary } from '../hooks/useOperatorSummary';
import MetricCard from '../components/MetricCard';
import { StalenessIndicator } from '../components/StalenessIndicator';
import { DataAgeBadge } from '../components/DataAgeBadge';
import DataFreshnessPanel from '../components/DataFreshnessPanel';
import ExplainabilityTimeline from '../components/ExplainabilityTimeline';
import TickTimeline from '../components/TickTimeline';
import AlertHistoryPanel from '../components/AlertHistoryPanel';
import TradingHaltBanner from '../components/TradingHaltBanner';
import ModeSafetyPanel from '../components/ModeSafetyPanel';
import SessionLogPanel from '../components/SessionLogPanel';
import CryptoAlertStatusPanel from '../components/CryptoAlertStatusPanel';
import SpotBasisPanel from '../components/SpotBasisPanel';
import ContractHealthPanel from '../components/ContractHealthPanel';
import { Kalshi15mAlignmentPanel, Kalshi15mHealthPanel, Kalshi15mShadowModePanel, Kalshi15mPreflightCheck } from '../components';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { OperatorRiskState } from '../types/risk';
import { formatCurrency } from '../utils/formatters';
import { Monitor, AlertTriangle, CheckCircle2 } from '../ui/icons';

export default function OperatorDashboard() {
  const {
    data,
    loading,
    error,
    lastUpdated,
  } = useOperatorSummary();

  const { data: kalshiBalance } = useApiData<{ total_value_cents?: number; balance_cents?: number; portfolio_cents?: number; available?: number; usd?: number; usd_dollars?: number }>(
    API_ENDPOINTS.KALSHI_BALANCE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiPnl } = useApiData<{ daily_pnl_usd?: number; daily_total_pnl_usd?: number }>(
    API_ENDPOINTS.KALSHI_PNL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiPositions } = useApiData<{ positions: unknown[] }>(
    API_ENDPOINTS.KALSHI_POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiGridStatus } = useApiData<{
    agent_count?: number;
    running?: boolean;
    metrics?: {
      total_orders?: number;
      total_fills?: number;
      active_markets?: number;
      coverage_pct?: number;
    };
  }>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: operatorRiskState } = useApiData<OperatorRiskState>(
    API_ENDPOINTS.OPERATOR_RISK_STATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  const { data: agentActivity } = useApiData<{
    agents: Array<{ agent_id: string; status: string; tasks_completed: number }>;
    total_agents: number;
    active_agents: number;
    total_tasks_1h: number;
  }>(
    API_ENDPOINTS.OPERATOR_AGENT_ACTIVITY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const kalshiBalanceUsd = (() => {
    if (!kalshiBalance) return null;
    // Use total_value_cents (cash + portfolio) for balance display, fallback to available/usd for backward compatibility
    const balanceCents = kalshiBalance.total_value_cents ?? (kalshiBalance.available ?? kalshiBalance.usd ?? 0) * 100;
    return balanceCents / 100;
  })();

  const kalshiDayPnlUsd = (() => {
    if (!kalshiPnl) return null;
    if (typeof kalshiPnl.daily_pnl_usd === 'number') return kalshiPnl.daily_pnl_usd;
    if (typeof kalshiPnl.daily_total_pnl_usd === 'number') return kalshiPnl.daily_total_pnl_usd;
    return null;
  })();

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4 lg:p-6 max-w-[1800px] mx-auto">

      {/* Header */}
      <div className="flex items-center gap-3">
        <Monitor className="w-6 h-6 text-blue-400" />
        <h1 className="text-xl font-bold text-slate-100">Operator Dashboard</h1>
        {error && (
          <span className="text-xs text-red-400 bg-red-900/20 px-2 py-0.5 rounded">{error}</span>
        )}
        <div className="ml-auto flex items-center gap-3">
          <DataAgeBadge lastUpdated={lastUpdated} />
          <StalenessIndicator
            lastUpdated={lastUpdated ? new Date(lastUpdated) : null}
            thresholdMs={10000}
            criticalThresholdMs={30000}
            label="Dashboard"
          />
        </div>
      </div>

      {/* Trading Halt Banner */}
      <TradingHaltBanner />

      {/* Kalshi Key Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
        <MetricCard
          label="Balance"
          value={kalshiBalanceUsd != null ? formatCurrency(kalshiBalanceUsd) : '--'}
          status="GOOD"
        />
        <MetricCard
          label="Day P&L"
          value={kalshiDayPnlUsd != null ? formatCurrency(kalshiDayPnlUsd) : '--'}
          status={kalshiDayPnlUsd != null ? (kalshiDayPnlUsd >= 0 ? 'GOOD' : 'BAD') : undefined}
          delta={kalshiDayPnlUsd ?? undefined}
        />
        <MetricCard
          label="Positions"
          value={String(kalshiPositions?.positions?.length ?? 0)}
        />
        <MetricCard
          label="Agents Running"
          value={String(kalshiGridStatus?.agent_count ?? 0)}
          status={kalshiGridStatus?.running ? 'GOOD' : 'WARNING'}
        />
        <MetricCard
          label="Total Orders"
          value={String(kalshiGridStatus?.metrics?.total_orders ?? 0)}
        />
        <MetricCard
          label="Total Fills"
          value={String(kalshiGridStatus?.metrics?.total_fills ?? 0)}
        />
        <MetricCard
          label="Active Markets"
          value={String(kalshiGridStatus?.metrics?.active_markets ?? 0)}
        />
        <MetricCard
          label="Coverage"
          value={`${kalshiGridStatus?.metrics?.coverage_pct?.toFixed(1) ?? '0'}%`}
          status={
            (kalshiGridStatus?.metrics?.coverage_pct ?? 0) >= 80 ? 'GOOD'
              : (kalshiGridStatus?.metrics?.coverage_pct ?? 0) >= 50 ? 'WARNING' : 'BAD'
          }
        />
      </div>

      {/* Mode Safety */}
      <ModeSafetyPanel />

      {/* Contract Health */}
      <ContractHealthPanel />

      {/* Risk State + Agent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {operatorRiskState && (
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
            <h3 className="text-sm font-semibold text-slate-300">Risk State</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className={`rounded-lg p-3 ${
                operatorRiskState.kill_switch.active
                  ? 'bg-red-950/40 border border-red-700/40'
                  : 'bg-emerald-950/30 border border-emerald-700/30'
              }`}>
                <p className="text-[10px] text-slate-500 uppercase">Kill Switch</p>
                <p className={`text-sm font-bold ${
                  operatorRiskState.kill_switch.active ? 'text-red-400' : 'text-emerald-400'
                }`}>{operatorRiskState.kill_switch.active ? 'ACTIVE' : 'Clear'}</p>
                {operatorRiskState.kill_switch.reason && (
                  <p className="text-[10px] text-red-400 mt-0.5 truncate">{operatorRiskState.kill_switch.reason}</p>
                )}
              </div>
              <div className="bg-slate-800 rounded-lg p-3">
                <p className="text-[10px] text-slate-500 uppercase">Daily P&L</p>
                <p className={`text-sm font-bold font-mono ${
                  operatorRiskState.pnl.daily_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}>{formatCurrency(operatorRiskState.pnl.daily_pnl)}</p>
                <p className="text-[10px] text-slate-500">
                  {(operatorRiskState.pnl.utilization_pct ?? 0).toFixed(1)}% of limit used
                </p>
              </div>
              <div className="bg-slate-800 rounded-lg p-3">
                <p className="text-[10px] text-slate-500 uppercase">Position</p>
                <p className="text-sm font-bold text-white">{formatCurrency(operatorRiskState.position.total_value)}</p>
                <p className="text-[10px] text-slate-500">
                  {(operatorRiskState.position.utilization_pct ?? 0).toFixed(1)}% of max
                </p>
              </div>
              <div className={`rounded-lg p-3 ${
                operatorRiskState.errors.near_limit
                  ? 'bg-amber-950/30 border border-amber-700/30'
                  : 'bg-slate-800'
              }`}>
                <p className="text-[10px] text-slate-500 uppercase">Errors (1h)</p>
                <p className={`text-sm font-bold ${
                  operatorRiskState.errors.near_limit ? 'text-amber-400' : 'text-white'
                }`}>{operatorRiskState.errors.count_1h} / {operatorRiskState.errors.threshold}</p>
                {operatorRiskState.errors.near_limit && (
                  <p className="text-[10px] text-amber-400">Near limit</p>
                )}
              </div>
            </div>
          </div>
        )}
        {agentActivity && (
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-300">Agent Activity</h3>
              <span className="text-xs text-slate-500">{agentActivity.total_tasks_1h} tasks/hr</span>
            </div>
            <div className="flex items-center gap-3 mb-2">
              <div className="flex-1 bg-slate-800 rounded-lg p-3 text-center">
                <p className="text-[10px] text-slate-500">Active</p>
                <p className={`text-xl font-bold ${
                  agentActivity.active_agents > 0 ? 'text-emerald-400' : 'text-slate-500'
                }`}>{agentActivity.active_agents}</p>
              </div>
              <div className="flex-1 bg-slate-800 rounded-lg p-3 text-center">
                <p className="text-[10px] text-slate-500">Total</p>
                <p className="text-xl font-bold text-white">{agentActivity.total_agents}</p>
              </div>
            </div>
            <div className="max-h-[140px] overflow-y-auto space-y-1">
              {agentActivity.agents.slice(0, 8).map((a) => (
                <div key={a.agent_id} className="flex items-center justify-between px-2 py-1 rounded bg-slate-800/50 text-xs">
                  <span className="font-mono text-slate-300 truncate max-w-[120px]">{a.agent_id}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-slate-500">{a.tasks_completed} tasks</span>
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      a.status === 'active' ? 'bg-emerald-400' :
                      a.status === 'idle' ? 'bg-slate-500' : 'bg-red-400'
                    }`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* PM Spot Health — same payload as Kill Switch limited mode; visible here without extra navigation */}
      {operatorRiskState && (
        <div
          className={`rounded-xl border p-4 ${
            operatorRiskState.all_pm_assets_have_spot === false
              ? 'bg-amber-950/25 border-amber-600/40'
              : 'bg-emerald-950/20 border-emerald-600/30'
          }`}
        >
          <div className="flex items-start gap-3 mb-3">
            {operatorRiskState.all_pm_assets_have_spot === false ? (
              <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
            )}
            <div>
              <h3 className="text-sm font-semibold text-slate-200">PM Spot Health (Coinbase / LivePriceFeed)</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Used by prediction-market crypto pricing and{' '}
                <span className="text-slate-400">market_maker</span> agents with{' '}
                <span className="font-mono text-slate-400">pm_spot_hard_gate</span>. When spot is missing or stale,
                CRYPTO_15M_MM (and other opted-in MM agents) <span className="text-amber-200/90">block QUOTE</span> — no
                silent neutral-vol fallback.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs mb-3">
            <span
              className={`px-2 py-0.5 rounded font-semibold ${
                operatorRiskState.all_pm_assets_have_spot === false
                  ? 'bg-amber-900/50 text-amber-200'
                  : 'bg-emerald-900/40 text-emerald-200'
              }`}
            >
              all_pm_assets_have_spot: {String(operatorRiskState.all_pm_assets_have_spot ?? true)}
            </span>
            {operatorRiskState.crypto_pm_feed?.summary?.kalshi_only_mode === true && (
              <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-600/50">
                KALSHI_ONLY — CCXT not initialized; Coinbase Advanced HTTP is the usual PM spot path
              </span>
            )}
          </div>
          {operatorRiskState.crypto_pm_feed?.assets && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700/80">
                    <th className="py-1.5 pr-3 font-medium">Asset</th>
                    <th className="py-1.5 pr-3 font-medium">PM spot OK</th>
                    <th
                      className="py-1.5 pr-3 font-medium"
                      title="Stream liveness (recent tick). False when Coinbase/LivePriceFeed is down or stale; compare to Reason for PM max-age vs feed outage."
                    >
                      Feed OK
                    </th>
                    <th
                      className="py-1.5 pr-3 font-medium"
                      title="pm_spot_unusable_reason: pm_max_age_exceeded = quote exists but MERID_PM_MAX_SPOT_AGE_SECONDS is tight; live_price_feed_unhealthy = no tick / stream unhealthy."
                    >
                      Reason
                    </th>
                    <th className="py-1.5 pr-3 font-medium">Cache age (s)</th>
                    <th className="py-1.5 pr-3 font-medium" title="Seconds since last successful stream tick (per asset).">
                      Tick age (s)
                    </th>
                    <th className="py-1.5 font-medium">Feed TTL expired</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(operatorRiskState.crypto_pm_feed.assets).map(([sym, row]) => {
                    const feed = row.live_price_feed as {
                      cache_age_seconds?: number;
                      feed_ttl_expired?: boolean;
                    } | undefined;
                    const ok = row.pm_spot_effective_ok ?? row.pm_spot_ok;
                    const lfOk = row.live_price_feed_healthy;
                    const tickAge = row.last_stream_tick_age_seconds;
                    return (
                      <tr key={sym} className="border-b border-slate-800/60">
                        <td className="py-1.5 pr-3 font-mono text-slate-300">{sym}</td>
                        <td className={`py-1.5 pr-3 font-medium ${ok ? 'text-emerald-400' : 'text-amber-400'}`}>
                          {String(ok ?? false)}
                        </td>
                        <td
                          className={`py-1.5 pr-3 font-medium ${
                            lfOk === false ? 'text-rose-400/90' : lfOk === true ? 'text-emerald-400/90' : 'text-slate-500'
                          }`}
                          title={
                            lfOk === false
                              ? 'Underlying LivePriceFeed stream unhealthy or stale — likely Coinbase/network.'
                              : 'Stream tick recent enough for feed health threshold.'
                          }
                        >
                          {lfOk === undefined || lfOk === null ? '—' : String(lfOk)}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-400 max-w-[240px]">
                          {ok ? '—' : row.pm_spot_unusable_reason ?? 'unknown'}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-400">
                          {feed?.cache_age_seconds != null ? feed.cache_age_seconds : '—'}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-400">
                          {tickAge != null && typeof tickAge === 'number' ? tickAge.toFixed(1) : '—'}
                        </td>
                        <td className="py-1.5 text-slate-400">{String(feed?.feed_ttl_expired ?? '—')}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {operatorRiskState.all_pm_assets_have_spot === false && (
            <p className="text-xs text-amber-200/90 mt-3">
              At least one monitored asset lacks effective PM spot. Check <span className="font-mono">Feed OK</span>{' '}
              vs <span className="font-mono">Reason</span>: if Feed OK is false, fix Coinbase/stream; if Feed OK is
              true but PM spot is false with <span className="font-mono">pm_max_age_exceeded</span>, tighten timing or
              MERID_PM_MAX_SPOT_AGE_SECONDS. MM agents with <span className="font-mono">pm_spot_hard_gate: true</span>{' '}
              emit <span className="font-mono">NO_ACTION</span> instead of <span className="font-mono">QUOTE</span> (
              <span className="font-mono">PM_SPOT_BLOCK</span>, <span className="font-mono">[PM_SPOT]</span>).
            </p>
          )}
        </div>
      )}

      {/* Execution Guard */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-300">Execution Guard</h3>
          <div className={`px-3 py-1.5 rounded-lg text-xs font-bold ${
            data?.guard?.kill_switch_active
              ? 'bg-red-600/20 text-red-400 border border-red-500/30'
              : 'bg-green-600/20 text-green-400 border border-green-500/30'
          }`}>
            {data?.guard?.kill_switch_active ? 'KILL SWITCH ON' : 'Execution Enabled'}
          </div>
        </div>
        {data?.guard && (
          <p className="text-xs text-slate-500">{data.guard.recent_verdicts_count} recent verdicts</p>
        )}
      </div>

      {/* Crypto Alert Router */}
      <CryptoAlertStatusPanel />

      {/* 15m Kalshi Alignment & Health */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Kalshi15mAlignmentPanel />
        <Kalshi15mHealthPanel />
      </div>

      {/* 15m Shadow Mode */}
      <Kalshi15mShadowModePanel />

      {/* 15m Pre-Flight Check */}
      <Kalshi15mPreflightCheck />

      {/* Spot / Kalshi Basis Monitor */}
      <SpotBasisPanel />

      {/* Decision Audit Trail */}
      <ExplainabilityTimeline />

      {/* Tick Timeline */}
      <TickTimeline />

      {/* Data Freshness + Alert History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DataFreshnessPanel />
        <AlertHistoryPanel />
      </div>

      {/* Session Log */}
      <SessionLogPanel />

      {/* Operator Runbooks */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Operator Runbooks</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <a
            href="https://docs.kalshi.com"
            target="_blank"
            rel="noopener noreferrer"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">Kalshi API Documentation</div>
            <div className="text-xs text-slate-500 mt-1">Official Kalshi API reference</div>
          </a>
          <a
            href="/docs/15m-stack-overview"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">15m Stack Overview</div>
            <div className="text-xs text-slate-500 mt-1">Architecture and invariants</div>
          </a>
          <a
            href="/docs/troubleshooting"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">Troubleshooting Guide</div>
            <div className="text-xs text-slate-500 mt-1">Common issues and solutions</div>
          </a>
          <a
            href="/docs/risk-management"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">Risk Management</div>
            <div className="text-xs text-slate-500 mt-1">Kill switches and limits</div>
          </a>
          <a
            href="/docs/deployment"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">Deployment Procedures</div>
            <div className="text-xs text-slate-500 mt-1">Live/shadow promotions</div>
          </a>
          <a
            href="/docs/monitoring"
            className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
          >
            <div className="text-sm font-medium text-white">Monitoring & Alerts</div>
            <div className="text-xs text-slate-500 mt-1">Metrics and dashboards</div>
          </a>
        </div>
      </div>

    </div>
  );
}
