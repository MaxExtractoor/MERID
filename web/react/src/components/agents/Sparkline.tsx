/**
 * Sparkline — dependency-free SVG micro-chart. Renders a polyline + soft
 * area fill. With `threshold`, the last value decides pass/fail coloring and
 * a dashed threshold guide is drawn. Empty/missing data -> explicit 'n/a'.
 */

import { memo, useId, useMemo } from 'react';
import { clamp } from '../../agents/format';

interface SparklineProps {
  data?: number[] | null;
  width?: number;
  height?: number;
  /** Horizontal guide line; last-point color reflects pass/fail vs it. */
  threshold?: number;
  /** Fixed stroke color override (takes precedence over threshold coloring). */
  color?: string;
  className?: string;
}

export const Sparkline = memo(function Sparkline({
  data,
  width = 96,
  height = 28,
  threshold,
  color,
  className = '',
}: SparklineProps) {
  const gid = useId();

  const geom = useMemo(() => {
    const pts = (data ?? []).filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
    if (pts.length < 2) return null;
    let lo = Math.min(...pts);
    let hi = Math.max(...pts);
    if (threshold != null) {
      lo = Math.min(lo, threshold);
      hi = Math.max(hi, threshold);
    }
    const span = hi - lo || Math.abs(hi) || 1;
    const pad = span * 0.08;
    lo -= pad;
    hi += pad;
    const stepX = width / (pts.length - 1);
    const y = (v: number) => height - ((v - lo) / (hi - lo)) * height;
    const line = pts.map((v, i) => `${(i * stepX).toFixed(2)},${y(v).toFixed(2)}`).join(' ');
    const area = `0,${height} ${line} ${width},${height}`;
    return {
      line,
      area,
      threshY: threshold != null ? y(threshold) : undefined,
      last: pts[pts.length - 1],
      lastY: y(pts[pts.length - 1]),
    };
  }, [data, width, height, threshold]);

  if (!geom) {
    return (
      <div
        className={`flex items-center justify-center text-[9px] text-slate-600 ${className}`}
        style={{ width, height }}
        role="img"
        aria-label="no series data"
      >
        n/a
      </div>
    );
  }

  const stroke = color
    ?? (threshold != null ? (geom.last >= threshold ? '#10b981' : '#ef4444')
    : (geom.last >= 0 ? '#10b981' : '#ef4444'));

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label={`sparkline, last value ${geom.last}`}
    >
      <defs>
        <linearGradient id={`sg-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={geom.area} fill={`url(#sg-${gid})`} />
      {geom.threshY != null && (
        <line
          x1="0" x2={width} y1={geom.threshY} y2={geom.threshY}
          stroke="#f59e0b" strokeWidth="1" strokeDasharray="3 2" opacity="0.7"
        />
      )}
      <polyline
        points={geom.line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={width} cy={clamp(geom.lastY, 1.5, height - 1.5)} r="1.8" fill={stroke} />
    </svg>
  );
});

export default Sparkline;
