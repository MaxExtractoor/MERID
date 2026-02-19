/**
 * LoopCadenceChart — Visualizes loop cycle timing and throughput over time.
 *
 * ComposedChart with:
 *   - Bar: cycle duration (ms)
 *   - Line: proposals generated per cycle
 *   - ReferenceLine: average cycle duration
 */

import React, { useMemo } from "react";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { CycleHistoryEntry } from "../../hooks/useLoopOrchestration";

/* ── Props ─────────────────────────────────────────────────────── */

interface LoopCadenceChartProps {
  history: CycleHistoryEntry[];
  avgCycleDurationMs?: number;
  height?: number;
}

/* ── Tooltip ───────────────────────────────────────────────────── */

interface CadenceTooltipItem {
  dataKey?: string;
  color?: string;
  name?: string;
  value?: number;
}

interface CadenceTooltipProps {
  active?: boolean;
  payload?: CadenceTooltipItem[];
  label?: number | string;
}

function CadenceTooltip({ active, payload, label }: CadenceTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs shadow-xl">
      <div className="text-slate-400 mb-1.5">Cycle #{label ?? '-'}</div>
      {payload.map((p) => {
        const value = typeof p.value === "number" ? p.value : 0;
        const name = typeof p.name === "string" ? p.name : String(p.dataKey ?? "");
        const key = p.dataKey ?? p.name ?? String(value);
        return (
        <div key={key} className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: p.color ?? "#64748b" }}
          />
          <span className="text-slate-300">{name}:</span>
          <span className="text-white font-mono">
            {p.dataKey === "durationMs"
              ? `${(value / 1000).toFixed(2)}s`
              : value}
          </span>
        </div>
        );
      })}
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────── */

export default function LoopCadenceChart({
  history,
  avgCycleDurationMs = 0,
  height = 260,
}: LoopCadenceChartProps) {
  const chartData = useMemo(
    () =>
      history.map((c) => ({
        cycle: c.cycleId,
        durationMs: c.totalDurationMs,
        proposals: c.proposalsGenerated,
        phases: c.phaseCount,
      })),
    [history]
  );

  if (chartData.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-slate-600 text-xs"
        style={{ height }}
      >
        No cycle history available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="cycle"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#475569" }}
          label={{ value: "Cycle #", position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 10 }}
        />
        <YAxis
          yAxisId="duration"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#475569" }}
          tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}s`}
          label={{ value: "Duration", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 10 }}
        />
        <YAxis
          yAxisId="count"
          orientation="right"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#475569" }}
          label={{ value: "Count", angle: 90, position: "insideRight", fill: "#64748b", fontSize: 10 }}
        />
        <Tooltip content={<CadenceTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 10, color: "#94a3b8" }}
          iconSize={8}
        />

        {/* Average duration reference line */}
        {avgCycleDurationMs > 0 && (
          <ReferenceLine
            yAxisId="duration"
            y={avgCycleDurationMs}
            stroke="#f59e0b"
            strokeDasharray="4 4"
            label={{
              value: `avg ${(avgCycleDurationMs / 1000).toFixed(1)}s`,
              fill: "#f59e0b",
              fontSize: 9,
              position: "right",
            }}
          />
        )}

        <Bar
          yAxisId="duration"
          dataKey="durationMs"
          name="Duration"
          fill="#3b82f6"
          fillOpacity={0.6}
          radius={[3, 3, 0, 0]}
          maxBarSize={30}
        />
        <Line
          yAxisId="count"
          dataKey="proposals"
          name="Proposals"
          stroke="#10b981"
          strokeWidth={2}
          dot={{ r: 2, fill: "#10b981" }}
          activeDot={{ r: 4 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
