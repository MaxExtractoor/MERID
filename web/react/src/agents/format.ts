/**
 * agents/format.ts — pure formatting and matching helpers shared by the
 * agent-monitoring surface. No React, no fetching — safe to import anywhere.
 *
 * Truthfulness rules:
 *  - Every formatter returns an explicit 'n/a' style placeholder for missing
 *    data rather than a plausible-looking zero.
 *  - Numeric coercion goes through isFiniteNum — never `Number(x) || 0`.
 */

import type { AssetSymbol, MarketState } from './types';
import { ASSETS } from './types';

export const NA = 'n/a';

/** Type guard for usable finite numbers (rejects NaN/Infinity/non-numbers). */
export function isFiniteNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Coerce unknown input to a finite number or undefined. */
export function numOr(v: unknown): number | undefined {
  if (isFiniteNum(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

/** clsx-lite: join truthy class fragments. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

/* ------------------------------------------------------------------ */
/* Numbers / money                                                     */
/* ------------------------------------------------------------------ */

/** Format a cent-denominated price: `93c`. Missing -> 'n/a'. */
export function fmtCents(v: unknown, digits = 0): string {
  const n = numOr(v);
  if (n == null) return NA;
  return `${n.toFixed(digits)}c`;
}

/** Format cents as signed cents: `+2.3c` / `-0.8c`. */
export function fmtSignedCents(v: unknown, digits = 1): string {
  const n = numOr(v);
  if (n == null) return NA;
  const sign = n > 0 ? '+' : n < 0 ? '-' : '';
  return `${sign}${Math.abs(n).toFixed(digits)}c`;
}

/** Format a cents value as USD: `4832c` -> `$48.32`. */
export function fmtCentsAsUsd(v: unknown): string {
  const n = numOr(v);
  if (n == null) return NA;
  return fmtUsd(n / 100);
}

/** Format a dollar value as USD. */
export function fmtUsd(v: unknown, digits = 2): string {
  const n = numOr(v);
  if (n == null) return NA;
  const neg = n < 0;
  return `${neg ? '-' : ''}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

/** Format a dollar PnL as signed USD. */
export function fmtSignedUsd(v: unknown, digits = 2): string {
  const n = numOr(v);
  if (n == null) return NA;
  const sign = n > 0 ? '+' : n < 0 ? '-' : '';
  return `${sign}$${Math.abs(n).toFixed(digits)}`;
}

/** Centi-contracts -> contract count (100 centi-contracts = 1 contract). */
export function centiToContracts(centi: unknown): number | undefined {
  const n = numOr(centi);
  return n == null ? undefined : n / 100;
}

/** Compact contract count: `250cc` -> `2.5`. */
export function fmtContracts(centiQty: unknown): string {
  const n = centiToContracts(centiQty);
  if (n == null) return NA;
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

/* ------------------------------------------------------------------ */
/* Time                                                                */
/* ------------------------------------------------------------------ */

/** `3721ms` -> `3.7s`, `92_000` -> `1.5m`, missing -> 'n/a'. */
export function fmtAgeMs(ms: unknown): string {
  const n = numOr(ms);
  if (n == null || n < 0) return NA;
  if (n < 1000) return `${Math.round(n)}ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)}s`;
  if (n < 3_600_000) return `${(n / 60_000).toFixed(1)}m`;
  return `${(n / 3_600_000).toFixed(1)}h`;
}

/** `123` -> `02:03` (mm:ss). */
export function fmtMMSS(secs: unknown): string {
  const n = numOr(secs);
  if (n == null) return '--:--';
  const s = Math.max(0, Math.round(n));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

/** Parse an ISO/ts string to epoch ms, undefined when absent/invalid. */
export function parseTsMs(ts: unknown): number | undefined {
  if (isFiniteNum(ts)) {
    // epoch seconds vs ms heuristic
    return ts > 1e12 ? ts : ts * 1000;
  }
  if (typeof ts === 'string' && ts) {
    const d = Date.parse(ts);
    if (Number.isFinite(d)) return d;
  }
  return undefined;
}

/** `2026-10-27T04:15:03Z` -> `04:15:03` local wall clock; missing -> '--:--:--'. */
export function fmtClock(ts: unknown): string {
  const ms = parseTsMs(ts);
  if (ms == null) return '--:--:--';
  return new Date(ms).toLocaleTimeString('en-GB', { hour12: false });
}

/** Age string from a ts to now: "4s ago". */
export function fmtAgo(ts: unknown, nowMs = Date.now()): string {
  const ms = parseTsMs(ts);
  if (ms == null) return NA;
  return `${fmtAgeMs(Math.max(0, nowMs - ms))}`;
}

/** Seconds remaining until the next quarter-hour (15m) boundary. */
export function secsToQuarterEnd(nowMs = Date.now()): number {
  const nowS = Math.floor(nowMs / 1000);
  return 900 - (nowS % 900);
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/* ------------------------------------------------------------------ */
/* Asset / ticker matching                                             */
/* ------------------------------------------------------------------ */

/** Extract the asset symbol from a Kalshi ticker like `KXBTC15M-...`. */
export function tickerAsset(ticker: string | undefined | null): AssetSymbol | undefined {
  if (!ticker) return undefined;
  const up = ticker.toUpperCase();
  // Match longest first so e.g. DOGE wins over GE-like substrings.
  for (const a of ASSETS) {
    if (up.includes(a)) return a;
  }
  return undefined;
}

/**
 * Find the market-state row for an agent. Prefers an exact ticker match,
 * then a 15m-series ticker containing the asset, then any asset match.
 */
export function matchMarketState(
  asset: AssetSymbol,
  ticker: string | undefined,
  states: MarketState[],
): MarketState | undefined {
  if (!states.length) return undefined;
  if (ticker) {
    const exact = states.find((m) => m.ticker === ticker);
    if (exact) return exact;
  }
  const cands = states.filter((m) => (m.ticker ?? '').toUpperCase().includes(asset));
  return cands.find((m) => (m.ticker ?? '').toUpperCase().includes('15M')) ?? cands[0];
}

/* ------------------------------------------------------------------ */
/* Spot price payload coercion                                         */
/* ------------------------------------------------------------------ */

export interface SpotInfo {
  price: number;
  ageS?: number;
  source?: string;
}

/**
 * Coerce the `/api/v1/spot/prices` payload into a per-asset map.
 * Backend shape (verified): `{ available, prices: { BTC: {price, ts, source, age_seconds} } }`.
 * Tolerates a flat `{ BTC: 97000 }` map too.
 */
export function toSpotMap(raw: unknown): Partial<Record<AssetSymbol, SpotInfo>> {
  const out: Partial<Record<AssetSymbol, SpotInfo>> = {};
  if (!raw || typeof raw !== 'object') return out;
  const obj = raw as Record<string, unknown>;
  const prices = (obj.prices && typeof obj.prices === 'object' ? obj.prices : obj) as Record<string, unknown>;
  for (const asset of ASSETS) {
    const entry = prices[asset];
    if (isFiniteNum(entry)) {
      out[asset] = { price: entry };
      continue;
    }
    if (entry && typeof entry === 'object') {
      const e = entry as Record<string, unknown>;
      const price = numOr(e.price ?? e.spot ?? e.last);
      if (price != null) {
        out[asset] = {
          price,
          ageS: numOr(e.age_seconds ?? e.age_s ?? e.ageSecs),
          source: typeof e.source === 'string' ? e.source : undefined,
        };
      }
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */

/** Case-normalize a veto/guard reason code into a chip label. */
export function reasonLabel(reason: string | undefined | null): string {
  if (!reason) return NA;
  return reason.replace(/[_-]+/g, ' ').trim().toLowerCase();
}
