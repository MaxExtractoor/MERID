/**
 * AgentWall — the operator-grade default view for the five 15m asset
 * agents: SystemRibbon (verdict + bankroll + halt control), the
 * attention-sorted AgentCard grid (auto-animated on reorder), the
 * DecisionFeed tape and a compact blotter strip.
 *
 * Data comes exclusively from useAgentWall — fault-isolated per source,
 * with skeletons on first load and explicit error chips per failed source.
 */

import { useCallback, useMemo, useState } from 'react';
import { useAutoAnimate } from '@formkit/auto-animate/react';
import { useAgentWall } from '../agents/useAgentWall';
import type { WallSourceId } from '../agents/useAgentWall';
import type { AssetAgent } from '../agents/types';
import { SkeletonCard } from '../ui';
import {
  AgentCard, AgentDetailDrawer, DecisionFeed, SystemRibbon,
} from '../components/agents';
import { cx, fmtAgeMs } from '../agents/format';

const SOURCE_LABELS: Record<WallSourceId, string> = {
  agents: 'agents',
  grid: 'grid summary',
  feed: 'decision feed',
  markets: 'market states',
  balance: 'balance',
  runtime: 'runtime state',
  spot: 'spot prices',
};

function SourceErrorChips({ sources }: { sources: ReturnType<typeof useAgentWall>['sources'] }) {
  const failed = (Object.entries(sources) as Array<[WallSourceId, { ok: boolean; attempted: boolean; error?: string }]>)
    .filter(([, s]) => s.attempted && !s.ok);
  if (!failed.length) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap" role="alert">
      {failed.map(([id, s]) => (
        <span
          key={id}
          className="inline-flex items-center gap-1 rounded border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-red-400"
          title={s.error ?? 'fetch failed'}
        >
          <span className="w-1 h-1 rounded-full bg-red-400" aria-hidden="true" />
          {SOURCE_LABELS[id]} source down
        </span>
      ))}
    </div>
  );
}

export default function AgentWall() {
  const { agents, ribbon, feed, sources, lastUpdate, loading, refresh, spotPrices } = useAgentWall({ pollMs: 5000 });
  const [gridRef] = useAutoAnimate<HTMLDivElement>({ duration: 220, disrespectUserMotionPreference: false });
  const [selected, setSelected] = useState<AssetAgent | null>(null);

  const handleSelect = useCallback((agent: AssetAgent) => setSelected(agent), []);
  const handleLaneSelect = useCallback((agent: AssetAgent) => {
    setSelected(agent);
  }, []);
  const handleClose = useCallback(() => setSelected(null), []);

  // Compact blotter strip: positions / working orders / fills on tape.
  const blotter = useMemo(() => {
    const positions = agents.filter((a) => a.position != null).length;
    const working = agents.filter((a) => a.state === 'WORKING_ORDER').length;
    const fills = feed.filter((e) => e.kind === 'fill').length;
    const vetoes = feed.filter((e) => e.kind === 'veto').length;
    return { positions, working, fills, vetoes };
  }, [agents, feed]);

  return (
    <div className="space-y-3">
      <SystemRibbon ribbon={ribbon} sources={sources} onRefresh={refresh} />

      <div className="flex items-center justify-between gap-2">
        <SourceErrorChips sources={sources} />
        <span className="ml-auto text-[9px] text-slate-600 tabular-nums">
          {lastUpdate != null ? `updated ${fmtAgeMs(Date.now() - lastUpdate)} ago` : 'connecting…'}
        </span>
      </div>

      {/* attention-sorted agent grid */}
      {loading && agents.length === 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonCard key={i} rows={4} />
          ))}
        </div>
      ) : (
        <div
          ref={gridRef}
          className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5 gap-3"
          role="list"
          aria-label="asset agents, sorted by attention"
        >
          {agents.map((agent) => (
            <div key={agent.asset} role="listitem">
              <AgentCard
                agent={agent}
                spot={spotPrices[agent.asset]}
                onSelect={handleSelect}
                onLaneSelect={handleLaneSelect}
              />
            </div>
          ))}
        </div>
      )}

      {/* decision tape */}
      <section aria-label="decision feed" className="card p-3">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-[11px] font-bold uppercase tracking-widest text-slate-400">decision tape</h2>
          <span className="text-[9px] text-slate-600 tabular-nums">{feed.length} events</span>
        </div>
        <DecisionFeed events={feed} height={300} />
      </section>

      {/* compact blotter strip */}
      <section
        aria-label="blotter"
        className={cx(
          'flex items-center gap-4 flex-wrap rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2',
        )}
      >
        <span className="text-[9px] font-bold uppercase tracking-widest text-slate-500">blotter</span>
        <span className="tabular-nums text-[11px] text-slate-300">
          <span className="text-blue-400 font-bold">{blotter.working}</span> working
        </span>
        <span className="tabular-nums text-[11px] text-slate-300">
          <span className="text-emerald-400 font-bold">{blotter.positions}</span> positions
        </span>
        <span className="tabular-nums text-[11px] text-slate-300">
          <span className="text-cyan-400 font-bold">{blotter.fills}</span> fills on tape
        </span>
        <span className="tabular-nums text-[11px] text-slate-300">
          <span className="text-red-400 font-bold">{blotter.vetoes}</span> vetoes
        </span>
        <span className="ml-auto text-[9px] text-slate-600">
          {ribbon.grid?.running === false ? 'grid stopped' : ribbon.grid?.running === true ? `${ribbon.grid.agents_running ?? '?'}/${ribbon.grid.agents_total ?? '?'} agents running` : 'grid state n/a'}
        </span>
      </section>

      <AgentDetailDrawer
        agent={selected}
        spot={selected ? spotPrices[selected.asset] : undefined}
        open={selected != null}
        onClose={handleClose}
      />
    </div>
  );
}
