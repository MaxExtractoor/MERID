/**
 * lwc.ts — lightweight-charts v5 bridge.
 *
 * The repo ships a legacy ambient stub (src/types/lightweight-charts.d.ts)
 * which shadows the real package typings for the bare specifier
 * 'lightweight-charts'. This module re-exports the real v5 runtime paired
 * with the real v5 types from the package's own dist/typings.d.ts
 * (resolved via the deep specifier, which the stub does NOT cover).
 * All instrument components should import lwc symbols from here.
 */

import * as lwcRuntime from 'lightweight-charts';

/** Real v5 module type, resolved from the package's bundled declarations. */
type LWC = typeof import('lightweight-charts/dist/typings');

const lwc = lwcRuntime as unknown as LWC;

export const createChart = lwc.createChart;
export const createSeriesMarkers = lwc.createSeriesMarkers;
export const AreaSeries = lwc.AreaSeries;
export const LineSeries = lwc.LineSeries;
export const BaselineSeries = lwc.BaselineSeries;
export const LineStyle = lwc.LineStyle;
export const ColorType = lwc.ColorType;
export const CrosshairMode = lwc.CrosshairMode;

export type {
  AreaData,
  BaselineData,
  ChartOptions,
  DeepPartial,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineData,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from 'lightweight-charts/dist/typings';
