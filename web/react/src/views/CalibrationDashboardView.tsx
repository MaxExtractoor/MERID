import React, { useEffect, useState, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { CorrelationRiskPanel } from '../components/CorrelationRiskPanel';
import { getAuthHeaders } from '../services/auth';

// ── Types ────────────────────────────────────────────────────────────────

interface ForecasterStats {
  forecaster_id: string;
  avg_ewma_brier: number;
  consensus_weight: number;
  total_forecasts_resolved: number;
  total_trades: number;
  total_pnl_cents: number;
  brier_by_bucket: Record<string, any>;
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
  const [recalibration, setRecalibration] = useState<Record<string, any> | null>(null);
  const [critiques, setCritiques] = useState<Record<string, any>[]>([]);
  const [execStats, setExecStats] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveAllStatus, setResolveAllStatus] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const opts = { headers: getAuthHeaders() };
      const [fRes, rRes, rcRes, crRes, exRes] = await Promise.all([
        fetch(`${API_BASE_URL}${API_ENDPOINTS.METRICS_FORECASTERS}`, opts),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.METRICS_RESOLVER}`, opts),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.SWARM_RECALIBRATION}`, opts).catch(() => null),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.SWARM_CRITIC_HISTORY}`, opts).catch(() => null),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.SWARM_EXECUTION_STATS}`, opts).catch(() => null),
      ]);

      if (fRes.ok) {
        const fJson = await fRes.json();
        setForecasters(fJson.forecasters || []);
      }
      if (rRes.ok) {
        const rJson = await rRes.json();
        setResolver(rJson.resolver || null);
      }
      if (rcRes?.ok) {
        const rcJson = await rcRes.json();
        setRecalibration(rcJson.latest || null);
      }
      if (crRes?.ok) {
        const crJson = await crRes.json();
        setCritiques(crJson.critiques?.slice(-10) || []);
      }
      if (exRes?.ok) {
        const exJson = await exRes.json();
        setExecStats(exJson.stats || null);
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
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_METRICS_RESOLVE_ALL}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (res.ok) {
        const json = await res.json();
        setResolveAllStatus(`Resolved ${json.resolved_count ?? 0} markets`);
        setTimeout(() => setResolveAllStatus(null), DEFAULTS.TIMEOUTS.TOAST);
        fetchData();
      } else {
        setResolveAllStatus('Failed');
        setTimeout(() => setResolveAllStatus(null), DEFAULTS.TIMEOUTS.TOAST);
      }
    } catch {
      setResolveAllStatus('Error');
      setTimeout(() => setResolveAllStatus(null), DEFAULTS.TIMEOUTS.TOAST);
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
          <button type="button"
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
            {(forecasters.reduce((a, f) => a + f.total_forecasts_resolved, 0) ?? 0).toLocaleString()}
          </div>
        </div>
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">
            Avg Brier
          </div>
          <div className={`text-xl font-bold ${brierColor(
            forecasters.length > 0
              ? forecasters.reduce((a, f) => a + f.avg_ewma_brier, 0) / forecasters.length
              : 0.5
          )}`}>
            {forecasters.length > 0
              ? ((forecasters.reduce((a, f) => a + f.avg_ewma_brier, 0) / forecasters.length) ?? 0).toFixed(3)
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
                    <th className="text-right text-gray-500 py-1.5 px-2">Brier</th>
                    <th className="text-right text-gray-500 py-1.5 px-2">Weight</th>
                    <th className="text-left text-gray-500 py-1.5 px-2">Weight Bar</th>
                    <th className="text-right text-gray-500 py-1.5 px-2"># Resolved</th>
                    <th className="text-right text-gray-500 py-1.5 px-2">Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasters
                    .sort((a, b) => a.avg_ewma_brier - b.avg_ewma_brier)
                    .map((f) => (
                    <tr
                      key={f.forecaster_id}
                      className="border-b border-gray-800/30 hover:bg-gray-800/20"
                    >
                      <td className="py-1.5 px-2 text-gray-300 font-mono font-medium">
                        {f.forecaster_id}
                      </td>
                      <td className={`py-1.5 px-2 text-right font-mono font-semibold ${brierColor(f.avg_ewma_brier)}`}>
                        {(f.avg_ewma_brier ?? 0).toFixed(4)}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono text-gray-300">
                        {(f.consensus_weight ?? 0).toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2">
                        <div className="w-20 h-2 bg-gray-700/50 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-indigo-500 rounded-full transition-all"
                            style={{ width: weightBar(f.consensus_weight) }}
                          />
                        </div>
                      </td>
                      <td className="py-1.5 px-2 text-right text-gray-400">
                        {(f.total_forecasts_resolved ?? 0).toLocaleString()}
                      </td>
                      <td className="py-1.5 px-2 text-right text-gray-400">
                        {(f.total_trades ?? 0).toLocaleString()}
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

      {/* Edge Recalibration + Critic Feed + Execution Stats */}
      <div className="grid grid-cols-3 gap-4">
        {/* Edge Recalibration — 1 col */}
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Edge Recalibration</h3>
          {recalibration ? (
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">Trades</span>
                <span className="text-gray-300 font-mono">{recalibration.trade_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Predicted Edge</span>
                <span className="text-gray-300 font-mono">{(((recalibration.avg_predicted_edge ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Realized Edge</span>
                <span className="text-gray-300 font-mono">{(((recalibration.avg_realized_edge ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Bias</span>
                <span className={`font-mono font-semibold ${recalibration.edge_bias > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                  {(recalibration.edge_bias ?? 0) > 0 ? '+' : ''}{(((recalibration.edge_bias ?? 0) * 100)).toFixed(2)}%
                </span>
              </div>
              {Object.keys(recalibration.adjustments || {}).length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-700/50">
                  <div className="text-[10px] text-gray-500 uppercase mb-1">Adjustments</div>
                  {Object.entries(recalibration.adjustments).map(([phase, change]) => (
                    <div key={phase} className="flex justify-between text-[10px]">
                      <span className="text-gray-400">{phase}</span>
                      <span className="text-gray-300 font-mono">{String(change)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-gray-500 text-center py-4">
              No recalibration data yet
            </div>
          )}
        </div>

        {/* Critic Feed — 1 col */}
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">
            Critic Feed
            {critiques.length > 0 && (
              <span className="ml-2 text-[10px] text-gray-500 font-normal">({critiques.length})</span>
            )}
          </h3>
          {critiques.length > 0 ? (
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {critiques.slice().reverse().map((c, idx) => (
                <div key={idx} className="flex items-start gap-2 text-[10px] py-1 border-b border-gray-800/30">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${
                    (c.severity ?? 0) >= 0.8 ? 'bg-red-500/20 text-red-400' :
                    (c.severity ?? 0) >= 0.5 ? 'bg-amber-500/20 text-amber-400' :
                    'bg-gray-600/20 text-gray-400'
                  }`}>
                    {c.critique_type}
                  </span>
                  <span className="text-gray-400 truncate flex-1">{c.reason}</span>
                  <span className="text-gray-600 shrink-0">w={c.weight_adjustment?.toFixed(1)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-gray-500 text-center py-4">
              No critiques — all feeds healthy
            </div>
          )}
        </div>

        {/* Execution Subscriber Stats — 1 col */}
        <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">Execution Bus</h3>
          {execStats ? (
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">Decisions Received</span>
                <span className="text-gray-300 font-mono">{execStats.received}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Routed to Execution</span>
                <span className="text-emerald-400 font-mono font-semibold">{execStats.routed}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Skipped</span>
                <span className="text-gray-400 font-mono">{execStats.skipped}</span>
              </div>
              {execStats.received > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-700/50">
                  <div className="w-full h-2 bg-gray-700/50 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 rounded-full"
                      style={{ width: `${(execStats.routed / execStats.received) * 100}%` }}
                    />
                  </div>
                  <div className="text-[10px] text-gray-500 mt-1 text-center">
                    {((((execStats.routed ?? 0) / (execStats.received || 1)) * 100)).toFixed(0)}% routed
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-gray-500 text-center py-4">
              Execution subscriber idle
            </div>
          )}
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
