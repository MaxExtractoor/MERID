/**
 * KalshiSentimentView — Fear/Greed Sentiment Dashboard.
 *
 * Layout:
 *   Top strip:   Global gauge (0–100) + regime badge + external crypto F/G
 *   Row 1:       Per-category sentiment cards (crypto, economics, financials, …)
 *   Row 2:       Component breakdown (volatility, volume heat, book imbalance)
 *   Row 3:       Top-10 most extreme markets table
 */

import React, { useMemo } from 'react';
import {
  Activity, TrendingUp, TrendingDown, BarChart3,
  AlertTriangle, Gauge, RefreshCw, Flame, Snowflake,
  ArrowUp, ArrowDown,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';

// ── Interfaces ──────────────────────────────────────────────────────────────

interface SentimentComponents {
  volatility: number;
  volume_heat: number;
  book_imbal: number;
}

interface SentimentScore {
  score: number;
  regime: string;
  components: SentimentComponents;
  sample_count: number;
  timestamp?: number;
  external_score?: number | null;
  external_regime?: string | null;
}

interface MarketSentiment {
  ticker: string;
  score: number;
  regime: string;
  category: string;
  components: SentimentComponents;
  last_update: number;
}

interface SentimentData {
  global: SentimentScore;
  by_category: Record<string, SentimentScore>;
  tracked_markets: number;
  external?: { score: number | null; regime: string | null; fetched_at: number };
  top_markets?: MarketSentiment[];
  error?: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

const REGIME_CONFIG: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  extreme_fear:  { label: 'Extreme Fear',  color: 'text-red-400',    bg: 'bg-red-500/20',    icon: <Snowflake className="w-4 h-4" /> },
  fear:          { label: 'Fear',          color: 'text-orange-400', bg: 'bg-orange-500/20', icon: <TrendingDown className="w-4 h-4" /> },
  greed:         { label: 'Greed',         color: 'text-green-400',  bg: 'bg-green-500/20',  icon: <TrendingUp className="w-4 h-4" /> },
  extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400',bg: 'bg-emerald-500/20',icon: <Flame className="w-4 h-4" /> },
};

function regimeCfg(regime: string) {
  return REGIME_CONFIG[regime] ?? REGIME_CONFIG.greed;
}

function gaugeColor(score: number): string {
  if (score <= 24) return '#ef4444';   // red
  if (score <= 49) return '#f97316';   // orange
  if (score <= 74) return '#22c55e';   // green
  return '#10b981';                     // emerald
}

function arcPath(score: number, r: number, cx: number, cy: number): string {
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

// ── Sub-components ──────────────────────────────────────────────────────────

function GaugeWidget({ score, regime, label, size = 'lg' }: { score: number; regime: string; label: string; size?: 'lg' | 'sm' }) {
  const cfg = regimeCfg(regime);
  const r = size === 'lg' ? 80 : 48;
  const cx = size === 'lg' ? 100 : 56;
  const cy = size === 'lg' ? 90 : 54;
  const sw = size === 'lg' ? 12 : 8;
  const w = cx * 2;
  const h = size === 'lg' ? 110 : 64;
  const fontSize = size === 'lg' ? 'text-3xl' : 'text-lg';

  return (
    <div className="flex flex-col items-center">
      <svg width={w} height={h} className="overflow-visible">
        {/* Background arc */}
        <path d={arcPath(100, r, cx, cy)} fill="none" stroke="#334155" strokeWidth={sw} strokeLinecap="round" />
        {/* Value arc */}
        <path d={arcPath(Math.max(score, 1), r, cx, cy)} fill="none" stroke={gaugeColor(score)} strokeWidth={sw} strokeLinecap="round" />
        {/* Score text */}
        <text x={cx} y={cy - (size === 'lg' ? 8 : 4)} textAnchor="middle" className={`${fontSize} font-bold fill-white`}>
          {Math.round(score)}
        </text>
      </svg>
      <div className="flex items-center gap-1.5 mt-1">
        <span className={cfg.color}>{cfg.icon}</span>
        <span className={`text-xs font-semibold ${cfg.color}`}>{cfg.label}</span>
      </div>
      <p className="text-[10px] text-slate-500 mt-0.5">{label}</p>
    </div>
  );
}

function ComponentBar({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
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

function CategoryCard({ name, data }: { name: string; data: SentimentScore }) {
  const cfg = regimeCfg(data.regime);
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
        <button
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
              icon={<BarChart3 className="w-3.5 h-3.5" />}
            />
            <ComponentBar
              label="Book Imbalance"
              value={data?.global?.components?.book_imbal ?? 0.5}
              icon={<Gauge className="w-3.5 h-3.5" />}
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

      {/* ── Category Cards ────────────────────────────────────── */}
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
