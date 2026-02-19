import { useState } from 'react';
import {
  Bell, RefreshCw, Search, AlertTriangle,
  AlertOctagon, Info, CheckCircle
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface AlertRecord {
  id: string;
  timestamp: string;
  severity: 'critical' | 'warning' | 'info' | 'resolved';
  source: string;
  title: string;
  detail: string;
  acknowledged: boolean;
}

const SEV_CONFIG: Record<string, { icon: typeof AlertOctagon; color: string; bg: string }> = {
  critical: { icon: AlertOctagon, color: 'text-red-400', bg: 'bg-red-500/10' },
  warning: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  info: { icon: Info, color: 'text-blue-400', bg: 'bg-blue-500/10' },
  resolved: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10' },
};

export default function AlertHistoryPanel() {
  const [search, setSearch] = useState('');
  const [sevFilter, setSevFilter] = useState<string>('all');

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ alerts: AlertRecord[] }>(
    API_ENDPOINTS.SIGNALS_ALERTS_HISTORY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Alert history" error={fetchError} onRetry={refetch} />;
  }
  const alerts = rawData?.alerts ?? [];

  const filtered = alerts
    .filter(a => sevFilter === 'all' || a.severity === sevFilter)
    .filter(a => !search || a.title.toLowerCase().includes(search.toLowerCase()) || a.source.toLowerCase().includes(search.toLowerCase()));

  const formatTime = (ts: string) => {
    const ms = Date.now() - new Date(ts).getTime();
    if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`;
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
    return `${Math.floor(ms / 3600000)}h ago`;
  };

  const critCount = alerts.filter(a => a.severity === 'critical' && !a.acknowledged).length;

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading alert history...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="w-5 h-5 text-amber-400" />
          <h3 className="text-lg font-bold text-white">Alert History</h3>
          {critCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 animate-pulse">
              {critCount} unack
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" />
            <input aria-label="Search"
              id="alert-history-search"
              name="alertSearch"
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search..."
              className="pl-7 pr-2 py-1 text-xs bg-slate-700 border border-slate-600 rounded text-gray-300 placeholder-gray-500 w-32 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="flex gap-1">
            {['all', 'critical', 'warning', 'info', 'resolved'].map(f => (
              <button type="button"
                key={f}
                onClick={() => setSevFilter(f)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  sevFilter === f ? 'bg-amber-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => refetch()} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh alerts" aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {filtered.map(alert => {
          const cfg = SEV_CONFIG[alert.severity] || SEV_CONFIG.info;
          const Icon = cfg.icon;
          return (
            <div
              key={alert.id}
              className={`${cfg.bg} rounded-lg border border-slate-700/50 p-3 ${
                !alert.acknowledged ? 'border-l-2 border-l-red-500' : ''
              }`}
            >
              <div className="flex items-start gap-2">
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${cfg.color}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-white">{alert.title}</span>
                    <span className="text-xs text-gray-500 flex-shrink-0 ml-2">{formatTime(alert.timestamp)}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-gray-400">{alert.source}</span>
                    <span className="text-xs text-gray-500">·</span>
                    <span className="text-xs text-gray-500">{alert.detail}</span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
