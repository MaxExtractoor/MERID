/**
 * Design Tokens - Kalshi Design System
 * 
 * Centralized design tokens for consistent UI across all Kalshi views.
 * These tokens map to the component API contracts defined in the UI redesign plan.
 * 
 * Usage:
 * import { KALSHI_STATUS_COLORS, SPACING, TYPOGRAPHY } from './ui/tokens';
 * 
 * Tier 2: Design Tokens Implementation
 */

/**
 * Color Tokens - Kalshi States
 * Maps to StatusIndicator, Badge, DataPanel, and AlertPanel variants
 */
export const KALSHI_STATUS_COLORS = {
  success: { 
    bg: 'bg-emerald-950/30', 
    border: 'border-emerald-500/30', 
    text: 'text-emerald-400' 
  },
  warning: { 
    bg: 'bg-amber-950/30', 
    border: 'border-amber-500/30', 
    text: 'text-amber-400' 
  },
  error: { 
    bg: 'bg-red-950/40', 
    border: 'border-red-500/40', 
    text: 'text-red-400' 
  },
  info: { 
    bg: 'bg-blue-950/30', 
    border: 'border-blue-500/30', 
    text: 'text-blue-400' 
  },
  neutral: { 
    bg: 'bg-slate-800/70', 
    border: 'border-slate-700/40', 
    text: 'text-slate-300' 
  },
} as const;

export type KalshiStatusColor = keyof typeof KALSHI_STATUS_COLORS;

/**
 * Spacing Tokens
 * Maps to component padding, margins, and gaps
 */
export const SPACING = {
  xs: '0.25rem',  // 4px
  sm: '0.5rem',   // 8px
  md: '1rem',     // 16px
  lg: '1.5rem',   // 24px
  xl: '2rem',     // 32px
  '2xl': '3rem',  // 48px
} as const;

export type SpacingToken = keyof typeof SPACING;

/**
 * Typography Tokens
 * Maps to StatusIndicator labels, Badge text, and panel headings
 */
export const TYPOGRAPHY = {
  'label-xs': 'text-[10px] uppercase text-slate-500',
  'label-sm': 'text-xs text-slate-400',
  'value-md': 'text-sm font-semibold text-slate-200',
  'value-lg': 'text-lg font-bold text-slate-100',
  'heading-md': 'text-base font-semibold text-slate-100',
  'heading-lg': 'text-xl font-bold text-slate-100',
} as const;

export type TypographyToken = keyof typeof TYPOGRAPHY;

/**
 * Chart Color Schemes
 * Maps to TimeSeriesChart colorScheme prop
 */
export const CHART_COLOR_SCHEMES = {
  'kalshi-blue': {
    primary: '#3b82f6',
    secondary: '#60a5fa',
    gradient: ['rgba(59, 130, 246, 0.8)', 'rgba(59, 130, 246, 0.2)'],
  },
  'kalshi-green': {
    primary: '#10b981',
    secondary: '#34d399',
    gradient: ['rgba(16, 185, 129, 0.8)', 'rgba(16, 185, 129, 0.2)'],
  },
  'kalshi-orange': {
    primary: '#f59e0b',
    secondary: '#fbbf24',
    gradient: ['rgba(245, 158, 11, 0.8)', 'rgba(245, 158, 11, 0.2)'],
  },
} as const;

export type ChartColorScheme = keyof typeof CHART_COLOR_SCHEMES;

/**
 * Size Tokens
 * Maps to StatusIndicator and Badge size props
 */
export const SIZE_TOKENS = {
  xs: { icon: 'w-3 h-3', text: 'text-[10px]', padding: 'px-1.5 py-0.5' },
  sm: { icon: 'w-4 h-4', text: 'text-xs', padding: 'px-2 py-1' },
  md: { icon: 'w-5 h-5', text: 'text-sm', padding: 'px-2.5 py-1.5' },
  lg: { icon: 'w-6 h-6', text: 'text-base', padding: 'px-3 py-2' },
} as const;

export type SizeToken = keyof typeof SIZE_TOKENS;
