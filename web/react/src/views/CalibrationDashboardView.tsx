import React, { useEffect, useState, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { CorrelationRiskPanel } from '../components/CorrelationRiskPanel';

// ── Types ────────────────────────────────────────────────────────────────

interface ForecasterStats {
  forecaster_id: string;
  bucket: string;
  brier_score: number;
  weight: number;
  forecast_count: number;
  last_forecast_ts: number;
}

interface ResolverStatus {
  resolved_count: number;
  pending_count: number;
  last_run_ts: number;
  running: boolean;
}

// ── Component ────────────────────────────────────────────────────────────

const CalibrationDashboardView: React.FC = () => {
  const [forecasters, setForecasters] = useState<ForecasterStats[]>([]);
  const [resolver, setResolver] = useState<ResolverStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveAllStatus, setResolveAllStatus] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [fRes, rRes] = await Promise.all([
        fetch(`${API_BASE_URL}${API_ENDPOINTS.METRICS_FORECASTERS}`),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.METRICS_RESOLVER}`),
      ]);

      if (fRes.ok) {
        const fJson = await fRes.json();
        setForecasters(fJson.forecasters || []);
      }
      if (rRes.ok) {
        const rJson = await rRes.json();
        setResolver(rJson.resolver || null);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load calibration data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(interval);
  }, [fetchData]);

  const triggerResolveAll = async () => {
    try {
      setResolveAllStatus('resolving...');
      const res = await fetch(`${API_BASE_URL}/api/v1/kalshi/metrics/resolve-all`, {
        method: 'POST',
      });
      if (res.ok) {
        const json = await res.json();
        setResolveAllStatus(`Resolved ${json.resolved_count ?? 0} markets`);
        setTimeout(() => setResolveAllStatus(null), 3000);
        fetchData();
      } else {
        setResolveAllStatus('Failed');
        setTimeout(() => setResolveAllStatus(null), 3000);
      }
    } catch {
      setResolveAllStatus('Error');
      setTimeout(() => setResolveAllStatus(null), 3000);
    }
  };

  const brierColor = (score: number): string => {
    if (score <= 0.1) return 'text-emerald-400';
    if (score <= 0.2) return 'text-green-400';
    if (score <= 0.3) return 'text-yellow-300';
    if (score <= 0.4) return 'text-amber-400';
    return 'text-red-400';
  };

  const weightBar = (weight: number): string => {
    const pct = Math.min(100, Math.max(0, (weight / 5.0) * 100));
    return `${pct}%`;
  };

  const formatTs = (ts: number): string => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="p-4 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-100">
            Calibration Dashboard
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Brier scores, forecaster weights, resolution status, and correlation risk
          </p>
        </div>
        <div className="flex items-center gap-2">
          {resolveAllStatus && (
            <span className="text-xs text-amber-400 bg-amber-500/10 rounded px-2 py-1">
              {resolveAllStatus}
            </span>
          )}
          <button
            onClick={triggerResolveAll}
            className="px-3 py-1.5 text-xs font-medium text-gray-300 bg-indigo-600/30 border border-indigo-500/30 rounded hover:bg-indigo-600/50 transition-colors"
          >
            Resolve All Markets
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {/* Stats Cards Row */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Forecasters
          </div>
          <div className="text-xl font-bold text-gray-100">
            {new Set(forecasters.map(f => f.forecaster_id)).size}
          </div>
        </div>
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Total Forecasts
          </div>
          <div className="text-xl font-bold text-gray-100">
            {forecasters.reduce((a, f) => a + f.forecast_count, 0).toLocaleString()}
          </div>
        </div>
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Avg Brier
          </div>
          <div className={`text-xl font-bold ${brierColor(
            forecasters.length > 0
              ? forecasters.reduce((a, f) => a + f.brier_score, 0) / forecasters.length
              : 0.5
          )}`}>
            {forecasters.length > 0
              ? (forecasters.reduce((a, f) => a + f.brier_score, 0) / forecasters.length).toFixed(3)
              : '—'}
          </div>
        </div>
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Resolver
          </div>
          <div className={`text-xl font-bold ${resolver?.running ? 'text-emerald-400' : 'text-gray-500'}`}>
            {resolver?.running ? 'Active' : 'Idle'}
          </div>
          {resolver && (
            <div className="text-[10px] text-gray-500 mt-0.5">
              {resolver.resolved_count} resolved / {resolver.pending_count} pending
            </div>
          )}
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-3 gap-4">
        {/* Forecaster Table — 2 cols */}
        <div className="col-span-2 bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">
            Forecaster Performance
          </h3>
          {loading ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3].map(i => <div key={i} className="h-8 bg-gray-700 rounded" />)}
            </div>
          ) : forecasters.length === 0 ? (
            <div className="text-xs text-gray-500 text-center py-8">
              No forecaster data yet — agents will populate this as they trade
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-700/50">
                    <th className="text-left text-gray-500 py-1.5 px-2">Forecaster</th>
                    <th className="text-left text-gray-500 py-1.5 px-2">Bucket</th>
                    <th className="text-right text-gray-500 py-1.5 px-2">Brier</th>
                    <th className="text-right text-gray-500 py-1.5 px-2">Weight</th>
                    <th className="text-left text-gray-500 py-1.5 px-2">Weight Bar</th>
                    <th className="text-right text-gray-500 py-1.5 px-2"># Forecasts</th>
                    <th className="text-right text-gray-500 py-1.5 px-2">Last</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasters
                    .sort((a, b) => a.brier_score - b.brier_score)
                    .map((f) => (
                    <tr
                      key={`${f.forecaster_id}-${f.bucket}`}
                      className="border-b border-gray-800/30 hover:bg-gray-800/20"
                    >
                      <td className="py-1.5 px-2 text-gray-300 font-mono font-medium">
                        {f.forecaster_id}
                      </td>
                      <td className="py-1.5 px-2">
                        <span className="text-gray-400 bg-gray-700/40 rounded px-1.5 py-0.5">
                          {f.bucket}
                        </span>
                      </td>
                      <td className={`py-1.5 px-2 text-right font-mono font-semibold ${brierColor(f.brier_score)}`}>
                        {f.brier_score.toFixed(4)}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono text-gray-300">
                        {f.weight.toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2">
                        <div className="w-20 h-2 bg-gray-700/50 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-indigo-500 rounded-full transition-all"
                            style={{ width: weightBar(f.weight) }}
                          />
                        </div>
                      </td>
                      <td className="py-1.5 px-2 text-right text-gray-400">
                        {f.forecast_count.toLocaleString()}
                      </td>
                      <td className="py-1.5 px-2 text-right text-gray-500">
                        {formatTs(f.last_forecast_ts)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Correlation Risk Panel — 1 col */}
        <div className="col-span-1">
          <CorrelationRiskPanel />
        </div>
      </div>

      {/* Brier Score Guide */}
      <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
        <div className="flex items-center gap-6 text-[10px]">
          <span className="text-gray-500 font-semibold uppercase tracking-wider">
            Brier Guide:
          </span>
          <span className="text-emerald-400">≤0.10 Excellent</span>
          <span className="text-green-400">≤0.20 Good</span>
          <span className="text-yellow-300">≤0.30 Fair</span>
          <span className="text-amber-400">≤0.40 Poor</span>
          <span className="text-red-400">&gt;0.40 Bad</span>
          <span className="text-gray-600 ml-auto">
            Lower is better — 0.0 = perfect calibration
          </span>
        </div>
      </div>
    </div>
  );
};

export default CalibrationDashboardView;
