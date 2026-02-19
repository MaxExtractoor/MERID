/**
 * LoopOrchestrationView — Top-level view for MERID loop orchestration.
 *
 * Assembles:
 *   - LoopPipelineDiagram: visual pipeline flow with stage nodes
 *   - LoopCadenceChart: cycle timing and throughput over time
 *   - StageHealthCards: per-stage latency, throughput, error rate
 *   - WiringStatusPanel: connection status between stages + infra services
 */

import { useState } from "react";
import {
  RefreshCw,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Timer,
  BarChart3,
  Wifi,
  Activity,
  Layers,
  Zap,
  AlertTriangle,
} from "lucide-react";
import { useLoopOrchestration, useStageMetrics } from "../hooks/useLoopOrchestration";
import type { StageStatus } from "../hooks/useLoopOrchestration";
import LoopPipelineDiagram from "../components/charts/LoopPipelineDiagram";
import LoopCadenceChart from "../components/charts/LoopCadenceChart";
import StageHealthCards from "../components/charts/StageHealthCards";
import WiringStatusPanel from "../components/charts/WiringStatusPanel";

/* ── Component ─────────────────────────────────────────────────── */

export default function LoopOrchestrationView() {
  const { data: loopData, loading: loopLoading, error: loopError, refresh: refreshLoop } = useLoopOrchestration();
  const { data: stageData, loading: stageLoading, refresh: refreshStages } = useStageMetrics();

  const [showPipeline, setShowPipeline] = useState(true);
  const [showCadence, setShowCadence] = useState(true);
  const [showStages, setShowStages] = useState(true);
  const [showWiring, setShowWiring] = useState(true);

  const loading = loopLoading || stageLoading;

  const handleRefresh = () => {
    refreshLoop();
    refreshStages();
  };

  // Build stage status map for pipeline diagram
  const stageStatusMap: Record<string, StageStatus> = {};
  if (stageData?.stages) {
    for (const s of stageData.stages) {
      stageStatusMap[s.name] = s.status;
    }
  }

  // Overall status badge
  const overallStatus = stageData?.overallStatus ?? "unknown";
  const statusCfg = {
    healthy: { color: "text-emerald-400", bg: "bg-emerald-900/20", border: "border-emerald-500/30", label: "All Systems Healthy" },
    degraded: { color: "text-amber-400", bg: "bg-amber-900/20", border: "border-amber-500/30", label: "Degraded" },
    down: { color: "text-rose-400", bg: "bg-rose-900/20", border: "border-rose-500/30", label: "Systems Down" },
    unknown: { color: "text-slate-400", bg: "bg-slate-800/40", border: "border-slate-600/30", label: "Initializing..." },
  }[overallStatus] ?? { color: "text-slate-400", bg: "bg-slate-800/40", border: "border-slate-600/30", label: "Unknown" };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-900/30 rounded-xl border border-indigo-500/20">
            <GitBranch className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">Loop Orchestration</h1>
            <p className="text-xs text-slate-500">
              MERID pipeline cadence, stage health, and wiring status
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Overall status badge */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${statusCfg.bg} ${statusCfg.border}`}>
            <div className={`w-2 h-2 rounded-full ${statusCfg.color.replace("text-", "bg-")} animate-pulse`} />
            <span className={`text-xs font-medium ${statusCfg.color}`}>{statusCfg.label}</span>
          </div>
          <button type="button"
            onClick={handleRefresh}
            disabled={loading}
            aria-label="Refresh orchestration data"
            className="p-2 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Summary stats bar */}
      {loopData && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: "Status", value: loopData.status, icon: Activity, color: "text-emerald-400" },
            { label: "Avg Cycle", value: loopData.avgCycleDurationMs > 0 ? `${(loopData.avgCycleDurationMs / 1000).toFixed(1)}s` : "—", icon: Timer, color: "text-blue-400" },
            { label: "Cycles/min", value: loopData.cyclesPerMinute > 0 ? loopData.cyclesPerMinute.toFixed(2) : "—", icon: Zap, color: "text-amber-400" },
            { label: "Total Proposals", value: loopData.totalProposals, icon: BarChart3, color: "text-purple-400" },
            { label: "History", value: `${loopData.history.length} cycles`, icon: Layers, color: "text-cyan-400" },
          ].map((stat) => (
            <div
              key={stat.label}
              className="bg-slate-900/50 border border-slate-800 rounded-xl p-3 flex items-center gap-3"
            >
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
              <div>
                <div className="text-[10px] text-slate-500">{stat.label}</div>
                <div className="text-sm font-mono text-white">{stat.value}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error banner */}
      {loopError && (
        <div className="flex items-center gap-2 px-4 py-2 bg-amber-900/20 border border-amber-500/30 rounded-lg">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-xs text-amber-300">{loopError}</span>
        </div>
      )}

      {/* ── Pipeline Diagram ───────────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl">
        <button type="button"
          onClick={() => setShowPipeline(!showPipeline)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors rounded-t-xl"
        >
          {showPipeline ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <GitBranch className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-semibold text-white">Pipeline Flow</span>
          <span className="text-[10px] text-slate-500 ml-2">
            {loopData?.latestCycle
              ? `Cycle #${loopData.latestCycle.cycleId} — ${loopData.latestCycle.phases.length} phases`
              : "Waiting for data..."}
          </span>
        </button>
        {showPipeline && (
          <div className="px-4 pb-4">
            <LoopPipelineDiagram
              latestCycle={loopData?.latestCycle ?? null}
              stageStatuses={stageStatusMap}
            />
          </div>
        )}
      </div>

      {/* ── Cadence Chart ──────────────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl">
        <button type="button"
          onClick={() => setShowCadence(!showCadence)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors rounded-t-xl"
        >
          {showCadence ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Timer className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-white">Cycle Cadence & Throughput</span>
          <span className="text-[10px] text-slate-500 ml-2">
            {loopData?.history.length ?? 0} cycles recorded
          </span>
        </button>
        {showCadence && (
          <div className="px-4 pb-4">
            <LoopCadenceChart
              history={loopData?.history ?? []}
              avgCycleDurationMs={loopData?.avgCycleDurationMs}
            />
          </div>
        )}
      </div>

      {/* ── Stage Health Cards ─────────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl">
        <button type="button"
          onClick={() => setShowStages(!showStages)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors rounded-t-xl"
        >
          {showStages ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Activity className="w-4 h-4 text-emerald-400" />
          <span className="text-sm font-semibold text-white">Stage Health</span>
          <span className="text-[10px] text-slate-500 ml-2">
            {stageData?.stages.length ?? 0} stages monitored
          </span>
        </button>
        {showStages && (
          <div className="px-4 pb-4">
            <StageHealthCards stages={stageData?.stages ?? []} />
          </div>
        )}
      </div>

      {/* ── Wiring Status ──────────────────────────────────────── */}
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl">
        <button type="button"
          onClick={() => setShowWiring(!showWiring)}
          className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-slate-800/30 transition-colors rounded-t-xl"
        >
          {showWiring ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Wifi className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-semibold text-white">Wiring & Infrastructure</span>
          <span className="text-[10px] text-slate-500 ml-2">
            {stageData?.wiring.length ?? 0} links,{" "}
            {Object.keys(stageData?.services ?? {}).length} services
          </span>
        </button>
        {showWiring && (
          <div className="px-4 pb-4">
            <WiringStatusPanel
              wiring={stageData?.wiring ?? []}
              services={stageData?.services}
            />
          </div>
        )}
      </div>
    </div>
  );
}
