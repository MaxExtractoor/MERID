// web/react/src/components/HeaderStats.tsx
import React from "react";

type Props = {
  summary: Record<string, any>;
};

export const HeaderStats: React.FC<Props> = ({ summary }) => {
  const {
    total_pnl = 0,
    win_rate = 0,
    max_dd = 0,
    trades_today = 0,
    trades_7d = 0,
  } = summary;

  return (
    <div className="header-stats">
      <div className="stat">
        <div className="label">Total PnL</div>
        <div className="value">{(total_pnl ?? 0).toFixed(2)}</div>
      </div>
      <div className="stat">
        <div className="label">Win rate</div>
        <div className="value">{((win_rate ?? 0) * 100).toFixed(1)}%</div>
      </div>
      <div className="stat">
        <div className="label">Max DD</div>
        <div className="value">{(max_dd ?? 0).toFixed(2)}</div>
      </div>
      <div className="stat">
        <div className="label">Trades 24h</div>
        <div className="value">{trades_today}</div>
      </div>
      <div className="stat">
        <div className="label">Trades 7d</div>
        <div className="value">{trades_7d}</div>
      </div>
    </div>
  );
};
