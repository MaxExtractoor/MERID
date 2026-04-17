import { useState, useEffect } from 'react';

const CLOCK_TICK_MS = 1000; // UI clock tick — updates age badge every second

interface DataAgeBadgeProps {
  lastUpdated: Date | null;
  /** Threshold in ms before showing warning color (default 10s) */
  warningMs?: number;
  /** Threshold in ms before showing critical color (default 30s) */
  criticalMs?: number;
  className?: string;
}

/**
 * Inline badge showing how old the most recent data fetch is.
 * Updates every second. Turns amber > red as data ages.
 */
export function DataAgeBadge({
  lastUpdated,
  warningMs = 10_000,
  criticalMs = 30_000,
  className = '',
}: DataAgeBadgeProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(id);
  }, []);

  if (!lastUpdated) {
    return (
      <span className={`text-[10px] text-slate-500 ${className}`}>
        no data
      </span>
    );
  }

  const ageMs = now - lastUpdated.getTime();
  const ageSec = Math.round(ageMs / 1000);

  let color = 'text-slate-500';
  if (ageMs >= criticalMs) color = 'text-red-400';
  else if (ageMs >= warningMs) color = 'text-amber-400';

  const label = ageSec < 60 ? `${ageSec}s ago` : `${Math.round(ageSec / 60)}m ago`;

  return (
    <span className={`text-[10px] font-mono ${color} ${className}`}>
      {label}
    </span>
  );
}

export default DataAgeBadge;
