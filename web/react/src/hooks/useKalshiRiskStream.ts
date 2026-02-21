/**
 * useKalshiRiskStream — Live risk alert stream via WebSocket.
 *
 * Connects to /ws/risk and accumulates risk_alert events into a
 * buffer that KalshiRiskFeed can merge with polled events.
 *
 * Also exposes the latest risk_summary for live equity/PnL display.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { WS_PORTFOLIO_URL } from '../config/constants';

export interface WsRiskAlert {
  id: string;
  ts: string;
  severity: string;
  category: string;
  title: string;
  detail?: string;
  source: 'ws';
}

export interface WsRiskSummary {
  total_equity: number;
  total_pnl: number;
  unrealized_pnl: number;
  position_count: number;
  exposure: number;
  timestamp: number;
}

interface UseKalshiRiskStreamReturn {
  alerts: WsRiskAlert[];
  summary: WsRiskSummary | null;
  connected: boolean;
  clearAlerts: () => void;
}

const MAX_WS_ALERTS = 100;

export function useKalshiRiskStream(): UseKalshiRiskStreamReturn {
  const [alerts, setAlerts] = useState<WsRiskAlert[]>([]);
  const [summary, setSummary] = useState<WsRiskSummary | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());

  const clearAlerts = useCallback(() => {
    setAlerts([]);
    seenIdsRef.current.clear();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    retriesRef.current = 0;

    const connect = () => {
      if (!mountedRef.current) return;

      try {
        const ws = new WebSocket(WS_PORTFOLIO_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mountedRef.current) { ws.close(); return; }
          retriesRef.current = 0;
          setConnected(true);
        };

        ws.onclose = () => {
          if (!mountedRef.current) return;
          setConnected(false);
          wsRef.current = null;
          // Reconnect with exponential backoff
          retriesRef.current += 1;
          const jitter = Math.random() * 1000;
          const timeout = Math.min(1000 * 2 ** Math.min(retriesRef.current, 8), 30_000) + jitter;
          reconnectTimerRef.current = setTimeout(connect, timeout);
        };

        ws.onerror = () => { ws.close(); };

        ws.onmessage = (event) => {
          if (!mountedRef.current) return;
          try {
            const data = JSON.parse(event.data);

            // Handle pong / heartbeat
            if (data.event === 'pong' || data.type === 'pong' || data.event_type === 'heartbeat') {
              return;
            }

            // Risk summary updates
            if (data.event_type === 'risk_summary') {
              setSummary({
                total_equity: data.total_equity ?? 0,
                total_pnl: data.total_pnl ?? 0,
                unrealized_pnl: data.unrealized_pnl ?? 0,
                position_count: data.position_count ?? 0,
                exposure: data.exposure ?? 0,
                timestamp: data.timestamp ?? Date.now() / 1000,
              });
              return;
            }

            // Risk alert events
            if (data.event_type === 'risk_alert') {
              const alertId = data.extra?.event_id
                || `ws-${data.signal}-${Math.floor(data.timestamp)}`;

              // Deduplicate
              if (seenIdsRef.current.has(alertId)) return;
              seenIdsRef.current.add(alertId);

              // Cap seen IDs set
              if (seenIdsRef.current.size > MAX_WS_ALERTS * 2) {
                const arr = Array.from(seenIdsRef.current);
                seenIdsRef.current = new Set(arr.slice(-MAX_WS_ALERTS));
              }

              const alert: WsRiskAlert = {
                id: alertId,
                ts: new Date(data.timestamp * 1000).toISOString(),
                severity: data.status || 'warning',
                category: data.extra?.category || data.signal || 'general',
                title: data.reasoning || 'Risk alert',
                detail: data.extra?.detail,
                source: 'ws',
              };

              setAlerts(prev => {
                const next = [alert, ...prev];
                return next.length > MAX_WS_ALERTS ? next.slice(0, MAX_WS_ALERTS) : next;
              });
            }
          } catch {
            // Ignore malformed messages
          }
        };
      } catch {
        // WebSocket constructor failed — retry
        retriesRef.current += 1;
        const timeout = Math.min(1000 * 2 ** retriesRef.current, 30_000);
        reconnectTimerRef.current = setTimeout(connect, timeout);
      }
    };

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* ignore */ }
      }
    };
  }, []);

  return { alerts, summary, connected, clearAlerts };
}
