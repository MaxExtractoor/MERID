/**
 * useFillToast — polls KALSHI_FILLS and fires a toast notification
 * whenever a new fill arrives (fill_id not seen before).
 *
 * Mount once at the app level (inside ToastProvider).
 * Uses the canonical fills ledger for guaranteed real fills only.
 */

import { useEffect, useRef, useCallback } from 'react';
import { useToast } from '../components/ToastProvider';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';

interface KalshiFill {
  fill_id: string;
  trade_id?: string;
  order_id?: string;
  ticker: string;
  side: string;
  action: string;
  size: number;
  price_usd: number;
  price_cents: number;
  fee_usd: number;
  timestamp: string;
  agent_id?: string;
  reconciled?: boolean;
  ingestion_source?: string;
  incomplete?: boolean;
  asset?: string | null;
  price?: number;
}

interface FillsMeta {
  source: string;
  reconciliation_status?: {
    status: string;
    last_run?: string;
    issues_count?: number;
  };
  warning?: string;
}

export interface FillsState {
  fills: KalshiFill[];
  meta: FillsMeta | null;
  reconciliationOk: boolean;
}

export function useFillToast() {
  const { toast } = useToast();
  const seenIds = useRef<Set<string>>(new Set());
  const initialised = useRef(false);
  const lastMeta = useRef<FillsMeta | null>(null);

  const poll = useCallback(async () => {
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FILLS}?since_hours=24&limit=100`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
      });
      if (!res.ok) return;
      const data = await res.json() as { fills?: KalshiFill[]; meta?: FillsMeta; warning?: string };
      const fills: KalshiFill[] = data.fills ?? [];
      const meta = data.meta ?? null;

      // Track reconciliation status changes
      if (meta?.reconciliation_status && lastMeta.current?.reconciliation_status?.status !== meta.reconciliation_status.status) {
        if (meta.reconciliation_status.status === 'broken') {
          toast({
            type: 'error',
            title: 'Fills Reconciliation Broken',
            message: 'Position/fill divergence detected — trading may be inaccurate',
            durationMs: 15000,
          });
        } else if (meta.reconciliation_status.status === 'degraded') {
          toast({
            type: 'warning',
            title: 'Fills Reconciliation Degraded',
            message: `${meta.reconciliation_status.issues_count || 'Some'} fills pending reconciliation`,
            durationMs: 10000,
          });
        }
      }
      lastMeta.current = meta;

      if (!initialised.current) {
        // Seed seen IDs on first load — don't toast for existing fills
        for (const f of fills) seenIds.current.add(f.fill_id);
        initialised.current = true;
        return;
      }

      for (const f of fills) {
        if (seenIds.current.has(f.fill_id)) continue;
        seenIds.current.add(f.fill_id);

        if (f.incomplete) {
          console.warn('[useFillToast] skipping incomplete fill row', f.fill_id, f.ticker);
          continue;
        }

        // Only show toast for newly ingested fills (last 5 minutes)
        const fillTime = new Date(f.timestamp).getTime();
        const ageMinutes = (Date.now() - fillTime) / 60000;
        if (ageMinutes > 5) continue;

        // Canonical fill alerts: require ledger id, nonzero size, and a price (no ghost / thin rows)
        const sz = Number(f.size);
        if (!f.fill_id || !Number.isFinite(sz) || sz <= 0) continue;
        const hasPrice =
          (f.price_usd != null && Number.isFinite(Number(f.price_usd)) && Number(f.price_usd) > 0) ||
          (f.price_cents != null && Number.isFinite(Number(f.price_cents)) && Number(f.price_cents) > 0) ||
          (f.price != null && Number.isFinite(Number(f.price)) && Number(f.price) > 0);
        if (!hasPrice) {
          console.warn('[useFillToast] skipping toast: missing price for fill', f.fill_id, f.ticker);
          continue;
        }

        const priceCents = f.price_cents ?? Math.round((f.price_usd ?? 0) * 100);
        const side = (f.side ?? '').toUpperCase();
        const action = (f.action ?? '').toLowerCase();
        
        // Calculate notional PnL if win
        const notionalIfWin = f.side === 'yes'
          ? (100 - priceCents) * f.size / 100
          : priceCents * f.size / 100;
        const netIfWin = notionalIfWin - (f.fee_usd ?? 0);

        const assetTag = f.asset ? `${f.asset} · ` : '';
        toast({
          type: 'success',
          title: `Fill: ${f.size}× ${action} ${side} ${assetTag}${f.ticker}`,
          message: `@ ${priceCents}¢  ·  Net if win: $${netIfWin.toFixed(2)}  ·  Fee: $${(f.fee_usd ?? 0).toFixed(2)}${f.reconciled ? '' : ' ⏳'}`,
          durationMs: 8000,
        });
      }
    } catch (err) {
      // Log polling errors to console for visibility
      console.warn('[useFillToast] Fills polling error:', err);
    }
  }, [toast]);

  useEffect(() => {
    void poll();
    const interval = setInterval(() => void poll(), DEFAULTS.POLLING_INTERVALS.STANDARD);
    return () => clearInterval(interval);
  }, [poll]);

  // Return current state for components that need it
  return {
    reconciliationStatus: lastMeta.current?.reconciliation_status?.status ?? 'unknown',
    warning: lastMeta.current?.warning,
  };
}
