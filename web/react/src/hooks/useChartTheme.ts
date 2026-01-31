import { Chart } from "chart.js";

export function getChartThemeColors() {
  const isDark = document.documentElement.classList.contains("dark");
  
  return {
    tooltip: {
      backgroundColor: isDark ? "#020617" : "#f9fafb", // slate-950 / gray-50
      titleColor: isDark ? "#e5e7eb" : "#111827",
      bodyColor: isDark ? "#e5e7eb" : "#111827",
      borderColor: isDark ? "#1e293b" : "#e5e7eb",
      borderWidth: 1,
      padding: 10,
      displayColors: false,
    },
    legend: {
      labels: {
        color: isDark ? "#e5e7eb" : "#111827",
      },
    },
    scales: {
      x: { 
        ticks: { color: isDark ? "#9ca3af" : "#4b5563" },
        grid: { color: isDark ? "#374151" : "#e5e7eb" },
      },
      y: { 
        ticks: { color: isDark ? "#9ca3af" : "#4b5563" },
        grid: { color: isDark ? "#374151" : "#e5e7eb" },
      },
    },
  };
}

export function updateChartTheme(chart: Chart) {
  const colors = getChartThemeColors();

  if (chart.options.plugins) {
    chart.options.plugins.tooltip = colors.tooltip;
    chart.options.plugins.legend = colors.legend;
  }
  if (chart.options.scales) {
    chart.options.scales.x = { ...chart.options.scales.x, ...colors.scales.x };
    chart.options.scales.y = { ...chart.options.scales.y, ...colors.scales.y };
  }

  chart.update();
}

export function createThemedChart(ctx: CanvasRenderingContext2D, config: any) {
  const colors = getChartThemeColors();

  const options = config.options || {};
  const plugins = options.plugins || {};
  const scales = options.scales || {};

  return new Chart(ctx, {
    ...config,
    options: {
      ...options,
      plugins: {
        ...plugins,
        tooltip: colors.tooltip,
        legend: colors.legend,
      },
      scales: {
        ...scales,
        x: { ...scales.x, ...colors.scales.x },
        y: { ...scales.y, ...colors.scales.y },
      },
    },
  });
}
