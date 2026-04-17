import { useMemo } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { DataFreshnessIndicator } from './DataFreshnessIndicator';

interface DataFeed {
  name: string;
  source: string;
  lastUpdate: string;
  stalenessMs: number;
  thresholdMs: number;
  status: 'fresh' | 'stale' | 'dead';
}

export default function DataHealthSummary() {
  const {
    data,
    loading,
    error,
    refetch,
  } = useApiData<{ feeds: DataFeed[] }>(API_ENDPOINTS.DATA_FRESHNESS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });

  const { staleCount, deadCount, lastUpdated } = useMemo(() => {
    const feeds = data?.feeds ?? [];
    const stale = feeds.filter((f) => f.status === 'stale').length;
    const dead = feeds.filter((f) => f.status === 'dead').length;
    const latest = feeds.reduce((ts: number | null, feed) => {
      if (!feed.lastUpdate) return ts;
      const currentTs = Date.parse(feed.lastUpdate);
      if (Number.isNaN(currentTs)) return ts;
      return ts == null || currentTs > ts ? currentTs : ts;
    }, null);
    return { staleCount: stale, deadCount: dead, lastUpdated: latest };
  }, [data?.feeds]);

  const statusLabel = deadCount > 0
    ? `${deadCount} dead feed${deadCount > 1 ? 's' : ''}`
    : staleCount > 0
      ? `${staleCount} stale`
      : loading
        ? 'Checking feeds…'
        : 'All feeds live';

  return (
    <section
      className="flex flex-wrap items-center gap-3 px-3 py-2 rounded-xl border border-slate-800/60 bg-slate-900/60 min-w-[220px]"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
        <Icon name="activity" size={16} className="w-4 h-4 text-cyan-300" aria-hidden="true" />
        <span>Data Health</span>
      </div>
      <div className="text-xs text-slate-400">
        {error ? (
          <button
            type="button"
            className="text-red-300 hover:text-red-200"
            onClick={() => refetch()}
          >
            Failed — retry
          </button>
        ) : (
          statusLabel
        )}
      </div>
      <div className="ml-auto">
        <DataFreshnessIndicator
          lastUpdated={lastUpdated}
          thresholdMs={DEFAULTS.POLLING_INTERVALS.FAST_REFRESH}
        />
      </div>
    </section>
  );
}
