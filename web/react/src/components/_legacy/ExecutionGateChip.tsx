import { ShieldCheck, ShieldOff, ShieldAlert } from 'lucide-react';
import { useExecutionGate } from '../hooks/useExecutionGate';

const STATE_STYLES = {
  blocked: {
    border: 'border-red-500/40 bg-red-500/5',
    pill: 'bg-red-500/15 text-red-300 border border-red-500/30',
    icon: 'text-red-400',
    text: 'text-red-300',
    label: 'BLOCKED',
    Icon: ShieldOff,
  },
  limited: {
    border: 'border-amber-500/30 bg-amber-500/5',
    pill: 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
    icon: 'text-amber-400',
    text: 'text-amber-300',
    label: 'LIMITED',
    Icon: ShieldAlert,
  },
  clear: {
    border: 'border-green-500/30 bg-green-500/5',
    pill: 'bg-green-500/15 text-green-300 border border-green-500/30',
    icon: 'text-green-400',
    text: 'text-green-300',
    label: 'CLEAR',
    Icon: ShieldCheck,
  },
} as const;

/**
 * Compact chip showing execution gate status with top reason.
 * Drop into any agent/strategy panel for at-a-glance gate awareness.
 *
 * Variants:
 *  - "inline" (default): single-line chip for headers/toolbars
 *  - "card": slightly larger with hint text
 */
export function ExecutionGateChip({ variant = 'inline' }: { variant?: 'inline' | 'card' }) {
  const { gateState, reasons, topHint } = useExecutionGate();

  const topReason = reasons[0];
  const s = STATE_STYLES[gateState];

  if (variant === 'card') {
    return (
      <div className={`rounded-lg border px-3 py-2 text-xs ${s.border}`}>
        <div className="flex items-center gap-1.5">
          <s.Icon className={`w-3.5 h-3.5 ${s.icon}`} />
          <span className={`font-semibold ${s.text}`}>{s.label}</span>
          {gateState === 'limited' && (
            <span className="text-amber-400/70 text-[10px] font-normal">— reduce-only</span>
          )}
          {topReason && (
            <span className="text-slate-500 truncate ml-1">— {topReason.message}</span>
          )}
        </div>
        {topHint && gateState !== 'clear' && (
          <p className="text-[10px] text-slate-500 italic mt-1 truncate">→ {topHint}</p>
        )}
      </div>
    );
  }

  // inline variant
  return (
    <div className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold ${s.pill}`}
      title={topReason?.message || 'All safety checks passed'}
    >
      <s.Icon className="w-3 h-3" />
      <span>{s.label}</span>
      {gateState === 'limited' && (
        <span className="text-[9px] font-normal opacity-70">reduce-only</span>
      )}
      {topReason && gateState === 'blocked' && (
        <span className="text-[9px] font-normal text-slate-500 truncate max-w-[120px]">
          {topReason.message}
        </span>
      )}
    </div>
  );
}
