// web/react/src/components/EquityChart.tsx
import React from "react";

type Point = { ts: string; value: number };

type Props = {
  series: Point[];
};

export const EquityChart: React.FC<Props> = ({ series }) => {
  if (!series || series.length === 0) {
    return <div className="equity-chart empty">No equity data yet.</div>;
  }

  // Placeholder: list last few points; replace with real chart.
  return (
    <div className="equity-chart">
      <div className="chart-header">Equity curve (last {series.length} points)</div>
      <ul>
        {series.slice(-20).map((p) => (
          <li key={p.ts}>
            <span>{new Date(p.ts).toLocaleString()}</span>
            <span>{p.value.toFixed(2)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};
