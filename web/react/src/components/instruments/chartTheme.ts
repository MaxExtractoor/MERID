/**
 * chartTheme.ts — shared dark terminal theme for lightweight-charts v5.
 * Kept as plain data so both PriceChart and EquityCurve stay consistent.
 */

import { ColorType, LineStyle } from './lwc';
import type { ChartOptions, DeepPartial } from './lwc';

export const CHART_COLORS = {
  bg: 'rgba(2,6,23,0)',
  text: '#64748b',
  grid: '#1e293b',
  border: '#334155',
  up: '#10b981',
  down: '#ef4444',
  accent: '#38bdf8',
  strike: '#f59e0b',
  bid: 'rgba(16,185,129,0.45)',
  ask: 'rgba(239,68,68,0.45)',
};

export function baseChartOptions(height: number): DeepPartial<ChartOptions> {
  return {
    height,
    layout: {
      background: { type: ColorType.Solid, color: CHART_COLORS.bg },
      textColor: CHART_COLORS.text,
      fontSize: 10,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: CHART_COLORS.grid, style: LineStyle.SparseDotted },
      horzLines: { color: CHART_COLORS.grid, style: LineStyle.SparseDotted },
    },
    crosshair: {
      vertLine: { color: '#475569', labelBackgroundColor: '#334155' },
      horzLine: { color: '#475569', labelBackgroundColor: '#334155' },
    },
    rightPriceScale: {
      borderColor: CHART_COLORS.border,
      scaleMargins: { top: 0.15, bottom: 0.1 },
    },
    timeScale: {
      borderColor: CHART_COLORS.border,
      timeVisible: true,
      secondsVisible: true,
      rightOffset: 2,
    },
    handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: false, vertTouchDrag: false },
    handleScale: { mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: false },
  };
}
