import { Wifi, WifiOff, AlertTriangle, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { DataAgeBadge } from './DataAgeBadge';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface FeedEntry {
  feed_id: string;
  instrument: string;
  age_seconds: number;
  stale: boolean;
  critical: boolean;
  paused: boolean;
  last_update: number;
}

interface FreshnessData {
  feeds: FeedEntry[];
  total_feeds: number;
  stale_count: number;
  critical_count: number;
  paused_instruments: string[];
}

function statusColor(entry: FeedEntry): string {
  if (entry.critical) return 'text-red-400';
  if (entry.stale) return 'text-amber-400';
  return 'text-green-400';
}

function statusBg(entry: FeedEntry): string {
  if (entry.critical) return 'bg-red-500/20';
  if (entry.stale) return 'bg-amber-500/20';
  return 'bg-green-500/20';
}

export default function DataHealthCard() {
  const { data, loading, error: fetchError, refetch, lastUpdated } = useApiData<FreshnessData>(
    API_ENDPOINTS.DATA_FRESHNESS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STALENESS },
  );

  if (fetchError && !data) {
    return <ErrorBar label="Data health" error={fetchError} onRetry={refetch} />;
  }

  const feeds = data?.feeds ?? [];
  const staleCount = data?.stale_count ?? 0;
  const criticalCount = data?.critical_count ?? 0;
  const totalFeeds = data?.total_feeds ?? feeds.length;

  const overallStatus = criticalCount > 0 ? 'critical' : staleCount > 0 ? 'degraded' : 'healthy';

  if (loading && !data) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
        <div className="flex items-center gap-2 text-gray-400 text-sm">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading feed health…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {overallStatus === 'healthy' ? (
            <Wifi className="w-4 h-4 text-green-400" />
          ) : overallStatus === 'degraded' ? (
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          ) : (
            <WifiOff className="w-4 h-4 text-red-400" />
          )}
          <h3 className="text-sm font-semibold text-white">Data Health</h3>
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
            overallStatus === 'healthy' ? 'bg-green-500/20 text-green-400'
            : overallStatus === 'degraded' ? 'bg-amber-500/20 text-amber-400'
            : 'bg-red-500/20 text-red-400'
          }`}>
            {overallStatus.toUpperCase()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <DataAgeBadge lastUpdated={lastUpdated} />
          <button
            type="button"
            onClick={() => refetch()}
            className="p-1 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh feed health"
            aria-label="Refresh feed health"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Summary strip */}
      <div className="flex items-center gap-4 text-xs">
        <span className="text-green-400">{totalFeeds - staleCount - criticalCount} healthy</span>
        {staleCount > 0 && <span className="text-amber-400">{staleCount} stale</span>}
        {criticalCount > 0 && <span className="text-red-400">{criticalCount} critical</span>}
      </div>

      {/* Feed list */}
      {feeds.length > 0 && (
        <div className="space-y-1 max-h-[200px] overflow-y-auto">
          {feeds.map((f, idx) => (
            <div
              key={f.feed_id && f.instrument ? `${f.feed_id}:${f.instrument}` : `feed-${idx}`}
              className={`flex items-center justify-between px-2 py-1 rounded text-xs ${statusBg(f)}`}
            >
              <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${
                  f.critical ? 'bg-red-400' : f.stale ? 'bg-amber-400' : 'bg-green-400'
                }`} />
                <span className="text-slate-300 font-mono">{f.feed_id}</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-400">{f.instrument}</span>
              </div>
              <span className={`font-mono ${statusColor(f)}`}>
                {f.age_seconds < 60
                  ? `${Math.round(f.age_seconds)}s`
                  : `${Math.round(f.age_seconds / 60)}m`}
              </span>
            </div>
          ))}
        </div>
      )}

      {feeds.length === 0 && (
        <p className="text-xs text-slate-500">No feed data registered yet.</p>
      )}
    </div>
  );
}
