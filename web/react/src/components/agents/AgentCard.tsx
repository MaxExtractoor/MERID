/**
 * AgentCard — the signature tile of the Agent Wall: one card per asset
 * agent showing state, current task, heartbeat ages, lane chips, the 15m
 * window track, moneyness context, edge meter and position/veto status.
 *
 * Every field degrades to an explicit 'n/a' treatment when data is absent;
 * nothing on this card invents a plausible-looking value.
 */

import { memo, useMemo } from 'react';
import type { AssetAgent, LaneId, LaneInfo } from '../../agents/types';
import { LANES, LANE_LABELS, freshnessClass } from '../../agents/types';
import type { SpotInfo } from '../../agents/format';
import { clamp, cx, fmtAgeMs, fmtCents, fmtMMSS, numOr } from '../../agents/format';
import { useLiveCountdown } from '../../agents/hooks';
import { AssetBadge } from './AssetBadge';
import { StatePill } from './StatePill';
import { VetoChip } from './VetoChip';
import { EdgeMeter } from './EdgeMeter';
import { Sparkline } from './Sparkline';
import { PositionBar } from './PositionBar';
import { MoneynessGauge } from './MoneynessGauge';
import { LANE_META, freshnessTextClass } from './agentMeta';

/* ------------------------------------------------------------------ */

interface HeartbeatChipProps {
  label: string;
  ageMs?: number;
}

const HeartbeatChip = memo(function HeartbeatChip({ label, ageMs }: HeartbeatChipProps) {
  const cls = freshnessClass(ageMs);
  return (
    <span
      className={cx('tabular-nums text-[9px] font-medium', freshnessTextClass(cls))}
      title={`${label} age: ${ageMs != null ? fmtAgeMs(ageMs) : 'n/a'} (${cls})`}
    >
      {label} {ageMs != null ? fmtAgeMs(ageMs) : 'n/a'}
    </span>
  );
});

/* ------------------------------------------------------------------ */

interface LaneChipProps {
  lane: LaneInfo;
  onClick?: () => void;
}

const LaneChip = memo(function LaneChip({ lane, onClick }: LaneChipProps) {
  const meta = LANE_META[lane.status] ?? LANE_META.unknown;
  const label = `${LANE_LABELS[lane.lane as LaneId] ?? String(lane.lane)}`;
  const cls = cx(
    'inline-flex items-center rounded border px-1 py-px text-[8px] font-bold tracking-wide leading-4',
    meta.cell,
    onClick && 'cursor-pointer hover:brightness-125 focus:outline-none focus:ring-1 focus:ring-blue-500/60',
  );
  const title = `lane ${label}: ${lane.status}${lane.reason ? ` — ${lane.reason}` : ''}`;
  if (onClick) {
    return (
      <button
        type="button"
        className={cls}
        title={title}
        aria-label={title}
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
      >
        {label}
      </button>
    );
  }
  return <span className={cls} title={title}>{label}</span>;
});

/* ------------------------------------------------------------------ */

