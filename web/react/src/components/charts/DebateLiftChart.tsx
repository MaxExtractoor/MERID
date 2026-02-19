/**
 * DebateLiftChart — Bar chart showing pre-debate vs post-debate accuracy
 * per agent, with the "lift" (improvement) highlighted.
 *
 * Uses the debate_impact array from the leaderboard endpoint.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from "recharts";

interface DebateLiftEntry {
  agent_id: string;
  avg_lift: number;
  debate_count: number;
}

interface DebateLiftChartProps {
  data: DebateLiftEntry[];
  height?: number;
}

export default function DebateLiftChart({
  data,
  height = 220,
}: DebateLiftChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-slate-500">
        No debate lift data — resolve debates to see lift metrics
      </div>
    );
  }

  const chartData = data
    .slice(0, 12)
    .map((d) => ({
      name:
        d.agent_id.length > 14
          ? d.agent_id.slice(0, 14) + "\u2026"
          : d.agent_id,
      lift: Math.round(d.avg_lift * 10000) / 100,
      debates: d.debate_count,
      raw_lift: d.avg_lift,
    }))
    .sort((a, b) => b.lift - a.lift);

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={chartData}
          margin={{ top: 5, right: 15, bottom: 40, left: 10 }}
        >
          <XAxis
            dataKey="name"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            interval={0}
            angle={-25}
            textAnchor="end"
            height={55}
          />
          <YAxis
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            label={{
              value: "Avg Lift (pp)",
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
            formatter={(value: number, _name: string, props: { payload?: { debates?: number } }) => [
              `${value.toFixed(2)} pp (${props.payload?.debates ?? 0} debates)`,
              "Avg Lift",
            ]}
          />
          <ReferenceLine y={0} stroke="#475569" />
          <Bar dataKey="lift" radius={[4, 4, 0, 0]} barSize={24}>
            {chartData.map((entry, idx) => (
              <Cell
                key={idx}
                fill={
                  entry.lift > 1
                    ? "#22c55e"
                    : entry.lift > 0
                    ? "#3b82f6"
                    : entry.lift > -1
                    ? "#eab308"
                    : "#ef4444"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex items-center justify-center gap-4 text-[10px] text-slate-500 mt-1">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />{" "}
          Strong lift (&gt;1pp)
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />{" "}
          Positive
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-yellow-500 inline-block" />{" "}
          Marginal
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />{" "}
          Negative
        </span>
      </div>
    </div>
  );
}
