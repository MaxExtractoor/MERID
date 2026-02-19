/**
 * Risk Heatmap Widget
 *
 * Grid of instruments colored by PnL contribution or risk utilization.
 * Uses data from useRiskMetrics exposure map.
 */

import { useMemo } from 'react';
import { useRiskMetrics } from '../../hooks/useRiskMetrics';
import { LayoutGrid, TrendingUp, TrendingDown } from 'lucide-react';

interface RiskHeatmapWidgetProps {
  className?: string;
  maxItems?: number;
}

function getHeatColor(value: number, maxAbs: number): string {
  if (maxAbs === 0) return 'bg-slate-800';
  const ratio = value / maxAbs;
  if (ratio > 0.6) return 'bg-emerald-600';
  if (ratio > 0.2) return 'bg-emerald-500/60';
  if (ratio > 0) return 'bg-emerald-500/30';
  if (ratio > -0.2) return 'bg-rose-500/30';
  if (ratio > -0.6) return 'bg-rose-500/60';
  return 'bg-rose-600';
}

function getTextColor(value: number): string {
  if (value > 0) return 'text-emerald-400';
  if (value < 0) return 'text-rose-400';
  return 'text-slate-400';
}

export function RiskHeatmapWidget({ className = '', maxItems = 12 }: RiskHeatmapWidgetProps) {
  const { metrics } = useRiskMetrics();

  const items = useMemo(() => {
    const entries = Object.entries(metrics.exposure);
    if (entries.length === 0) return [];

    return entries
      .map(([symbol, sides]) => {
        const net = sides.long - sides.short;
        const total = sides.long + sides.short;
        return { symbol, net, total, long: sides.long, short: sides.short };
      })
      .sort((a, b) => Math.abs(b.total) - Math.abs(a.total))
      .slice(0, maxItems);
  }, [metrics.exposure, maxItems]);

  const maxAbsNet = useMemo(() => {
    if (items.length === 0) return 1;
    return Math.max(...items.map((i) => Math.abs(i.net)), 1);
  }, [items]);

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center gap-2 mb-3">
        <LayoutGrid className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-slate-300">Risk Heatmap</h3>
        <span className="text-[10px] text-slate-600 ml-auto">by net exposure</span>
      </div>

      {items.length === 0 ? (
        <div className="text-sm text-slate-600 text-center py-6">No exposure data</div>
      ) : (
        <div className="grid grid-cols-3 gap-1.5">
          {items.map((item) => (
            <div
              key={item.symbol}
              className={`rounded-lg p-2.5 ${getHeatColor(item.net, maxAbsNet)} transition-colors cursor-default group relative`}
            >
              <div className="text-xs font-bold text-white truncate">{item.symbol}</div>
              <div className={`text-[11px] font-semibold ${getTextColor(item.net)}`}>
                {item.net >= 0 ? '+' : ''}${Math.abs(item.net).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
              <div className="flex items-center gap-1 mt-0.5">
                <TrendingUp className="w-2.5 h-2.5 text-emerald-400/60" />
                <span className="text-[9px] text-slate-400">${item.long.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                <TrendingDown className="w-2.5 h-2.5 text-rose-400/60 ml-1" />
                <span className="text-[9px] text-slate-400">${item.short.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
