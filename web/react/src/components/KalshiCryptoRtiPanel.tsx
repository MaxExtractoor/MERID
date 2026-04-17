// web/react/src/components/KalshiCryptoRtiPanel.tsx
import React from "react";
import { useKalshiCryptoRti } from "../hooks/useKalshiCryptoRti";

const ASSET_COLORS = {
  btc: "text-orange-400",
  eth: "text-blue-400", 
  sol: "text-purple-400",
  xrp: "text-green-400",
};

export const KalshiCryptoRtiPanel: React.FC = () => {
  const { data, loading, error, refetch } = useKalshiCryptoRti();

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-48 mb-4" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-28 bg-slate-800 rounded-lg" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <span className="font-semibold">Crypto RTI Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button type="button" onClick={refetch} className="mt-3 text-sm text-blue-400 hover:text-blue-300">Retry</button>
      </div>
    );
  }

  if (!data || !data.data || Object.keys(data.data).length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 text-center">
        <p className="text-slate-500 text-sm">No RTI data available yet.</p>
      </div>
    );
  }

  const formatTime = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleTimeString();
  };

  return (
    <div className="kalshi-crypto-rti">
      <h3>Crypto RTI Diagnostics</h3>
      <div className="rti-grid">
        {Object.entries(data.data ?? {}).map(([asset, metrics]) => (
          <div key={asset} className={`asset-rti ${ASSET_COLORS[asset as keyof typeof ASSET_COLORS]}`}>
            <h4>{asset.toUpperCase()}</h4>
            <div className="rti-metrics">
              <div className="metric">
                <span className="label">RTI:</span>
                <span className="value">{(metrics.rti ?? 0).toFixed(3)}</span>
              </div>
              <div className="metric">
                <span className="label">SMA 60s:</span>
                <span className="value">{(metrics.sma_60s ?? 0).toFixed(3)}</span>
              </div>
              <div className="metric">
                <span className="label">Vol Ratio:</span>
                <span className={(metrics.vol_ratio ?? 0) > 1.2 ? "value warning" : "value"}>
                  {(metrics.vol_ratio ?? 0).toFixed(2)}
                </span>
              </div>
              <div className="metric">
                <span className="label">RTI Dev:</span>
                <span className={`value ${Math.abs(metrics.rti_sma_deviation ?? 0) > 0.05 ? "warning" : ""}`}>
                  {(metrics.rti_sma_deviation ?? 0) > 0 ? "+" : ""}{(metrics.rti_sma_deviation ?? 0).toFixed(3)}
                </span>
              </div>
              <div className="metric">
                <span className="label">Recent Spikes:</span>
                <span className="value">{metrics.recent_vol_spikes ?? 0}</span>
              </div>
            </div>
            
            {(metrics.vol_spike_events ?? []).length > 0 && (
              <div className="vol-spikes">
                <div className="spikes-header">Vol Spikes (last 24h)</div>
                <div className="spikes-list">
                  {(metrics.vol_spike_events ?? []).slice(-5).map((spike, idx) => (
                    <div key={idx} className="spike-item">
                      <span className="spike-time">{formatTime(spike.timestamp)}</span>
                      <span className="spike-magnitude">{(spike.magnitude ?? 0).toFixed(2)}x</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
