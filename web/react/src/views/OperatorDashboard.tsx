import { useState } from 'react';
import { useOperatorSummary } from '../hooks/useOperatorSummary';
import { OperatorStatusBar } from './OperatorStatusBar';
import { OperatorControlPlane } from './OperatorControlPlane';
import { OperatorActivityStream } from './OperatorActivityStream';
import { LiveRiskStrip } from './LiveRiskStrip';
import { LiveAgentHealthPanel } from './LiveAgentHealthPanel';
import MetricCard from '../components/MetricCard';
import { EquityPnLChart } from '../components/charts/EquityPnLChart';
import { RiskLimitBars } from '../components/charts/RiskLimitBars';
import { RiskHeatmapWidget } from '../components/charts/RiskHeatmapWidget';
import { DrawdownCard } from '../components/charts/DrawdownCard';
import { InstrumentRadar } from '../components/charts/InstrumentRadar';
import { RiskTreeMap } from '../components/charts/RiskTreeMap';
import { BreachAlertLog } from '../components/charts/BreachAlertLog';
import { LatencyChart } from '../components/charts/LatencyChart';
import { StalenessIndicator } from '../components/StalenessIndicator';
import DomainControlPanel from '../components/DomainControlPanel';
import VenueHealthGrid from '../components/VenueHealthGrid';
import DataFreshnessPanel from '../components/DataFreshnessPanel';
import OrchestratorPanel from '../components/OrchestratorPanel';
import SentimentTimeline from '../components/SentimentTimeline';
import ArbScannerPanel from '../components/ArbScannerPanel';
import OnChainHealthPanel from '../components/OnChainHealthPanel';
import PredictionMarketDetail from '../components/PredictionMarketDetail';
import ModeControlPanel from '../components/ModeControlPanel';
import ExplainabilityTimeline from '../components/ExplainabilityTimeline';
import TelegramLogViewer from '../components/TelegramLogViewer';
import AlertHistoryPanel from '../components/AlertHistoryPanel';
import DomainPnLChart from '../components/DomainPnLChart';
import StrategyLeaderboard from '../components/StrategyLeaderboard';
import CompliancePanel from '../components/CompliancePanel';
import ConsensusTable from '../components/ConsensusTable';
import TradingHaltBanner from '../components/TradingHaltBanner';
import { useConsensusSummary } from '../hooks/useConsensusSummary';
import { formatCurrency } from '../utils/formatters';
import {
  Monitor, BarChart3, Shield, Brain, Server, Sliders,
} from 'lucide-react';

/* ── Tab Definitions ──────────────────────────────── */
const TABS = [
  { id: 'overview',     label: 'Overview',      icon: BarChart3 },
  { id: 'trading',      label: 'Trading',       icon: Sliders },
  { id: 'risk',         label: 'Risk',          icon: Shield },
  { id: 'intelligence', label: 'Intelligence',  icon: Brain },
  { id: 'system',       label: 'System',        icon: Server },
] as const;

