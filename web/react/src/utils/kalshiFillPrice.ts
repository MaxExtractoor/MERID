/**
 * Canonical fill price parsing — GET /kalshi/fills returns price_usd/price_cents;
 * older clients expected `price` (dollars). Keeps UI free of NaN.
 */
import type { KalshiFill } from '../types/kalshi';

export function fillPriceDollars(f: KalshiFill): number | null {
  if (f.price != null && Number.isFinite(Number(f.price))) return Number(f.price);
  if (f.price_usd != null && Number.isFinite(Number(f.price_usd))) return Number(f.price_usd);
  if (f.price_cents != null && Number.isFinite(Number(f.price_cents))) return Number(f.price_cents) / 100;
  return null;
}

/** Whole cents for display, or em dash if unknown */
export function formatFillPriceCents(f: KalshiFill): string {
  const d = fillPriceDollars(f);
  if (d == null || !Number.isFinite(d)) return '—';
  return String(Math.round(d * 100));
}

/** Same as formatFillPriceCents but appends ¢ when numeric */
export function formatFillPriceCentsLabel(f: KalshiFill): string {
  const c = formatFillPriceCents(f);
  return c === '—' ? '—' : `${c}¢`;
}

export function formatFillFeeUsd(f: KalshiFill): string {
  const raw = f.fee ?? f.fee_usd;
  const n = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0;
  return n.toFixed(2);
}
