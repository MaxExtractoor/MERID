/**
 * Risk Configuration Constants
 * 
 * Centralized risk tier configurations to prevent duplication and drift
 * across multiple views. This is the single source of truth for:
 * - Drawdown tier labels, colors, and icons
 * - Risk thresholds and styling
 * 
 * Used by: ProtectView, SizeView, KalshiPortfolioView
 */

import React from 'react';
import { CheckCircle, AlertTriangle, ArrowDownRight, XCircle } from '../../ui/icons';

export type DrawdownTier = 'normal' | 'warning' | 'downsize' | 'halt';

export interface DrawdownTierConfig {
  label: string;
  color: string;
  bg: string;
  icon: React.ElementType;
}

/**
 * Drawdown tier configuration - single source of truth
 * Maps tier names to their display configuration
 */
export const DRAWDOWN_TIER_CONFIG: Record<DrawdownTier, DrawdownTierConfig> = {
  normal: {
    label: 'Normal',
    color: 'text-green-400',
    bg: 'bg-green-500/20',
    icon: CheckCircle,
  },
  warning: {
    label: 'Warning',
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/20',
    icon: AlertTriangle,
  },
  downsize: {
    label: 'Downsize',
    color: 'text-orange-400',
    bg: 'bg-orange-500/20',
    icon: ArrowDownRight,
  },
  halt: {
    label: 'HALT',
    color: 'text-red-400',
    bg: 'bg-red-500/20',
    icon: XCircle,
  },
};

/**
 * Helper to get tier config safely with fallback to normal
 */
export function getDrawdownTierConfig(tier: string | undefined): DrawdownTierConfig {
  if (!tier) return DRAWDOWN_TIER_CONFIG.normal;
  return DRAWDOWN_TIER_CONFIG[tier as DrawdownTier] ?? DRAWDOWN_TIER_CONFIG.normal;
}

/**
 * Risk threshold defaults (in percentage)
 */
export const DRAWDOWN_THRESHOLDS = {
  warning: 5.0,   // 5% drawdown triggers warning
  downsize: 10.0, // 10% drawdown triggers downsize
  halt: 20.0,     // 20% drawdown triggers halt
} as const;
