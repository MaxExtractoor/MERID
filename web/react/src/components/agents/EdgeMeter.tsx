/**
 * EdgeMeter — bidirectional bar of net_ev_c vs the entry threshold_c.
 * Zero baseline in the middle, amber threshold tick on the positive side.
 * Missing value or threshold -> explicit 'n/a' state, never a fake zero.
 */

import { memo, useMemo } from 'react';
import { clamp, fmtSignedCents, numOr } from '../../agents/format';

interface EdgeMeterProps {
  valueC?: number;
  thresholdC?: number;
  /** Full-width value. */
  width?: number;
  height?: number;
  className?: string;
}

export const EdgeMeter = memo(function EdgeMeter({
  valueC,
  thresholdC,
  width = 120,
  height = 8,
  className = '',
}: EdgeMeterProps) {
  const geom = useMemo(() => {
    const v = numOr(valueC);
    const t = numOr(thresholdC);
    if (v == null && t == null) return null;
    const max = Math.max(Math.abs(v ?? 0), Math.abs(t ?? 0) * 1.4, 0.5);
    const zeroX = width / 2;
    const scale = (width / 2 - 2) / max;
    const valueX = v == null ? null : zeroX + clamp(v, -max, max) * scale;
    const threshX = t == null ? null : zeroX + clamp(t, -max, max) * scale;
    return { v, t, valueX, threshX, zeroX };
  }, [valueC, thresholdC, width]);

  const v = geom?.v;
  const passing = v != null && geom?.t != null && v >= geom.t;
  const valueCls = v == null ? 'text-slate-600' : passing ? 'text-emerald-400' : v < 0 ? 'text-red-400' : 'text-slate-300';

  return (
    <div className={`inline-flex items-center gap-1.5 ${className}`} title={
      geom?.v != null
        ? `net edge ${fmtSignedCents(geom.v)} vs threshold ${fmtSignedCents(geom.t)}`
        : 'edge data unavailable'
    }>
      <svg width={width} height={height + 6} className="overflow-visible" role="img"
        aria-label={geom?.v != null ? `net edge ${geom.v} cents, threshold ${geom.t ?? 'n/a'} cents` : 'edge n/a'}>
        {/* track */}
        <rect x="0" y="3" width={width} height={height} rx="2" fill="#1e293b" />
        {geom ? (
          <>
            {/* zero baseline */}
            <line x1={geom.zeroX} x2={geom.zeroX} y1="1" y2={height + 5} stroke="#475569" strokeWidth="1" />
            {/* value bar */}
            {geom.valueX != null && (
              <rect
                x={Math.min(geom.zeroX, geom.valueX)}
                y="4"
                width={Math.max(1.5, Math.abs(geom.valueX - geom.zeroX))}
                height={height - 2}
                rx="1.5"
                fill={(v ?? 0) >= 0 ? (passing ? '#10b981' : '#34d399') : '#ef4444'}
                opacity={passing ? 1 : 0.75}
              />
            )}
            {/* threshold tick */}
            {geom.threshX != null && (
              <line x1={geom.threshX} x2={geom.threshX} y1="0" y2={height + 6}
                stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="2 1.5" />
            )}
          </>
        ) : (
          <text x={width / 2} y={height + 2} textAnchor="middle" fontSize="7" fill="#64748b">n/a</text>
        )}
      </svg>
      <span className={`tabular-nums text-[10px] font-medium ${valueCls}`}>
        {v != null ? fmtSignedCents(v) : 'n/a'}
      </span>
    </div>
  );
});

export default EdgeMeter;
