/**
 * CalibrationCurve — implied price (x, ¢) vs realized win-rate (y, 0..1)
 * per calibration cell, with a y=x perfect-calibration guide. On ECharts;
 * same props as the former recharts implementation.
 *
 * Bubble size encodes sample count `n`. Empty cells -> honest
 * 'no calibration cells' state. No data fabrication.
 */

import { memo, useMemo } from 'react';
import { EChart } from './EChart';
import type { EChartsCoreOption } from './EChart';
import { numOr } from '../../agents/format';

export interface CalibrationCell {
  /** implied price in cents (0-100). */
  price_c: number;
  /** realized win rate — fraction 0..1 (values >1 are treated as %). */
  win_rate: number;
  /** sample count for the cell (drives bubble size). */
  n?: number;
}

/** [price_c, win_rate, n] */
type Pt = [number, number, number];

interface CalibrationCurveProps {
  cells?: CalibrationCell[];
  height?: number;
  className?: string;
}

export const CalibrationCurve = memo(function CalibrationCurve({ cells, height = 220, className = '' }: CalibrationCurveProps) {
  const option = useMemo<EChartsCoreOption | null>(() => {
    const pts: Pt[] = (cells ?? [])
      .map((c): Pt | null => {
        const x = numOr(c.price_c);
        let y = numOr(c.win_rate);
        if (y != null && y > 1) y = y / 100;
        if (x == null || y == null) return null;
        return [x, Math.max(0, Math.min(1, y)), Math.max(0, numOr(c.n) ?? 0)];
      })
      .filter((p): p is Pt => p !== null);
    if (!pts.length) return null;

    const maxN = Math.max(1, ...pts.map((p) => p[2]));

    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { top: 10, right: 14, bottom: 22, left: 38, containLabel: false },
      xAxis: {
        type: 'value',
        min: 0,
        max: 100,
        name: 'implied',
        nameLocation: 'middle',
        nameGap: 16,
        nameTextStyle: { color: '#64748b', fontSize: 9 },
        axisLine: { lineStyle: { color: '#334155' } },
        axisTick: { show: false },
        axisLabel: { color: '#64748b', fontSize: 9, formatter: (v: number) => `${v}c` },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        name: 'realized',
        nameTextStyle: { color: '#64748b', fontSize: 9 },
        axisLine: { lineStyle: { color: '#334155' } },
        axisTick: { show: false },
        axisLabel: { color: '#64748b', fontSize: 9, formatter: (v: number) => `${Math.round(v * 100)}%` },
        splitLine: { lineStyle: { color: 'rgba(51,65,85,0.35)' } },
      },
      tooltip: {
        backgroundColor: 'rgba(2,6,23,0.95)',
        borderColor: '#334155',
        textStyle: { color: '#e2e8f0', fontSize: 10 },
        formatter: (params: unknown) => {
          const p = params as { value?: Pt };
          const v = p?.value;
          if (!v) return '';
          return [
            `<div style="color:#cbd5e1">${v[0]}c implied</div>`,
            `<div style="color:#34d399">${(v[1] * 100).toFixed(1)}% realized</div>`,
            `<div style="color:#64748b">n=${v[2]}</div>`,
          ].join('');
        },
      },
      series: [
        {
          name: 'cells',
          type: 'scatter',
          data: pts,
          symbolSize: (v: number[] | Pt) => {
            const n = Array.isArray(v) ? v[2] : 0;
            return 6 + 14 * Math.sqrt(n / maxN);
          },
          itemStyle: { color: 'rgba(56,189,248,0.75)', borderColor: 'rgba(56,189,248,0.9)', borderWidth: 0.5 },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            lineStyle: { color: '#475569', type: 'dashed', width: 1 },
            data: [[{ coord: [0, 0] }, { coord: [100, 1] }]],
          },
        },
      ],
    };
  }, [cells]);

  if (!option) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-dashed border-slate-800 text-[10px] uppercase tracking-widest text-slate-600 ${className}`}
        style={{ height }}
      >
        no calibration cells
      </div>
    );
  }

  return (
    <EChart
      option={option}
      height={height}
      className={className}
      ariaLabel="calibration curve: implied price versus realized win rate"
    />
  );
});

export default CalibrationCurve;
