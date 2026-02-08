/**
 * MERID Market Heatmap - Section 12: UI, Graphs, Charts, and Heatmaps
 * 
 * Market-wide heatmap showing returns, volatility, or sentiment intensity
 * across symbols and time periods.
 */

import { useMemo, type ReactNode } from 'react';
import { LayoutGrid, TrendingUp, TrendingDown, Activity } from 'lucide-react';

interface MarketData {
  symbol: string;
  price: number;
  change_1h: number;
  change_24h: number;
  volume_24h: number;
  volatility?: number;
  sentiment?: number;
}

interface MarketHeatmapProps {
  data: MarketData[];
  metric: 'change_1h' | 'change_24h' | 'volatility' | 'sentiment';
  title?: string;
  columns?: number;
  headerRight?: ReactNode;
  showHeader?: boolean;
}

function getColorForValue(value: number, metric: string): string {
  if (metric === 'volatility') {
    if (value > 0.1) return 'bg-purple-600';
    if (value > 0.05) return 'bg-purple-500';
    if (value > 0.02) return 'bg-purple-400/70';
    return 'bg-purple-400/40';
  }
  
  if (metric === 'sentiment') {
    if (value > 0.5) return 'bg-green-500';
    if (value > 0.2) return 'bg-green-400/70';
    if (value > -0.2) return 'bg-slate-500';
    if (value > -0.5) return 'bg-red-400/70';
    return 'bg-red-500';
  }
  
  // Price changes
  if (value > 5) return 'bg-green-500';
  if (value > 2) return 'bg-green-400';
  if (value > 0.5) return 'bg-green-400/70';
  if (value > 0) return 'bg-green-400/40';
  if (value > -0.5) return 'bg-red-400/40';
  if (value > -2) return 'bg-red-400/70';
  if (value > -5) return 'bg-red-400';
  return 'bg-red-500';
}

function formatValue(value: number, metric: string): string {
  if (metric === 'volatility') return `${(value * 100).toFixed(1)}%`;
  if (metric === 'sentiment') return value.toFixed(2);
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function formatPrice(price: number): string {
  if (price >= 1000) return `$${(price / 1000).toFixed(1)}k`;
  if (price >= 1) return `$${price.toFixed(2)}`;
  return `$${price.toFixed(4)}`;
}

export default function MarketHeatmap({
  data,
  metric,
  title = 'Market Heatmap',
  columns = 4,
  headerRight,
  showHeader = true,
}: MarketHeatmapProps) {
  const sortedData = useMemo(() => {
    return [...data].sort((a, b) => {
      const aVal = a[metric] || 0;
      const bVal = b[metric] || 0;
      return Math.abs(bVal) - Math.abs(aVal);
    });
  }, [data, metric]);

  const metricLabel = {
    change_1h: '1H Change',
    change_24h: '24H Change',
    volatility: 'Volatility',
    sentiment: 'Sentiment',
  }[metric];

  return (
    <div className="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4">
      {/* Header */}
      {showHeader && (
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <LayoutGrid className="w-5 h-5 text-purple-400" />
            <h3 className="text-lg font-semibold text-white">{title}</h3>
          </div>
          <div className="flex items-center gap-2">
            {headerRight ?? <span className="text-sm text-slate-400">{metricLabel}</span>}
          </div>
        </div>
      )}

      {/* Heatmap Grid */}
      <div 
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      >
        {sortedData.map((item) => {
          const value = item[metric] || 0;
          const colorClass = getColorForValue(value, metric);
          
          return (
            <div
              key={item.symbol}
              className={`${colorClass} rounded-lg p-3 transition-all hover:scale-105 cursor-pointer`}
              title={`${item.symbol}: ${formatValue(value, metric)}`}
            >
              <div className="flex flex-col">
                <span className="text-white font-semibold text-sm truncate">
                  {item.symbol.replace('/USD', '').replace('USDT', '')}
                </span>
                <span className="text-white/80 text-xs">
                  {formatPrice(item.price)}
                </span>
                <span className="text-white font-mono text-sm mt-1">
                  {formatValue(value, metric)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-4 pt-3 border-t border-slate-700/50">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            {metric.includes('change') ? (
              <>
                <TrendingDown className="w-3 h-3 text-red-400" />
                <span>Bearish</span>
              </>
            ) : metric === 'volatility' ? (
              <>
                <Activity className="w-3 h-3 text-purple-400" />
                <span>Low</span>
              </>
            ) : (
              <>
                <TrendingDown className="w-3 h-3 text-red-400" />
                <span>Negative</span>
              </>
            )}
          </div>
          <div className="flex gap-1">
            {metric.includes('change') ? (
              <>
                <div className="w-4 h-2 bg-red-500 rounded" />
                <div className="w-4 h-2 bg-red-400/70 rounded" />
                <div className="w-4 h-2 bg-slate-500 rounded" />
                <div className="w-4 h-2 bg-green-400/70 rounded" />
                <div className="w-4 h-2 bg-green-500 rounded" />
              </>
            ) : metric === 'volatility' ? (
              <>
                <div className="w-4 h-2 bg-purple-400/40 rounded" />
                <div className="w-4 h-2 bg-purple-400/70 rounded" />
                <div className="w-4 h-2 bg-purple-500 rounded" />
                <div className="w-4 h-2 bg-purple-600 rounded" />
              </>
            ) : (
              <>
                <div className="w-4 h-2 bg-red-500 rounded" />
                <div className="w-4 h-2 bg-slate-500 rounded" />
                <div className="w-4 h-2 bg-green-500 rounded" />
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {metric.includes('change') ? (
              <>
                <span>Bullish</span>
                <TrendingUp className="w-3 h-3 text-green-400" />
              </>
            ) : metric === 'volatility' ? (
              <>
                <span>High</span>
                <Activity className="w-3 h-3 text-purple-400" />
              </>
            ) : (
              <>
                <span>Positive</span>
                <TrendingUp className="w-3 h-3 text-green-400" />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
