import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

interface DriftItem {
  id: string;
  domain: string;
  category: string;
  severity: 'OK' | 'INFO' | 'WARNING' | 'CRITICAL';
  summary: string;
  current_value: any;
  baseline_value: any;
  fix_plan: string;
}

interface DriftData {
  passed: boolean;
  drift_count: number;
  critical_count: number;
  baseline_version: string;
  items: DriftItem[];
}

export default function CodebaseHealth() {
  const [data, setData] = useState<DriftData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/dev-swarm/codebase-drift');
      setData(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load codebase health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 120000);
    return () => clearInterval(interval);
  }, [refresh]);

  const severityColor = (severity: string) => {
    switch (severity) {
      case 'OK': return 'text-green-400';
      case 'INFO': return 'text-blue-400';
      case 'WARNING': return 'text-yellow-400';
      case 'CRITICAL': return 'text-red-400';
      default: return 'text-slate-400';
    }
  };

  const severityDot = (severity: string) => {
    switch (severity) {
      case 'OK': return 'bg-green-500';
      case 'INFO': return 'bg-blue-500';
      case 'WARNING': return 'bg-yellow-500';
      case 'CRITICAL': return 'bg-red-500';
      default: return 'bg-slate-500';
    }
  };

  if (error) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800 p-4">
        <h3 className="text-sm font-medium text-red-400">Codebase Health Unavailable</h3>
        <p className="text-xs text-red-300 mt-1">{error}</p>
      </div>
    );
  }

  const okCount = data ? data.items.filter(i => i.severity === 'OK').length : 0;
  const totalCount = data ? data.items.length : 0;
  const domains = data ? [...new Set(data.items.filter(i => i.severity !== 'OK').map(i => i.domain))] : [];

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-slate-400">Codebase Health</h3>
          {data && (
            <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold ${
              data.passed
                ? 'bg-green-500/10 text-green-400 border border-green-500/30'
                : 'bg-red-500/10 text-red-400 border border-red-500/30'
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${data.passed ? 'bg-green-500' : 'bg-red-500 animate-pulse'}`} />
              {data.passed
                ? `${okCount}/${totalCount} OK`
                : `${data.critical_count} CRITICAL`}
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
        <div className="flex gap-0.5 mb-3">
          {data.items.map((item, i) => (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full ${severityDot(item.severity)}`}
              title={`${item.id}: ${item.summary}`}
            />
          ))}
        </div>
      )}

      {/* Counts + drift domains */}
      {data && (
        <div className="flex flex-wrap gap-3 text-xs">
          <span className="text-green-400">{okCount} OK</span>
          {data.items.filter(i => i.severity === 'WARNING').length > 0 && (
            <span className="text-yellow-400">
              {data.items.filter(i => i.severity === 'WARNING').length} Warning
            </span>
          )}
          {data.critical_count > 0 && (
            <span className="text-red-400">{data.critical_count} Critical</span>
          )}
          {data.items.filter(i => i.severity === 'INFO').length > 0 && (
            <span className="text-blue-400">
              {data.items.filter(i => i.severity === 'INFO').length} Info
            </span>
          )}
          <span className="text-slate-500">{totalCount} checks</span>
          {domains.length > 0 && (
            <span className="text-slate-600">
              Drift in: {domains.join(', ')}
            </span>
          )}
        </div>
      )}

      {/* Expanded detail table */}
      {expanded && data && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left pb-2 font-medium">ID</th>
                <th className="text-left pb-2 font-medium">Domain</th>
                <th className="text-left pb-2 font-medium">Status</th>
                <th className="text-left pb-2 font-medium">Summary</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item, i) => (
                <tr key={i} className="border-t border-slate-800/50">
                  <td className="py-1.5 text-slate-400 font-mono">{item.id}</td>
                  <td className="py-1.5 text-slate-400">{item.domain}</td>
                  <td className="py-1.5">
                    <span className={`flex items-center gap-1 ${severityColor(item.severity)}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${severityDot(item.severity)}`} />
                      {item.severity}
                    </span>
                  </td>
                  <td className="py-1.5 text-white">{item.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
