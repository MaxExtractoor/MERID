/**
 * useLiveOdds — Hooks for live odds movement data and sparkline snapshots.
 *
 * Provides:
 *   - useLiveOddsSnapshots: polls betting consensus summary and extracts
 *     per-event odds movement data for sparklines
 *   - useEventOddsHistory: fetches historical odds for a single event
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

/* ── Types ─────────────────────────────────────────────────────── */

export interface OddsPoint {
  timestamp: number;
  book_prob: number;
  swarm_prob: number;
  edge: number;
}

export interface EventOddsSnapshot {
  event_id: string;
  title: string;
  sport: string;
  state: "pre" | "live" | "final";
  current_book_prob: number;
  current_swarm_prob: number;
  current_edge: number;
  sparkline: OddsPoint[];
  line_move_alert: boolean;
}

export interface LiveOddsData {
  events: EventOddsSnapshot[];
  live_count: number;
  last_updated: number;
}

/* ── Sparkline history accumulator ─────────────────────────────── */

const MAX_SPARKLINE_POINTS = 30;

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

/**
 * useLiveOddsSnapshots — Polls the betting consensus summary and accumulates
 * odds snapshots over time to build sparkline data for each event.
 */
export function useLiveOddsSnapshots(pollMs = 15_000) {
  const [data, setData] = useState<LiveOddsData | null>(null);
  const [loading, setLoading] = useState(true);
  const historyRef = useRef<Map<string, OddsPoint[]>>(new Map());

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.BETTING_CONSENSUS_SUMMARY}`, {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const raw = await res.json();
      const now = Date.now() / 1000;

      const events: EventOddsSnapshot[] = (raw.events ?? []).map(
        (ev: unknown) => {
          const row = (ev && typeof ev === 'object' ? ev : {}) as Record<string, unknown>;
          const eventMeta = (
            row.event && typeof row.event === 'object'
              ? row.event
              : {}
          ) as Record<string, unknown>;

          const eventId = String(row.event_id ?? row.id ?? '');
          const bookProbs = (
            row.sportsbook_consensus_prob && typeof row.sportsbook_consensus_prob === 'object'
              ? row.sportsbook_consensus_prob
              : {}
          ) as Record<string, number>;
          const swarmProbs = (
            row.swarm_prob && typeof row.swarm_prob === 'object'
              ? row.swarm_prob
              : {}
          ) as Record<string, number>;
          const edges = (
            row.edge_vs_books && typeof row.edge_vs_books === 'object'
              ? row.edge_vs_books
              : {}
          ) as Record<string, number>;

          // Use first outcome for sparkline
          const firstKey = Object.keys(bookProbs)[0] ?? "";
          const bookProb = bookProbs[firstKey] ?? 0.5;
          const swarmProb = swarmProbs[firstKey] ?? 0.5;
          const edge = edges[firstKey] ?? 0;

          // Accumulate history
          const history = historyRef.current.get(eventId) ?? [];
          history.push({
            timestamp: now,
            book_prob: bookProb,
            swarm_prob: swarmProb,
            edge,
          });
          while (history.length > MAX_SPARKLINE_POINTS) history.shift();
          historyRef.current.set(eventId, history);

          // Detect line move (>3% shift in last 2 points)
          let lineAlert = false;
          if (history.length >= 2) {
            const prev = history[history.length - 2];
            const curr = history[history.length - 1];
            lineAlert = Math.abs(curr.book_prob - prev.book_prob) > 0.03;
          }

          return {
            event_id: eventId,
            title: typeof eventMeta.title === 'string' ? eventMeta.title : eventId,
            sport: typeof eventMeta.sport === 'string' ? eventMeta.sport : 'unknown',
            state: row.state === 'live' || row.state === 'final' ? row.state : 'pre',
            current_book_prob: bookProb,
            current_swarm_prob: swarmProb,
            current_edge: edge,
            sparkline: [...history],
            line_move_alert: lineAlert,
          };
        }
      );

      setData({
        events,
        live_count: raw.live_count ?? events.filter((e) => e.state === "live").length,
        last_updated: now,
      });
    } catch {
      // Silently fail — data will be stale
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, refresh };
}

/**
 * useEventOddsHistory — Fetches live consensus for a single event.
 * Returns the current odds snapshot (not historical — backend doesn't store
 * time-series odds yet, so we use the accumulated sparkline from useLiveOddsSnapshots).
 */
export function useEventOddsHistory(eventId: string | null) {
  const [odds, setOdds] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!eventId) {
      setOdds(null);
      return;
    }
    setLoading(true);
    fetch(`${API_BASE_URL}${API_ENDPOINTS.SPORTS_LIVE_EVENT(eventId)}`, {
      headers: authHeaders(),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setOdds(d))
      .catch(() => setOdds(null))
      .finally(() => setLoading(false));
  }, [eventId]);

  return { odds, loading };
}
