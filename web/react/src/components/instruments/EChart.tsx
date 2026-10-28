/**
 * EChart — minimal React wrapper around Apache ECharts 6 (modular build).
 *
 * Registers the small set of charts/components the terminal uses and owns
 * init/resize/dispose lifecycle. `option` is a plain ECharts option object;
 * the wrapper applies it with notMerge so stale series never linger.
 *
 * Bundle note: imports from echarts/core + charts + components + renderers —
 * tree-shaken, no full echarts bundle.
 */

import { memo, useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart, ScatterChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';

echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
]);

export { echarts };
export type { EChartsCoreOption };

interface EChartProps {
  option: EChartsCoreOption;
  height?: number | string;
  className?: string;
  /** Extra aria-label on the container div. */
  ariaLabel?: string;
}

type ChartInstance = ReturnType<typeof echarts.init>;

export const EChart = memo(function EChart({ option, height = 160, className = '', ariaLabel }: EChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ChartInstance | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const chart = echarts.init(host, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);

  return (
    <div
      ref={hostRef}
      className={className}
      style={{ height, width: '100%' }}
      role="img"
      aria-label={ariaLabel ?? 'chart'}
    />
  );
});

export default EChart;
