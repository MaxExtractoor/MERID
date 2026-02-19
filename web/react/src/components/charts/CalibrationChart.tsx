/**
 * CalibrationChart — Predicted vs Actual probability calibration plot.
 *
 * Shows bins along the x-axis (predicted probability) and actual outcome
 * rate on the y-axis. A perfectly calibrated model lies on the diagonal.
 * Uses recharts ScatterChart with a reference diagonal line.
 */

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";
import type { CalibrationBin } from "../../hooks/useDebateCalibration";

interface CalibrationChartProps {
  bins: CalibrationBin[];
  agentId?: string;
  height?: number;
}

export default function CalibrationChart({
  bins,
  agentId,
  height = 260,
}: CalibrationChartProps) {
  if (!bins || bins.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-slate-500">
        No calibration data available
      </div>
    );
  }

  const data = bins.map((b) => ({
    predicted: Math.round(b.predicted_avg * 100),
    actual: Math.round(b.actual_rate * 100),
    count: b.count,
    deviation: Math.abs(b.predicted_avg - b.actual_rate),
  }));

  return (
    <div>
      {agentId && (
        <div className="text-xs text-slate-400 mb-2">
          Calibration for <span className="text-white font-medium">{agentId}</span>
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            type="number"
            dataKey="predicted"
            name="Predicted"
            domain={[0, 100]}
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            label={{
              value: "Predicted Probability (%)",
              position: "insideBottom",
              offset: -10,
              fill: "#64748b",
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="actual"
            name="Actual"
            domain={[0, 100]}
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            label={{
              value: "Actual Rate (%)",
              angle: -90,
              position: "insideLeft",
              offset: 5,
              fill: "#64748b",
              fontSize: 11,
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 8,
            }}
            formatter={(value: number, name: string) => [
              `${value}%`,
              name === "predicted" ? "Predicted" : "Actual",
            ]}
            labelFormatter={() => ""}
          />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: 100, y: 100 },
            ]}
            stroke="#475569"
            strokeDasharray="4 4"
            label={{
              value: "Perfect",
              position: "insideTopLeft",
              fill: "#475569",
              fontSize: 10,
            }}
          />
          <Scatter data={data} fill="#3b82f6">
            {data.map((entry, idx) => (
              <Cell
                key={idx}
                fill={
                  entry.deviation < 0.05
                    ? "#22c55e"
                    : entry.deviation < 0.15
                    ? "#eab308"
                    : "#ef4444"
                }
                r={Math.max(4, Math.min(12, entry.count / 2))}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <div className="flex items-center justify-center gap-4 text-[10px] text-slate-500 mt-1">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Well calibrated (&lt;5%)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-yellow-500 inline-block" /> Moderate (5-15%)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Poor (&gt;15%)
        </span>
      </div>
    </div>
  );
}
