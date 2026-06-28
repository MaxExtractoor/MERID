/**
 * Centralized UI constants for MERID frontend
 * Consolidates duplicate color definitions and shared values
 */

// =============================================================================
// COLOR CONSTANTS
// =============================================================================

export const CATEGORY_COLORS = {
  sports: '#10b981',      // green-500
  weather: '#3b82f6',     // blue-500
  crypto: '#f59e0b',      // amber-500
  politics: '#8b5cf6',    // violet-500
  finance: '#ef4444',      // red-500
  entertainment: '#ec4899', // pink-500
  other: '#6b7280',       // gray-500
  // Session log specific categories
  gate: '#ef4444',         // red-500
  kill_switch: '#ef4444',  // red-500
  mode: '#3b82f6',        // blue-500
  reconciliation: '#f59e0b', // amber-500
  feed: '#06b6d4',         // cyan-500
  system: '#6b7280',       // gray-500
  operator: '#10b981',     // green-500
} as const;

export const KALSHI_CATEGORY_COLORS = {
  crypto: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  cross_category: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  economics: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  macro: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
  financials: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  equities: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
  politics: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  sports: 'bg-green-500/20 text-green-300 border-green-500/30',
  climate: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  tech: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  culture: 'bg-pink-500/20 text-pink-300 border-pink-500/30',
  science: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  other: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
} as const;

export const DOMAIN_COLORS = {
  flow: '#10b981',        // green-500
  prediction: '#3b82f6',  // blue-500
  trading: '#f59e0b',     // amber-500
  governance: '#8b5cf6',  // violet-500
  analytics: '#06b6d4',   // cyan-500
  monitoring: '#84cc16',  // lime-500
} as const;

export const TIER_COLORS = {
  S: '#10b981',           // green-500
  A: '#3b82f6',           // blue-500
  B: '#f59e0b',           // amber-500
  C: '#ef4444',           // red-500
  D: '#6b7280',           // gray-500
  // Ladder tier colors
  0: { bg: 'bg-slate-800/60', border: 'border-slate-600/40', text: 'text-slate-300' },
  1: { bg: 'bg-green-900/30', border: 'border-green-600/40', text: 'text-green-400' },
  2: { bg: 'bg-blue-900/30', border: 'border-blue-600/40', text: 'text-blue-400' },
  3: { bg: 'bg-purple-900/30', border: 'border-purple-600/40', text: 'text-purple-400' },
  4: { bg: 'bg-amber-900/30', border: 'border-amber-600/40', text: 'text-amber-400' },
} as const;

export const MODE_COLORS = {
  paper: '#10b981',       // green-500
  live: '#ef4444',         // red-500
  hybrid: '#f59e0b',      // amber-500
  autonomous: '#8b5cf6',  // violet-500
  disabled: '#6b7280',    // gray-500
} as const;

// =============================================================================
// TIMING CONSTANTS
// =============================================================================

export const CLOCK_TICK_MS = 1000;  // UI clock tick interval
export const DATA_FRESHNESS_WARNING_MS = 10_000;  // 10 seconds
export const DATA_FRESHNESS_CRITICAL_MS = 30_000;  // 30 seconds

// =============================================================================
// UI CONFIGURATION
// =============================================================================

export const MAX_EVENTS = 1000;  // Maximum events to display in feeds
export const DEFAULT_PAGE_SIZE = 20;
export const MAX_TABLE_ROWS = 50;

// =============================================================================
// BREAKPOINTS
// =============================================================================

export const BREAKPOINTS = {
  sm: '640px',
  md: '768px', 
  lg: '1024px',
  xl: '1280px',
  '2xl': '1536px',
} as const;

// =============================================================================
// ANIMATION DURATIONS
// =============================================================================

export const ANIMATION_DURATIONS = {
  fast: '150ms',
  normal: '300ms',
  slow: '500ms',
} as const;
