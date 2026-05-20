/**
 * StatusIndicator - Unified status indicator component
 * 
 * Consolidates 5 indicator components into one configurable primitive:
 * - StatusIndicator (base)
 * - DataFreshnessIndicator (variant with timestamp)
 * - StalenessIndicator (variant with staleness logic)
 * - OfflineIndicator (variant)
 * - ConnectionStatusIndicator (variant)
 * 
 * Uses design tokens for consistent styling across all Kalshi views.
 * 
 * Tier 2: Indicator Consolidation (5 → 1)
 */

import React from 'react';
import { KALSHI_STATUS_COLORS, SIZE_TOKENS } from '../tokens';

export interface StatusIndicatorProps {
  /**
   * Status type - maps to KALSHI_STATUS_COLORS tokens
   */
  status: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  
  /**
   * Size variant - maps to SIZE_TOKENS
   */
  size?: 'xs' | 'sm' | 'md' | 'lg';
  
  /**
   * Optional label text
   */
  label?: string;
  
  /**
   * Optional icon (overrides default status icon)
   */
  icon?: React.ReactNode;
  
  /**
   * Show timestamp for data freshness indicators
   */
  showTimestamp?: boolean;
  
  /**
   * Timestamp for data freshness calculation
   */
  timestamp?: Date;
  
  /**
   * Threshold in milliseconds for staleness (default: 30s)
   */
  thresholdMs?: number;
  
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
 * Format timestamp as relative time (e.g., "2m ago", "30s ago")
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
 * Determine staleness status based on timestamp and threshold
 */
function getStalenessStatus(timestamp: Date, thresholdMs: number): 'success' | 'warning' | 'error' {
  const ageMs = Date.now() - timestamp.getTime();
  
  if (ageMs > thresholdMs * 2) {
    return 'error'; // Offline/critical
  } else if (ageMs > thresholdMs) {
    return 'warning'; // Stale
  } else {
    return 'success'; // Fresh
  }
}

/**
 * Default icons for each status type
 */
function getDefaultIcon(status: 'success' | 'warning' | 'error' | 'info' | 'neutral'): React.ReactNode {
  // Simple colored dots as default icons
  const colors = KALSHI_STATUS_COLORS[status];
  return (
    <span className="relative flex h-2 w-2">
      <span className={`absolute inline-flex h-full w-full rounded-full ${colors.bg} opacity-75 animate-ping`} />
      <span className={`relative inline-flex rounded-full h-2 w-2 ${colors.bg}`} />
    </span>
  );
}

/**
 * StatusIndicator Component
 */
export const StatusIndicator = React.memo(function StatusIndicator({
  status,
  size = 'md',
  label,
  icon,
  showTimestamp = false,
  timestamp,
  thresholdMs = 30000,
  onClick,
  className = '',
}: StatusIndicatorProps) {
  // Determine status based on staleness if timestamp is provided
  const effectiveStatus = timestamp && showTimestamp 
    ? getStalenessStatus(timestamp, thresholdMs)
    : status;
  
  const colors = KALSHI_STATUS_COLORS[effectiveStatus];
  const sizes = SIZE_TOKENS[size];
  
  // Use provided icon or default
  const displayIcon = icon ?? getDefaultIcon(effectiveStatus);
  
  // Use provided label or timestamp
  const displayLabel = label ?? (showTimestamp && timestamp ? formatRelativeTime(timestamp) : undefined);
  
  return (
    <div
      className={`flex items-center gap-2 ${colors.bg} ${colors.border} border rounded-lg px-2.5 py-1.5 ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : 'status'}
      tabIndex={onClick ? 0 : undefined}
    >
      {displayIcon}
      {displayLabel && (
        <span className={`${sizes.text} ${colors.text} font-medium`}>
          {displayLabel}
        </span>
      )}
    </div>
  );
});

/**
 * Convenience components for common use cases
 */

/**
 * DataFreshnessIndicator - Shows data freshness with timestamp
 */
export function DataFreshnessIndicator({
  lastUpdated,
  thresholdMs = 30000,
  className = '',
}: {
  lastUpdated: Date | number | null | undefined;
  thresholdMs?: number;
  className?: string;
}) {
  if (!lastUpdated) {
    return (
      <StatusIndicator
        status="neutral"
        label="--"
        size="sm"
        className={className}
      />
    );
  }

  const timestamp = typeof lastUpdated === 'number' ? new Date(lastUpdated) : lastUpdated;
  
  return (
    <StatusIndicator
      status="success"
      showTimestamp={true}
      timestamp={timestamp}
      thresholdMs={thresholdMs}
      size="sm"
      className={className}
    />
  );
}

/**
 * StalenessIndicator - Shows staleness with live/stale/critical states
 */
export function StalenessIndicator({
  lastUpdated,
  thresholdMs = 10000,
  criticalThresholdMs = 30000,
  label = 'Data',
  className = '',
}: {
  lastUpdated: Date | null;
  thresholdMs?: number;
  criticalThresholdMs?: number;
  label?: string;
  className?: string;
}) {
  if (!lastUpdated) {
    return (
      <StatusIndicator
        status="neutral"
        label={`${label}: no data`}
        size="xs"
        className={className}
      />
    );
  }

  const ageMs = Date.now() - lastUpdated.getTime();
  const ageSec = Math.floor(ageMs / 1000);

  let status: 'success' | 'warning' | 'error' = 'success';
  let displayLabel = `${label}: live`;

  if (ageMs > criticalThresholdMs) {
    status = 'error';
    displayLabel = `${label}: stale (${ageSec}s ago)`;
  } else if (ageMs > thresholdMs) {
    status = 'warning';
    displayLabel = `${label}: ${ageSec}s ago`;
  }

  return (
    <StatusIndicator
      status={status}
      label={displayLabel}
      size="xs"
      className={className}
    />
  );
}

/**
 * OfflineIndicator - Shows offline status
 */
export function OfflineIndicator({
  isOffline,
  className = '',
}: {
  isOffline: boolean;
  className?: string;
}) {
  return (
    <StatusIndicator
      status={isOffline ? 'error' : 'success'}
      label={isOffline ? 'Offline' : 'Online'}
      size="sm"
      className={className}
    />
  );
}

/**
 * ConnectionStatusIndicator - Shows connection status
 */
export function ConnectionStatusIndicator({
  connected,
  className = '',
}: {
  connected: boolean;
  className?: string;
}) {
  return (
    <StatusIndicator
      status={connected ? 'success' : 'error'}
      label={connected ? 'Connected' : 'Disconnected'}
      size="sm"
      className={className}
    />
  );
}
