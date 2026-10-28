/**
 * CountdownRing — SVG progress ring for time remaining in a window
 * (default the 900s 15m window). Uses useLiveCountdown so the display keeps
 * ticking between server polls. Missing secs -> '--:--' + gray ring.
 */

import { memo } from 'react';
import { useLiveCountdown } from '../../agents/hooks';
import { fmtMMSS } from '../../agents/format';

interface CountdownRingProps {
  /** Seconds remaining (server-provided; resynced each change). */
  secs?: number;
  /** Window length in seconds. Default 900 (the 15m window). */
  total?: number;
  size?: number;
  strokeWidth?: number;
  showLabel?: boolean;
  className?: string;
}

export const CountdownRing = memo(function CountdownRing({
  secs,
  total = 900,
  size = 44,
  strokeWidth = 4,
  showLabel = true,
  className = '',
}: CountdownRingProps) {
  const remaining = useLiveCountdown(secs);
  const r = (size - strokeWidth) / 2;
  const circ = 2 * Math.PI * r;
  const frac = remaining != null && total > 0 ? Math.max(0, Math.min(1, remaining / total)) : 0;
  const urgent = remaining != null && remaining < 60;
  const color = remaining == null ? '#475569' : urgent ? '#ef4444' : remaining < 300 ? '#f59e0b' : '#10b981';

  return (
    <span className={`inline-flex flex-col items-center gap-0.5 ${className}`}
      title={remaining != null ? `${Math.round(remaining)}s to window close` : 'window time unknown'}>
      <svg width={size} height={size} role="img" aria-label={remaining != null ? `window closes in ${fmtMMSS(remaining)}` : 'window countdown n/a'}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1e293b" strokeWidth={strokeWidth} />
        {remaining != null && (
          <circle
            cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={color} strokeWidth={strokeWidth} strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - frac)}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            className="transition-[stroke-dashoffset] duration-1000 ease-linear motion-reduce:transition-none"
          />
        )}
        <text x="50%" y="50%" dy="0.35em" textAnchor="middle"
          fontSize={size * 0.24} fill={remaining == null ? '#475569' : color}
          className="tabular-nums" fontWeight="600">
          {remaining != null ? fmtMMSS(remaining) : '--:--'}
        </text>
      </svg>
      {showLabel && <span className="text-[9px] uppercase tracking-wider text-slate-600">window</span>}
    </span>
  );
});

export default CountdownRing;
