/**
 * DecisionFeed — scrolling live tape of DecisionEvents.
 *
 * Rows: clock time, asset badge, kind icon (enter=green arrow, veto=red
 * slash, guard=amber shield, fill=blue dot, settle=check), summary text,
 * reason chip. Counterfactual vetoes get a distinct dashed/dimmed style.
 * Kind + asset filter chips. Virtualized via react-virtuoso past 50 rows.
 */

import { memo, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import type { AssetSymbol, DecisionEvent, DecisionEventKind } from '../../agents/types';
import { ASSETS } from '../../agents/types';
import { AssetBadge } from './AssetBadge';
import { KIND_META } from './agentMeta';
import { cx, fmtClock, fmtSignedCents, numOr } from '../../agents/format';
import {
  ArrowUpRight, ArrowDownRight, Ban, Shield, Check, CheckCircle2,
  Minus, FileText,
} from '../../ui/icons';

const KIND_ICON: Record<DecisionEventKind, (cls: string) => JSX.Element> = {
  enter: (cls) => <ArrowUpRight className={cls} />,
  veto: (cls) => <Ban className={cls} />,
  guard: (cls) => <Shield className={cls} />,
  fill: (cls) => <span className={cx('inline-block rounded-full bg-blue-400', cls)} style={{ width: 7, height: 7 }} />,
  settle: (cls) => <CheckCircle2 className={cls} />,
  skip: (cls) => <Minus className={cls} />,
  order: (cls) => <FileText className={cls} />,
  exit: (cls) => <ArrowDownRight className={cls} />,
};

const KIND_ORDER: DecisionEventKind[] = ['enter', 'veto', 'guard', 'fill', 'exit', 'settle', 'order', 'skip'];

interface FeedRowProps {
  event: DecisionEvent;
  compact?: boolean;
}

const FeedRow = memo(function FeedRow({ event, compact = false }: FeedRowProps) {
  const meta = KIND_META[event.kind] ?? KIND_META.skip;
  const cf = event.counterfactual === true;
  return (
    <div
      className={cx(
        'flex items-center gap-2 px-2 border-b border-slate-800/60 text-[11px] leading-5',
        compact ? 'py-1' : 'py-1.5',
        cf && 'border-dashed opacity-80',
      )}
      title={cf ? 'counterfactual — would have traded if not vetoed' : undefined}
    >
      <span className="tabular-nums text-slate-500 w-16 shrink-0">{fmtClock(event.ts)}</span>
      <span className={cx('shrink-0 w-4 flex justify-center', meta.text)}>
        {KIND_ICON[event.kind]?.('w-3.5 h-3.5') ?? <Check className="w-3.5 h-3.5" />}
      </span>
      {event.asset ? (
        <AssetBadge asset={String(event.asset)} size="sm" />
      ) : (
        <span className="w-5 h-5 shrink-0 rounded bg-slate-800/60 border border-slate-700/40" aria-hidden="true" />
      )}
      <span className={cx('flex-1 min-w-0 truncate text-slate-300', cf && 'italic')}>
        {event.summary || 'n/a'}
      </span>
      {numOr(event.price_c) != null && (
        <span className="tabular-nums text-slate-400 shrink-0">@{event.price_c}c</span>
      )}
      {numOr(event.edge_c) != null && (
        <span className={cx('tabular-nums shrink-0', (event.edge_c ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400')}>
          {fmtSignedCents(event.edge_c)}
        </span>
      )}
      {event.reason && (
        <span className={cx('shrink-0 rounded border px-1 py-px text-[8px] font-semibold max-w-[110px] truncate', meta.chip)}>
          {event.reason}
        </span>
      )}
      {cf && (
        <span className="shrink-0 rounded border border-dashed border-amber-500/50 px-1 py-px text-[8px] font-bold text-amber-400">
          CF
        </span>
      )}
    </div>
  );
});

/* ------------------------------------------------------------------ */

interface DecisionFeedProps {
  events: DecisionEvent[];
  height?: number;
  compact?: boolean;
  /** Hide the filter chip row (e.g. embedded in a drawer). */
  hideFilters?: boolean;
  className?: string;
}

export const DecisionFeed = memo(function DecisionFeed({
  events,
  height = 280,
  compact = false,
  hideFilters = false,
  className = '',
}: DecisionFeedProps) {
  const [kindFilter, setKindFilter] = useState<DecisionEventKind | 'all'>('all');
  const [assetFilter, setAssetFilter] = useState<AssetSymbol | 'all'>('all');

  const presentKinds = useMemo(() => {
    const set = new Set(events.map((e) => e.kind));
    return KIND_ORDER.filter((k) => set.has(k));
  }, [events]);

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (kindFilter !== 'all' && e.kind !== kindFilter) return false;
      if (assetFilter !== 'all') {
        const a = typeof e.asset === 'string' ? e.asset.toUpperCase() : '';
        if (a !== assetFilter) return false;
      }
      return true;
    });
  }, [events, kindFilter, assetFilter]);

  return (
    <div className={cx('flex flex-col min-w-0', className)}>
      {!hideFilters && (
        <div className="flex items-center gap-1 flex-wrap pb-2">
          <button
            type="button"
            onClick={() => setKindFilter('all')}
            aria-pressed={kindFilter === 'all'}
            className={cx(
              'rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide',
              kindFilter === 'all' ? 'bg-slate-600/40 text-slate-100 border-slate-500' : 'text-slate-500 border-slate-700/60 hover:text-slate-300',
            )}
          >
            ALL
          </button>
          {presentKinds.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setKindFilter(kindFilter === k ? 'all' : k)}
              aria-pressed={kindFilter === k}
              className={cx(
                'rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide',
                kindFilter === k ? KIND_META[k].chip : 'text-slate-500 border-slate-700/60 hover:text-slate-300',
              )}
            >
              {KIND_META[k].label}
            </button>
          ))}
          <span className="mx-1 h-3 w-px bg-slate-700" aria-hidden="true" />
          <button
            type="button"
            onClick={() => setAssetFilter('all')}
            aria-pressed={assetFilter === 'all'}
            className={cx(
              'rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide',
              assetFilter === 'all' ? 'bg-slate-600/40 text-slate-100 border-slate-500' : 'text-slate-500 border-slate-700/60 hover:text-slate-300',
            )}
          >
            ANY
          </button>
          {ASSETS.map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => setAssetFilter(assetFilter === a ? 'all' : a)}
              aria-pressed={assetFilter === a}
              className={cx(
                'rounded border px-1.5 py-0.5 text-[9px] font-bold tracking-wide',
                assetFilter === a ? 'bg-slate-600/40 text-slate-100 border-slate-500' : 'text-slate-500 border-slate-700/60 hover:text-slate-300',
              )}
            >
              {a}
            </button>
          ))}
          <span className="ml-auto tabular-nums text-[9px] text-slate-600">
            {filtered.length}/{events.length}
          </span>
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-[11px] text-slate-600 border border-dashed border-slate-800 rounded-lg">
          {events.length === 0 ? 'no decision events' : 'no events match filters'}
        </div>
      ) : filtered.length > 50 ? (
        <Virtuoso
          style={{ height }}
          data={filtered}
          overscan={12}
          itemContent={(_, e) => <FeedRow event={e} compact={compact} />}
        />
      ) : (
        <div className="overflow-y-auto rounded-md" style={{ maxHeight: height }}>
          {filtered.map((e, i) => (
            <FeedRow key={`${e.ts}-${i}`} event={e} compact={compact} />
          ))}
        </div>
      )}
    </div>
  );
});

export default DecisionFeed;
