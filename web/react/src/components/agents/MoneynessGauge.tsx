/**
 * MoneynessGauge — 0–100¢ entry-price landscape for one asset.
 *
 * Renders the audited MONEYNESS_BANDS contract truthfully:
 *   green  = allowed NO-side band (1c .. noMaxC)
 *   red    = blocked regions (noBlockedPocket + above noMaxC)
 *   indigo = pinned-fav maker zone (>= pinnedFavFloorC, favorites lane)
 * The live contract price is a marker on the track. All regions carry
 * title tooltips describing the underlying band rule.
 */

import { memo, useMemo } from 'react';
import type { AssetSymbol } from '../../agents/types';
import { MONEYNESS_BANDS } from '../../agents/types';
import { clamp, cx, fmtCents, numOr } from '../../agents/format';

interface Zone {
  lo: number;
  hi: number;
  color: string;
  label: string;
}

interface MoneynessGaugeProps {
  asset: AssetSymbol;
  /** Live own-side price in cents (YES mid or held-side price). */
  priceC?: number;
  /** Side context for the marker tooltip. */
  side?: 'yes' | 'no';
  compact?: boolean;
  className?: string;
}

export const MoneynessGauge = memo(function MoneynessGauge({
  asset,
  priceC,
  side,
  compact = false,
  className = '',
}: MoneynessGaugeProps) {
  const band = MONEYNESS_BANDS[asset];

  const zones = useMemo<Zone[]>(() => {
    const z: Zone[] = [];
    const pocket = band.noBlockedPocket;
    // Allowed NO band = (0, noMaxC] minus the blocked pocket.
    const allowedSegments: Array<[number, number]> = pocket
      ? [[0, Math.min(pocket[0], band.noMaxC)], [Math.min(pocket[1], band.noMaxC), band.noMaxC]]
      : [[0, band.noMaxC]];
    for (const [lo, hi] of allowedSegments) {
      if (hi - lo > 0.4) {
        z.push({ lo, hi, color: 'rgba(16,185,129,0.35)', label: `NO allowed ${lo}-${hi}c` });
      }
    }
    if (pocket) {
      z.push({ lo: pocket[0], hi: pocket[1], color: 'rgba(239,68,68,0.4)', label: `NO blocked pocket ${pocket[0]}-${pocket[1]}c` });
    }
    if (band.noMaxC < 100) {
      z.push({ lo: band.noMaxC, hi: 100, color: 'rgba(239,68,68,0.22)', label: `NO blocked >${band.noMaxC}c` });
    }
    // Pinned-fav maker zone overlay (favorites lane, YES>=floor).
    z.push({ lo: band.pinnedFavFloorC, hi: 100, color: 'rgba(59,130,246,0.35)', label: `pinned-fav maker zone >=${band.pinnedFavFloorC}c` });
    return z;
  }, [band]);

  const price = numOr(priceC);
  const markerPct = price != null ? clamp(price, 0, 100) : null;
  const pinnedZone = zones[zones.length - 1]; // last = pinned overlay

  return (
    <div className={cx('w-full', className)}>
      <div
        className="relative w-full rounded border border-slate-700/60 bg-slate-900/80 overflow-visible"
        style={{ height: compact ? 10 : 14 }}
        role="img"
        aria-label={`${asset} moneyness bands: NO cap ${band.noMaxC}c${band.noBlockedPocket ? `, blocked pocket ${band.noBlockedPocket[0]}-${band.noBlockedPocket[1]}c` : ''}, pinned-fav >=${band.pinnedFavFloorC}c${price != null ? `, price ${price}c` : ''}`}
      >
        {/* base zones */}
        {zones.slice(0, -1).map((z) => (
          <div
            key={z.label}
            className="absolute top-0 bottom-0 first:rounded-l last:rounded-r"
            style={{ left: `${z.lo}%`, width: `${Math.max(0, z.hi - z.lo)}%`, backgroundColor: z.color }}
            title={z.label}
          />
        ))}
        {/* pinned-fav maker strip (top half overlay) */}
        {pinnedZone && (
          <div
            className="absolute top-0 rounded-r"
            style={{
              left: `${pinnedZone.lo}%`,
              width: `${100 - pinnedZone.lo}%`,
              height: '45%',
              backgroundColor: pinnedZone.color,
              borderBottom: '1px solid rgba(59,130,246,0.7)',
            }}
            title={pinnedZone.label}
          />
        )}
        {/* tick marks at band edges */}
        {[band.noMaxC, ...(band.noBlockedPocket ?? []), band.pinnedFavFloorC].map((x) => (
          <div
            key={`tick-${x}`}
            className="absolute top-0 bottom-0 w-px bg-slate-500/70"
            style={{ left: `${clamp(x, 0, 100)}%` }}
            aria-hidden="true"
          />
        ))}
        {/* live price marker */}
        {markerPct != null && (
          <div
            className="absolute"
            style={{ left: `${markerPct}%`, top: -3, bottom: -3 }}
            title={`live price ${price}c${side ? ` (${side.toUpperCase()} side)` : ''}`}
          >
            <div className="w-0.5 h-full bg-white rounded shadow-[0_0_6px_rgba(255,255,255,0.8)]" />
          </div>
        )}
        {markerPct == null && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[8px] text-slate-600">price n/a</span>
          </div>
        )}
      </div>
      {!compact && (
        <div className="flex items-center justify-between mt-1 text-[9px] text-slate-500 tabular-nums">
          <span className="text-emerald-400/80">NO&le;{band.noMaxC}c</span>
          {band.noBlockedPocket && (
            <span className="text-red-400/80">{band.noBlockedPocket[0]}-{band.noBlockedPocket[1]}c blocked</span>
          )}
          <span className="text-blue-400/80">pin-fav &ge;{band.pinnedFavFloorC}c</span>
        </div>
      )}
      {compact && price != null && (
        <div className="sr-only">price {fmtCents(price)}</div>
      )}
    </div>
  );
});

export default MoneynessGauge;
