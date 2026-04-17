/**
 * Normalize GET /api/v1/kalshi/health/reconciliation payloads.
 * Older servers mistakenly set `status` to the full reconciliation dict; UI must never render that object.
 */

export type KalshiReconHealth = {
  status?: unknown;
  message?: unknown;
  last_run?: string | null;
  divergence_count?: number;
  ghost_trade_candidates?: number;
};

export type KalshiReconStatus = 'ok' | 'degraded' | 'broken' | 'unknown';

export function flattenKalshiReconciliationStatus(
  data: KalshiReconHealth | null | undefined
): KalshiReconStatus {
  const s = data?.status;
  if (typeof s === 'string') {
    if (s === 'ok' || s === 'degraded' || s === 'broken' || s === 'unknown') return s;
    return 'unknown';
  }
  if (typeof s === 'object' && s !== null && 'status' in s) {
    const inner = (s as { status?: unknown }).status;
    if (inner === 'ok' || inner === 'degraded' || inner === 'broken' || inner === 'unknown') {
      return inner;
    }
  }
  return 'unknown';
}

export function flattenKalshiReconciliationMessage(
  data: KalshiReconHealth | null | undefined,
  fallback: string
): string {
  const m = data?.message;
  if (typeof m === 'string' && m.trim().length > 0) return m;
  return fallback;
}
