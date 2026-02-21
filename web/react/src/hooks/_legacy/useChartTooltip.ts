import { Chart } from "chart.js";

export function getTooltipColors() {
  const isDark = document.documentElement.classList.contains("dark");

  return {
    backgroundColor: isDark ? "#020617" : "#f9fafb",  // slate-950 / gray-50
    titleColor: isDark ? "#e5e7eb" : "#111827",       // slate-200 / gray-900
    bodyColor: isDark ? "#e5e7eb" : "#111827",
    borderColor: isDark ? "#1f2937" : "#e5e7eb",      // gray-800 / gray-200
  };
}

export function createTooltipOptions() {
  const colors = getTooltipColors();

  return {
    enabled: true,
    backgroundColor: colors.backgroundColor,
    titleColor: colors.titleColor,
    bodyColor: colors.bodyColor,
    borderColor: colors.borderColor,
    borderWidth: 1,
    padding: 10,
    cornerRadius: 6,
    displayColors: false,
  };
}

export function updateChartTooltip(chart: Chart) {
  const tooltipOptions = createTooltipOptions();
  if (chart.options.plugins) {
    chart.options.plugins.tooltip = tooltipOptions;
  }
  chart.update();
}

// Usage in chart configuration
export function getChartOptions(baseOptions: Record<string, unknown> = {}) {
  return {
    ...baseOptions,
    plugins: {
      ...baseOptions.plugins,
      tooltip: createTooltipOptions(),
    },
  };
}
