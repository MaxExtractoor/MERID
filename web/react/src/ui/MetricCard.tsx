/**
 * Optimized Metric Card - For trading metrics with trend indicators
 */

import React from 'react';
import { ArrowUp, ArrowDown, Minus } from './icons';

export type MetricTrend = 'up' | 'down' | 'neutral';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: MetricTrend;
  trendValue?: string;
  icon?: React.ReactNode;
  color?: 'default' | 'success' | 'warning' | 'danger' | 'info';
  loading?: boolean;
  onClick?: () => void;
  className?: string;
}

const colorStyles = {
  default: { bg: 'bg-slate-800', accent: 'text-slate-400', border: 'border-slate-700' },
  success: { bg: 'bg-emerald-900/20', accent: 'text-emerald-400', border: 'border-emerald-500/30' },
  warning: { bg: 'bg-amber-900/20', accent: 'text-amber-400', border: 'border-amber-500/30' },
  danger: { bg: 'bg-red-900/20', accent: 'text-red-400', border: 'border-red-500/30' },
  info: { bg: 'bg-blue-900/20', accent: 'text-blue-400', border: 'border-blue-500/30' },
};

const trendIcons = {
  up: ArrowUp,
  down: ArrowDown,
  neutral: Minus,
};

const trendColors = {
  up: 'text-emerald-400',
  down: 'text-red-400',
  neutral: 'text-slate-400',
};

export const MetricCard = React.memo(function MetricCard({
  title,
  value,
  subtitle,
  trend,
  trendValue,
  icon,
  color = 'default',
  loading = false,
  onClick,
  className = '',
}: MetricCardProps) {
  const colors = colorStyles[color];
  const TrendIcon = trend ? trendIcons[trend] : null;
  
  if (loading) {
    return (
      <div className={`rounded-xl border ${colors.border} ${colors.bg} p-4 animate-pulse ${className}`}>
        <div className="h-4 w-20 bg-slate-700 rounded mb-2" />
        <div className="h-8 w-32 bg-slate-700 rounded" />
      </div>
    );
  }
  
  return (
    <div 
      className={`
        rounded-xl border ${colors.border} ${colors.bg} 
        ${onClick ? 'cursor-pointer hover:border-slate-600 transition-colors' : ''}
        p-4
        ${className}
      `}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className={`text-xs font-medium uppercase tracking-wider ${colors.accent} mb-1`}>
            {title}
          </p>
          <p className="text-2xl font-bold text-slate-100">{value}</p>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
          )}
        </div>
        {icon && (
          <div className={`p-2 rounded-lg ${colors.bg}`}>
            {icon}
          </div>
        )}
      </div>
      
      {(trend || trendValue) && (
        <div className="flex items-center gap-1 mt-2">
          {TrendIcon && (
            <TrendIcon className={`w-3 h-3 ${trendColors[trend!]}`} />
          )}
          {trendValue && (
            <span className={`text-xs font-medium ${trend ? trendColors[trend] : 'text-slate-400'}`}>
              {trendValue}
            </span>
          )}
        </div>
      )}
    </div>
  );
});
