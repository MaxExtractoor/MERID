export const TRADABLE_TIMEFRAMES = ['15m', '1h', 'daily', 'weekly', 'monthly', 'annual'] as const;

export type TradableTimeframe = (typeof TRADABLE_TIMEFRAMES)[number];

export const TRADABLE_TIMEFRAME_LABELS: Record<TradableTimeframe, string> = {
  '15m': '15m',
  '1h': '1h',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  annual: 'Annual',
};

const TIMEFRAME_ORDER: Record<string, number> = {
  '15m': 0,
  scalp: 0,
  '1h': 1,
  intraday: 1,
  daily: 2,
  swing: 2,
  weekly: 3,
  monthly: 4,
  annual: 5,
};

export function sortTimeframes<T extends string>(timeframes: T[]): T[] {
  return [...timeframes].sort((left, right) => {
    const leftOrder = TIMEFRAME_ORDER[left] ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = TIMEFRAME_ORDER[right] ?? Number.MAX_SAFE_INTEGER;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    return left.localeCompare(right);
  });
}
