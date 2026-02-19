import { useOperatorSummary } from '../hooks/useOperatorSummary';
import { OperatorStatusBar } from './OperatorStatusBar';
import { OperatorControlPlane } from './OperatorControlPlane';
import { OperatorActivityStream } from './OperatorActivityStream';
import MetricCard from '../components/MetricCard';
import { StalenessIndicator } from '../components/StalenessIndicator';
import { DataAgeBadge } from '../components/DataAgeBadge';
import VenueHealthGrid from '../components/VenueHealthGrid';
import DataFreshnessPanel from '../components/DataFreshnessPanel';
import ModeControlPanel from '../components/ModeControlPanel';
import ExplainabilityTimeline from '../components/ExplainabilityTimeline';
import TelegramLogViewer from '../components/TelegramLogViewer';
import AlertHistoryPanel from '../components/AlertHistoryPanel';
import TradingHaltBanner from '../components/TradingHaltBanner';
import ModeSafetyPanel from '../components/ModeSafetyPanel';
import SessionLogPanel from '../components/SessionLogPanel';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { formatCurrency } from '../utils/formatters';
import { Monitor } from 'lucide-react';

export default function OperatorDashboard() {
  const {
    data,
    loading,
    error,
    refetch,
    lastUpdated,
    pauseSwarm,
    resumeSwarm,
    switchMode,
    toggleKillSwitch,
  } = useOperatorSummary(15000);

  const { data: kalshiBalance } = useApiData<any>(
    API_ENDPOINTS.KALSHI_BALANCE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiPnl } = useApiData<any>(
    API_ENDPOINTS.KALSHI_PNL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiPositions } = useApiData<{ positions: any[] }>(
    API_ENDPOINTS.KALSHI_POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: kalshiGridStatus } = useApiData<any>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: operatorRiskState } = useApiData<{
    kill_switch: { active: boolean; reason: string | null; can_trade: boolean };
    pnl: { daily_pnl: number; daily_loss_limit: number; limit_remaining: number; utilization_pct: number };
    position: { total_value: number; max_allowed: number; utilization_pct: number };
    errors: { count_1h: number; threshold: number; near_limit: boolean };
  }>(
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
    if (typeof kalshiBalance.available === 'number') return kalshiBalance.available;
    if (typeof kalshiBalance.usd === 'number') return kalshiBalance.usd;
    return null;
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

      {/* Status Bar */}
      <OperatorStatusBar summary={data} lastUpdated={lastUpdated} />

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
                  {operatorRiskState.pnl.utilization_pct.toFixed(1)}% of limit used
                </p>
              </div>
              <div className="bg-slate-800 rounded-lg p-3">
                <p className="text-[10px] text-slate-500 uppercase">Position</p>
                <p className="text-sm font-bold text-white">{formatCurrency(operatorRiskState.position.total_value)}</p>
                <p className="text-[10px] text-slate-500">
                  {operatorRiskState.position.utilization_pct.toFixed(1)}% of max
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

      {/* Execution Guard */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-300">Execution Guard</h3>
          <button
            type="button"
            onClick={() => {
              const next = !data?.guard?.kill_switch_active;
              const msg = next
                ? 'Activate KILL SWITCH? This will halt ALL execution immediately.'
                : 'Deactivate kill switch and resume execution?';
              if (window.confirm(msg)) toggleKillSwitch(next);
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
              data?.guard?.kill_switch_active
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-green-600/20 hover:bg-green-600/40 text-green-400 border border-green-500/30'
            }`}
          >
            {data?.guard?.kill_switch_active ? 'KILL SWITCH ON — Click to Deactivate' : 'Execution Enabled'}
          </button>
        </div>
        {data?.guard && (
          <p className="text-xs text-slate-500">{data.guard.recent_verdicts_count} recent verdicts</p>
        )}
      </div>

      {/* Mode Control */}
      <ModeControlPanel />

      {/* Venue Health */}
      <VenueHealthGrid />

      {/* Decision Audit Trail */}
      <ExplainabilityTimeline />

      {/* Activity Stream + Control Plane */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <OperatorActivityStream />
        </div>
        <OperatorControlPlane
          summary={data}
          onPauseSwarm={pauseSwarm}
          onResumeSwarm={resumeSwarm}
          onSwitchMode={switchMode}
          onRefresh={refetch}
        />
      </div>

      {/* Data Freshness + Alert History */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <DataFreshnessPanel />
        <AlertHistoryPanel />
      </div>

      {/* Session Log */}
      <SessionLogPanel />

      {/* Telegram Log */}
      <TelegramLogViewer />

    </div>
  );
}
