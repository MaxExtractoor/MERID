/**
 * LoopPipelineDiagram — Visual pipeline flow showing MERID loop stages
 * as connected nodes with status indicators, agent counts, and durations.
 *
 * Renders a horizontal pipeline: Signal → Consensus → Debate → Risk → Execution → Betting
 * Each node shows status color, phase duration, and agent count from the latest cycle.
 */

import React from "react";
import {
  Activity,
  Users,
  MessageSquare,
  Shield,
  Zap,
  TrendingUp,
  ArrowRight,
  CheckCircle,
  AlertTriangle,
  XCircle,
  HelpCircle,
} from "lucide-react";
import type { LatestCycle, CyclePhase, StageStatus } from "../../hooks/useLoopOrchestration";

/* ── Stage config ──────────────────────────────────────────────── */

interface StageConfig {
  name: string;
  displayName: string;
  icon: React.ElementType;
  phaseMatch: string[];
}

const STAGE_CONFIGS: StageConfig[] = [
  { name: "signal", displayName: "Signal", icon: Activity, phaseMatch: ["SIGNAL", "SIGNALS", "signal"] },
  { name: "consensus", displayName: "Consensus", icon: Users, phaseMatch: ["CONSENSUS", "OPINION", "consensus"] },
  { name: "debate", displayName: "Debate", icon: MessageSquare, phaseMatch: ["DEBATE", "CHALLENGE", "debate"] },
  { name: "risk", displayName: "Risk", icon: Shield, phaseMatch: ["RISK", "VALIDATE", "risk"] },
  { name: "execution", displayName: "Execution", icon: Zap, phaseMatch: ["EXECUTE", "EXECUTION", "execution"] },
  { name: "betting", displayName: "Betting", icon: TrendingUp, phaseMatch: ["BETTING", "BET", "betting"] },
];

const STATUS_STYLES: Record<StageStatus | "completed", { bg: string; border: string; text: string; Icon: React.ElementType }> = {
  healthy: { bg: "bg-emerald-900/30", border: "border-emerald-500/50", text: "text-emerald-400", Icon: CheckCircle },
  completed: { bg: "bg-emerald-900/30", border: "border-emerald-500/50", text: "text-emerald-400", Icon: CheckCircle },
  degraded: { bg: "bg-amber-900/30", border: "border-amber-500/50", text: "text-amber-400", Icon: AlertTriangle },
  down: { bg: "bg-rose-900/30", border: "border-rose-500/50", text: "text-rose-400", Icon: XCircle },
  unknown: { bg: "bg-slate-800/60", border: "border-slate-600/50", text: "text-slate-400", Icon: HelpCircle },
};

/* ── Helpers ───────────────────────────────────────────────────── */

function matchPhase(phases: CyclePhase[], matchers: string[]): CyclePhase | undefined {
  return phases.find((p) =>
    matchers.some((m) => p.name.toUpperCase().includes(m.toUpperCase()))
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/* ── Props ─────────────────────────────────────────────────────── */

interface LoopPipelineDiagramProps {
  latestCycle: LatestCycle | null;
  stageStatuses?: Record<string, StageStatus>;
  className?: string;
}

/* ── Component ─────────────────────────────────────────────────── */

export default function LoopPipelineDiagram({
  latestCycle,
  stageStatuses,
  className = "",
}: LoopPipelineDiagramProps) {
  const phases = latestCycle?.phases ?? [];

  return (
    <div className={`${className}`}>
      {/* Pipeline flow — horizontal on desktop, vertical on mobile */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center gap-2 md:gap-0">
        {STAGE_CONFIGS.map((stage, idx) => {
          const phase = matchPhase(phases, stage.phaseMatch);
          const externalStatus = stageStatuses?.[stage.name];
          const nodeStatus: StageStatus | "completed" = phase
            ? "completed"
            : externalStatus ?? "unknown";
          const style = STATUS_STYLES[nodeStatus] ?? STATUS_STYLES.unknown;
          const StageIcon = stage.icon;
          const StatusIcon = style.Icon;

          return (
            <React.Fragment key={stage.name}>
              {/* Arrow connector (not before first) */}
              {idx > 0 && (
                <div className="hidden md:flex items-center justify-center px-1">
                  <ArrowRight className="w-4 h-4 text-slate-600" />
                </div>
              )}

              {/* Stage node */}
              <div
                className={`flex-1 min-w-0 rounded-xl border p-3 ${style.bg} ${style.border} transition-all hover:scale-[1.02]`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <StageIcon className={`w-4 h-4 ${style.text}`} />
                  <span className="text-xs font-semibold text-white truncate">
                    {stage.displayName}
                  </span>
                  <StatusIcon className={`w-3 h-3 ml-auto ${style.text}`} />
                </div>

                {phase ? (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-500">Duration</span>
                      <span className="text-[10px] font-mono text-white">
                        {formatDuration(phase.durationMs)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-slate-500">Agents</span>
                      <span className="text-[10px] font-mono text-white">
                        {phase.outputCount}/{phase.agentCount}
                      </span>
                    </div>
                    {/* Mini progress bar */}
                    <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          phase.outputCount === phase.agentCount
                            ? "bg-emerald-500"
                            : "bg-amber-500"
                        }`}
                        style={{
                          width: `${
                            phase.agentCount > 0
                              ? (phase.outputCount / phase.agentCount) * 100
                              : 0
                          }%`,
                        }}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="text-[10px] text-slate-600 italic">
                    {externalStatus === "healthy" ? "Idle" : "No data"}
                  </div>
                )}
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {/* Cycle summary bar */}
      {latestCycle && (
        <div className="mt-3 flex items-center gap-4 text-[10px] text-slate-500">
          <span>
            Cycle <span className="text-white font-mono">#{latestCycle.cycleId}</span>
          </span>
          <span>
            Total: <span className="text-white font-mono">{formatDuration(latestCycle.totalDurationMs)}</span>
          </span>
          <span>
            Proposals: <span className="text-white font-mono">{latestCycle.proposalsGenerated}</span>
          </span>
          <span>
            Spikes: <span className="text-white font-mono">{latestCycle.spikesDetected}</span>
          </span>
          <span>
            Verdicts: <span className="text-white font-mono">{latestCycle.verdictsIssued}</span>
          </span>
        </div>
      )}
    </div>
  );
}
