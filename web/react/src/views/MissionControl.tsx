/**
 * MissionControl — distance-readable wallboard for the five 15m agents:
 * giant verdict banner, HealthOrb row, LaneMatrix (click opens the
 * AgentDetailDrawer), the most recent decision's GateFunnel, a compact
 * DecisionFeed rail, a trading-shard collateral tile, and the 15m
 * observability panels (venue health + pipeline alignment).
 */

import { useCallback, useMemo, useState } from 'react';
import { useAgentWall, tradingShardCents } from '../agents/useAgentWall';
import type { AssetAgent } from '../agents/types';
import {
  AgentDetailDrawer, DecisionFeed, GateFunnel, HealthOrb, LaneMatrix, SystemRibbon,
} from '../components/agents';
import Kalshi15mHealthPanel from '../components/Kalshi15mHealthPanel';
import Kalshi15mAlignmentPanel from '../components/Kalshi15mAlignmentPanel';
import { Skeleton } from '../ui';
import { cx, fmtAgeMs, fmtCentsAsUsd, numOr, parseTsMs } from '../agents/format';
import { useNow } from '../agents/hooks';

export default function MissionControl() {
  const { agents, ribbon, feed, sources, loading, refresh, spotPrices } = useAgentWall({ pollMs: 5000 });
  const now = useNow(1000);
  const [selected, setSelected] = useState<AssetAgent | null>(null);

  const handleOrbSelect = useCallback((agent: AssetAgent) => setSelected(agent), []);
  const handleLaneSelect = useCallback((agent: AssetAgent) => setSelected(agent), []);
  const handleClose = useCallback(() => setSelected(null), []);

  // Most recent decision across all agents (by decision ts, else agent order).
  const recent = useMemo(() => {
    let best: AssetAgent | null = null;
    let bestTs = -1;
    for (const a of agents) {
      if (!a.last_decision) continue;
      const t = parseTsMs(a.last_decision.ts) ?? 0;
      if (t > bestTs) {
        bestTs = t;
        best = a;
      }
    }
    return best ?? agents.find((a) => a.last_decision) ?? null;
  }, [agents]);

  const shardCents = tradingShardCents(ribbon.balance);
  const runtime = ribbon.runtime;
  const live = runtime?.state === 'LIVE_ENTRIES_ENABLED';
  const halted = runtime?.entry_halted === true || runtime?.state === 'LIVE_ENTRIES_HALTED';

  return (
    <div className="space-y-4 select-none">
      {/* giant verdict banner */}
      <div
        className={cx(
          'rounded-2xl border px-6 py-5 flex items-center justify-between gap-4 flex-wrap',
          live
            ? 'border-emerald-500/50 bg-gradient-to-r from-emerald-950/60 to-slate-950/40 shadow-[0_0_40px_rgba(16,185,129,0.15)]'
            : halted
              ? 'border-red-500/50 bg-gradient-to-r from-red-950/60 to-slate-950/40 shadow-[0_0_40px_rgba(239,68,68,0.18)]'
              : 'border-slate-700/60 bg-slate-900/70',
        )}
        role="status"
      >
        <div className="min-w-0">
          <div
            className={cx(
              'font-black tracking-widest uppercase leading-none tabular-nums',
              live ? 'text-emerald-300' : halted ? 'text-red-300' : 'text-slate-400',
            )}
            style={{ fontSize: 'clamp(1.8rem, 4vw, 3rem)' }}
          >
            {live ? 'LIVE — ENTRIES ENABLED' : halted ? 'ENTRIES HALTED' : 'STATE UNKNOWN'}
          </div>
          <div className="mt-2 text-sm text-slate-400 truncate max-w-3xl" title={runtime?.reason ?? runtime?.reason_code}>
            {runtime?.reason ?? runtime?.reason_code ?? (runtime == null ? 'live-runtime-state unavailable' : 'no reason recorded')}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">15m window</span>
          <WindowClock />
        </div>
      </div>

      {/* controls strip — the same defensive money control as the wall */}
      <SystemRibbon ribbon={ribbon} sources={sources} onRefresh={refresh} />

      {/* health orbs */}
      <section aria-label="agent health" className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">fleet health</h2>
          <span className="text-[10px] text-slate-600 tabular-nums">
            {agents.filter((a) => a.state !== 'HALTED').length}/{agents.length} operational
          </span>
        </div>
        {loading && agents.length === 0 ? (
          <div className="flex gap-6 justify-center py-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} width={96} height={120} className="rounded-full" />
            ))}
          </div>
        ) : (
          <div className="flex items-start justify-center gap-6 lg:gap-10 flex-wrap">
            {agents.map((a) => (
              <HealthOrb key={a.asset} agent={a} size={104} onSelect={handleOrbSelect} />
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
        {/* lane matrix + last decision (3/5) */}
        <div className="xl:col-span-3 space-y-4">
          <section aria-label="lane matrix" className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">lane matrix</h2>
            <LaneMatrix agents={agents} onSelect={handleLaneSelect} variant="grid" />
          </section>

          <section aria-label="most recent decision" className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">most recent decision</h2>
              {recent?.last_decision?.ts && (
                <span className="text-[10px] text-slate-600 tabular-nums">
                  {recent.asset} · {fmtAgeMs(Math.max(0, now - (parseTsMs(recent.last_decision.ts) ?? now)))} ago
                </span>
              )}
            </div>
            {recent?.last_decision ? (
              <>
                <div className="text-[11px] text-slate-300 mb-2 truncate" title={recent.last_decision.ticker}>
                  {recent.last_decision.action?.toUpperCase() ?? 'n/a'}
                  {recent.last_decision.side ? ` ${recent.last_decision.side.toUpperCase()}` : ''}
                  {recent.last_decision.ticker ? ` · ${recent.last_decision.ticker}` : ''}
                  {numOr(recent.last_decision.net_edge_c) != null && ` · edge ${recent.last_decision.net_edge_c}c`}
                </div>
                <GateFunnel decision={recent.last_decision} width={640} />
              </>
            ) : (
              <div className="text-[11px] text-slate-600">no decision data</div>
            )}
          </section>
        </div>

        {/* feed rail + shard tile (2/5) */}
        <div className="xl:col-span-2 space-y-4">
          <section aria-label="shard collateral" className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">shard collateral</h2>
            <div className="flex items-baseline gap-3 flex-wrap">
              <span className={cx('tabular-nums font-black', shardCents != null ? 'text-emerald-300' : 'text-slate-500')}
                style={{ fontSize: 'clamp(1.6rem, 3vw, 2.4rem)' }}>
                {shardCents != null ? fmtCentsAsUsd(shardCents) : 'n/a'}
              </span>
              <span className="text-[10px] text-slate-500">
                trading shard {ribbon.balance?.trading_shard ?? 'n/a'} — backs 15m orders
              </span>
            </div>
            <div className="mt-2 space-y-1">
              {ribbon.balance?.shards?.map((s) => (
                <div key={s.shard} className={cx(
                  'flex items-center justify-between rounded px-2 py-1 text-[11px] tabular-nums',
                  s.shard === ribbon.balance?.trading_shard ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30' : 'text-slate-400 border border-transparent',
                )}>
                  <span>shard {s.shard}{s.shard === ribbon.balance?.trading_shard ? ' · trading' : ''}</span>
                  <span>
                    {fmtCentsAsUsd(s.balance_cents)}
                    {s.available_cents != null && <span className="text-slate-500"> / avail {fmtCentsAsUsd(s.available_cents)}</span>}
                  </span>
                </div>
              )) ?? (
                <div className="text-[10px] text-slate-600">shard breakdown n/a</div>
              )}
            </div>
          </section>

          <section aria-label="decision rail" className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-2">decision rail</h2>
            <DecisionFeed events={feed.slice(0, 24)} height={380} compact hideFilters />
          </section>
        </div>
      </div>

      {/* 15m observability: venue health + end-to-end pipeline alignment */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Kalshi15mHealthPanel />
        <Kalshi15mAlignmentPanel />
      </div>

      <AgentDetailDrawer
        agent={selected}
        spot={selected ? spotPrices[selected.asset] : undefined}
        open={selected != null}
        onClose={handleClose}
      />
    </div>
  );
}

/** Big wall-clock countdown to the next quarter-hour boundary. */
function WindowClock() {
  const now = useNow(1000);
  const rem = 900 - (Math.floor(now / 1000) % 900);
  const mm = Math.floor(rem / 60);
  const ss = rem % 60;
  return (
    <span
      className={cx('tabular-nums font-black leading-none', rem < 60 ? 'text-red-400' : 'text-slate-100')}
      style={{ fontSize: 'clamp(1.8rem, 3.5vw, 2.6rem)' }}
      aria-label={`${mm} minutes ${ss} seconds to next window`}
    >
      {String(mm).padStart(2, '0')}:{String(ss).padStart(2, '0')}
    </span>
  );
}
