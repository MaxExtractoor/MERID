/**
 * StageHealthCards — Per-stage health gauge cards showing latency,
 * throughput, error rate, and status for each MERID pipeline stage.
 */

import React from "react";
import {
  Activity,
  Users,
  MessageSquare,
  Shield,
  Zap,
  TrendingUp,
  CheckCircle,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Clock,
  BarChart3,
  AlertOctagon,
} from "lucide-react";
import type { StageHealth, StageStatus } from "../../hooks/useLoopOrchestration";

/* ── Stage icon map ────────────────────────────────────────────── */

const STAGE_ICONS: Record<string, React.ElementType> = {
  signal: Activity,
  consensus: Users,
  debate: MessageSquare,
  risk: Shield,
  execution: Zap,
  betting: TrendingUp,
};

const STATUS_CFG: Record<StageStatus, { color: string; bg: string; border: string; label: string; Icon: React.ElementType }> = {
  healthy: { color: "text-emerald-400", bg: "bg-emerald-900/20", border: "border-emerald-500/30", label: "Healthy", Icon: CheckCircle },
  degraded: { color: "text-amber-400", bg: "bg-amber-900/20", border: "border-amber-500/30", label: "Degraded", Icon: AlertTriangle },
  down: { color: "text-rose-400", bg: "bg-rose-900/20", border: "border-rose-500/30", label: "Down", Icon: XCircle },
  unknown: { color: "text-slate-400", bg: "bg-slate-800/40", border: "border-slate-600/30", label: "Unknown", Icon: HelpCircle },
};

/* ── Props ─────────────────────────────────────────────────────── */

interface StageHealthCardsProps {
  stages: StageHealth[];
  className?: string;
}

/* ── Single card ───────────────────────────────────────────────── */

function StageCard({ stage }: { stage: StageHealth }) {
  const cfg = STATUS_CFG[stage.status] ?? STATUS_CFG.unknown;
  const StageIcon = STAGE_ICONS[stage.name] ?? Activity;
  const StatusIcon = cfg.Icon;

  // Latency bar (0-2000ms range)
  const latencyPct = Math.min((stage.latencyMs / 2000) * 100, 100);
  const latencyColor =
    stage.latencyMs <= 500
      ? "bg-emerald-500"
      : stage.latencyMs <= 1000
      ? "bg-amber-500"
      : "bg-rose-500";

  // Error rate bar (0-100% range)
  const errorPct = Math.min(stage.errorRate * 100, 100);
  const errorColor =
    stage.errorRate <= 0.01
      ? "bg-emerald-500"
      : stage.errorRate <= 0.05
      ? "bg-amber-500"
      : "bg-rose-500";

  return (
    <div className={`rounded-xl border p-4 ${cfg.bg} ${cfg.border} transition-all hover:scale-[1.01]`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <StageIcon className={`w-4 h-4 ${cfg.color}`} />
          <span className="text-sm font-semibold text-white">{stage.displayName}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <StatusIcon className={`w-3.5 h-3.5 ${cfg.color}`} />
          <span className={`text-[10px] font-medium ${cfg.color}`}>{cfg.label}</span>
        </div>
      </div>

      {/* Metrics */}
      <div className="space-y-2.5">
        {/* Latency */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-slate-500 flex items-center gap-1">
              <Clock className="w-3 h-3" /> Latency
            </span>
            <span className="text-[10px] font-mono text-white">
              {stage.latencyMs > 0 ? `${stage.latencyMs}ms` : "—"}
            </span>
          </div>
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${latencyColor}`}
              style={{ width: `${latencyPct}%` }}
            />
          </div>
        </div>

        {/* Throughput */}
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-slate-500 flex items-center gap-1">
            <BarChart3 className="w-3 h-3" /> Throughput
          </span>
          <span className="text-[10px] font-mono text-white">
            {stage.throughput > 0 ? stage.throughput : "—"}
          </span>
        </div>

        {/* Error rate */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-slate-500 flex items-center gap-1">
              <AlertOctagon className="w-3 h-3" /> Error Rate
            </span>
            <span className="text-[10px] font-mono text-white">
              {stage.errorRate > 0 ? `${(stage.errorRate * 100).toFixed(1)}%` : "0%"}
            </span>
          </div>
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${errorColor}`}
              style={{ width: `${errorPct}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main component ────────────────────────────────────────────── */

export default function StageHealthCards({ stages, className = "" }: StageHealthCardsProps) {
  if (stages.length === 0) {
    return (
      <div className="text-center py-8 text-slate-600 text-xs">
        No stage health data available
      </div>
    );
  }

  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 ${className}`}>
      {stages.map((stage) => (
        <StageCard key={stage.name} stage={stage} />
      ))}
    </div>
  );
}
