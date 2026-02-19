import { useState } from 'react';
import { DollarSign, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { DataAgeBadge } from './DataAgeBadge';
import ErrorBar from './ErrorBar';
import { DEFAULTS, API_ENDPOINTS, CHART_COLORS} from "../config/constants";
import { useFeatureFlags } from '../config/featureFlags';

interface PnLDataPoint {
  timestamp: string;
  prediction: number;
  crypto: number;
  equity: number;
  total: number;
}

const DOMAIN_COLORS: Record<string, string> = {
  prediction: CHART_COLORS.DEEP_ORANGE,
  crypto: CHART_COLORS.BLUE,
  equity: CHART_COLORS.GREEN,
  total: CHART_COLORS.LIGHT_PURPLE,
};

export type TimeRange = '1h' | '4h' | '24h' | '7d';

interface DomainPnLChartProps {
  /** When provided, overrides the internal time range selector. */
  externalTimeRange?: TimeRange;
}

export default function DomainPnLChart({ externalTimeRange }: DomainPnLChartProps = {}) {
  const { kalshiOnly } = useFeatureFlags();
  const [internalRange, setInternalRange] = useState<TimeRange>('24h');
  const timeRange = externalTimeRange ?? internalRange;

  // Skip in Kalshi mode - this is crypto-specific domain PnL
  const { data: rawData, loading, error, refetch, lastUpdated } = useApiData<{ data: PnLDataPoint[] }>(
    kalshiOnly ? '' : API_ENDPOINTS.PIPELINE_PNL(timeRange),
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );
  const data = rawData?.data ?? [];

  if (error && !rawData) {
    return <ErrorBar label="PnL chart" error={error} onRetry={refetch} />;
  }

  const latest = data.length > 0 ? data[data.length - 1] : null;
  const minVal = data.length > 0 ? Math.min(...data.map(d => Math.min(d.prediction, d.crypto, d.equity, d.total))) : 0;
  const maxVal = data.length > 0 ? Math.max(...data.map(d => Math.max(d.prediction, d.crypto, d.equity, d.total))) : 100;
  const range = maxVal - minVal || 1;

  const toY = (val: number) => {
    return 100 - ((val - minVal) / range) * 100;
  };

  const buildPath = (key: keyof PnLDataPoint) => {
    if (data.length === 0) return '';
    return data.map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = toY(d[key] as number);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading PnL data...</span>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-500">
          <DollarSign className="w-5 h-5" />
          <span>No PnL data yet — waiting for first trades</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-green-400" />
          <h3 className="text-lg font-bold text-white">Domain PnL</h3>
          <DataAgeBadge lastUpdated={lastUpdated} />
          {latest && (
            <span className={`text-sm font-mono font-medium ${latest.total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {latest.total >= 0 ? '+' : ''}${latest.total.toFixed(2)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['1h', '4h', '24h', '7d'] as const).map(r => (
              <button type="button"
                key={r}
                onClick={() => setInternalRange(r)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  timeRange === r ? 'bg-green-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => refetch()} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh PnL" aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4">
        {Object.entries(DOMAIN_COLORS).map(([domain, color]) => (
          <div key={domain} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-xs text-gray-400 capitalize">{domain}</span>
            {latest && (
              <span className={`text-xs font-mono ${(latest[domain as keyof PnLDataPoint] as number) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {(latest[domain as keyof PnLDataPoint] as number) >= 0 ? '+' : ''}
                ${(latest[domain as keyof PnLDataPoint] as number).toFixed(0)}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* SVG Chart */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
        <svg viewBox="0 0 100 50" className="w-full h-40" preserveAspectRatio="none">
          {/* Zero line */}
          <line x1="0" y1={toY(0)} x2="100" y2={toY(0)} stroke={CHART_COLORS.SLATE_500} strokeWidth="0.2" strokeDasharray="1,1" />
          {/* Domain lines */}
          {(['prediction', 'crypto', 'equity', 'total'] as const).map(key => (
            <path
              key={key}
              d={buildPath(key)}
              fill="none"
              stroke={DOMAIN_COLORS[key]}
              strokeWidth={key === 'total' ? '0.6' : '0.4'}
              opacity={key === 'total' ? 1 : 0.7}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        <div className="flex justify-between text-[10px] text-gray-600 mt-1">
          <span>{data.length > 0 ? new Date(data[0].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
          <span>{data.length > 0 ? new Date(data[data.length - 1].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
        </div>
      </div>
    </div>
  );
}
