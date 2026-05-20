/**
 * SwarmSentimentPanel - Swarm sentiment intelligence panel
 * 
 * Tier 4: KalshiSentimentView.tsx Split (748→3 files)
 */

import { useMemo } from 'react';
import { AlertTriangle, Zap, Activity } from '../../ui/icons';
import { useApiData } from '../../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../../config/constants';

export function SwarmSentimentPanel() {
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
