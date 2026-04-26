/**
 * Staleness Indicator
 *
 * Shows a visual warning when dashboard data is older than a threshold.
 * Per Deephaven guidance: visible staleness indicator if data > N seconds old.
 * Default threshold: 10 seconds for critical data, 30 seconds for non-critical.
 */

import { useState, useEffect } from 'react';
import { Wifi, WifiOff, Clock } from '../ui/icons';
import { DEFAULTS } from "../config/constants";

interface StalenessIndicatorProps {
  lastUpdated: Date | null;
  thresholdMs?: number;
  criticalThresholdMs?: number;
  label?: string;
  className?: string;
}

export function StalenessIndicator({
  lastUpdated,
  thresholdMs = 10000,
  criticalThresholdMs = 30000,
  label = 'Data',
  className = '',
}: StalenessIndicatorProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), DEFAULTS.POLLING_INTERVALS.STALENESS);
    return () => clearInterval(id);
  }, []);

  if (!lastUpdated) {
    return (
      <div className={`flex items-center gap-1.5 text-[10px] text-slate-600 ${className}`}>
        <WifiOff className="w-3 h-3" />
        <span>{label}: no data</span>
      </div>
    );
  }

  const ageMs = now - lastUpdated.getTime();
  const ageSec = Math.floor(ageMs / 1000);

  const isCritical = ageMs > criticalThresholdMs;
  const isStale = ageMs > thresholdMs;

  if (isCritical) {
    return (
      <div className={`flex items-center gap-1.5 text-[10px] ${className}`}>
        <WifiOff className="w-3 h-3 text-red-400 animate-pulse" />
        <span className="text-red-400 font-semibold">
          {label}: stale ({ageSec}s ago)
        </span>
      </div>
    );
  }

  if (isStale) {
    return (
      <div className={`flex items-center gap-1.5 text-[10px] ${className}`}>
        <Clock className="w-3 h-3 text-amber-400" />
        <span className="text-amber-400">
          {label}: {ageSec}s ago
        </span>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-1.5 text-[10px] ${className}`}>
      <Wifi className="w-3 h-3 text-emerald-400" />
      <span className="text-slate-500">
        {label}: live
      </span>
    </div>
  );
}
