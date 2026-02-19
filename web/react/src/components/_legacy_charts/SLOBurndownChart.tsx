/**
 * SLOBurndownChart — Error budget burn-down over time.
 *
 * Shows a recharts AreaChart with:
 *   - Error budget remaining % (green → amber → red gradient)
 *   - Violation count as secondary bar overlay
 *   - 80% and 50% warning reference lines
 */

import {
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Bar,
  ComposedChart,
} from "recharts";
import type { SLOBurnPoint } from "../../hooks/useSLOMetrics";

interface SLOBurndownChartProps {
  data: SLOBurnPoint[];
  height?: number;
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getHours().toString().padStart(2, "0")}:${d
    .getMinutes()
    .toString()
    .padStart(2, "0")}`;
}

export default function SLOBurndownChart({
  data,
  height = 200,
}: SLOBurndownChartProps) {
  if (data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-sm text-slate-500"
        style={{ height }}
      >
        Collecting SLO data…
      </div>
    );
  }

  const chartData = data.map((p) => ({
    time: formatTime(p.timestamp),
    budget: p.budget_remaining_pct,
    violations: p.violations,
  }));

  // Determine gradient color based on current budget
  const currentBudget = data[data.length - 1].budget_remaining_pct;
  const areaColor =
    currentBudget >= 80
      ? "#34d399"
      : currentBudget >= 50
      ? "#fbbf24"
      : "#f87171";

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="time"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#475569" }}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: "#475569" }}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#1e293b",
            border: "1px solid #475569",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "#94a3b8" }}
          formatter={(value: number, name: string) =>
            name === "budget"
              ? [`${value}%`, "Budget Remaining"]
              : [value, "Violations"]
          }
        />
        <ReferenceLine
          y={80}
          stroke="#fbbf24"
          strokeDasharray="4 4"
          label={{ value: "80%", fill: "#fbbf24", fontSize: 9, position: "right" }}
        />
        <ReferenceLine
          y={50}
          stroke="#f87171"
          strokeDasharray="4 4"
          label={{ value: "50%", fill: "#f87171", fontSize: 9, position: "right" }}
        />
        <Area
          type="monotone"
          dataKey="budget"
          stroke={areaColor}
          fill={areaColor}
          fillOpacity={0.15}
          strokeWidth={2}
        />
        <Bar
          dataKey="violations"
          fill="#f87171"
          fillOpacity={0.4}
          barSize={4}
          radius={[2, 2, 0, 0]}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
