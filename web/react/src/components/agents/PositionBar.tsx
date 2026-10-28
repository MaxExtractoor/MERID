/**
 * PositionBar — open-position exposure bar vs an optional cap.
 * YES = emerald, NO = red. When no cap is provided we show the position
 * size inline without a percentage (truthful — no invented cap).
 */

import { memo } from 'react';
import type { AgentPosition } from '../../agents/types';
import { centiToContracts, cx, fmtCentsAsUsd, fmtContracts, fmtSignedCents, numOr } from '../../agents/format';

interface PositionBarProps {
  position: AgentPosition;
  /** Cap in centi-contracts; omit to render size without utilization. */
  capCenti?: number;
  className?: string;
}

export const PositionBar = memo(function PositionBar({ position, capCenti, className = '' }: PositionBarProps) {
  const contracts = centiToContracts(position.qty_centi);
  const cap = numOr(capCenti);
  const pct = cap != null && cap > 0 && contracts != null
    ? Math.min(100, (contracts / (cap / 100)) * 100)
    : undefined;
  const isYes = position.side === 'yes';
  const barColor = isYes ? '#10b981' : '#ef4444';
  const pnlC = numOr(position.unrealized_pnl_c);

  return (
    <div className={cx('space-y-1', className)}>
      <div className="flex items-center justify-between gap-2 text-[10px]">
        <span className={cx('font-semibold uppercase tracking-wide', isYes ? 'text-emerald-400' : 'text-red-400')}>
          {position.side.toUpperCase()} {fmtContracts(position.qty_centi)}
          <span className="text-slate-500 font-normal"> @{numOr(position.avg_price_c) ?? 'n/a'}c</span>
        </span>
        <span className={cx('tabular-nums font-medium', pnlC == null ? 'text-slate-600' : pnlC >= 0 ? 'text-emerald-400' : 'text-red-400')}>
          {pnlC != null ? fmtSignedCents(pnlC) : 'pnl n/a'}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden" role="progressbar"
        aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}
        aria-label={pct != null ? `position utilization ${pct.toFixed(0)} percent` : 'position size, cap unknown'}
        title={pct != null ? `${pct.toFixed(0)}% of cap` : `notional ${fmtCentsAsUsd((contracts ?? 0) * (numOr(position.avg_price_c) ?? 0))}`}>
        <div
          className="h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none"
          style={{ width: `${pct ?? (contracts ? 100 : 0)}%`, backgroundColor: barColor, opacity: pct == null ? 0.35 : 0.9 }}
        />
      </div>
      <div className="flex items-center justify-between text-[9px] text-slate-600">
        <span>{pct != null ? `${pct.toFixed(0)}% of cap` : 'cap n/a'}</span>
        {position.exits_armed != null && (
          <span className={position.exits_armed ? 'text-emerald-500' : 'text-red-400'}>
            {position.exits_armed ? 'exits armed' : 'EXITS NOT ARMED'}
          </span>
        )}
      </div>
    </div>
  );
});

export default PositionBar;
