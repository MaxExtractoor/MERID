/**
 * SentimentGauge - Gauge widget for sentiment display
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import React from 'react';
import {
  Snowflake, TrendingDown, Minus, TrendingUp, Flame,
} from '../../ui/icons';
import { CHART_COLORS } from '../../config/constants';
import { regimeCfg, gaugeColor, arcPath } from './types';

interface GaugeWidgetProps {
  score: number;
  regime: string;
  label: string;
  size?: 'lg' | 'sm';
}

const ICON_MAP: Record<string, React.ReactNode> = {
  snowflake: <Snowflake className="w-4 h-4" />,
  'trending-down': <TrendingDown className="w-4 h-4" />,
  minus: <Minus className="w-4 h-4" />,
  'trending-up': <TrendingUp className="w-4 h-4" />,
  flame: <Flame className="w-4 h-4" />,
};

export function GaugeWidget({ score, regime, label, size = 'lg' }: GaugeWidgetProps) {
  const cfg = regimeCfg(regime);
  const r = size === 'lg' ? 80 : 48;
  const cx = size === 'lg' ? 100 : 56;
  const cy = size === 'lg' ? 90 : 54;
  const sw = size === 'lg' ? 12 : 8;
  const w = cx * 2;
  const h = size === 'lg' ? 110 : 64;
  const fontSize = size === 'lg' ? 'text-3xl' : 'text-lg';
  const icon = ICON_MAP[cfg.icon] ?? ICON_MAP.minus;

  return (
    <div className="flex flex-col items-center">
      <svg width={w} height={h} className="overflow-visible">
        {/* Background arc */}
        <path d={arcPath(100, r, cx, cy)} fill="none" stroke={CHART_COLORS.GRID_STROKE} strokeWidth={sw} strokeLinecap="round" />
        {/* Value arc */}
        <path d={arcPath(Math.max(score, 1), r, cx, cy)} fill="none" stroke={gaugeColor(score)} strokeWidth={sw} strokeLinecap="round" />
        {/* Score text */}
        <text x={cx} y={cy - (size === 'lg' ? 8 : 4)} textAnchor="middle" className={`${fontSize} font-bold fill-white`}>
          {Math.round(score)}
        </text>
      </svg>
      <div className="flex items-center gap-1.5 mt-1">
        <span className={cfg.color}>{icon}</span>
        <span className={`text-xs font-semibold ${cfg.color}`}>{cfg.label}</span>
      </div>
      <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
    </div>
  );
}
