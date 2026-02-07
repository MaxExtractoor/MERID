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
  } = useOperatorSummary(5000);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
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

      {/* 1. Status Bar */}
      <OperatorStatusBar
        summary={data}
        lastUpdated={lastUpdated}
      />

      {/* 2. Portfolio & Risk + 3. Swarm Health (side by side) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left: Portfolio & Risk */}
        <div className="space-y-4">
          {/* Portfolio Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
                  ? data.portfolio.unrealized_pnl >= 0
                    ? 'GOOD'
                    : 'BAD'
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
                (data?.swarm?.success_rate ?? 0) >= 80
                  ? 'GOOD'
                  : (data?.swarm?.success_rate ?? 0) >= 50
                    ? 'WARNING'
                    : 'BAD'
              }
            />
          </div>

          {/* Live Risk Strip */}
          <LiveRiskStrip />

          {/* Streaming Equity / PnL Chart */}
          <EquityPnLChart />
        </div>

        {/* Right: Swarm Health */}
        <div className="space-y-4">
          {/* Swarm Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard
              label="Agents"
              value={String(data?.swarm?.agents ?? 0)}
              status="GOOD"
            />
            <MetricCard
              label="Active Tasks"
              value={String(data?.swarm?.active_tasks ?? 0)}
              status={
                (data?.swarm?.active_tasks ?? 0) > 0 ? 'GOOD' : undefined
              }
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

          {/* Agent Health Panel */}
          <LiveAgentHealthPanel />
        </div>
      </div>

      {/* 3. Risk Visualization Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <RiskLimitBars />
        <RiskHeatmapWidget />
        <DrawdownCard />
      </div>

      {/* 4. Instrument Radar + Risk TreeMap */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <InstrumentRadar />
        <RiskTreeMap />
      </div>

      {/* 5. Breach Log + Latency */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BreachAlertLog />
        <LatencyChart />
      </div>

      {/* 6. Domain Control + Venue Health */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DomainControlPanel />
        <VenueHealthGrid />
      </div>

      {/* 7. Orchestrator + Sentiment */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OrchestratorPanel />
        <SentimentTimeline />
      </div>

      {/* 8. Arb Scanner */}
      <ArbScannerPanel />

      {/* 9. On-Chain Health + Data Freshness */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OnChainHealthPanel />
        <DataFreshnessPanel />
      </div>

      {/* 9. Activity Stream + Control Plane (side by side) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Activity Stream (2/3 width) */}
        <div className="lg:col-span-2">
          <OperatorActivityStream />
        </div>

        {/* Control Plane (1/3 width) */}
        <div>
          <OperatorControlPlane
            summary={data}
            onPauseSwarm={pauseSwarm}
            onResumeSwarm={resumeSwarm}
            onSwitchMode={switchMode}
            onRefresh={refetch}
          />
        </div>
      </div>
    </div>
  );
}
