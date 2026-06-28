// web/react/src/components/KalshiPaperVsShadowPanel.tsx
import React from "react";
import { useKalshiPaperVsShadow } from "../hooks/useKalshiPaperVsShadow";

const AGENT_LABELS: { [key: string]: string } = {
  "btc_15m_regime": "BTC 15m",
  "eth_15m_regime": "ETH 15m",
  "sol_15m_regime": "SOL 15m",
  "xrp_15m_regime": "XRP 15m",
  // LEGACY REMOVAL: btc_1h_regime removed - 15m stack only
};

export const KalshiPaperVsShadowPanel: React.FC = () => {
  const { data, loading, error, refetch } = useKalshiPaperVsShadow();

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-64 mb-4" />
        <div className="h-24 bg-slate-800 rounded-lg mb-4" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <div key={i} className="h-8 bg-slate-800 rounded" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <span className="font-semibold">Paper vs Shadow Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button type="button" onClick={refetch} className="mt-3 text-sm text-blue-400 hover:text-blue-300">Retry</button>
      </div>
    );
  }

  if (!data || !data.comparison || Object.keys(data.comparison).length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 text-center">
        <p className="text-slate-500 text-sm">No paper vs shadow comparison data yet.</p>
      </div>
    );
  }

  const formatDelta = (value: number) => {
    const sign = value >= 0 ? "+" : "";
    return `${sign}${value.toFixed(2)}`;
  };

  const getDeltaClass = (value: number) => {
    if (value > 0) return "positive";
    if (value < 0) return "negative";
    return "neutral";
  };

  return (
    <div className="kalshi-paper-vs-shadow">
      <h3>Paper vs Shadow Comparison</h3>
      
      {/* Portfolio Summary */}
      {data.paper_summary && (
        <div className="paper-summary">
          <h4>Paper Portfolio Summary</h4>
          <div className="summary-grid">
            <div className="summary-item">
              <span className="label">Cash Balance:</span>
              <span className="value">${(data.paper_summary.cash_balance ?? 0).toFixed(2)}</span>
            </div>
            <div className="summary-item">
              <span className="label">Margin Used:</span>
              <span className="value">${(data.paper_summary.margin_used ?? 0).toFixed(2)}</span>
            </div>
            <div className="summary-item">
              <span className="label">Total P&L:</span>
              <span className={`value ${data.paper_summary.total_pnl >= 0 ? "positive" : "negative"}`}>
                ${(data.paper_summary.total_pnl ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="summary-item">
              <span className="label">Win Rate:</span>
              <span className="value">{((data.paper_summary.win_rate ?? 0) * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Agent Comparison */}
      <div className="agent-comparison">
        <h4>Agent Performance Comparison</h4>
        <table className="comparison-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Paper P&L</th>
              <th>Shadow P&L</th>
              <th>P&L Delta</th>
              <th>Paper Win Rate</th>
              <th>Shadow Win Rate</th>
              <th>Win Rate Delta</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.comparison).map(([agentId, comparison]) => (
              <tr key={agentId}>
                <td>{AGENT_LABELS[agentId] || agentId}</td>
                <td className={comparison.paper.total_pnl >= 0 ? "positive" : "negative"}>
                  ${(comparison.paper.total_pnl ?? 0).toFixed(2)}
                </td>
                <td className={(comparison.shadow.total_pnl ?? 0) >= 0 ? "positive" : "negative"}>
                  ${(comparison.shadow.total_pnl ?? 0).toFixed(2)}
                </td>
                <td className={getDeltaClass(comparison.pnl_delta)}>
                  {formatDelta(comparison.pnl_delta)}
                </td>
                <td>{((comparison.paper.win_rate ?? 0) * 100).toFixed(1)}%</td>
                <td>{((comparison.shadow.win_rate ?? 0) * 100).toFixed(1)}%</td>
                <td className={getDeltaClass(comparison.win_rate_delta)}>
                  {formatDelta(comparison.win_rate_delta * 100)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
