import React from 'react';
import { TrendingUp, TrendingDown, Activity, Minus, HelpCircle } from '../ui/icons';

export type RegimeLabel = 
  | 'trending_up' 
  | 'trending_down' 
  | 'mean_reverting' 
  | 'high_volatility' 
  | 'low_volatility' 
  | 'choppy' 
  | 'unknown';

export interface RegimeData {
  label: RegimeLabel;
  confidence: number;
  duration_minutes?: number;
  asset?: string;
}

interface RegimeBadgeProps {
  regime: RegimeData;
  showConfidence?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

const REGIME_CONFIG: Record<RegimeLabel, {
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
  description: string;
}> = {
  trending_up: {
    label: 'TRENDING',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    icon: <TrendingUp className="w-3 h-3" />,
    description: 'Upward trend detected',
  },
  trending_down: {
    label: 'DOWNTREND',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-orange-500/30',
    icon: <TrendingDown className="w-3 h-3" />,
    description: 'Downward trend detected',
  },
  mean_reverting: {
    label: 'MEAN REV',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/30',
    icon: <Minus className="w-3 h-3" />,
    description: 'Price oscillating around mean',
  },
  high_volatility: {
    label: 'VOLATILE',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    icon: <Activity className="w-3 h-3" />,
    description: 'High volatility regime',
  },
  low_volatility: {
    label: 'QUIET',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30',
    icon: <Minus className="w-3 h-3" />,
    description: 'Low volatility regime',
  },
  choppy: {
    label: 'CHOPPY',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/30',
    icon: <Activity className="w-3 h-3" />,
    description: 'Directionless price action',
  },
  unknown: {
    label: 'UNKNOWN',
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10',
    borderColor: 'border-slate-500/30',
    icon: <HelpCircle className="w-3 h-3" />,
    description: 'Regime not determined',
  },
};

export function RegimeBadge({ 
  regime, 
  showConfidence = true, 
  size = 'sm' 
}: RegimeBadgeProps) {
  const config = REGIME_CONFIG[regime.label] || REGIME_CONFIG.unknown;
  const confidencePercent = Math.round((regime.confidence || 0) * 100);
  
  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5 gap-1',
    md: 'text-sm px-2.5 py-1 gap-1.5',
    lg: 'text-base px-3 py-1.5 gap-2',
  };
  
  const iconSizes = {
    sm: 'w-3 h-3',
    md: 'w-3.5 h-3.5',
    lg: 'w-4 h-4',
  };
  
  return (
    <span
      className={`
        inline-flex items-center rounded-md border font-medium
        ${config.bgColor} ${config.color} ${config.borderColor}
        ${sizeClasses[size]}
        transition-all duration-200 hover:opacity-80
      `}
      title={`${config.description}${regime.duration_minutes ? ` • ${Math.round(regime.duration_minutes)}min` : ''}`}
    >
      <span className={iconSizes[size]}>{config.icon}</span>
      <span>{config.label}</span>
      {showConfidence && regime.confidence > 0 && (
        <span className="opacity-60">({confidencePercent}%)</span>
      )}
    </span>
  );
}

// Helper to format regime for display
export function formatRegimeLabel(label: RegimeLabel): string {
  return REGIME_CONFIG[label]?.label || 'UNKNOWN';
}

// Helper to get regime color class
export function getRegimeColorClass(label: RegimeLabel): string {
  return REGIME_CONFIG[label]?.color || 'text-slate-400';
}

// Compact version for table/list views
export function RegimeDot({ regime }: { regime: RegimeData }) {
  const config = REGIME_CONFIG[regime.label] || REGIME_CONFIG.unknown;
  const confidencePercent = Math.round((regime.confidence || 0) * 100);
  
  return (
    <span 
      className={`inline-flex items-center gap-1.5 text-xs ${config.color}`}
      title={`${config.description} (${confidencePercent}% confidence)`}
    >
      <span className={`w-2 h-2 rounded-full ${config.bgColor.replace('/10', '')}`} />
      <span className="font-medium">{config.label}</span>
    </span>
  );
}
