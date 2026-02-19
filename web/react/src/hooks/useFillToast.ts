/**
 * useFillToast — polls KALSHI_FILLS and fires a toast notification
 * whenever a new fill arrives (trade_id not seen before).
 *
 * Mount once at the app level (inside ToastProvider).
 */

import { useEffect, useRef, useCallback } from 'react';
import { useToast } from '../components/ToastProvider';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface KalshiFill {
  trade_id: string;
  ticker: string;
  side: string;
  size: number;
  price: number;
  fee: number;
  timestamp: string;
}

export function useFillToast() {
  const { toast } = useToast();
  const seenIds = useRef<Set<string>>(new Set());
  const initialised = useRef(false);

  const poll = useCallback(async () => {
    try {
      const token = localStorage.getItem('merid-access');
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FILLS}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) return;
      const data = await res.json() as { fills?: KalshiFill[] };
      const fills: KalshiFill[] = data.fills ?? [];

      if (!initialised.current) {
        // Seed seen IDs on first load — don't toast for existing fills
        for (const f of fills) seenIds.current.add(f.trade_id);
        initialised.current = true;
        return;
      }

      for (const f of fills) {
        if (seenIds.current.has(f.trade_id)) continue;
        seenIds.current.add(f.trade_id);

        const priceCents = Math.round(f.price * 100);
        const side = f.side.toUpperCase();
        const pnl = f.side === 'yes'
          ? (1 - f.price) * f.size - f.fee
          : f.price * f.size - f.fee;

        toast({
          type: 'success',
          title: `Fill: ${f.size}× ${side} ${f.ticker}`,
          message: `@ ${priceCents}¢  ·  Net if win: $${pnl.toFixed(2)}  ·  Fee: $${f.fee.toFixed(2)}`,
          durationMs: 8000,
        });
      }
    } catch {
      // best effort — never throw from a background poller
    }
  }, [toast]);

  useEffect(() => {
    void poll();
    const interval = setInterval(() => void poll(), DEFAULTS.POLLING_INTERVALS.STANDARD);
    return () => clearInterval(interval);
  }, [poll]);
}
