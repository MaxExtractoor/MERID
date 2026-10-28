/**
 * DepthChart — cumulative YES-book depth chart on Apache ECharts.
 *
 * Bids accumulate from the mid leftward (green), asks accumulate rightward
 * (red). Props in -> render; empty book -> honest 'no book data' state.
 * Same props as the former SVG implementation.
 */

import { memo, useMemo } from 'react';
import { EChart } from './EChart';
import type { EChartsCoreOption } from './EChart';

export interface DepthLevel {
  price: number;
  size: number;
}

interface DepthChartProps {
  bids?: DepthLevel[];
  asks?: DepthLevel[];
  height?: number;
  className?: string;
}

interface SideGeom {
  /** [price, cumulativeSize] sorted by price ascending. */
  pts: [number, number][];
  cum: number;
  best?: number;
}

function buildSide(levels: DepthLevel[] | undefined, isBid: boolean): SideGeom | null {
  const clean = (levels ?? []).filter(
    (l) => Number.isFinite(l.price) && Number.isFinite(l.size) && l.size > 0,
  );
  if (!clean.length) return null;
  // Cum from the best price outward. Bid: sort desc then accumulate; ask: asc.
  const sorted = [...clean].sort((a, b) => (isBid ? b.price - a.price : a.price - b.price));
  const pts: [number, number][] = [];
  let cum = 0;
  for (const l of sorted) {
    cum += l.size;
    pts.push([l.price, cum]);
  }
  // ECharts value-axis line needs x-ascending order.
  pts.sort((a, b) => a[0] - b[0]);
  return { pts, cum, best: sorted[0].price };
}

export const DepthChart = memo(function DepthChart({ bids, asks, height = 120, className = '' }: DepthChartProps) {
  const { option, bid, ask, mid } = useMemo(() => {
    const bid = buildSide(bids, true);
    const ask = buildSide(asks, false);
    if (!bid && !ask) return { option: null, bid, ask, mid: null };

    const prices = [...(bid?.pts ?? []), ...(ask?.pts ?? [])].map((p) => p[0]);
    const lo = Math.min(...prices);
    const hi = Math.max(...prices);
    const mid = bid?.best != null && ask?.best != null ? (bid.best + ask.best) / 2 : null;

    const option: EChartsCoreOption = {
      animation: false,
      backgroundColor: 'transparent',
      grid: { top: 6, right: 6, bottom: 2, left: 6, containLabel: false },
      xAxis: {
        type: 'value',
        min: lo,
        max: hi,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(2,6,23,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 10 },
        axisPointer: { lineStyle: { color: '#475569', type: 'dashed' } },
        formatter: (params: unknown) => {
          const items = (params as Array<{ axisValue?: number; seriesName?: string; value?: [number, number] }>) ?? [];
          const price = items[0]?.axisValue;
          const lines = [`<div style="font-weight:600">${Number(price).toFixed(0)}c</div>`];
          for (const it of items) {
            if (it.value == null) continue;
            const color = it.seriesName === 'bid' ? '#34d399' : '#f87171';
            lines.push(`<span style="color:${color}">${it.seriesName}</span> depth ${it.value[1]}`);
          }
          return lines.join('<br/>');
        },
      },
      series: [
        ...(bid
          ? [{
              name: 'bid',
              type: 'line' as const,
              data: bid.pts,
              showSymbol: false,
              lineStyle: { color: '#10b981', width: 1 },
              areaStyle: { color: 'rgba(16,185,129,0.28)' },
            }]
          : []),
        ...(ask
          ? [{
              name: 'ask',
              type: 'line' as const,
              data: ask.pts,
              showSymbol: false,
              lineStyle: { color: '#ef4444', width: 1 },
              areaStyle: { color: 'rgba(239,68,68,0.28)' },
            }]
          : []),
        ...(mid != null
          ? [{
              name: 'mid',
              type: 'line' as const,
              data: [],
              markLine: {
                silent: true,
                symbol: 'none',
                label: { show: false },
                lineStyle: { color: '#334155', type: 'dashed' as const, width: 1 },
                data: [{ xAxis: mid }],
              },
            }]
          : []),
      ],
    };
    return { option, bid, ask, mid };
  }, [bids, asks]);

  if (!option) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-dashed border-slate-800 text-[10px] uppercase tracking-widest text-slate-600 ${className}`}
        style={{ height }}
        role="img"
        aria-label="no orderbook depth data"
      >
        no book data
      </div>
    );
  }

  return (
    <div className={className}>
      <EChart
        option={option}
        height={height - 16}
        ariaLabel={`book depth: ${bid ? `${bid.cum} bid contracts` : 'no bids'}, ${ask ? `${ask.cum} ask contracts` : 'no asks'}`}
      />
      <div className="flex items-center justify-between text-[9px] tabular-nums text-slate-500 pt-0.5">
        <span className="text-emerald-400/90">
          bid {bid?.best != null ? `@${bid.best.toFixed(0)}c` : 'n/a'} · {bid ? bid.cum : 'n/a'} ct
        </span>
        <span className="text-slate-600">{mid != null ? `mid ${mid.toFixed(1)}c` : 'mid'}</span>
        <span className="text-red-400/90">
          {ask ? ask.cum : 'n/a'} ct · ask {ask?.best != null ? `@${ask.best.toFixed(0)}c` : 'n/a'}
        </span>
      </div>
    </div>
  );
});

export default DepthChart;
