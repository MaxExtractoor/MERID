import React from 'react';

export interface LiquiditySignal {
  spread_bp: number;
  depth: number;        // e.g. size within N ticks
  volume_24h: number;
  bucket: 'good' | 'ok' | 'poor';
  reason_tags: string[]; // ['wide_spread', 'thin_depth']
}

interface KalshiLiquidityBadgeProps {
  signal: LiquiditySignal;
  size?: 'sm' | 'md';
}

const BUCKET_STYLES: Record<LiquiditySignal['bucket'], { text: string; bg: string; border: string }> = {
  good: { text: 'text-green-400', bg: 'bg-green-400/10', border: 'border-green-400/20' },
  ok: { text: 'text-yellow-400', bg: 'bg-yellow-400/10', border: 'border-yellow-400/20' },
  poor: { text: 'text-red-400', bg: 'bg-red-400/10', border: 'border-red-400/20' },
};

export const KalshiLiquidityBadge: React.FC<KalshiLiquidityBadgeProps> = ({
  signal,
  size = 'sm',
}) => {
  const style = BUCKET_STYLES[signal.bucket];
  const sizeClasses = size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-1 text-sm';

  const tooltip = [
    signal.reason_tags.includes('wide_spread') ? `Wide spread: ${(signal.spread_bp / 100).toFixed(2)}%` : `Tight spread: ${(signal.spread_bp / 100).toFixed(2)}%`,
    signal.reason_tags.includes('thin_depth') ? `Thin depth: ${signal.depth}` : `Good depth: ${signal.depth}`,
    `Volume: ${signal.volume_24h.toLocaleString()}`,
  ].join('\n');

  return (
    <span
      className={`inline-flex items-center rounded border font-medium ${style.text} ${style.bg} ${style.border} ${sizeClasses}`}
      title={tooltip}
    >
      {signal.bucket === 'good' && '●'}
      {signal.bucket === 'ok' && '○'}
      {signal.bucket === 'poor' && '■'}
      <span className="ml-1 capitalize">{signal.bucket}</span>
    </span>
  );
};

export default KalshiLiquidityBadge;
