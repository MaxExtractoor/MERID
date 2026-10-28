/**
 * EquityCurve — lightweight-charts v5 BaselineSeries equity/PnL curve.
 * Values above the baseline render green, below render red. Props in ->
 * render; no fetching. Empty data -> empty chart + 'n/a' overlay.
 */

import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef } from 'react';
import { BaselineSeries, createChart } from './lwc';
import type { IChartApi, ISeriesApi, UTCTimestamp } from './lwc';
import { CHART_COLORS, baseChartOptions } from './chartTheme';
import type { PricePoint } from './PriceChart';

export interface EquityCurveHandle {
  update: (point: PricePoint) => void;
  setData: (data: PricePoint[]) => void;
}

interface EquityCurveProps {
  data?: PricePoint[];
  /** Baseline value; default 0 (breakeven). */
  baseValue?: number;
  height?: number;
  emptyLabel?: string | null;
  className?: string;
}

function toTime(t: number | string): UTCTimestamp | null {
  if (typeof t === 'number' && Number.isFinite(t)) {
    return (t > 1e12 ? Math.floor(t / 1000) : Math.floor(t)) as UTCTimestamp;
  }
  if (typeof t === 'string') {
    const ms = Date.parse(t);
    if (Number.isFinite(ms)) return Math.floor(ms / 1000) as UTCTimestamp;
  }
  return null;
}

export const EquityCurve = memo(forwardRef<EquityCurveHandle, EquityCurveProps>(function EquityCurve(
  { data, baseValue = 0, height = 200, emptyLabel = 'no pnl history', className = '' },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Baseline'> | null>(null);
  const seededRef = useRef(false);

  const applyData = useCallback((points: PricePoint[] | undefined) => {
    const s = seriesRef.current;
    if (!s) return;
    const seen = new Map<number, number>();
    for (const p of points ?? []) {
      const t = toTime(p.time);
      if (t != null && Number.isFinite(p.value)) seen.set(t as number, p.value);
    }
    const norm = [...seen.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
    s.setData(norm);
    if (norm.length && !seededRef.current) {
      seededRef.current = true;
      chartRef.current?.timeScale().fitContent();
    }
    if (!norm.length) seededRef.current = false;
  }, []);

  useImperativeHandle(ref, () => ({
    update: (p: PricePoint) => {
      const t = toTime(p.time);
      if (t == null || !seriesRef.current || !Number.isFinite(p.value)) return;
      seriesRef.current.update({ time: t, value: p.value });
    },
    setData: applyData,
  }), [applyData]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, baseChartOptions(height));
    const series = chart.addSeries(BaselineSeries, {
      baseValue: { type: 'price', price: baseValue },
      topLineColor: CHART_COLORS.up,
      topFillColor1: 'rgba(16,185,129,0.30)',
      topFillColor2: 'rgba(16,185,129,0.04)',
      bottomLineColor: CHART_COLORS.down,
      bottomFillColor1: 'rgba(239,68,68,0.04)',
      bottomFillColor2: 'rgba(239,68,68,0.30)',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.resize(Math.floor(w), height, false);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chart created once
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (el && chartRef.current) chartRef.current.resize(el.clientWidth || 1, height, false);
  }, [height]);

  // `data?.length` is tracked too so a ref-mutated series still re-applies.
  useEffect(() => { applyData(data); }, [data, data?.length, applyData]);

  const empty = !data || data.length === 0;

  return (
    <div className={`relative w-full ${className}`} style={{ height }}>
      <div ref={containerRef} className="absolute inset-0" />
      {empty && emptyLabel && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[10px] text-slate-600 uppercase tracking-widest">{emptyLabel}</span>
        </div>
      )}
    </div>
  );
}));

export default EquityCurve;
