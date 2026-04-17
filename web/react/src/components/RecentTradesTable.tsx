// web/react/src/components/RecentTradesTable.tsx
import React from "react";

type TradeRow = {
  ts: string;
  market_id: string;
  side: string;
  size_pct: number;
  pnl: number;
  reason?: string;
};

type Props = {
  trades: TradeRow[];
};

export const RecentTradesTable: React.FC<Props> = ({ trades }) => {
  if (!trades || trades.length === 0) {
    return <div className="recent-trades empty">No trades yet.</div>;
  }

  return (
    <table className="recent-trades">
      <thead>
        <tr>
          <th>Time</th>
          <th>Market</th>
          <th>Side</th>
          <th>Size %</th>
          <th>PnL</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {trades.slice(0, 50).map((t, idx) => (
          <tr key={`${t.ts}-${idx}`}>
            <td>{new Date(t.ts).toLocaleTimeString()}</td>
            <td>{t.market_id}</td>
            <td>{t.side}</td>
            <td>{(t.size_pct * 100).toFixed(1)}</td>
            <td className={t.pnl >= 0 ? "pnl-pos" : "pnl-neg"}>{t.pnl.toFixed(2)}</td>
            <td>{t.reason ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};
