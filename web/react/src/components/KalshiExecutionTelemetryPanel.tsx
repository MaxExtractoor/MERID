// web/react/src/components/KalshiExecutionTelemetryPanel.tsx
import React from "react";
import { useKalshiExecutionTelemetry } from "../hooks/useKalshiExecutionTelemetry";

const STATUS_COLORS = {
  good: "text-green-400",
  warning: "text-yellow-400", 
  info: "text-slate-400",
};

export const KalshiExecutionTelemetryPanel: React.FC = () => {
  const { data, loading, error, refetch } = useKalshiExecutionTelemetry();

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-52 mb-4" />
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-24 bg-slate-800 rounded-lg" />)}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <span className="font-semibold">Execution Telemetry Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button type="button" onClick={refetch} className="mt-3 text-sm text-blue-400 hover:text-blue-300">Retry</button>
      </div>
    );
  }

  if (!data || !data.metrics || Object.keys(data.metrics).length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 text-center">
        <p className="text-slate-500 text-sm">No execution telemetry data yet.</p>
      </div>
    );
  }

  return (
    <div className="kalshi-execution-telemetry">
      <h3>Execution Telemetry</h3>
      <div className="telemetry-grid">
        {Object.entries(data.status ?? {}).map(([product, metrics]) => (
          <div key={product} className="product-telemetry">
            <h4>{product.replace('_', ' ').toUpperCase()}</h4>
            <div className="metrics-row">
              {Object.entries(metrics ?? {}).map(([metric, info]) => (
                <div key={metric} className="metric-item">
                  <div className="metric-name">{metric.replace(/_/g, ' ')}</div>
                  <div className={`metric-value ${STATUS_COLORS[info.status]}`}>
                    {typeof info.value === 'number' ? 
                      (metric.includes('latency') ? `${info.value.toFixed(0)}ms` : 
                       metric.includes('slippage') ? `${info.value.toFixed(2)}¢` :
                       info.value.toFixed(3)) :
                      info.value
                    }
                  </div>
                  {info.threshold && (
                    <div className="metric-threshold">
                      ≤{info.threshold}{metric.includes('latency') ? 'ms' : '¢'}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
