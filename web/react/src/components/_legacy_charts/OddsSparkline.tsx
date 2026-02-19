/**
 * OddsSparkline — Compact inline sparkline showing odds movement over time.
 *
 * Renders a tiny recharts LineChart suitable for embedding in event cards.
 * Shows book_prob (blue) and swarm_prob (emerald) lines.
 * Optionally shows a line-move alert indicator.
 */

import {
  LineChart,
  Line,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import type { OddsPoint } from "../../hooks/useLiveOdds";

interface OddsSparklineProps {
  data: OddsPoint[];
  width?: number;
  height?: number;
  showAlert?: boolean;
}

export default function OddsSparkline({
  data,
  width = 120,
  height = 32,
  showAlert = false,
}: OddsSparklineProps) {
  if (data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[9px] text-slate-600"
        style={{ width, height }}
      >
        —
      </div>
    );
  }

  // Compute Y domain with padding
  const allVals = data.flatMap((d) => [d.book_prob, d.swarm_prob]);
  const yMin = Math.max(0, Math.min(...allVals) - 0.02);
  const yMax = Math.min(1, Math.max(...allVals) + 0.02);

  return (
    <div className="relative" style={{ width, height }}>
      {showAlert && (
        <div className="absolute -top-1 -right-1 w-2 h-2 bg-amber-400 rounded-full animate-pulse z-10" />
      )}
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <YAxis domain={[yMin, yMax]} hide />
          <Line
            type="monotone"
            dataKey="book_prob"
            stroke="#60a5fa"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="swarm_prob"
            stroke="#34d399"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