/** Horizontal 0-900s window track: fill = elapsed, marker = now. */
function WindowTrack({ secsToClose, priceC }: { secsToClose?: number; priceC?: number }) {
  const live = useLiveCountdown(secsToClose);
  if (live == null) {
    return (
      <div className="flex items-center gap-2 text-[9px] text-slate-600">
        <div className="h-1 flex-1 rounded bg-slate-800" />
        <span className="tabular-nums">--:--</span>
      </div>
    );
  }
  const frac = clamp(1 - live / 900, 0, 1);
  const urgent = live < 60;
  return (
    <div className="flex items-center gap-2" title={`window closes in ${fmtMMSS(live)}`}>
      <div className="relative h-1 flex-1 rounded bg-slate-800">
        <div
          className={cx('absolute inset-y-0 left-0 rounded transition-[width] duration-1000 ease-linear motion-reduce:transition-none',
            urgent ? 'bg-red-500/70' : 'bg-blue-500/60')}
          style={{ width: `${frac * 100}%` }}
        />
        <div
          className={cx('absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2 h-2 rounded-full border',
            urgent ? 'bg-red-400 border-red-200' : 'bg-blue-300 border-blue-100')}
          style={{ left: `${frac * 100}%` }}
          aria-hidden="true"
        />
      </div>
      <span className={cx('tabular-nums text-[10px] font-semibold w-8 text-right', urgent ? 'text-red-400' : 'text-slate-300')}>
        {fmtMMSS(live)}
      </span>
      {priceC != null && (
        <span className="tabular-nums text-[10px] text-slate-500 w-8 text-right" title="contract mid">
          {fmtCents(priceC)}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export interface AgentCardProps {
  agent: AssetAgent;
  spot?: SpotInfo;
  onSelect?: (agent: AssetAgent) => void;
  onLaneSelect?: (agent: AssetAgent, lane: LaneId) => void;
  /** Optional external series for the sparkline (mid-c price etc). */
  series?: number[];
  className?: string;
}

export const AgentCard = memo(function AgentCard({
  agent,
  spot,
  onSelect,
  onLaneSelect,
  series,
  className = '',
}: AgentCardProps) {
  const m = agent.market;
  const priceC = numOr(m?.mid_c ?? m?.last_price_c ?? (m?.yes_bid_c != null && m?.yes_ask_c != null ? (m.yes_bid_c + m.yes_ask_c) / 2 : undefined));

  // Series for the sparkline: explicit prop wins, else look for a numeric
  // array the server may have attached to the raw payload. Never synthesize.
  const spark = useMemo<number[] | undefined>(() => {
    if (series && series.length >= 2) return series;
    const raw = agent.raw;
    if (raw) {
      for (const key of ['sparkline', 'price_series', 'mid_series', 'pnl_series']) {
        const v = raw[key];
        if (Array.isArray(v) && v.length >= 2 && v.every((n) => typeof n === 'number')) {
          return v as number[];
        }
      }
    }
    return undefined;
  }, [series, agent.raw]);

  const dimmed = agent.state === 'HALTED' || agent.state === 'STALE_FEED';

  return (
    <article
      className={cx(
        'card group relative p-3 space-y-2 min-w-0',
        dimmed && 'opacity-70',
        onSelect && 'hover:border-slate-500/70',
        className,
      )}
      aria-label={`${agent.asset} agent card, ${agent.state}`}
    >
      {/* stretched-link overlay: whole-card click without nesting buttons.
          Sits above non-interactive content; interactive children use z-20. */}
      {onSelect && (
        <button
          type="button"
          className="absolute inset-0 rounded-xl cursor-pointer focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/60 z-10"
          aria-label={`open ${agent.asset} detail`}
          onClick={() => onSelect(agent)}
          tabIndex={0}
        />
      )}
      {/* header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <AssetBadge asset={agent.asset} size="md" />
          <div className="min-w-0">
            <div className="font-bold text-slate-100 text-sm leading-4 truncate">{agent.asset}</div>
            {spot?.price != null && (
              <div className="text-[9px] text-slate-500 tabular-nums" title={spot.source ? `spot via ${spot.source}` : 'spot price'}>
                ${spot.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
                {spot.ageS != null && <span className="text-slate-600"> · {fmtAgeMs(spot.ageS * 1000)}</span>}
              </div>
            )}
          </div>
        </div>
        <StatePill state={agent.state} size="sm" />
      </div>

      {/* current task */}
      <div className="text-[11px] text-slate-300 leading-4 min-h-4 truncate" title={agent.current_task}>
        {agent.current_task || 'n/a'}
      </div>

      {/* heartbeat ages */}
      <div className="flex items-center gap-2.5 flex-wrap border-t border-slate-800/80 pt-1.5">
        <HeartbeatChip label="EVAL" ageMs={agent.heartbeat.last_eval_ms} />
        <HeartbeatChip label="BOOK" ageMs={agent.heartbeat.book_age_ms} />
        <HeartbeatChip label="WM" ageMs={agent.heartbeat.watermark_ms} />
      </div>

      {/* lane chips — raised above the stretched-link overlay */}
      <div className="relative z-20 flex items-center gap-1 flex-wrap">
        {agent.lanes.filter((l) => LANES.includes(l.lane)).map((l) => (
          <LaneChip
            key={l.lane}
            lane={l}
            onClick={onLaneSelect ? () => onLaneSelect(agent, l.lane) : undefined}
          />
        ))}
      </div>

      {/* window track */}
      <WindowTrack secsToClose={m?.secs_to_close} priceC={priceC ?? undefined} />

      {/* moneyness context */}
      <MoneynessGauge asset={agent.asset} priceC={priceC ?? undefined} compact />

      {/* edge meter + sparkline row */}
      <div className="flex items-center justify-between gap-2">
        <EdgeMeter valueC={numOr(agent.edge?.net_ev_c)} thresholdC={numOr(agent.edge?.threshold_c)} width={104} />
        {spark && <Sparkline data={spark} width={72} height={22} threshold={numOr(agent.edge?.threshold_c)} />}
      </div>

      {/* position strip or last veto */}
      {agent.position ? (
        <PositionBar position={agent.position} />
      ) : agent.last_decision?.rejection_reason ? (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[9px] uppercase tracking-wider text-slate-600 shrink-0">last veto</span>
          <VetoChip reason={agent.last_decision.rejection_reason} />
        </div>
      ) : agent.state === 'VETOED' ? (
        <div className="text-[10px] text-amber-400/80">vetoed — reason n/a</div>
      ) : (
        <div className="text-[10px] text-slate-600">flat — scanning</div>
      )}
    </article>
  );
});

export default AgentCard;
