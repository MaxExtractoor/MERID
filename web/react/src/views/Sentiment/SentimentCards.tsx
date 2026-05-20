/**
 * SentimentCards - Category cards and component bars for sentiment display
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import React from 'react';
import { Activity, BarChart3, Gauge } from '../../ui/icons';
import { GaugeWidget } from './SentimentGauge';
import type { SentimentScore } from './types';

interface ComponentBarProps {
  label: string;
  value: number;
  icon: React.ReactNode;
}

export function ComponentBar({ label, value, icon }: ComponentBarProps) {
  const pct = Math.round(value * 100);
  const color = pct <= 30 ? 'bg-red-500' : pct <= 60 ? 'bg-amber-500' : 'bg-green-500';

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <span className="text-slate-400">{icon}</span>
          <span className="text-xs text-slate-300 font-medium">{label}</span>
        </div>
        <span className="text-xs font-mono text-slate-400">{pct}%</span>
      </div>
      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

interface CategoryCardProps {
  name: string;
  data: SentimentScore;
}

export function CategoryCard({ name, data }: CategoryCardProps) {
  const cfg = data.regime ? (
    {
      extreme_fear:  { label: 'Extreme Fear',  color: 'text-red-400',    bg: 'bg-red-500/20' },
      fear:          { label: 'Fear',          color: 'text-orange-400', bg: 'bg-orange-500/20' },
      neutral:       { label: 'Neutral',       color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
      greed:         { label: 'Greed',         color: 'text-green-400',  bg: 'bg-green-500/20' },
      extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400',bg: 'bg-emerald-500/20' },
    }[data.regime] ?? { label: data.regime, color: 'text-slate-400', bg: 'bg-slate-800' }
  ) : { label: 'Unknown', color: 'text-slate-400', bg: 'bg-slate-800' };

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 hover:border-slate-700 transition-colors">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-white capitalize">{name}</h4>
        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${cfg.color} ${cfg.bg}`}>
          {cfg.label}
        </span>
      </div>
      <GaugeWidget score={data.score} regime={data.regime} label={`${data.sample_count} markets`} size="sm" />
      {data.components && Object.keys(data.components).length > 0 && (
        <div className="mt-3 space-y-2">
          <ComponentBar label="Volatility" value={data.components.volatility ?? 0} icon={<Activity className="w-3 h-3" />} />
          <ComponentBar label="Volume" value={data.components.volume_heat ?? 0} icon={<BarChart3 className="w-3 h-3" />} />
          <ComponentBar label="Imbalance" value={data.components.book_imbal ?? 0} icon={<Gauge className="w-3 h-3" />} />
        </div>
      )}
    </div>
  );
}
