/**
 * TimeSeriesChart - Unified time series chart component
 * 
 * Consolidates 4 chart components into 1 configurable primitive:
 * - KalshiPnlChart
 * - PortfolioChart
 * - DomainPnLChart
 * - DrawdownChart
 * 
 * Uses design tokens for consistent styling across all Kalshi views.
 * Lightweight wrapper around charting library (Recharts) to reduce bundle size.
 * 
 * Tier 2: Chart Consolidation (4 → 1)
 */

import React from 'react';
import { LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { CHART_COLOR_SCHEMES, ChartColorScheme } from '../tokens';

/**
 * Time series data point interface
 */
export interface TimeSeriesDataPoint {
  timestamp: string | Date;
  value: number;
  [key: string]: string | Date | number;
}

/**
 * TimeSeriesChart API
 */
export interface TimeSeriesChartProps {
  /**
   * Chart data
   */
  data: TimeSeriesDataPoint[];
  
  /**
   * Chart type
   */
  type: 'line' | 'area' | 'bar';
  
  /**
   * Metric type (determines y-axis label and formatting)
   */
  metric: 'pnl' | 'equity' | 'drawdown' | 'volume' | 'fills';
  
  /**
   * Chart height in pixels
   */
  height?: number;
  
  /**
   * Show tooltip
   */
  showTooltip?: boolean;
  
  /**
   * Show legend
   */
  showLegend?: boolean;
  
  /**
   * Color scheme (maps to Kalshi brand colors)
   */
  colorScheme?: ChartColorScheme;
  
  /**
   * Point click handler
   */
  onPointClick?: (point: TimeSeriesDataPoint) => void;
  
  /**
   * Additional CSS classes
   */
  className?: string;
}

/**
 * Format value based on metric type
 */
function formatValue(value: number, metric: string): string {
  switch (metric) {
    case 'pnl':
    case 'equity':
      return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
    case 'drawdown':
      return `${(value * 100).toFixed(2)}%`;
    case 'volume':
      return value.toLocaleString('en-US');
    case 'fills':
      return value.toString();
    default:
      return value.toString();
  }
}

/**
 * Get Y-axis label based on metric type
 */
function getYAxisLabel(metric: string): string {
  switch (metric) {
    case 'pnl':
      return 'PnL ($)';
    case 'equity':
      return 'Equity ($)';
    case 'drawdown':
      return 'Drawdown (%)';
    case 'volume':
      return 'Volume';
    case 'fills':
      return 'Fills';
    default:
      return 'Value';
  }
}

/**
 * Format timestamp for X-axis
 */
function formatTimestamp(timestamp: string | Date): string {
  const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

/**
 * TimeSeriesChart Component
 */
export const TimeSeriesChart = React.memo(function TimeSeriesChart({
  data,
  type = 'line',
  metric = 'pnl',
  height = 300,
  showTooltip = true,
  showLegend = false,
  colorScheme = 'kalshi-green',
  onPointClick,
  className = '',
}: TimeSeriesChartProps) {
  const colors = CHART_COLOR_SCHEMES[colorScheme];
  
  // Format data for Recharts
  const formattedData = data.map(point => ({
    ...point,
    timestamp: formatTimestamp(point.timestamp),
  }));
  
  const yAxisLabel = getYAxisLabel(metric);
  
  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload || !payload.length) return null;
    
    const data = payload[0].payload;
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-lg">
        <p className="text-xs text-slate-400 mb-1">{data.timestamp}</p>
        <p className="text-sm font-semibold text-slate-200">
          {yAxisLabel}: {formatValue(data.value, metric)}
        </p>
      </div>
    );
  };
  
  // Common chart props
  const commonProps = {
    data: formattedData,
    height,
    className,
  };
  
  // Render based on chart type
  if (type === 'area') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis 
            dataKey="timestamp" 
            stroke="#64748b" 
            fontSize={12}
            tickFormatter={formatTimestamp}
          />
          <YAxis 
            stroke="#64748b" 
            fontSize={12}
            tickFormatter={(value) => formatValue(value, metric)}
            label={{ value: yAxisLabel, angle: -90, position: 'insideLeft' }}
          />
          {showTooltip && <Tooltip content={<CustomTooltip />} />}
          {showLegend && <Legend />}
          <Area 
            type="monotone" 
            dataKey="value" 
            stroke={colors.primary}
            strokeWidth={2}
            fill={colors.gradient[0]}
            fillOpacity={0.3}
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  
  if (type === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis 
            dataKey="timestamp" 
            stroke="#64748b" 
            fontSize={12}
            tickFormatter={formatTimestamp}
          />
          <YAxis 
            stroke="#64748b" 
            fontSize={12}
            tickFormatter={(value) => formatValue(value, metric)}
            label={{ value: yAxisLabel, angle: -90, position: 'insideLeft' }}
          />
          {showTooltip && <Tooltip content={<CustomTooltip />} />}
          {showLegend && <Legend />}
          <Bar 
            dataKey="value" 
            fill={colors.primary}
            onClick={onPointClick}
          />
        </BarChart>
      </ResponsiveContainer>
    );
  }
  
  // Default to line chart
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart {...commonProps}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis 
          dataKey="timestamp" 
          stroke="#64748b" 
          fontSize={12}
          tickFormatter={formatTimestamp}
        />
        <YAxis 
          stroke="#64748b" 
          fontSize={12}
          tickFormatter={(value) => formatValue(value, metric)}
          label={{ value: yAxisLabel, angle: -90, position: 'insideLeft' }}
        />
        {showTooltip && <Tooltip content={<CustomTooltip />} />}
        {showLegend && <Legend />}
        <Line 
          type="monotone" 
          dataKey="value" 
          stroke={colors.primary}
          strokeWidth={2}
          dot={{ fill: colors.primary, r: 3 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
});