type TabId = typeof TABS[number]['id'];

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
  } = useOperatorSummary(5000);

  const consensusSummary = useConsensusSummary();
  const [activeTab, setActiveTab] = useState<TabId>('overview');

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4 lg:p-6 max-w-[1800px] mx-auto">

      {/* ─── Header ─────────────────────────────── */}
      <div className="flex items-center gap-3">
        <Monitor className="w-6 h-6 text-blue-400" />
        <h1 className="text-xl font-bold text-slate-100">Operator Dashboard</h1>
        {error && (
          <span className="text-xs text-red-400 bg-red-900/20 px-2 py-0.5 rounded">
            {error}
          </span>
        )}
        <div className="ml-auto">
          <StalenessIndicator
            lastUpdated={lastUpdated ? new Date(lastUpdated) : null}
            thresholdMs={10000}
            criticalThresholdMs={30000}
            label="Dashboard"
          />
        </div>
      </div>

      {/* ─── Trading Halt Banner ────────────────── */}
      <TradingHaltBanner />

      {/* ─── Status Bar ─────────────────────────── */}
      <OperatorStatusBar summary={data} lastUpdated={lastUpdated} />

      {/* ─── Key Metrics (always visible) ────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
        <MetricCard
          label="Portfolio Value"
          value={data?.portfolio ? formatCurrency(data.portfolio.total_value) : '--'}
          status={data?.portfolio && data.portfolio.total_value > 0 ? 'GOOD' : 'WARNING'}
        />
        <MetricCard
          label="Unrealized P&L"
          value={data?.portfolio ? formatCurrency(data.portfolio.unrealized_pnl) : '--'}
          status={
            data?.portfolio
              ? data.portfolio.unrealized_pnl >= 0 ? 'GOOD' : 'BAD'
              : undefined
          }
          delta={data?.portfolio?.unrealized_pnl}
        />
        <MetricCard
          label="Positions"
          value={String(data?.portfolio?.position_count ?? 0)}
        />
        <MetricCard
          label="Success Rate"
          value={`${data?.swarm?.success_rate?.toFixed(1) ?? '0'}%`}
          status={
            (data?.swarm?.success_rate ?? 0) >= 80 ? 'GOOD'
              : (data?.swarm?.success_rate ?? 0) >= 50 ? 'WARNING' : 'BAD'
          }
        />
        <MetricCard
          label="Agents"
          value={String(data?.swarm?.agents ?? 0)}
          status="GOOD"
        />
        <MetricCard
          label="Active Tasks"
          value={String(data?.swarm?.active_tasks ?? 0)}
          status={(data?.swarm?.active_tasks ?? 0) > 0 ? 'GOOD' : undefined}
        />
        <MetricCard
          label="Completed"
          value={String(data?.swarm?.completed ?? 0)}
        />
        <MetricCard
          label="Failed"
          value={String(data?.swarm?.failed ?? 0)}
          status={(data?.swarm?.failed ?? 0) > 0 ? 'WARNING' : 'GOOD'}
        />
      </div>

      {/* ─── Tab Navigation ─────────────────────── */}
      <nav className="flex items-center gap-1 bg-slate-900/60 rounded-xl p-1 border border-slate-800">
        {TABS.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30 shadow-lg shadow-blue-500/10'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {/* ─── Tab Content ────────────────────────── */}
      <div className="min-h-[600px]">

        {/* ═══ OVERVIEW TAB ═══ */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Risk Strip */}
            <LiveRiskStrip />

            {/* Equity Chart + Agent Health */}
            <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
              <div className="xl:col-span-3">
                <EquityPnLChart />
              </div>
              <div className="xl:col-span-2">
                <LiveAgentHealthPanel />
              </div>
            </div>

            {/* Domain PnL + Strategy Leaderboard */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <DomainPnLChart />
              <StrategyLeaderboard />
            </div>

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
          </div>
        )}

        {/* ═══ TRADING TAB ═══ */}
        {activeTab === 'trading' && (
          <div className="space-y-6">
            {/* Domain Control + Venue Health */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <DomainControlPanel />
              <VenueHealthGrid />
            </div>

            {/* Mode Control + Prediction Markets */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <ModeControlPanel />
              <PredictionMarketDetail />
            </div>

            {/* Decision Audit Trail */}
            <ExplainabilityTimeline />
          </div>
        )}

        {/* ═══ RISK TAB ═══ */}
        {activeTab === 'risk' && (
          <div className="space-y-6">
            {/* Cross-Market Consensus */}
            <ConsensusTable summary={consensusSummary} />

            {/* Risk Visualization */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <RiskLimitBars />
              <RiskHeatmapWidget />
              <DrawdownCard />
            </div>

            {/* Instrument Radar + Risk TreeMap */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <InstrumentRadar />
              <RiskTreeMap />
            </div>

            {/* Breach Log + Latency */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <BreachAlertLog />
              <LatencyChart />
            </div>
          </div>
        )}

        {/* ═══ INTELLIGENCE TAB ═══ */}
        {activeTab === 'intelligence' && (
          <div className="space-y-6">
            {/* Orchestrator + Sentiment */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <OrchestratorPanel />
              <SentimentTimeline />
            </div>

            {/* Arb Scanner */}
            <ArbScannerPanel />
          </div>
        )}

        {/* ═══ SYSTEM TAB ═══ */}
        {activeTab === 'system' && (
          <div className="space-y-6">
            {/* Execution Guard + Loop Status */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              {/* Kill Switch & Guard */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-semibold text-slate-300">Execution Guard</h3>
                  <button
                    onClick={() => toggleKillSwitch(!data?.guard?.kill_switch_active)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                      data?.guard?.kill_switch_active
                        ? 'bg-red-600 hover:bg-red-500 text-white'
                        : 'bg-green-600/20 hover:bg-green-600/40 text-green-400 border border-green-500/30'
                    }`}
                  >
                    {data?.guard?.kill_switch_active ? '🛑 KILL SWITCH ON — Click to Deactivate' : '✅ Execution Enabled'}
                  </button>
                </div>
                {data?.guard && (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      {Object.entries(data.guard.last_cqi || {}).map(([domain, cqi]) => (
                        <div key={domain} className="bg-slate-800/50 rounded-lg p-3">
                          <div className="text-xs text-slate-500 uppercase">{domain} CQI</div>
                          <div className={`text-lg font-bold ${
                            cqi >= 0.65 ? 'text-green-400' : cqi >= 0.35 ? 'text-yellow-400' : 'text-red-400'
                          }`}>{(cqi * 100).toFixed(1)}%</div>
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      {Object.entries(data.guard.domain_caps || {}).map(([domain, cap]) => (
                        <div key={domain} className="flex items-center justify-between bg-slate-800/50 rounded-lg p-2 text-xs">
                          <span className="text-slate-400">{domain}</span>
                          <span className="text-slate-300">${cap.remaining_usd.toLocaleString()} left</span>
                          {cap.kill && <span className="text-red-400 font-bold">KILLED</span>}
                        </div>
                      ))}
                    </div>
                    <div className="text-xs text-slate-500">
                      {data.guard.recent_verdicts_count} recent verdicts
                    </div>
                  </div>
                )}
              </div>

              {/* Loop Status */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-4">Loop Status</h3>
                {data?.loop ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${data.loop.running ? 'bg-green-400 animate-pulse' : 'bg-slate-600'}`} />
                      <span className="text-sm text-slate-300">{data.loop.running ? 'Running' : 'Stopped'}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">Total Ticks</div>
                        <div className="text-lg font-bold text-slate-200">{data.loop.total_ticks.toLocaleString()}</div>
                      </div>
                      <div className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">Plans Executed</div>
                        <div className="text-lg font-bold text-blue-400">{data.loop.plans_executed}</div>
                      </div>
                      <div className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">Errors</div>
                        <div className={`text-lg font-bold ${data.loop.total_errors > 0 ? 'text-red-400' : 'text-green-400'}`}>
                          {data.loop.total_errors}
                        </div>
                      </div>
                      <div className="bg-slate-800/50 rounded-lg p-3">
                        <div className="text-xs text-slate-500">Last Tick</div>
                        <div className="text-lg font-bold text-slate-200">{data.loop.last_tick_duration_ms}ms</div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">Loop not initialized</div>
                )}
              </div>
            </div>

            {/* On-Chain Health + Data Freshness */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <OnChainHealthPanel />
              <DataFreshnessPanel />
            </div>

            {/* Alert History + Compliance */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <AlertHistoryPanel />
              <CompliancePanel />
            </div>

            {/* Telegram Log */}
            <TelegramLogViewer />
          </div>
        )}

      </div>
    </div>
  );
}
