// web/react/src/components/KalshiCryptoSignalsPanel.tsx
import React from "react";
import { useKalshiCryptoEdgeSignals } from "../hooks/useKalshiCryptoSignals";

export const KalshiCryptoSignalsPanel: React.FC = () => {
  const { data, loading, error, refetch } = useKalshiCryptoEdgeSignals();

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-52 mb-4" />
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
          <span className="font-semibold">Crypto Signals Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button type="button" onClick={refetch} className="mt-3 text-sm text-blue-400 hover:text-blue-300">Retry</button>
      </div>
    );
  }

  if (!data || data.count === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 text-center">
        <p className="text-slate-500 text-sm">No crypto edge signals available.</p>
      </div>
    );
  }

  return (
    <div className="kalshi-crypto-signals">
      <h3>Crypto Edge Signals ({data.count})</h3>
      <table className="signals-table">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Product</th>
            <th>EV (¢)</th>
            <th>Edge %</th>
            <th>Confidence</th>
            <th>Bucket</th>
            <th>Bid</th>
            <th>Ask</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.signals).map(([agentId, signal]) => (
            <tr key={agentId}>
              <td>{agentId.replace('_regime', '')}</td>
              <td>{signal.product || '—'}</td>
              <td className={signal.ev_cents >= 0 ? "positive" : "negative"}>
                {(signal.ev_cents ?? 0).toFixed(2)}
              </td>
              <td className={signal.edge_pct >= 0 ? "positive" : "negative"}>
                {((signal.edge_pct ?? 0) * 100).toFixed(2)}%
              </td>
              <td>{((signal.confidence ?? 0) * 100).toFixed(1)}%</td>
              <td>{signal.confidence_bucket}</td>
              <td>{signal.bid?.toFixed(2) ?? '—'}</td>
              <td>{signal.ask?.toFixed(2) ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="summary">
        <span>Kelly: {((data.kelly_fraction ?? 0) * 100).toFixed(1)}%</span>
        <span>Effective: {((data.effective_fraction ?? 0) * 100).toFixed(1)}%</span>
        <span>DD: {(data.drawdown_pct ?? 0).toFixed(2)}%</span>
      </div>
    </div>
  );
};
