/**
 * LaneMatrix — 5×4 heatmap of bounded sub-lane status (rows = assets,
 * cols = settle / pinned_fav / cheap_no / mband). Whole rows dim when the
 * agent is halted or its feed is stale. Cells are buttons (click selects).
 */

import { memo } from 'react';
import type { AssetAgent, LaneId, LaneInfo } from '../../agents/types';
import { LANES, LANE_LABELS } from '../../agents/types';
import { AssetBadge } from './AssetBadge';
import { LANE_META } from './agentMeta';
import { cx } from '../../agents/format';

interface LaneMatrixProps {
  agents: AssetAgent[];
  onSelect?: (agent: AssetAgent, lane: LaneId) => void;
  /** 'grid' = roomy cells for wallboards, 'compact' = card-scale. */
  variant?: 'grid' | 'compact';
  className?: string;
}

function laneOf(agent: AssetAgent, lane: LaneId): LaneInfo {
  return agent.lanes.find((l) => l.lane === lane) ?? { lane, status: 'unknown' };
}

export const LaneMatrix = memo(function LaneMatrix({
  agents,
  onSelect,
  variant = 'grid',
  className = '',
}: LaneMatrixProps) {
  const cellH = variant === 'grid' ? 'h-10' : 'h-7';
  const cellText = variant === 'grid' ? 'text-[10px]' : 'text-[8px]';
  const sorted = agents; // caller decides row order (wall = attention order)

  return (
    <div className={cx('w-full', className)} role="grid" aria-label="lane status matrix">
      {/* header */}
      <div className="grid gap-1" style={{ gridTemplateColumns: `64px repeat(${LANES.length}, minmax(0,1fr))` }}>
        <div />
        {LANES.map((lane) => (
          <div key={lane} className={`text-center ${cellText} font-bold tracking-wider text-slate-500 pb-1`}>
            {LANE_LABELS[lane]}
          </div>
        ))}
        {sorted.map((agent) => {
          const dimmed = agent.state === 'HALTED' || agent.state === 'STALE_FEED' || !agent.enabled;
          return (
            <div key={agent.asset} className="contents" role="row">
              <div
                className={cx('flex items-center', dimmed && 'opacity-40')}
                role="rowheader"
              >
                <AssetBadge asset={agent.asset} size="sm" showLabel />
              </div>
              {LANES.map((lane) => {
                const info = laneOf(agent, lane);
                const meta = LANE_META[info.status] ?? LANE_META.unknown;
                const title = `${agent.asset} ${LANE_LABELS[lane]}: ${info.status}${info.reason ? ` — ${info.reason}` : ''}${info.last_order_ts ? ` · last order ${info.last_order_ts}` : ''}`;
                return (
                  <button
                    key={lane}
                    type="button"
                    role="gridcell"
                    disabled={!onSelect}
                    onClick={onSelect ? () => onSelect(agent, lane) : undefined}
                    title={title}
                    aria-label={title}
                    className={cx(
                      'rounded border font-bold tracking-wide transition-colors',
                      cellH, cellText, meta.cell,
                      dimmed && 'opacity-40 saturate-50',
                      onSelect
                        ? 'cursor-pointer hover:brightness-125 focus:outline-none focus:ring-2 focus:ring-blue-500/60'
                        : 'cursor-default',
                    )}
                  >
                    {info.status === 'unknown' ? 'n/a' : info.status.toUpperCase()}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default LaneMatrix;
