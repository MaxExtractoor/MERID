import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

interface ReadinessCheck {
  area: string;
  item: string;
  status: 'OK' | 'DRIFTED' | 'MISSING';
  evidence: string;
  fix_plan: string;
}

interface ReadinessData {
  passed: boolean;
  drift_count: number;
  checks: ReadinessCheck[];
}

interface SLOData {
  total_runs: number;
  window_runs: number;
  window_pass_count: number;
  pass_rate: number;
  current_streak: number;
  mean_time_to_fix_seconds: number;
  last_run_epoch: number;
  last_run_passed: boolean;
  history: Array<{ ts: number; passed: boolean; drift_count: number }>;
}

export default function DevSwarmReadiness() {
  const [data, setData] = useState<ReadinessData | null>(null);
  const [slo, setSlo] = useState<SLOData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [readinessRes, sloRes] = await Promise.all([
        axios.get('/api/dev-swarm/readiness'),
        axios.get('/api/dev-swarm/readiness/slo').catch(() => null),
      ]);
      setData(readinessRes.data);
      if (sloRes) setSlo(sloRes.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load readiness');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60000);
    return () => clearInterval(interval);
  }, [refresh]);

  const formatDuration = (seconds: number) => {
    if (seconds === 0) return 'N/A';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
  };

  const formatTimeAgo = (epoch: number) => {
    if (epoch === 0) return 'never';
    const ago = Math.round((Date.now() / 1000) - epoch);
    if (ago < 60) return `${ago}s ago`;
    if (ago < 3600) return `${Math.round(ago / 60)}m ago`;
    if (ago < 86400) return `${Math.round(ago / 3600)}h ago`;
    return `${Math.round(ago / 86400)}d ago`;
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'OK': return 'text-green-400';
      case 'DRIFTED': return 'text-yellow-400';
      case 'MISSING': return 'text-red-400';
      default: return 'text-slate-400';
    }
  };

  const statusDot = (status: string) => {
    switch (status) {
      case 'OK': return 'bg-green-500';
      case 'DRIFTED': return 'bg-yellow-500';
      case 'MISSING': return 'bg-red-500';
      default: return 'bg-slate-500';
    }
  };

  if (error) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800 p-4">
        <h3 className="text-sm font-medium text-red-400">Readiness Unavailable</h3>
        <p className="text-xs text-red-300 mt-1">{error}</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-slate-400">Readiness Audit</h3>
          {data && (
            <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold ${
              data.passed
                ? 'bg-green-500/10 text-green-400 border border-green-500/30'
                : 'bg-red-500/10 text-red-400 border border-red-500/30'
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${data.passed ? 'bg-green-500' : 'bg-red-500 animate-pulse'}`} />
              {data.passed ? 'ALL CLEAR' : `${data.drift_count} DRIFT`}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading && (
            <div className="animate-spin rounded-full h-3 w-3 border-b border-blue-500" />
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            {expanded ? 'Collapse' : 'Details'}
          </button>
          <button
            onClick={refresh}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Summary bar */}
      {data && (
        <div className="flex gap-1 mb-3">
          {data.checks.map((check, i) => (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full ${statusDot(check.status)}`}
              title={`${check.item}: ${check.status}`}
            />
          ))}
        </div>
      )}

      {/* Counts */}
      {data && (
        <div className="flex gap-4 text-xs">
          <span className="text-green-400">
            {data.checks.filter(c => c.status === 'OK').length} OK
          </span>
          {data.checks.filter(c => c.status === 'DRIFTED').length > 0 && (
            <span className="text-yellow-400">
              {data.checks.filter(c => c.status === 'DRIFTED').length} Drifted
            </span>
          )}
          {data.checks.filter(c => c.status === 'MISSING').length > 0 && (
            <span className="text-red-400">
              {data.checks.filter(c => c.status === 'MISSING').length} Missing
            </span>
          )}
          <span className="text-slate-500">
            {data.checks.length} checks
          </span>
        </div>
      )}

      {/* SLO Metrics */}
      {slo && slo.total_runs > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <h4 className="text-xs font-medium text-slate-500">SLO (last {slo.window_runs} runs)</h4>
            <span className="text-xs text-slate-600">{formatTimeAgo(slo.last_run_epoch)}</span>
          </div>
          <div className="grid grid-cols-4 gap-3">
            {/* Pass Rate */}
            <div>
              <div className={`text-lg font-bold ${slo.pass_rate >= 0.95 ? 'text-green-400' : slo.pass_rate >= 0.8 ? 'text-yellow-400' : 'text-red-400'}`}>
                {(slo.pass_rate * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-slate-500">Pass Rate</div>
            </div>
            {/* Streak */}
            <div>
              <div className="text-lg font-bold text-white">{slo.current_streak}</div>
              <div className="text-xs text-slate-500">Streak</div>
            </div>
            {/* MTTF */}
            <div>
              <div className="text-lg font-bold text-white">{formatDuration(slo.mean_time_to_fix_seconds)}</div>
              <div className="text-xs text-slate-500">MTTF</div>
            </div>
            {/* Total Runs */}
            <div>
              <div className="text-lg font-bold text-white">{slo.total_runs}</div>
              <div className="text-xs text-slate-500">Total Runs</div>
            </div>
          </div>
          {/* Mini history sparkline */}
          {slo.history.length > 1 && (
            <div className="flex gap-0.5 mt-2">
              {slo.history.map((run, i) => (
                <div
                  key={i}
                  className={`h-3 flex-1 rounded-sm ${run.passed ? 'bg-green-500/60' : 'bg-red-500/60'}`}
                  title={`${new Date(run.ts * 1000).toLocaleString()}: ${run.passed ? 'PASS' : `FAIL (${run.drift_count} drift)`}`}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Expanded detail table */}
      {expanded && data && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left pb-2 font-medium">Area</th>
                <th className="text-left pb-2 font-medium">Check</th>
                <th className="text-left pb-2 font-medium">Status</th>
                <th className="text-left pb-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data.checks.map((check, i) => (
                <tr key={i} className="border-t border-slate-800/50">
                  <td className="py-1.5 text-slate-400">{check.area}</td>
                  <td className="py-1.5 text-white">{check.item}</td>
                  <td className="py-1.5">
                    <span className={`flex items-center gap-1 ${statusColor(check.status)}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${statusDot(check.status)}`} />
                      {check.status}
                    </span>
                  </td>
                  <td className="py-1.5 text-slate-500 font-mono">{check.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
