/**
 * agentMeta.ts — shared visual metadata for agent states, lanes, feed kinds
 * and asset identities. Pure constants — no components live here so the file
 * can be imported by any part of the agent surface.
 *
 * Canonical status palette (design contract):
 *   WORKING_ORDER = blue, IN_POSITION = emerald, VETOED = amber,
 *   STALE_FEED = orange, HALTED = red, SCANNING = slate
 */

import type { AgentState, AssetSymbol, DecisionEventKind, LaneStatus } from '../../agents/types';

/* ------------------------------------------------------------------ */
/* Agent states                                                        */
/* ------------------------------------------------------------------ */

export interface StateMeta {
  label: string;
  /** Tailwind text color for the pill/dot. */
  text: string;
  /** Pill classes (bg + border + text). */
  pill: string;
  /** Raw hex for SVG consumers (rings, orbs). */
  hex: string;
  /** Pulse the state indicator — live operational states only. */
  pulse: boolean;
}

export const STATE_META: Record<AgentState, StateMeta> = {
  WORKING_ORDER: {
    label: 'WORKING', text: 'text-blue-400', hex: '#3b82f6',
    pill: 'bg-blue-500/15 text-blue-300 border-blue-500/40', pulse: true,
  },
  IN_POSITION: {
    label: 'IN POS', text: 'text-emerald-400', hex: '#10b981',
    pill: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40', pulse: true,
  },
  VETOED: {
    label: 'VETOED', text: 'text-amber-400', hex: '#f59e0b',
    pill: 'bg-amber-500/15 text-amber-300 border-amber-500/40', pulse: false,
  },
  STALE_FEED: {
    label: 'STALE', text: 'text-orange-400', hex: '#fb923c',
    pill: 'bg-orange-500/15 text-orange-300 border-orange-500/40', pulse: false,
  },
  HALTED: {
    label: 'HALTED', text: 'text-red-400', hex: '#ef4444',
    pill: 'bg-red-500/15 text-red-300 border-red-500/40', pulse: false,
  },
  SCANNING: {
    label: 'SCANNING', text: 'text-slate-400', hex: '#94a3b8',
    pill: 'bg-slate-500/15 text-slate-300 border-slate-500/40', pulse: false,
  },
};

/* ------------------------------------------------------------------ */
/* Lane statuses                                                       */
/* ------------------------------------------------------------------ */

export interface LaneMeta {
  text: string;
  hex: string;
  cell: string;
}

export const LANE_META: Record<LaneStatus, LaneMeta> = {
  active: {
    text: 'text-emerald-300', hex: '#10b981',
    cell: 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.35)]',
  },
  resting: {
    text: 'text-blue-300', hex: '#3b82f6',
    cell: 'bg-blue-500/15 border-blue-500/40 text-blue-300',
  },
  flat: {
    text: 'text-slate-300', hex: '#94a3b8',
    cell: 'bg-slate-600/15 border-slate-600/40 text-slate-300',
  },
  blocked: {
    text: 'text-amber-300', hex: '#f59e0b',
    cell: 'bg-amber-500/15 border-amber-500/40 text-amber-300',
  },
  suspended: {
    text: 'text-red-300', hex: '#ef4444',
    cell: 'bg-red-500/15 border-red-500/40 text-red-300',
  },
  unknown: {
    text: 'text-slate-500', hex: '#64748b',
    cell: 'bg-slate-700/10 border-slate-700/40 text-slate-500 border-dashed',
  },
};

/* ------------------------------------------------------------------ */
/* Decision-feed kinds                                                 */
/* ------------------------------------------------------------------ */

export interface KindMeta {
  label: string;
  text: string;
  chip: string;
}

export const KIND_META: Record<DecisionEventKind, KindMeta> = {
  enter: { label: 'ENTER', text: 'text-emerald-400', chip: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  veto: { label: 'VETO', text: 'text-red-400', chip: 'bg-red-500/15 text-red-300 border-red-500/40' },
  skip: { label: 'SKIP', text: 'text-slate-400', chip: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
  order: { label: 'ORDER', text: 'text-cyan-400', chip: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40' },
  fill: { label: 'FILL', text: 'text-blue-400', chip: 'bg-blue-500/15 text-blue-300 border-blue-500/40' },
  guard: { label: 'GUARD', text: 'text-amber-400', chip: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  exit: { label: 'EXIT', text: 'text-orange-400', chip: 'bg-orange-500/15 text-orange-300 border-orange-500/40' },
  settle: { label: 'SETTLE', text: 'text-emerald-300', chip: 'bg-emerald-500/10 text-emerald-300 border-emerald-600/40' },
};

/* ------------------------------------------------------------------ */
/* Asset identities                                                    */
/* ------------------------------------------------------------------ */

export interface AssetMeta {
  glyph: string;
  /** Accent hex — loosely the asset's brand color. */
  hex: string;
  chipClass: string;
}

export const ASSET_META: Record<AssetSymbol, AssetMeta> = {
  BTC: { glyph: '₿', hex: '#f7931a', chipClass: 'bg-[#f7931a]/15 text-[#f7931a] border-[#f7931a]/40' },
  ETH: { glyph: 'Ξ', hex: '#627eea', chipClass: 'bg-[#627eea]/15 text-[#8ba1f0] border-[#627eea]/40' },
  SOL: { glyph: '◎', hex: '#14f195', chipClass: 'bg-[#14f195]/15 text-[#14f195] border-[#14f195]/40' },
  XRP: { glyph: '✕', hex: '#cbd5e1', chipClass: 'bg-slate-400/15 text-slate-300 border-slate-400/40' },
  DOGE: { glyph: 'Ð', hex: '#c2a633', chipClass: 'bg-[#c2a633]/15 text-[#d8bc48] border-[#c2a633]/40' },
};

/* ------------------------------------------------------------------ */
/* Veto reason -> chip mapping                                         */
/* ------------------------------------------------------------------ */

export type VetoTone = 'danger' | 'warning' | 'info' | 'neutral';

/**
 * Classify a raw veto/guard reason code into a display tone. The raw text is
 * always preserved for the label — this only drives color.
 */
export function vetoTone(reason: string | undefined | null): VetoTone {
  const r = (reason ?? '').toLowerCase();
  if (!r) return 'neutral';
  if (/moneyness|band|pocket|price_cap|cap/.test(r)) return 'danger';
  if (/tail|lcb|calibrat/.test(r)) return 'danger';
  if (/shard|collateral|balance|fund|insufficient/.test(r)) return 'danger';
  if (/halt|kill|circuit|breaker|guard|blocked|forbidden/.test(r)) return 'danger';
  if (/ev|edge|expect|threshold/.test(r)) return 'warning';
  if (/slot|exposure|limit|size|qty/.test(r)) return 'warning';
  if (/stale|fresh|age|watermark|feed|book/.test(r)) return 'info';
  if (/final|window|close|expiry|settle/.test(r)) return 'info';
  return 'neutral';
}

export const VETO_TONE_CLASSES: Record<VetoTone, string> = {
  danger: 'bg-red-500/15 text-red-300 border-red-500/40',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  info: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40',
  neutral: 'bg-slate-600/15 text-slate-300 border-slate-600/40',
};

/** Freshness (eval/book/watermark age) -> color classes. */
export function freshnessTextClass(cls: 'live' | 'stale' | 'dead'): string {
  if (cls === 'live') return 'text-emerald-400';
  if (cls === 'stale') return 'text-amber-400';
  return 'text-red-400';
}
