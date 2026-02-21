/**
 * SLOStatusCards — Per-subsystem SLO health gauges with budget remaining.
 *
 * Shows a grid of cards, each with:
 *   - Subsystem name
 *   - P95 latency vs threshold
 *   - OK/breach indicator
 *   - Mini progress bar for budget usage
 *   - Sample count
 */

import { CheckCircle, XCircle, Timer } from "lucide-react";
import type { SubsystemSLO } from "../../hooks/useSLOMetrics";

interface SLOStatusCardsProps {
  subsystems: SubsystemSLO[];
  overallOk: boolean;
  overallP95Ms: number | null;
  overallThresholdMs: number;
  errorBudgetPct: number;
}

export default function SLOStatusCards({
  subsystems,
  overallOk,
  overallP95Ms,
  overallThresholdMs,
  errorBudgetPct,
}: SLOStatusCardsProps) {
  return (
    <div className="space-y-4">
      {/* Overall budget gauge */}
      <div
        className={`flex items-center justify-between p-4 rounded-xl border ${
          overallOk
            ? "bg-emerald-500/10 border-emerald-500/30"
            : "bg-rose-500/10 border-rose-500/30"
        }`}
      >
        <div className="flex items-center gap-3">
          {overallOk ? (
            <CheckCircle className="w-6 h-6 text-emerald-400" />
          ) : (
            <XCircle className="w-6 h-6 text-rose-400" />
          )}
          <div>
            <p className="text-sm font-semibold text-white">
              Overall SLO: {overallOk ? "Healthy" : "Breached"}
            </p>
            <p className="text-xs text-slate-400">
              P95: {overallP95Ms !== null ? `${overallP95Ms}ms` : "—"} /{" "}
              {overallThresholdMs}ms target
            </p>
          </div>
        </div>
        <div className="text-right">
          <p
            className={`text-2xl font-bold ${
              errorBudgetPct >= 80
                ? "text-emerald-400"
                : errorBudgetPct >= 50
                ? "text-amber-400"
                : "text-rose-400"
            }`}
          >
            {errorBudgetPct}%
          </p>
          <p className="text-[10px] text-slate-500">Error Budget</p>
        </div>
      </div>

      {/* Per-subsystem cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {subsystems.map((sub) => {
          const usagePct =
            sub.p95_ms !== null && sub.threshold_ms > 0
              ? Math.min(100, Math.round((sub.p95_ms / sub.threshold_ms) * 100))
              : 0;
          const barColor = sub.ok
            ? "bg-emerald-500"
            : usagePct > 120
            ? "bg-rose-500"
            : "bg-amber-500";

          return (
            <div
              key={sub.name}
              className={`border rounded-xl p-3 transition-all ${
                sub.ok
                  ? "bg-slate-800/40 border-slate-700/50"
                  : "bg-rose-500/5 border-rose-500/20"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {sub.ok ? (
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-rose-400" />
                  )}
                  <span className="text-xs font-medium text-white capitalize">
                    {sub.name.replace(/_/g, " ")}
                  </span>
                </div>
                <span className="text-[10px] text-slate-500">
                  {sub.samples} samples
                </span>
              </div>

              {/* Latency display */}
              <div className="flex items-baseline gap-1 mb-2">
                <Timer className="w-3 h-3 text-slate-500" />
                <span
                  className={`text-lg font-bold ${
                    sub.ok ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {sub.p95_ms !== null ? `${sub.p95_ms}ms` : "—"}
                </span>
                <span className="text-[10px] text-slate-500">
                  / {sub.threshold_ms}ms
                </span>
              </div>

              {/* Usage bar */}
              <div className="w-full h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor}`}
                  style={{ width: `${Math.min(usagePct, 100)}%` }}
                />
              </div>
              <div className="flex justify-between mt-1">
                <span className="text-[9px] text-slate-600">0ms</span>
                <span className="text-[9px] text-slate-600">
                  {usagePct}% of budget
                </span>
                <span className="text-[9px] text-slate-600">
                  {sub.threshold_ms}ms
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
