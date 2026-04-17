// web/react/src/components/BlockedReasonsChart.tsx
import React from "react";

type Props = {
  data?: Record<string, number>;
};

const ORDER = [
  "vol_alert",
  "exposure_cap",
  "dd_guard",
  "min_edge",
  "chop_filter",
  "time_window",
  "venue_error",
];

export const BlockedReasonsChart: React.FC<Props> = ({ data }) => {
  if (!data || Object.keys(data).length === 0) {
    return <div className="blocked-reasons empty">No blocked signals in this window.</div>;
  }

  const entries = ORDER.filter((k) => data[k] != null).map((k) => [k, data[k]!] as [string, number]);

  return (
    <div className="blocked-reasons">
      <div className="chart-header">Blocked signals by reason</div>
      <ul>
        {entries.map(([reason, count]) => (
          <li key={reason}>
            <span className="reason-label">{reason}</span>
            <span className="bar">
              <span
                className="bar-fill"
                style={{ width: `${Math.min(100, count)}%` }}
              />
            </span>
            <span className="count">{count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};
