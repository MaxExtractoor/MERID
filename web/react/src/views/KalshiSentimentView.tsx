/**
 * KalshiSentimentView — Fear/Greed Sentiment Dashboard.
 *
 * Layout:
 *   Top strip:   Global gauge (0–100) + regime badge + external crypto F/G
 *   Row 1:       Per-category sentiment cards (crypto, economics, financials, …)
 *   Row 2:       Component breakdown (volatility, volume heat, book imbalance)
 *   Row 3:       Top-10 most extreme markets table
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import { useMemo } from 'react';
import {
  Activity, AlertTriangle, RefreshCw, Flame, ArrowUp, ArrowDown, Snowflake, Target, ArrowRight,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import { GaugeWidget } from './Sentiment/SentimentGauge';
import { CategoryCard, ComponentBar } from './Sentiment/SentimentCards';
import { LaneSentimentStrip } from './Sentiment/LaneSentimentStrip';
// LEGACY REMOVAL: SwarmSentimentPanel removed - swarm consensus not used in 15m stack
import { regimeCfg } from './Sentiment/types';
import type { SentimentData, SizingEffectCardData } from './Sentiment/types';

// ── Sizing Effect Card ──────────────────────────────────────────────────────

function SizingEffectCard() {
  const { data, loading } = useApiData<{
    assets: Record<string, SizingEffectCardData>;
  }>(
    API_ENDPOINTS.SENTIMENT_VOL_ASSETS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );

  const primaryAsset = data?.assets?.['BTC'] ?? Object.values(data?.assets ?? {})[0];

  if (loading && !primaryAsset) {
    return (
      <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 animate-pulse">
        <div className="h-4 bg-slate-800 rounded w-32 mb-2" />
        <div className="h-8 bg-slate-800 rounded w-24" />
      </div>
    );
  }

  if (!primaryAsset) {
    return null;
  }

  const multiplier = primaryAsset.sizing_multiplier;
  const isExtreme = multiplier.regime_label === 'HALTED' || multiplier.regime_label === 'CAUTION';

  // Determine color based on sizing multiplier value
  const valueColor = multiplier.value < 0.5 ? 'text-red-400' :
                     multiplier.value < 0.8 ? 'text-amber-400' :
                     'text-green-400';

  const regimeBg = multiplier.regime_label === 'HALTED' ? 'bg-red-500/20' :
                   multiplier.regime_label === 'CAUTION' ? 'bg-amber-500/20' :
                   'bg-green-500/20';

  const regimeColor = multiplier.regime_label === 'HALTED' ? 'text-red-400' :
                      multiplier.regime_label === 'CAUTION' ? 'text-amber-400' :
                      'text-green-400';

  return (
    <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-semibold text-white">Effect on Sizing</span>
        </div>
        <span className="text-xs text-slate-500">{primaryAsset.asset}</span>
      </div>

      {/* Main content */}
      <div className="flex items-center gap-4">
        {/* Sizing multiplier value */}
        <div className="text-center">
          <p className={`text-3xl font-bold ${valueColor}`}>
            {(multiplier.value * 100).toFixed(0)}%
          </p>
          <p className="text-xs text-slate-400">of baseline size</p>
        </div>

        {/* Divider */}
        <div className="h-12 w-px bg-slate-700" />

        {/* Details */}
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${regimeBg} ${regimeColor}`}>
              {multiplier.regime_label}
            </span>
            {isContrarianOpportunity(primaryAsset) && (
              <span className="text-xs bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded-full">
                Contrarian boost active
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 line-clamp-2">
            {multiplier.reasoning}
          </p>
        </div>
      </div>

      {/* Warning for extreme regimes */}
      {isExtreme && (
        <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-500/10 rounded-lg p-2">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          <span>
            {multiplier.regime_label === 'HALTED'
              ? 'Position sizing severely reduced — review risk parameters'
              : 'Position sizing reduced — elevated risk regime detected'}
          </span>
        </div>
      )}

      {/* Link to vol dashboard */}
      <div className="flex justify-end pt-1">
        <a
          href="#/kalshi-vol-dashboard"
          className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
        >
          View Vol & Sizing <ArrowRight className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
}

function isContrarianOpportunity(asset: SizingEffectCardData): boolean {
  // Contrarian boost is active when:
  // - Extreme fear (FGI <= 20) with bullish signal, or
  // - Extreme greed (FGI >= 80) with bearish signal
  if (!asset.sentiment) return false;
  const fgi = asset.sentiment.value;
  // This is a simplified check - the actual contrarian logic is in the backend
  return (fgi <= 20 || fgi >= 80);
}

// ── Main View ───────────────────────────────────────────────────────────────

export default function KalshiSentimentView() {
  const { data, loading, refetch } = useApiData<SentimentData>(
    API_ENDPOINTS.KALSHI_GRID_SENTIMENT,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );

  const categories = useMemo(() => {
    if (!data?.by_category) return [];
    return Object.entries(data.by_category)
      .filter(([, v]) => v.sample_count > 0)
      .sort((a, b) => b[1].sample_count - a[1].sample_count);
  }, [data?.by_category]);

  const topMarkets = useMemo(() => {
    if (!data?.top_markets) return [];
    return data.top_markets.slice(0, 10);
  }, [data?.top_markets]);

  const globalScore = data?.global?.score ?? 50;
  const globalRegime = data?.global?.regime ?? 'greed';

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" />
        Loading sentiment data…
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <ExecutionGateStrip />

      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-6 h-6 text-rose-400" />
          <h1 className="text-xl font-bold text-white">Fear / Greed Index</h1>
          <KalshiModeBadge />
        </div>
        <button type="button"
          onClick={() => refetch?.()}
          className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          aria-label="Refresh sentiment"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {data?.error && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{data.error}</span>
        </div>
      )}

      {/* ── Global Gauge Strip ────────────────────────────────── */}
      <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-6">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          {/* Main gauge */}
          <GaugeWidget score={globalScore} regime={globalRegime} label={`${data?.tracked_markets ?? 0} tracked markets`} size="lg" />

          {/* Component breakdown */}
          <div className="flex-1 min-w-0 max-w-md space-y-3">
            <h3 className="text-sm font-semibold text-white mb-2">Component Breakdown</h3>
            <ComponentBar
              label="Prob Volatility"
              value={data?.global?.components?.volatility ?? 0.5}
              icon={<Activity className="w-3.5 h-3.5" />}
            />
            <ComponentBar
              label="Volume Heat"
              value={data?.global?.components?.volume_heat ?? 0.5}
              icon={<Activity className="w-3.5 h-3.5" />}
            />
            <ComponentBar
              label="Book Imbalance"
              value={data?.global?.components?.book_imbal ?? 0.5}
              icon={<Activity className="w-3.5 h-3.5" />}
            />
          </div>

          {/* External crypto F/G */}
          <div className="bg-slate-800/60 rounded-xl border border-slate-700 p-4 text-center min-w-[150px]">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Crypto F/G (ext)</p>
            {data?.external?.score != null ? (
              <>
                <p className="text-2xl font-bold text-white">{Math.round(data.external.score)}</p>
                <p className={`text-xs font-semibold capitalize ${regimeCfg(data.external.regime ?? 'greed').color}`}>
                  {(data.external.regime ?? 'N/A').replace(/_/g, ' ')}
                </p>
              </>
            ) : (
              <p className="text-sm text-slate-600">No data</p>
            )}
          </div>
        </div>
      </div>

      {/* ── Crypto 15m Lane Sentiment Strip ─────────────────── */}
      <LaneSentimentStrip />

      {/* ── Sizing Effect Card ──────────────────────────────── */}
      <SizingEffectCard />

      {/* LEGACY REMOVAL: SwarmSentimentPanel removed - swarm consensus not used in 15m stack */}

      {/* ── Category Cards ────────────────────────────────── */}
      {categories.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-300 mb-3">By Category</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {categories.map(([name, score]) => (
              <CategoryCard key={name} name={name} data={score} />
            ))}
          </div>
        </div>
      )}

      {/* ── Top Extreme Markets ───────────────────────────────── */}
      {topMarkets.length > 0 && (
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <Flame className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-semibold text-white">Most Extreme Markets</h3>
            <span className="text-xs text-slate-500 ml-auto">by distance from 50</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500">
                <th className="text-left px-4 py-2">Ticker</th>
                <th className="text-left px-4 py-2">Category</th>
                <th className="text-right px-4 py-2">Score</th>
                <th className="text-left px-4 py-2">Regime</th>
                <th className="text-right px-4 py-2">Vol</th>
                <th className="text-right px-4 py-2">Volume</th>
                <th className="text-right px-4 py-2">Imbal</th>
              </tr>
            </thead>
            <tbody>
              {topMarkets.map((m) => {
                const mc = regimeCfg(m.regime);
                const dir = m.score >= 50;
                return (
                  <tr key={m.ticker} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-1.5">
                        {dir
                          ? <ArrowUp className="w-3 h-3 text-green-400" />
                          : <ArrowDown className="w-3 h-3 text-red-400" />}
                        <span className="text-slate-200 font-medium font-mono">{m.ticker}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-slate-400 capitalize">{m.category}</td>
                    <td className="px-4 py-2 text-right">
                      <span className={`font-bold font-mono ${mc.color}`}>{Math.round(m.score)}</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${mc.color} ${mc.bg}`}>
                        {mc.label}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-slate-400">
                      {((m.components?.volatility ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-slate-400">
                      {((m.components?.volume_heat ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-slate-400">
                      {((m.components?.book_imbal ?? 0) * 100).toFixed(0)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Empty State ──────────────────────────────────────── */}
      {!data?.tracked_markets && !loading && (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500">
          <Snowflake className="w-10 h-10 mb-3 text-slate-600" />
          <p className="text-sm font-medium">No sentiment data yet</p>
          <p className="text-xs mt-1">Start the grid or wait for the catalog to populate</p>
        </div>
      )}
    </div>
  );
}
