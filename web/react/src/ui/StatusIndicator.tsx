/**
 * Optimized Status Indicator - For system/trading status
 */

import React from 'react';

export type StatusSize = 'sm' | 'md' | 'lg';

interface StatusIndicatorProps {
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown' | 'active' | 'inactive' | 'warning';
  label?: string;
  size?: StatusSize;
  pulse?: boolean;
  className?: string;
}

const statusColors = {
  healthy: 'bg-emerald-400',
  active: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  warning: 'bg-amber-400',
  unhealthy: 'bg-red-400',
  inactive: 'bg-slate-400',
  unknown: 'bg-slate-400',
};

const statusLabels = {
  healthy: 'Healthy',
  active: 'Active',
  degraded: 'Degraded',
  warning: 'Warning',
  unhealthy: 'Unhealthy',
  inactive: 'Inactive',
  unknown: 'Unknown',
};

const sizeStyles = {
  sm: { dot: 'w-1.5 h-1.5', text: 'text-[10px]' },
  md: { dot: 'w-2 h-2', text: 'text-xs' },
  lg: { dot: 'w-2.5 h-2.5', text: 'text-sm' },
};

export const StatusIndicator = React.memo(function StatusIndicator({
  status,
  label,
  size = 'md',
  pulse = true,
  className = '',
}: StatusIndicatorProps) {
  const colors = statusColors[status];
  const sizes = sizeStyles[size];
  const displayLabel = label || statusLabels[status];
  
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <span className={`relative flex h-2 w-2 ${sizes.dot}`}>
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${colors} opacity-75 ${pulse ? '' : 'hidden'}`} />
        <span className={`relative inline-flex rounded-full ${colors} ${sizes.dot}`} />
      </span>
      <span className={`${sizes.text} text-slate-400 font-medium`}>
        {displayLabel}
      </span>
    </div>
  );
});

// Specialized trading status indicator
interface TradingStatusProps {
  isLive: boolean;
  isRunning?: boolean;
  className?: string;
}

export const TradingStatus = React.memo(function TradingStatus({
  isLive,
  isRunning = true,
  className = '',
}: TradingStatusProps) {
  if (!isRunning) {
    return (
      <div className={`flex items-center gap-1.5 ${className}`}>
        <span className="w-2 h-2 rounded-full bg-slate-400" />
        <span className="text-xs text-slate-400 font-medium">Stopped</span>
      </div>
    );
  }
  
  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      <span className="relative flex h-2 w-2">
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${isLive ? 'bg-red-400' : 'bg-emerald-400'} opacity-75`} />
        <span className={`relative inline-flex rounded-full w-2 h-2 ${isLive ? 'bg-red-400' : 'bg-emerald-400'}`} />
      </span>
      <span className={`text-xs font-medium ${isLive ? 'text-red-400' : 'text-emerald-400'}`}>
        {isLive ? '● LIVE' : '○ PAPER'}
      </span>
    </div>
  );
});
