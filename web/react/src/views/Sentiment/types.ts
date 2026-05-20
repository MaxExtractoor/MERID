/**
 * Sentiment Types
 * 
 * Shared type definitions and helpers for sentiment views.
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import { CHART_COLORS } from '../../config/constants';

export interface SentimentComponents {
  volatility: number;
  volume_heat: number;
  book_imbal: number;
}

export interface SentimentScore {
  score: number;
  regime: string;
  components: SentimentComponents;
  sample_count: number;
  timestamp?: number;
  external_score?: number | null;
  external_regime?: string | null;
}

export interface MarketSentiment {
  ticker: string;
  score: number;
  regime: string;
  category: string;
  components: SentimentComponents;
  last_update: number;
}

export interface SentimentData {
  global: SentimentScore;
  by_category: Record<string, SentimentScore>;
  tracked_markets: number;
  external?: { score: number | null; regime: string | null; fetched_at: number };
  top_markets?: MarketSentiment[];
  error?: string;
}

export interface SizingEffectCardData {
  asset: string;
  sentiment: {
    value: number;
    regime: string;
  } | null;
  sizing_multiplier: {
    value: number;
    regime_label: string;
    reasoning: string;
  };
}

export const REGIME_CONFIG: Record<string, { label: string; color: string; bg: string; icon: string }> = {
  extreme_fear:  { label: 'Extreme Fear',  color: 'text-red-400',    bg: 'bg-red-500/20',    icon: 'snowflake' },
  fear:          { label: 'Fear',          color: 'text-orange-400', bg: 'bg-orange-500/20', icon: 'trending-down' },
  neutral:       { label: 'Neutral',       color: 'text-yellow-400', bg: 'bg-yellow-500/20', icon: 'minus' },
  greed:         { label: 'Greed',         color: 'text-green-400',  bg: 'bg-green-500/20',  icon: 'trending-up' },
  extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400',bg: 'bg-emerald-500/20',icon: 'flame' },
};

export function regimeCfg(regime: string) {
  return REGIME_CONFIG[regime] ?? REGIME_CONFIG.greed;
}

export function gaugeColor(score: number): string {
  if (score <= 24) return CHART_COLORS.RED;   // red
  if (score <= 49) return CHART_COLORS.ORANGE;   // orange
  if (score <= 74) return CHART_COLORS.GREEN;   // green
  return CHART_COLORS.EMERALD;                     // emerald
}

export function arcPath(score: number, r: number, cx: number, cy: number): string {
  const startAngle = -180;
  const endAngle = startAngle + (score / 100) * 180;
  const startRad = (startAngle * Math.PI) / 180;
  const endRad = (endAngle * Math.PI) / 180;
  const x1 = cx + r * Math.cos(startRad);
  const y1 = cy + r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad);
  const y2 = cy + r * Math.sin(endRad);
  const largeArc = score > 50 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
}
