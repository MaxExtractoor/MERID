/**
 * StatePill — colored agent-state pill with a subtle pulse-dot for live
 * operational states (WORKING_ORDER / IN_POSITION). Reduced-motion safe:
 * the pulse is gated behind Tailwind's motion-safe variant.
 */

import { memo } from 'react';
import type { AgentState } from '../../agents/types';
import { STATE_META } from './agentMeta';
import { cx } from '../../agents/format';

interface StatePillProps {
  state: AgentState | string | undefined;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatePill = memo(function StatePill({ state, size = 'md', className = '' }: StatePillProps) {
  const meta = state ? STATE_META[state as AgentState] : undefined;
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-md border font-semibold uppercase tracking-wide',
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]',
        meta ? meta.pill : 'bg-slate-700/20 text-slate-400 border-slate-600/40 border-dashed',
        className,
      )}
      title={meta ? `agent state: ${state}` : `agent state unknown${state ? ` (${state})` : ''}`}
    >
      <span className="relative flex w-1.5 h-1.5">
        {meta?.pulse && (
          <span
            className="motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full opacity-60"
            style={{ backgroundColor: meta.hex }}
          />
        )}
        <span
          className="relative inline-flex rounded-full w-1.5 h-1.5"
          style={{ backgroundColor: meta?.hex ?? '#64748b' }}
        />
      </span>
      {meta ? meta.label : 'n/a'}
    </span>
  );
});

export default StatePill;
