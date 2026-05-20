/**
 * Badge - Unified badge component
 * 
 * Consolidates 9 badge components into 2 configurable primitives:
 * - Badge (generic badge component)
 * - DataBadge (specialized for Kalshi data-related badges)
 * 
 * Uses design tokens for consistent styling across all Kalshi views.
 * 
 * Tier 2: Badge Consolidation (9 → 2)
 */

import React from 'react';
import { KALSHI_STATUS_COLORS, SIZE_TOKENS } from '../tokens';

/**
 * Badge API - Generic badge component
 */
export interface BadgeProps {
  /**
   * Status variant - maps to KALSHI_STATUS_COLORS tokens
   */
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  
  /**
   * Size variant - maps to SIZE_TOKENS
   */
  size?: 'xs' | 'sm' | 'md';
  
  /**
   * Badge content
   */
  children: React.ReactNode;
  
  /**
   * Optional click handler
   */
  onClick?: () => void;
  
  /**
   * Additional CSS classes
   */
  className?: string;
}

/**
 * Badge Component - Generic badge for status indicators
 */
export const Badge = React.memo(function Badge({
  variant = 'neutral',
  size = 'sm',
  children,
  onClick,
  className = '',
}: BadgeProps) {
  const colors = KALSHI_STATUS_COLORS[variant];
  const sizes = SIZE_TOKENS[size];
  
  return (
    <span
      className={`
        inline-flex items-center font-medium rounded-full
        ${colors.bg} ${colors.border} border
        ${sizes.padding} ${sizes.text}
        ${onClick ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}
        ${className}
      `}
      onClick={onClick}
      role={onClick ? 'button' : 'status'}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </span>
  );
});

/**
 * DataBadge API - Specialized for Kalshi data-related badges
 */
export interface DataBadgeProps {
  /**
   * Badge type
   */
  type: 'age' | 'source' | 'reconciliation' | 'kalshi-status';
  
  /**
   * Badge value
   */
  value: string | number;
  
  /**
   * Optional timestamp for age calculation
   */
  timestamp?: Date;
  
  /**
   * Optional data source
   */
  source?: string;
  
  /**
   * Size variant
   */
  size?: 'xs' | 'sm' | 'md';
  
  /**
   * Optional click handler
   */
  onClick?: () => void;
  
  /**
   * Additional CSS classes
   */
  className?: string;
}

/**
 * Format timestamp as relative time
 */
function formatRelativeTime(timestamp: Date): string {
  const now = Date.now();
  const ageMs = now - timestamp.getTime();
  const ageSeconds = Math.floor(ageMs / 1000);
  
  if (ageSeconds < 60) {
    return `${ageSeconds}s ago`;
  } else if (ageSeconds < 3600) {
    return `${Math.floor(ageSeconds / 60)}m ago`;
  } else {
    return `${Math.floor(ageSeconds / 3600)}h ago`;
  }
}

/**
 * Determine status based on data type and value
 */
function getDataBadgeStatus(type: DataBadgeProps['type'], value: string | number): 'success' | 'warning' | 'error' | 'info' | 'neutral' {
  switch (type) {
    case 'age':
      if (typeof value === 'string' && value.includes('s')) return 'success';
      if (typeof value === 'string' && value.includes('m')) return 'warning';
      if (typeof value === 'string' && value.includes('h')) return 'error';
      return 'neutral';
    
    case 'source':
      return 'info';
    
    case 'reconciliation':
      if (value === 'reconciled') return 'success';
      if (value === 'pending') return 'warning';
      if (value === 'failed') return 'error';
      return 'neutral';
    
    case 'kalshi-status':
      if (value === 'healthy' || value === 'active') return 'success';
      if (value === 'degraded') return 'warning';
      if (value === 'unhealthy' || value === 'inactive') return 'error';
      return 'neutral';
    
    default:
      return 'neutral';
  }
}

/**
 * DataBadge Component - Specialized for Kalshi data labeling
 */
export const DataBadge = React.memo(function DataBadge({
  type,
  value,
  timestamp,
  source,
  size = 'sm',
  onClick,
  className = '',
}: DataBadgeProps) {
  let displayValue: string | number = value;
  
  // Format timestamp for age badges
  if (type === 'age' && timestamp) {
    displayValue = formatRelativeTime(timestamp);
  }
  
  // Add source to value for source badges
  if (type === 'source' && source) {
    displayValue = `${source}`;
  }
  
  const status = getDataBadgeStatus(type, displayValue);
  
  return (
    <Badge
      variant={status}
      size={size}
      onClick={onClick}
      className={className}
    >
      {displayValue}
    </Badge>
  );
});
