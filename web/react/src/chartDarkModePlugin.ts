import { Chart } from "chart.js";

export const MeridDarkModePlugin = {
  id: "meridDarkMode",
  beforeLayout(chart: Chart) {
    const root = document.documentElement;
    const isDark = root.classList.contains("dark");

    const axisColor = isDark ? "#9ca3af" : "#4b5563"; // slate-400 / gray-600
    const textColor = isDark ? "#e5e7eb" : "#111827"; // slate-200 / gray-900
    const gridColor = isDark ? "#1f2937" : "#e5e7eb"; // gray-800 / gray-200

    if (chart.options.scales) {
      for (const scale of Object.values(chart.options.scales)) {
        if (!scale) continue;
        // @ts-ignore
        scale.ticks = { ...(scale.ticks || {}), color: axisColor };
        // @ts-ignore
        scale.grid = { ...(scale.grid || {}), color: gridColor };
      }
    }

    if (chart.options.plugins?.legend?.labels) {
      chart.options.plugins.legend.labels.color = textColor;
    }

    if (chart.options.plugins?.tooltip) {
      chart.options.plugins.tooltip.backgroundColor = isDark ? "#020617" : "#f9fafb";
      chart.options.plugins.tooltip.titleColor = textColor;
      chart.options.plugins.tooltip.bodyColor = textColor;
      chart.options.plugins.tooltip.borderColor = gridColor;
    }
  },
};

// Registration helper
export function registerMeridDarkModePlugin() {
  Chart.register(MeridDarkModePlugin);
}

// Usage example:
// import { registerMeridDarkModePlugin } from './chartDarkModePlugin';
// registerMeridDarkModePlugin();
