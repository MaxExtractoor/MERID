/**
 * AssetBadge — per-asset identity chip (glyph + optional label).
 * Uses the asset's brand-ish accent; purely presentational.
 */

import { memo } from 'react';
import type { AssetSymbol } from '../../agents/types';
import { ASSET_META } from './agentMeta';
import { cx } from '../../agents/format';

interface AssetBadgeProps {
  asset: AssetSymbol | string | undefined;
  /** 'md' = glyph + name, 'sm' = compact glyph only, 'lg' = big orb-style. */
  size?: 'sm' | 'md' | 'lg';
  /** Show the asset ticker text next to the glyph. */
  showLabel?: boolean;
  className?: string;
}

const SIZES = {
  sm: 'w-5 h-5 text-[11px]',
  md: 'w-7 h-7 text-sm',
  lg: 'w-12 h-12 text-xl',
} as const;

export const AssetBadge = memo(function AssetBadge({
  asset,
  size = 'md',
  showLabel = false,
  className = '',
}: AssetBadgeProps) {
  const meta = asset ? ASSET_META[asset as AssetSymbol] : undefined;
  return (
    <span className={cx('inline-flex items-center gap-1.5 min-w-0', className)}>
      <span
        className={cx(
          'inline-flex items-center justify-center rounded-md border font-bold shrink-0 tabular-nums',
          SIZES[size],
          meta ? meta.chipClass : 'bg-slate-700/30 text-slate-400 border-slate-600/40',
        )}
        aria-hidden="true"
      >
        {meta ? meta.glyph : '?'}
      </span>
      {showLabel && (
        <span className="font-semibold text-slate-200 text-sm truncate">
          {asset ?? 'n/a'}
        </span>
      )}
    </span>
  );
});

export default AssetBadge;
