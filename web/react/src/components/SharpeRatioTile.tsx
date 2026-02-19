import React from 'react';
import { TrendingUp, TrendingDown, Minus, Award } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, CHART_COLORS} from "../config/constants";

interface SharpeRatioTileProps {
  agentId?: string;
  currentSharpe?: number;
  history?: { timestamp: number; sharpe: number }[];
  benchmarkSharpe?: number;
  label?: string;
  compact?: boolean;
}

export default function SharpeRatioTile({
  agentId,
  currentSharpe: propSharpe,
  history: propHistory,
  benchmarkSharpe = 1.0,
  label = "Sharpe Ratio",
  compact = false,
}: SharpeRatioTileProps) {
  const shouldFetch = !!agentId && propSharpe === undefined;
  const { data: metricsData, loading: fetchLoading, error: fetchError, refetch } = useApiData<{ sharpe_ratio: number }>(
    agentId ? API_ENDPOINTS.RISK_AGENT_METRICS(agentId) : '',
    { enabled: shouldFetch },
  );

  if (fetchError && !metricsData && shouldFetch) {
    return <ErrorBar label="Sharpe ratio" error={fetchError} onRetry={refetch} />;
  }

  const sharpe = propSharpe ?? metricsData?.sharpe_ratio ?? 0;
  const history = propHistory ?? [];
  const loading = shouldFetch && fetchLoading;

  const getColor = (value: number) => {
    if (value < 0) return 'text-red-400';
    if (value < 1) return 'text-yellow-400';
    if (value < 2) return 'text-green-400';
    return 'text-emerald-400';
  };

  const getBgColor = (value: number) => {
    if (value < 0) return 'bg-red-500/10 border-red-500/30';
    if (value < 1) return 'bg-yellow-500/10 border-yellow-500/30';
    if (value < 2) return 'bg-green-500/10 border-green-500/30';
    return 'bg-emerald-500/10 border-emerald-500/30';
  };

  const getIcon = (value: number) => {
    if (value < 0) return <TrendingDown className="w-5 h-5 text-red-400" />;
    if (value > 1) return <TrendingUp className="w-5 h-5 text-green-400" />;
    return <Minus className="w-5 h-5 text-yellow-400" />;
  };

  const formatSharpe = (value: number) => {
    return value.toFixed(2);
  };

  // Generate sparkline path
  const getSparklinePath = () => {
    if (history.length < 2) return '';
    
    const width = 80;
    const height = 24;
    const padding = 2;
    
    const values = history.map(h => h.sharpe);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 2);
    const range = max - min || 1;
    
    const points = values.map((v, i) => {
      const x = padding + (i / (values.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((v - min) / range) * (height - 2 * padding);
      return `${x},${y}`;
    });
    
    return `M ${points.join(' L ')}`;
  };

  if (loading) {
    return (
      <div className={`rounded-lg border p-4 bg-slate-800/50 border-slate-700/50 ${compact ? 'p-3' : 'p-4'}`}>
        <div className="animate-pulse">
          <div className="h-4 bg-slate-700 rounded w-20 mb-2"></div>
          <div className="h-8 bg-slate-700 rounded w-16"></div>
        </div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className={`rounded-lg border ${getBgColor(sharpe)} p-3`}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-400">{label}</p>
            <p className={`text-xl font-bold ${getColor(sharpe)}`}>
              {formatSharpe(sharpe)}
            </p>
          </div>
          {getIcon(sharpe)}
        </div>
      </div>
    );
  }

  return (
    <div className={`rounded-lg border ${getBgColor(sharpe)} p-4`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {getIcon(sharpe)}
          <span className="text-sm text-gray-400">{label}</span>
        </div>
        {sharpe >= benchmarkSharpe && (
          <div className="flex items-center gap-1 px-2 py-0.5 bg-emerald-500/20 rounded text-xs text-emerald-400">
            <Award className="w-3 h-3" />
            Above Benchmark
          </div>
        )}
      </div>
      
      <div className="flex items-end justify-between">
        <div>
          <p className={`text-3xl font-bold ${getColor(sharpe)}`}>
            {formatSharpe(sharpe)}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Benchmark: {formatSharpe(benchmarkSharpe)}
          </p>
        </div>
        
        {/* Sparkline */}
        {history.length >= 2 && (
          <svg width="80" height="24" className="opacity-60">
            <path
              d={getSparklinePath()}
              fill="none"
              stroke={sharpe >= 1 ? CHART_COLORS.LIGHT_GREEN : sharpe >= 0 ? CHART_COLORS.YELLOW : CHART_COLORS.LIGHT_RED}
              strokeWidth="1.5"
            />
          </svg>
        )}
      </div>
      
      {/* Threshold indicators */}
      <div className="flex gap-1 mt-3">
        <div className={`flex-1 h-1 rounded ${sharpe < 0 ? 'bg-red-400' : 'bg-slate-700'}`} title="<0: Poor" />
        <div className={`flex-1 h-1 rounded ${sharpe >= 0 && sharpe < 1 ? 'bg-yellow-400' : 'bg-slate-700'}`} title="0-1: Fair" />
        <div className={`flex-1 h-1 rounded ${sharpe >= 1 && sharpe < 2 ? 'bg-green-400' : 'bg-slate-700'}`} title="1-2: Good" />
        <div className={`flex-1 h-1 rounded ${sharpe >= 2 ? 'bg-emerald-400' : 'bg-slate-700'}`} title=">2: Excellent" />
      </div>
    </div>
  );
}
