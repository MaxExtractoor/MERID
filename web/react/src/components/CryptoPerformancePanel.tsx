// web/react/src/components/CryptoPerformancePanel.tsx
import React from "react";
import { HeaderStats } from "./HeaderStats";
import { EquityChart } from "./EquityChart";
import { RecentTradesTable } from "./RecentTradesTable";
import { BlockedReasonsChart } from "./BlockedReasonsChart";

type EquityPoint = { ts: string; value: number };

type TradeRow = {
  ts: string;
  market_id: string;
  side: string;
  size_pct: number;
  pnl: number;
  reason?: string;
};

type Props = {
  summary: Record<string, any>;
  equitySeries: EquityPoint[];
  recentTrades: TradeRow[];
  blockedReasons?: Record<string, number>;
};

export const CryptoPerformancePanel: React.FC<Props> = ({
  summary,
  equitySeries,
  recentTrades,
  blockedReasons,
}) => {
  if (!summary || Object.keys(summary).length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 text-center">
        <p className="text-slate-500 text-sm">No crypto performance data available yet.</p>
      </div>
    );
  }

  return (
    <div className="crypto-panel">
      <HeaderStats summary={summary} />
      <EquityChart series={equitySeries ?? []} />
      <div className="panel-grid">
        <RecentTradesTable trades={recentTrades ?? []} />
        <BlockedReasonsChart data={blockedReasons} />
      </div>
    </div>
  );
};
