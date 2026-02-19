import { useEffect, useRef } from "react";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  type ChartOptions,
  type ChartData,
} from "chart.js";

Chart.register(LineController, LineElement, PointElement, LinearScale, TimeScale, Tooltip);

export interface EquityPoint {
  t: string;
  v: number;
}

type EquityChartOptions = ChartOptions<"line">;
type EquityChartData = ChartData<"line">;

const getThemeColors = (isDark: boolean) => ({
  borderColor: isDark ? "#22c55e" : "#16a34a",
  legendColor: isDark ? "#e5e7eb" : "#111827",
  tooltipBg: isDark ? "#1f2937" : "#ffffff",
  tooltipText: isDark ? "#e5e7eb" : "#111827",
  tickColor: isDark ? "#9ca3af" : "#4b5563",
  gridColor: isDark ? "#374151" : "#e5e7eb",
});

const createChartData = (data: EquityPoint[], isDark: boolean): EquityChartData => {
  const colors = getThemeColors(isDark);
  return {
    labels: data.map((d) => d.t),
    datasets: [
      {
        label: "Equity",
        data: data.map((d) => d.v),
        borderColor: colors.borderColor,
        backgroundColor: "transparent",
        borderWidth: 2,
        tension: 0.4,
      },
    ],
  };
};

const createChartOptions = (isDark: boolean): EquityChartOptions => {
  const colors = getThemeColors(isDark);
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: colors.legendColor,
        },
      },
      tooltip: {
        backgroundColor: colors.tooltipBg,
        titleColor: colors.tooltipText,
        bodyColor: colors.tooltipText,
        borderColor: colors.gridColor,
      },
    },
    scales: {
      x: {
        ticks: { color: colors.tickColor },
        grid: { color: colors.gridColor },
      },
      y: {
        ticks: { color: colors.tickColor },
        grid: { color: colors.gridColor },
      },
    },
  };
};

export function useEquityChart(data: EquityPoint[]) {
  const chartRef = useRef<Chart<"line"> | null>(null);

  useEffect(() => {
    const canvas = document.getElementById("equityChart") as HTMLCanvasElement | null;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const isDark = document.documentElement.classList.contains("dark");

    // Destroy existing chart if present
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    const chartData = createChartData(data, isDark);
    const options = createChartOptions(isDark);

    chartRef.current = new Chart(ctx, {
      type: "line",
      data: chartData,
      options,
    });

    // Listen for theme changes
    const handleThemeChange = () => {
      const newIsDark = document.documentElement.classList.contains("dark");
      const newColors = getThemeColors(newIsDark);
      const chart = chartRef.current;

      if (!chart) return;

      // Update dataset colors
      const dataset = chart.data.datasets[0];
      if (dataset) {
        dataset.borderColor = newColors.borderColor;
      }

      // Update options with null checks
      const opts = chart.options;
      if (opts.plugins?.legend?.labels) {
        opts.plugins.legend.labels.color = newColors.legendColor;
      }
      if (opts.plugins?.tooltip) {
        opts.plugins.tooltip.backgroundColor = newColors.tooltipBg;
        opts.plugins.tooltip.titleColor = newColors.tooltipText;
        opts.plugins.tooltip.bodyColor = newColors.tooltipText;
        opts.plugins.tooltip.borderColor = newColors.gridColor;
      }
      if (opts.scales?.x?.ticks) {
        opts.scales.x.ticks.color = newColors.tickColor;
      }
      if (opts.scales?.y?.ticks) {
        opts.scales.y.ticks.color = newColors.tickColor;
      }
      if (opts.scales?.x?.grid) {
        opts.scales.x.grid.color = newColors.gridColor;
      }
      if (opts.scales?.y?.grid) {
        opts.scales.y.grid.color = newColors.gridColor;
      }

      chart.update();
    };

    const observer = new MutationObserver(handleThemeChange);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

    return () => {
      if (chartRef.current) {
        chartRef.current.destroy();
        chartRef.current = null;
      }
      observer.disconnect();
    };
  }, [data]);
}
