/**
 * PriceChart — lightweight-charts v5 area-series wrapper for a 15m window
 * price-vs-strike view. Pure props in -> render; no fetching inside.
 *
 * - `data` = {time, value}[] — time accepts epoch sec/ms or ISO strings;
 *   values render as an AreaSeries on the right price scale.
 * - `strike` draws a persistent amber price line (axis label on).
 * - `markers` draw fill dots via the v5 `createSeriesMarkers` plugin.
 * - Imperative handle exposes `update()`/`setData()`/`setMarkers()` for
 *   ticking feeds — refs avoid chart re-creation.
 * - Empty data renders an empty chart (truthful; an 'n/a' caption is the
 *   parent's call via the `emptyLabel` overlay).
 */

import {
  forwardRef, memo, useCallback, useEffect, useImperativeHandle, useRef,
} from 'react';
import {
  AreaSeries, LineStyle, createChart, createSeriesMarkers,
} from './lwc';
import type {
  IChartApi, IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time, UTCTimestamp,
} from './lwc';
import { CHART_COLORS, baseChartOptions } from './chartTheme';

/* ------------------------------------------------------------------ */

export interface PricePoint {
  /** epoch seconds, epoch ms, or ISO-8601 string. */
  time: number | string;
  value: number;
}

export interface PriceMarker {
  time: number | string;
  price?: number;
  side?: 'yes' | 'no' | 'buy' | 'sell';
  text?: string;
}

export interface PriceChartHandle {
  update: (point: PricePoint) => void;
  setData: (data: PricePoint[]) => void;
  setMarkers: (markers: PriceMarker[]) => void;
  setStrike: (price: number | undefined) => void;
}

interface PriceChartProps {
  data?: PricePoint[];
  strike?: number;
  markers?: PriceMarker[];
  height?: number;
  /** Series color for the line/area. */
  color?: string;
  /** Strike line label. */
  strikeLabel?: string;
  /** Overlay text when data is empty; set to null/'' to disable. */
  emptyLabel?: string | null;
  className?: string;
}

/* ------------------------------------------------------------------ */

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

function normalizeSeries(data: PricePoint[] | undefined): { time: UTCTimestamp; value: number }[] {
  if (!data?.length) return [];
  const seen = new Map<number, number>();
  for (const p of data) {
    const t = toTime(p.time);
    if (t != null && Number.isFinite(p.value)) seen.set(t as number, p.value);
  }
  return [...seen.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
}

function toMarkers(markers: PriceMarker[] | undefined): SeriesMarker<Time>[] {
  if (!markers?.length) return [];
  const out: SeriesMarker<Time>[] = [];
  for (const m of markers) {
    const t = toTime(m.time);
    if (t == null) continue;
    const sellish = m.side === 'no' || m.side === 'sell';
    out.push({
      time: t as Time,
      position: sellish ? 'belowBar' : 'aboveBar',
      shape: 'circle',
      color: sellish ? CHART_COLORS.down : CHART_COLORS.up,
      ...(m.text ? { text: m.text } : {}),
    });
  }
  return out;
}

/* ------------------------------------------------------------------ */

export const PriceChart = memo(forwardRef<PriceChartHandle, PriceChartProps>(function PriceChart(
  {
    data,
    strike,
    markers,
    height = 220,
    color = CHART_COLORS.accent,
    strikeLabel = 'strike',
    emptyLabel = 'no series data',
    className = '',
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const strikeLineRef = useRef<IPriceLine | null>(null);
  const dataLenRef = useRef(0);

  const applyStrike = useCallback((price: number | undefined) => {
    const s = seriesRef.current;
    if (!s) return;
    if (strikeLineRef.current) {
      s.removePriceLine(strikeLineRef.current);
      strikeLineRef.current = null;
    }
    if (price != null && Number.isFinite(price)) {
      strikeLineRef.current = s.createPriceLine({
        price,
        color: CHART_COLORS.strike,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: strikeLabel,
      });
    }
  }, [strikeLabel]);

  const applyData = useCallback((points: PricePoint[] | undefined) => {
    const s = seriesRef.current;
    if (!s) return;
    const norm = normalizeSeries(points);
    s.setData(norm);
    if (norm.length && dataLenRef.current === 0) {
      chartRef.current?.timeScale().fitContent();
    }
    dataLenRef.current = norm.length;
  }, []);

  useImperativeHandle(ref, () => ({
    update: (point: PricePoint) => {
      const t = toTime(point.time);
      const s = seriesRef.current;
      if (t == null || !s || !Number.isFinite(point.value)) return;
      s.update({ time: t, value: point.value });
      dataLenRef.current += 1;
    },
    setData: (d: PricePoint[]) => applyData(d),
    setMarkers: (m: PriceMarker[]) => markersApiRef.current?.setMarkers(toMarkers(m)),
    setStrike: (price: number | undefined) => applyStrike(price),
  }), [applyData, applyStrike]);

  // Create chart once.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, baseChartOptions(height));
    const series = chart.addSeries(AreaSeries, {
      lineColor: color,
      lineWidth: 2,
      topColor: `${color}55`,
      bottomColor: `${color}05`,
      priceLineVisible: true,
      priceLineColor: color,
      priceLineStyle: LineStyle.Solid,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersApiRef.current = createSeriesMarkers(series);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.resize(Math.floor(w), height, false);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      markersApiRef.current = null;
      strikeLineRef.current = null;
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chart created once; series color/height applied via effects below
  }, []);

  // Height changes -> resize.
  useEffect(() => {
    const el = containerRef.current;
    if (el && chartRef.current) chartRef.current.resize(el.clientWidth || 1, height, false);
  }, [height]);

  // Data / strike / markers -> apply. `data?.length` is tracked too so a
  // ref-mutated (same-identity) series still re-applies when it grows.
  useEffect(() => { applyData(data); }, [data, data?.length, applyData]);
  useEffect(() => { applyStrike(strike); }, [strike, applyStrike]);
  useEffect(() => { markersApiRef.current?.setMarkers(toMarkers(markers)); }, [markers]);

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

export default PriceChart;
