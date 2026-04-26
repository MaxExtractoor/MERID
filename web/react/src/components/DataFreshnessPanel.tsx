import React from 'react';
import { Clock, AlertTriangle, CheckCircle, XCircle, RefreshCw } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface DataFeed {
  name: string;
  source: string;
  lastUpdate: string;
  stalenessMs: number;
  thresholdMs: number;
  status: 'fresh' | 'stale' | 'dead';
}

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string; bg: string }> = {
  fresh: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10' },
  stale: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  dead: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10' },
};

function DataFreshnessPanel() {
  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ feeds: DataFeed[] }>(
    API_ENDPOINTS.DATA_FRESHNESS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Data freshness" error={fetchError} onRetry={refetch} />;
  }
  const feeds = rawData?.feeds ?? [];

  const sortedFeeds = [...feeds].sort((a, b) => {
    const order = { dead: 0, stale: 1, fresh: 2 };
    return order[a.status] - order[b.status];
  });

  const formatStaleness = (ms: number): string => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${((ms / 1000) ?? 0).toFixed(1)}s`;
    return `${((ms / 60000) ?? 0).toFixed(1)}m`;
  };

  const staleCount = feeds.filter(f => f.status === 'stale').length;
  const deadCount = feeds.filter(f => f.status === 'dead').length;

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading data freshness...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-bold text-white">Data Freshness</h3>
          {(staleCount > 0 || deadCount > 0) && (
            <span className="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-400">
              {staleCount > 0 && `${staleCount} stale`}
              {staleCount > 0 && deadCount > 0 && ' · '}
              {deadCount > 0 && `${deadCount} dead`}
            </span>
          )}
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh data freshness"
         aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-2 text-gray-400 font-medium">Feed</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Staleness</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Threshold</th>
              <th className="text-center px-4 py-2 text-gray-400 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {sortedFeeds.map((feed) => {
              const cfg = STATUS_CONFIG[feed.status] || STATUS_CONFIG['fresh'];
              const StatusIcon = cfg.icon;
              const staleness = feed.stalenessMs || 0;
              const threshold = feed.thresholdMs || 1;
              const pct = Math.min(100, (staleness / threshold) * 100);

              return (
                <tr key={feed.source || `feed-${sortedFeeds.indexOf(feed)}`} className={`border-b border-slate-700/30 ${cfg.bg}`}>
                  <td className="px-4 py-2">
                    <span className="text-white font-medium">{feed.name}</span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            pct > 100 ? 'bg-red-500' : pct > 80 ? 'bg-amber-500' : 'bg-green-500'
                          }`}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                      <span className={`font-mono ${cfg.color}`}>
                        {formatStaleness(feed.stalenessMs)}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400 font-mono">
                    {formatStaleness(feed.thresholdMs)}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <StatusIcon className={`w-4 h-4 mx-auto ${cfg.color}`} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

DataFreshnessPanel.displayName = 'DataFreshnessPanel';
export default React.memo(DataFreshnessPanel);
