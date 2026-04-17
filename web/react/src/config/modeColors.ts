/**
 * modeColors — Single source of truth for LIVE/PAPER/SHADOW mode badge styling.
 *
 * LIVE must always render in red/rose to signal real-money risk.
 * PAPER uses amber to signal caution (simulated, not safe to ignore).
 * SHADOW uses purple for signal-only mode.
 * Unknown/offline uses slate.
 *
 * Used by: KalshiModeBadge, ExecutionGateStrip, Sidebar NavItem, TopBar,
 *          KalshiGridView header badge, and any inline mode indicators.
 */

export const MODE_COLORS = {
  live: {
    badge: 'bg-red-500/20 text-red-400 border border-red-500/40',
    dot: 'bg-red-400',
    text: 'text-red-400',
    topbar: 'text-red-400 bg-gradient-to-r from-red-500/20 to-rose-500/20 border border-red-400/50 shadow-red-500/30',
    topbarDot: 'bg-red-400',
  },
  paper: {
    badge: 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
    dot: 'bg-amber-400',
    text: 'text-amber-400',
    topbar: 'text-amber-400 bg-gradient-to-r from-amber-500/20 to-yellow-500/20 border border-amber-400/50 shadow-amber-500/30',
    topbarDot: 'bg-amber-400',
  },
  shadow: {
    badge: 'bg-purple-500/20 text-purple-400 border border-purple-500/30',
    dot: 'bg-purple-400',
    text: 'text-purple-400',
    topbar: 'text-purple-400 bg-gradient-to-r from-purple-500/20 to-violet-500/20 border border-purple-400/50 shadow-purple-500/30',
    topbarDot: 'bg-purple-400',
  },
  unknown: {
    badge: 'bg-slate-700/50 text-slate-400 border border-slate-600/30',
    dot: 'bg-slate-400',
    text: 'text-slate-400',
    topbar: 'text-slate-400 bg-slate-700/50 border border-slate-600/50',
    topbarDot: 'bg-slate-400',
  },
} as const;

export type ModeKey = keyof typeof MODE_COLORS;

/** Resolve the color key from raw API mode string + is_live flag. */
export function resolveModeKey(mode: string | undefined, isLive: boolean): ModeKey {
  if (isLive) return 'live';
  const m = (mode ?? '').toLowerCase();
  if (m === 'shadow') return 'shadow';
  if (m === 'paper' || m === 'mock' || m === 'sim' || m === '') return 'paper';
  return 'unknown';
}
