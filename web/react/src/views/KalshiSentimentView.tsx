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
  ArrowUp, ArrowDown, Clock, Zap, Target, ArrowRight, Minus,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { useLaneSentimentSnapshot } from '../hooks/useSentimentBundle';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS } from '../config/constants';
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
  neutral:       { label: 'Neutral',       color: 'text-yellow-400', bg: 'bg-yellow-500/20', icon: <Minus className="w-4 h-4" /> },
  greed:         { label: 'Greed',         color: 'text-green-400',  bg: 'bg-green-500/20',  icon: <TrendingUp className="w-4 h-4" /> },
  extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400',bg: 'bg-emerald-500/20',icon: <Flame className="w-4 h-4" /> },
};

function regimeCfg(regime: string) {
  return REGIME_CONFIG[regime] ?? REGIME_CONFIG.greed;
}

function gaugeColor(score: number): string {
  if (score <= 24) return CHART_COLORS.RED;   // red
  if (score <= 49) return CHART_COLORS.ORANGE;   // orange
  if (score <= 74) return CHART_COLORS.GREEN;   // green
  return CHART_COLORS.EMERALD;                     // emerald
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
        <path d={arcPath(100, r, cx, cy)} fill="none" stroke={CHART_COLORS.GRID_STROKE} strokeWidth={sw} strokeLinecap="round" />
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

// ── Lane Sentiment Strip ─────────────────────────────────────────────────────

function sigColor(v: number): string {
  if (v >= 0.15) return 'text-green-400';
  if (v <= -0.15) return 'text-red-400';
  return 'text-slate-400';
}

function fmtSig(v: number): string {
  return (v >= 0 ? '+' : '') + (v ?? 0).toFixed(3);
}

function LaneSentimentStrip() {
  const { snapshot: s, loading, error, refetch } = useLaneSentimentSnapshot();

  const fgRegimeCfg = (r: string) =>
    ({
      extreme_fear:  { label: 'Extreme Fear',  color: 'text-red-400',     bg: 'bg-red-500/15' },
      fear:          { label: 'Fear',          color: 'text-orange-400',  bg: 'bg-orange-500/15' },
      neutral:       { label: 'Neutral',       color: 'text-yellow-400',  bg: 'bg-yellow-500/15' },
      greed:         { label: 'Greed',         color: 'text-green-400',   bg: 'bg-green-500/15' },
      extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
    }[r] ?? { label: r, color: 'text-slate-400', bg: 'bg-slate-800' });

  if (loading && !s) {
    return (
      <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 animate-pulse">
        <div className="h-4 bg-slate-800 rounded w-48 mb-3" />
        <div className="h-16 bg-slate-800 rounded" />
      </div>
    );
  }

  if (error && !s) {
    return (
      <div className="bg-slate-900/80 rounded-2xl border border-amber-800/40 p-4 flex items-center gap-2 text-amber-400 text-xs">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        Lane sentiment unavailable — lane may not be running yet.
      </div>
    );
  }

  if (!s) return null;

  const cfg = fgRegimeCfg(s.fg_regime ?? 'neutral');
  const clamp = s.fg_clamp_breakdown;
  const isContrarian = (s.fg_index <= 20 && s.combined_raw > 0.2) ||
                       (s.fg_index >= 80 && s.combined_raw < -0.2);

  return (
    <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-white">Crypto 15m Lane · Live Signal</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cfg.color} ${cfg.bg}`}>
            {cfg.label}
          </span>
          {s.fg_is_synthetic && (
            <span className="flex items-center gap-1 text-[10px] bg-amber-500/15 text-amber-400 px-2 py-0.5 rounded-full">
              <AlertTriangle className="w-3 h-3" /> synthetic FG
            </span>
          )}
          {isContrarian && (
            <span className="text-[10px] bg-purple-600/15 text-purple-300 px-2 py-0.5 rounded-full">
              🎯 contrarian
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {s.sentiment_stale && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
              <Clock className="w-3 h-3" /> stale
            </span>
          )}
          {s.sentiment_age_seconds != null && (
            <span className="text-[10px] text-slate-500">{Math.round(s.sentiment_age_seconds)}s ago</span>
          )}
          <button type="button" onClick={refetch} title="Refresh lane sentiment" aria-label="Refresh lane sentiment" className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-white transition-colors">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* FG bar */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="flex justify-between text-[10px] text-slate-600 mb-1">
            <span>0 · Fear</span><span>Greed · 100</span>
          </div>
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                s.fg_index <= 20 ? 'bg-red-500' :
                s.fg_index <= 40 ? 'bg-orange-500' :
                s.fg_index <= 60 ? 'bg-yellow-500' :
                s.fg_index <= 80 ? 'bg-green-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${s.fg_index}%` }}
            />
          </div>
        </div>
        <span className={`text-lg font-bold font-mono ${cfg.color} min-w-[2.5rem] text-right`}>
          {s.fg_index}
        </span>
      </div>

      {/* Signal stack */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: 'Kalman', value: s.combined_smoothed, sub: s.kalman_gain != null ? `gain ${(s.kalman_gain ?? 0).toFixed(2)}` : 'primary' },
          { label: 'Fib',    value: s.combined_fib,      sub: 'smoothed' },
          { label: 'Raw',    value: s.combined_raw,      sub: 'Tw+Rd' },
        ].map(({ label, value, sub }) => (
          <div key={label} className="bg-slate-800/60 rounded-lg p-2 text-center">
            <div className="text-[10px] text-slate-500 mb-0.5">{label}</div>
            <div className={`text-sm font-bold font-mono ${sigColor(value)}`}>{fmtSig(value)}</div>
            <div className="text-[9px] text-slate-600 mt-0.5">{sub}</div>
          </div>
        ))}
      </div>

      {/* Sources + confidence */}
      <div className="grid grid-cols-4 gap-2 text-xs">
        {[
          { label: 'Twitter', value: s.twitter },
          { label: 'Reddit',  value: s.reddit },
          { label: 'Conf',    value: s.confidence, pct: true },
          { label: 'Adj',     value: s.kalshi_prob_adj, pct: true },
        ].map(({ label, value, pct }) => (
          <div key={label} className="bg-slate-800/40 rounded px-2 py-1 flex flex-col items-center">
            <span className="text-[10px] text-slate-500">{label}</span>
            <span className={`font-mono text-xs ${pct ? 'text-slate-300' : sigColor(value)}`}>
              {pct ? `${((value ?? 0) * 100).toFixed(0)}%` : fmtSig(value)}
            </span>
          </div>
        ))}
      </div>

      {/* FG clamp breakdown */}
      {clamp && (
        <div className="bg-slate-800/50 rounded-lg p-2.5 space-y-1.5 text-xs border border-slate-700/50">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 font-semibold">FG Clamp</span>
            <span className={`font-mono font-bold ${clamp.sizing_multiplier < 0.8 ? 'text-amber-400' : 'text-green-400'}`}>
              {((clamp.sizing_multiplier ?? 0) * 100).toFixed(0)}% of base size
            </span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Per-trade cap</span>
            <span className="font-mono text-slate-300">${(clamp.per_trade_cap ?? 0).toFixed(3)}</span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Book cap</span>
            <span className="font-mono text-slate-300">${(clamp.max_book_cap ?? 0).toFixed(2)}</span>
          </div>
          {clamp.rules_fired.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {clamp.rules_fired.map((r: string) => (
                <span key={r} className="text-[10px] bg-amber-500/15 text-amber-400 px-1.5 py-0.5 rounded">
                  {r}
                </span>
              ))}
            </div>
          )}
          {clamp.fg_filter_blocked && (
            <div className="flex items-center gap-1 text-red-400 text-[10px]">
              <AlertTriangle className="w-3 h-3" />
              <span>Directional filter: {clamp.fg_filter_reason}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ── Sizing Effect Card ──────────────────────────────────────────────────────

interface SizingEffectCardData {
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

function SwarmSentimentPanel() {
  const { data: assets, loading: assetsLoading } = useApiData<Record<string, any>>(
    API_ENDPOINTS.SENTIMENT_ASSETS_ALL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );
  const { data: signalsData } = useApiData<{ count: number; signals: unknown[] }>(
    API_ENDPOINTS.SENTIMENT_HASHTAG_SIGNALS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );
  const { data: monitor } = useApiData<Record<string, any>>(
    API_ENDPOINTS.SENTIMENT_MONITOR_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND }
  );
  const { data: swarmHealth } = useApiData<{ ok: boolean; warnings: string[]; sentiment_tagged_fills_last_15m: number }>(
    API_ENDPOINTS.KALSHI_SWARM_HEALTH,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const assetList = useMemo(() => {
    if (!assets) return [];
    return Object.entries(assets)
      .map(([sym, ctx]: [string, any]) => ({ sym, ...ctx }))
      .sort((a, b) => Math.abs(b.combined_score ?? 0) - Math.abs(a.combined_score ?? 0));
  }, [assets]);

  const signals = signalsData?.signals ?? [];

  if (assetsLoading && !assets) {
    return (
      <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 animate-pulse">
        <div className="h-4 bg-slate-800 rounded w-56 mb-3" />
        <div className="h-24 bg-slate-800 rounded" />
      </div>
    );
  }

  if (!assets || assetList.length === 0) {
    return (
      <div className="bg-slate-900/80 rounded-2xl border border-amber-800/40 p-4 flex items-center gap-2 text-amber-400 text-xs">
        <AlertTriangle className="w-4 h-4 flex-shrink-0" />
        Swarm sentiment unavailable — HashtagMonitor may not be running yet.
      </div>
    );
  }

  return (
    <div className="bg-slate-900/80 rounded-2xl border border-slate-800 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-semibold text-white">Swarm Sentiment Intelligence</span>
          {monitor?.running && (
            <span className="text-[10px] bg-green-500/15 text-green-400 px-2 py-0.5 rounded-full font-semibold">LIVE</span>
          )}
          {monitor && !monitor.running && (
            <span className="text-[10px] bg-amber-500/15 text-amber-400 px-2 py-0.5 rounded-full font-semibold">STOPPED</span>
          )}
        </div>
        {monitor && (
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            <span>Hashtag: {monitor.hashtag_cycles ?? 0} cycles</span>
            <span>News: {monitor.news_cycles ?? 0} cycles</span>
            <span>Signals: {monitor.signals_generated ?? 0}</span>
            {swarmHealth && (
              <span className="text-slate-600">Fills/15m: {swarmHealth.sentiment_tagged_fills_last_15m ?? 0}</span>
            )}
          </div>
        )}
      </div>
      {swarmHealth?.warnings && swarmHealth.warnings.length > 0 && (
        <div className="space-y-1">
          {swarmHealth.warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[10px] text-amber-400 bg-amber-500/10 rounded px-2 py-1">
              <AlertTriangle className="w-3 h-3 shrink-0" />
              {w}
            </div>
          ))}
        </div>
      )}

      {/* Asset sentiment cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {assetList.slice(0, 10).map((a) => {
          const score = a.combined_score ?? 0;
          const label = a.label ?? 'neutral';
          const conf = a.confidence ?? 0;
          const contrarian = a.is_contrarian ?? false;
          const reduce = a.should_reduce_size ?? false;
          const labelColor = label === 'positive' ? 'text-green-400' : label === 'negative' ? 'text-red-400' : 'text-slate-400';
          const scoreBg = label === 'positive' ? 'bg-green-500/10' : label === 'negative' ? 'bg-red-500/10' : 'bg-slate-800/60';

          return (
            <div key={a.sym} className={`rounded-lg border border-slate-700/50 p-2.5 ${scoreBg}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-white">{a.sym}</span>
                <div className="flex items-center gap-1">
                  {contrarian && <span className="text-[9px] bg-purple-600/20 text-purple-300 px-1 rounded">CTR</span>}
                  {reduce && <span className="text-[9px] bg-red-600/20 text-red-300 px-1 rounded">RED</span>}
                </div>
              </div>
              <div className={`text-lg font-bold font-mono ${labelColor}`}>
                {score >= 0 ? '+' : ''}{(score ?? 0).toFixed(3)}
              </div>
              <div className="flex items-center justify-between mt-1">
                <span className={`text-[10px] font-semibold capitalize ${labelColor}`}>{label}</span>
                <span className="text-[10px] text-slate-500">{((conf ?? 0) * 100).toFixed(0)}%</span>
              </div>
              {a.fg_index != null && (
                <div className="mt-1 text-[10px] text-slate-500">
                  FG {a.fg_index} · {(a.fg_regime ?? '').replace(/_/g, ' ')}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Active signals */}
      {signals.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-xs font-semibold text-slate-300">Active Signals ({signals.length})</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {signals.slice(0, 6).map((s: unknown, i: number) => {
              const sig = s as Record<string, any>;
              const dirColor = sig.direction === 'bullish' ? 'text-green-400 bg-green-500/10 border-green-800/30'
                : sig.direction === 'bearish' ? 'text-red-400 bg-red-500/10 border-red-800/30'
                : 'text-slate-400 bg-slate-800/60 border-slate-700/30';
              return (
                <div key={i} className={`rounded-lg border p-2 text-xs ${dirColor}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-bold">{sig.asset_or_event}</span>
                    <span className="font-semibold capitalize">{sig.direction}</span>
                  </div>
                  <div className="text-[10px] mt-1 opacity-80">{sig.reason}</div>
                  <div className="flex items-center gap-2 mt-1 text-[10px] opacity-60">
                    <span>str: {(sig.strength ?? 0).toFixed(2)}</span>
                    <span>vol: {sig.volume ?? 0}</span>
                    {sig.tags?.length > 0 && <span>{sig.tags.slice(0, 3).join(' ')}</span>}
                  </div>
                </div>
              );
            })}
          </div>
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

      {/* ── Crypto 15m Lane Sentiment Strip ─────────────────── */}
      <LaneSentimentStrip />

      {/* ── Sizing Effect Card ──────────────────────────────── */}
      <SizingEffectCard />

      {/* ── Swarm Sentiment Intelligence ───────────────────── */}
      <SwarmSentimentPanel />

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
