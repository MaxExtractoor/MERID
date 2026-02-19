/**
 * BrierTimeSeriesChart — Line chart showing Brier score evolution over time.
 *
 * Displays swarm Brier vs market Brier as two lines, with a shaded area
 * between them to highlight when the swarm outperforms the market.
 *
 * Uses the calibration array from /prediction/metrics which contains
 * bucket-level data, or can accept a custom time-series array.
 */

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";

interface BrierTimePoint {
  label: string;
  swarm_brier: number;
  market_brier: number;
  resolved_count?: number;
}

interface BrierTimeSeriesChartProps {
  data: BrierTimePoint[];
  height?: number;
}

export default function BrierTimeSeriesChart({
  data,
  height = 240,
}: BrierTimeSeriesChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-slate-500">
        No Brier time-series data — resolve markets to track accuracy over time
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="label"
          tick={{ fill: "#94a3b8", fontSize: 10 }}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={[0, 0.5]}
          tick={{ fill: "#94a3b8", fontSize: 11 }}
          label={{
            value: "Brier Score",
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
          labelStyle={{ color: "#94a3b8" }}
          formatter={(value: number, name: string) => [
            value.toFixed(4),
            name === "swarm_brier" ? "Swarm" : "Market",
          ]}
        />
        <Legend
          wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
          formatter={(value: string) =>
            value === "swarm_brier" ? "Swarm Brier" : "Market Brier"
          }
        />
        <ReferenceLine
          y={0.25}
          stroke="#475569"
          strokeDasharray="4 4"
          label={{
            value: "0.25 baseline",
            position: "right",
            fill: "#475569",
            fontSize: 10,
          }}
        />
        <Line
          type="monotone"
          dataKey="swarm_brier"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={{ r: 3, fill: "#3b82f6" }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="market_brier"
          stroke="#94a3b8"
          strokeWidth={2}
          strokeDasharray="5 5"
          dot={{ r: 3, fill: "#94a3b8" }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
