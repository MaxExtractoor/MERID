/**
 * LaneSentimentStrip - Crypto 15m lane sentiment strip
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import {
  AlertTriangle, Zap, Clock, RefreshCw,
} from '../../ui/icons';
import { useLaneSentimentSnapshot } from '../../hooks/useSentimentBundle';

function sigColor(v: number): string {
  if (v >= 0.15) return 'text-green-400';
  if (v <= -0.15) return 'text-red-400';
  return 'text-slate-400';
}

function fmtSig(v: number): string {
  return (v >= 0 ? '+' : '') + (v ?? 0).toFixed(3);
}

export function LaneSentimentStrip() {
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
