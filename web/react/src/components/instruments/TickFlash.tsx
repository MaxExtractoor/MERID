/**
 * TickFlash — numeric cell that flashes green/red when its value ticks
 * up/down (uses the index.css .flash-green/.flash-red keyframes; both are
 * gated by the component's reduced-motion check). Optional smooth digit
 * morphing via @number-flow/react.
 */

import { memo, useMemo } from 'react';
import NumberFlow from '@number-flow/react';
import { useFlashOnChange, usePrefersReducedMotion } from '../../agents/hooks';
import { cx, numOr } from '../../agents/format';

interface TickFlashProps {
  /** Raw numeric value. Undefined/null -> 'n/a', no flash. */
  value?: number | null;
  /** Custom formatter; default toLocaleString with up to 2 decimals. */
  format?: (v: number) => string;
  /** Digit animation via NumberFlow (auto-disabled on reduced motion). */
  animateDigits?: boolean;
  /** Extra formatting passed to NumberFlow (Intl.NumberFormat options). */
  flowFormat?: Intl.NumberFormatOptions;
  className?: string;
}

export const TickFlash = memo(function TickFlash({
  value,
  format,
  animateDigits = false,
  flowFormat,
  className = '',
}: TickFlashProps) {
  const n = numOr(value);
  const flash = useFlashOnChange(n);
  const reduced = usePrefersReducedMotion();

  const text = useMemo(() => {
    if (n == null) return 'n/a';
    if (format) return format(n);
    return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }, [n, format]);

  const inner = animateDigits && !reduced && n != null
    ? <NumberFlow value={n} format={flowFormat ?? { maximumFractionDigits: 2 }} />
    : text;

  return (
    <span
      key={flash ?? 'static'}
      className={cx(
        'tabular-nums inline-block rounded px-0.5 -mx-0.5',
        flash === 'up' && 'flash-green',
        flash === 'down' && 'flash-red',
        className,
      )}
      aria-live="off"
      title={n == null ? 'no data' : undefined}
    >
      {inner}
    </span>
  );
});

export default TickFlash;
