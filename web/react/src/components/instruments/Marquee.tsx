/**
 * Marquee — CSS marquee rail for a fills/prices tape. Content is duplicated
 * and translated -50% on loop; pauses on hover; fully static under
 * prefers-reduced-motion (falls back to a scrollable rail).
 */

import { memo, useId } from 'react';
import type { ReactNode } from 'react';
import { usePrefersReducedMotion } from '../../agents/hooks';
import { cx } from '../../agents/format';

interface MarqueeProps {
  items: ReactNode[];
  /** seconds per full loop. */
  durationS?: number;
  pauseOnHover?: boolean;
  className?: string;
}

export const Marquee = memo(function Marquee({
  items,
  durationS = 30,
  pauseOnHover = true,
  className = '',
}: MarqueeProps) {
  const reduced = usePrefersReducedMotion();
  const rawId = useId();
  const animName = `marquee-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;

  if (!items.length) {
    return (
      <div className={cx('overflow-hidden text-[10px] text-slate-600 py-1', className)}>
        no tape data
      </div>
    );
  }

  if (reduced) {
    return (
      <div className={cx('overflow-x-auto whitespace-nowrap', className)}>
        <div className="inline-flex items-center gap-4 py-1">
          {items.map((it, i) => (
            <span key={i} className="inline-flex items-center">{it}</span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={cx('overflow-hidden whitespace-nowrap', className)} role="marquee" aria-live="off">
      <style>{`
        @keyframes ${animName} { from { transform: translateX(0) } to { transform: translateX(-50%) } }
        .${animName}-track { display: inline-flex; animation: ${animName} ${durationS}s linear infinite; will-change: transform; }
        ${pauseOnHover ? `.${animName}-wrap:hover .${animName}-track { animation-play-state: paused; }` : ''}
      `}</style>
      <div className={`${animName}-wrap`}>
        <div className={`${animName}-track`}>
          {[0, 1].map((dup) => (
            <span key={dup} className="inline-flex items-center gap-4 pr-4" aria-hidden={dup === 1}>
              {items.map((it, i) => (
                <span key={i} className="inline-flex items-center">{it}</span>
              ))}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
});

export default Marquee;
