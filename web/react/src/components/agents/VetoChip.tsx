/**
 * VetoChip — compact reason chip for vetoes/guards. Tone is classified from
 * the reason code (moneyness/tail/shard -> danger, EV/slots -> warning,
 * freshness/window -> info); the raw reason text is preserved verbatim.
 */

import { memo } from 'react';
import { VETO_TONE_CLASSES, vetoTone } from './agentMeta';
import { cx, reasonLabel } from '../../agents/format';

interface VetoChipProps {
  reason?: string | null;
  counterfactual?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

export const VetoChip = memo(function VetoChip({
  reason,
  counterfactual = false,
  size = 'sm',
  className = '',
}: VetoChipProps) {
  const tone = vetoTone(reason);
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded border font-medium max-w-full truncate',
        size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs',
        VETO_TONE_CLASSES[tone],
        counterfactual && 'border-dashed italic opacity-85',
        className,
      )}
      title={`${counterfactual ? 'counterfactual veto' : 'veto'}: ${reason ?? 'no reason recorded'}`}
    >
      {counterfactual && <span className="font-bold not-italic">CF</span>}
      <span className="truncate">{reason ? reasonLabel(reason) : 'no reason'}</span>
    </span>
  );
});

export default VetoChip;
