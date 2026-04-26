import { Clock, Wifi, WifiOff } from '../ui/icons';
import './DataFreshnessIndicator.css';

export interface DataFreshnessIndicatorProps {
  lastUpdated: Date | number | null | undefined;
  thresholdMs?: number;
  showIcon?: boolean;
  className?: string;
  // P0-001: Optional spot staleness metric value from backend (merid_pm_spot_age_seconds)
  spotAgeSeconds?: number | null;
  maxSpotAgeSeconds?: number; // Default 120s, override with MERID_PM_MAX_SPOT_AGE_SECONDS
}

export function DataFreshnessIndicator({
  lastUpdated,
  thresholdMs = 30000, // 30 seconds default
  showIcon = true,
  className = '',
  spotAgeSeconds,
  maxSpotAgeSeconds = 120, // P0-001: Default max_spot_age_seconds()
}: DataFreshnessIndicatorProps) {
  // P0-001: Check spot staleness from backend metric first
  const isSpotStale = spotAgeSeconds !== undefined && spotAgeSeconds !== null && spotAgeSeconds > maxSpotAgeSeconds;

  if (!lastUpdated) {
    return (
      <span className={`data-freshness data-freshness--unknown ${className}`}>
        {showIcon && <Clock size={12} className="mr-1" />}
        <span>--</span>
      </span>
    );
  }

  const now = Date.now();
  const last = typeof lastUpdated === 'number' ? lastUpdated : lastUpdated.getTime();
  const ageMs = now - last;
  const ageSeconds = Math.floor(ageMs / 1000);

  let status: 'fresh' | 'stale' | 'offline' = 'fresh';
  // P0-001: Override status if spot is stale from backend metric
  if (isSpotStale) status = 'stale';
  else if (ageMs > thresholdMs * 2) status = 'offline';
  else if (ageMs > thresholdMs) status = 'stale';

  const formatted = ageSeconds < 60
    ? `${ageSeconds}s ago`
    : ageSeconds < 3600
    ? `${Math.floor(ageSeconds / 60)}m ago`
    : `${Math.floor(ageSeconds / 3600)}h ago`;

  // P0-001: Build title with metric reference
  const titleText = isSpotStale
    ? `P0-001: Spot stale (age=${spotAgeSeconds}s > max=${maxSpotAgeSeconds}s). Metric: merid_pm_spot_age_seconds{asset="..."}`
    : `Last update: ${formatted}`;

  return (
    <span
      className={`data-freshness data-freshness--${status} ${className}`}
      title={titleText}
    >
      {showIcon && (
        status === 'offline' ? <WifiOff size={12} className="mr-1" />
        : status === 'stale' ? <Clock size={12} className="mr-1" />
        : <Wifi size={12} className="mr-1" />
      )}
      <span>{formatted}</span>
    </span>
  );
}

export function DataAgeBadge({
  timestamp,
  maxAgeMs = 60000,
}: {
  timestamp: Date | number | null | undefined;
  maxAgeMs?: number;
}) {
  if (!timestamp) return null;

  const age = Date.now() - (typeof timestamp === 'number' ? timestamp : timestamp.getTime());
  const isStale = age > maxAgeMs;

  return (
    <span
      className={`data-age-badge ${isStale ? 'data-age-badge--stale' : 'data-age-badge--fresh'}`}
      title={`Last updated: ${new Date(timestamp).toLocaleString()}`}
    >
      {isStale ? 'Stale' : 'Live'}
    </span>
  );
}
