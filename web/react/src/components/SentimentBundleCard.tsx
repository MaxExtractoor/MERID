import React from 'react';
import { AlertTriangle, Clock, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useLaneSentimentSnapshot, useSentimentBundle } from '../hooks/useSentimentBundle';

// ── Helpers ──────────────────────────────────────────────────────────────────

const FG_REGIME_CFG: Record<string, { label: string; color: string; bg: string }> = {
  extreme_fear:  { label: 'Extreme Fear',  color: 'text-red-400',     bg: 'bg-red-500/15' },
  fear:          { label: 'Fear',          color: 'text-orange-400',  bg: 'bg-orange-500/15' },
  neutral:       { label: 'Neutral',       color: 'text-yellow-400',  bg: 'bg-yellow-500/15' },
  greed:         { label: 'Greed',         color: 'text-green-400',   bg: 'bg-green-500/15' },
  extreme_greed: { label: 'Extreme Greed', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
};

function fgCfg(regime: string) {
  return FG_REGIME_CFG[regime] ?? FG_REGIME_CFG.neutral;
}

function signalColor(v: number): string {
  if (v >= 0.15) return 'text-green-400';
  if (v <= -0.15) return 'text-red-400';
  return 'text-slate-400';
}

function signalIcon(v: number) {
  if (v >= 0.15) return <TrendingUp className="w-3.5 h-3.5 text-green-400" />;
  if (v <= -0.15) return <TrendingDown className="w-3.5 h-3.5 text-red-400" />;
  return <Minus className="w-3.5 h-3.5 text-slate-500" />;
}

function fmt(v: number): string {
  return (v >= 0 ? '+' : '') + (v ?? 0).toFixed(3);
}

// ── Lane Sentiment Card (full) ────────────────────────────────────────────────

interface SentimentBundleCardProps {
  asset?: string;
  compact?: boolean;
  /** If true, uses the live lane-snapshot endpoint instead of the bundle endpoint */
  useLaneSnapshot?: boolean;
}

export const SentimentBundleCard: React.FC<SentimentBundleCardProps> = ({
  asset = 'BTC',
  compact = false,
  useLaneSnapshot = true,
}) => {
  const laneHook = useLaneSentimentSnapshot();
  const bundleHook = useSentimentBundle(asset);

  const loading = useLaneSnapshot ? laneHook.loading : bundleHook.loading;
  const error   = useLaneSnapshot ? laneHook.error   : bundleHook.error;
  const snap    = useLaneSnapshot ? laneHook.snapshot : null;
  const bundle  = useLaneSnapshot ? null : bundleHook.bundle;

  // Normalise to a common shape
  const fg_index     = snap?.fg_index     ?? bundle?.fg_index     ?? 50;
  const fg_regime    = snap?.fg_regime    ?? 'neutral';
  const fg_synthetic = snap?.fg_is_synthetic ?? false;
  const combined_raw = snap?.combined_raw ?? bundle?.combined ?? 0;
  const combined_sm  = snap?.combined_smoothed ?? combined_raw;
  const combined_fib = snap?.combined_fib ?? combined_raw;
  const kalman_gain  = snap?.kalman_gain ?? null;
  const confidence   = snap?.confidence  ?? bundle?.confidence ?? 0;
  const vader_signal = snap?.vader_signal ?? bundle?.vader_signal ?? 'neutral';
  const kalshi_adj   = snap?.kalshi_prob_adj ?? bundle?.kalshi_adjustment ?? 0;
  const age_s        = snap?.sentiment_age_seconds ?? null;
  const stale        = snap?.sentiment_stale ?? false;
  const clamp        = snap?.fg_clamp_breakdown ?? null;

  const isContrarian = (fg_index <= 20 && combined_raw > 0.2) ||
                       (fg_index >= 80 && combined_raw < -0.2);

  const cfg = fgCfg(fg_regime);

  if (loading && !snap && !bundle) {
    return (
      <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-800 rounded w-24 mb-2" />
        <div className="h-8 bg-slate-800 rounded w-full" />
      </div>
    );
  }

  if (error && !snap && !bundle) {
    return (
      <div className="p-4 bg-red-900/20 border border-red-800 rounded-xl flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0" />
        <span className="text-red-400 text-sm">Sentiment unavailable: {error}</span>
      </div>
    );
  }

  // ── Compact mode ─────────────────────────────────────────────────────────
  if (compact) {
    return (
      <div className="flex items-center gap-3 p-2 bg-slate-900 rounded-lg border border-slate-800">
        {signalIcon(combined_sm)}
        <div className="flex flex-col min-w-0">
          <span className={`font-semibold text-sm font-mono ${signalColor(combined_sm)}`}>
            {fmt(combined_sm)}
          </span>
          <span className={`text-xs ${cfg.color}`}>FG: {fg_index} · {cfg.label}</span>
        </div>
        {fg_synthetic && (
          <span className="ml-auto text-[10px] bg-amber-500/15 text-amber-400 px-1.5 py-0.5 rounded">
            synthetic
          </span>
        )}
        {isContrarian && (
          <span className="ml-auto text-[10px] bg-purple-600/20 text-purple-400 px-1.5 py-0.5 rounded">
            contrarian
          </span>
        )}
      </div>
    );
  }

  // ── Full mode ─────────────────────────────────────────────────────────────
  return (
    <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-white text-sm">{asset} Sentiment</h3>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${cfg.color} ${cfg.bg}`}>
            {cfg.label}
          </span>
          {fg_synthetic && (
            <span className="flex items-center gap-1 text-[10px] bg-amber-500/15 text-amber-400 px-2 py-0.5 rounded-full">
              <AlertTriangle className="w-3 h-3" /> synthetic FG
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {stale && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
              <Clock className="w-3 h-3" /> stale
            </span>
          )}
          {age_s != null && (
            <span className="text-[10px] text-slate-500">{Math.round(age_s)}s ago</span>
          )}
        </div>
      </div>

      {/* FG gauge row */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="flex justify-between text-[10px] text-slate-500 mb-1">
            <span>Fear</span><span>Greed</span>
          </div>
          <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                fg_index <= 20 ? 'bg-red-500' :
                fg_index <= 40 ? 'bg-orange-500' :
                fg_index <= 60 ? 'bg-yellow-500' :
                fg_index <= 80 ? 'bg-green-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${fg_index}%` }}
            />
          </div>
        </div>
        <span className={`text-xl font-bold font-mono ${cfg.color} min-w-[2.5rem] text-right`}>
          {fg_index}
        </span>
      </div>

      {/* Signal stack: Kalman / Fib / Raw */}
      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: 'Kalman', value: combined_sm, sub: kalman_gain != null ? `gain=${(kalman_gain ?? 0).toFixed(2)}` : 'primary' },
          { label: 'Fib',    value: combined_fib, sub: 'smoothed' },
          { label: 'Raw',    value: combined_raw, sub: 'Twitter+Reddit' },
        ].map(({ label, value, sub }) => (
          <div key={label} className="bg-slate-800/60 rounded-lg p-2">
            <div className="text-[10px] text-slate-500 mb-0.5">{label}</div>
            <div className={`text-sm font-bold font-mono ${signalColor(value)}`}>{fmt(value)}</div>
            <div className="text-[9px] text-slate-600 mt-0.5">{sub}</div>
          </div>
        ))}
      </div>

      {/* Sources */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        {[
          { label: 'Twitter', value: snap?.twitter ?? bundle?.twitter ?? 0 },
          { label: 'Reddit',  value: snap?.reddit  ?? bundle?.reddit  ?? 0 },
        ].map(({ label, value }) => (
          <div key={label} className="flex justify-between bg-slate-800/40 rounded px-2 py-1">
            <span className="text-slate-500">{label}</span>
            <span className={`font-mono ${signalColor(value)}`}>{fmt(value)}</span>
          </div>
        ))}
      </div>

      {/* Confidence + VADER */}
      <div className="flex items-center justify-between text-xs border-t border-slate-800 pt-2">
        <span className="text-slate-500">
          Conf: <span className="text-slate-300 font-mono">{((confidence ?? 0) * 100).toFixed(0)}%</span>
        </span>
        <span className="text-slate-500">
          Signal: <span className="text-slate-300">{vader_signal.replace('_', ' ')}</span>
        </span>
        {kalshi_adj !== 0 && (
          <span className="text-blue-400 font-mono">
            adj {kalshi_adj > 0 ? '+' : ''}{((kalshi_adj ?? 0) * 100).toFixed(2)}%
          </span>
        )}
      </div>

      {/* FG clamp breakdown */}
      {clamp && (
        <div className="bg-slate-800/50 rounded-lg p-2.5 space-y-1.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 font-semibold">FG Clamp</span>
            <span className={`font-mono font-bold ${clamp.sizing_multiplier < 0.8 ? 'text-amber-400' : 'text-green-400'}`}>
              {((clamp.sizing_multiplier ?? 0) * 100).toFixed(0)}% size
            </span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Per-trade cap</span>
            <span className="font-mono text-slate-300">${(clamp.per_trade_cap ?? 0).toFixed(3)}</span>
          </div>
          {clamp.rules_fired.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-0.5">
              {clamp.rules_fired.map(r => (
                <span key={r} className="text-[10px] bg-amber-500/15 text-amber-400 px-1.5 py-0.5 rounded">
                  {r}
                </span>
              ))}
            </div>
          )}
          {clamp.fg_filter_blocked && (
            <div className="flex items-center gap-1 text-red-400 text-[10px]">
              <AlertTriangle className="w-3 h-3" />
              <span>FG filter: {clamp.fg_filter_reason}</span>
            </div>
          )}
        </div>
      )}

      {/* Contrarian badge */}
      {isContrarian && (
        <div className="flex items-center gap-2 bg-purple-600/15 border border-purple-700/40 rounded-lg px-3 py-1.5 text-xs text-purple-300">
          🎯 <span>Contrarian setup detected</span>
        </div>
      )}
    </div>
  );
};
