/**
 * useKalshiRiskStream — Live risk alert stream via WebSocket.
 *
 * Connects to /ws/risk and accumulates risk_alert events into a
 * buffer that KalshiRiskFeed can merge with polled events.
 *
 * Also exposes the latest risk_summary for live equity/PnL display.
 */

import { useEffect, useRef, useState, useCallback, useContext } from 'react';
import { WS_PORTFOLIO_URL, AUTH_TOKEN_KEY } from '../config/constants';
import { BackendHealthContext } from '../context/BackendHealthContext';

export type RiskAlertType = 'kill_switch' | 'portfolio_breach' | 'agent_rollback' | 'general';

export interface WsRiskAlert {
  id: string;
  ts: string;
  timestamp?: string;
  level: 'info' | 'warning' | 'error' | 'critical';
  type: RiskAlertType;
  message: string;
  source_agent_id?: string;
  market_id?: string;
  source: 'ws';
  severity?: string;
  category?: string;
  title?: string;
  detail?: string;
}

export interface WsRiskSummary {
  total_equity: number;
  total_pnl: number;
  unrealized_pnl: number;
  position_count: number;
  exposure: number;
  timestamp: number;
}

export interface UseKalshiRiskStreamReturn {
  alerts: WsRiskAlert[];
  summary: WsRiskSummary | null;
  /** Epoch ms when the last risk_summary WS message was received. null if never received. */
  summaryReceivedAt: number | null;
  connected: boolean;
  clearAlerts: () => void;
  /** True when backend is unreachable (network error or down). */
  backendOffline: boolean;
}

export interface UseKalshiRiskStreamOptions {
  customUrl?: string;
  authToken?: string;
}

const MAX_WS_ALERTS = 100;

export function useKalshiRiskStream(options: UseKalshiRiskStreamOptions = {}): UseKalshiRiskStreamReturn {
  const [alerts, setAlerts] = useState<WsRiskAlert[]>([]);
  const [summary, setSummary] = useState<WsRiskSummary | null>(null);
  const [summaryReceivedAt, setSummaryReceivedAt] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  // Read backend-level offline state from context (separate from WebSocket connected state)
  const { backendOffline } = useContext(BackendHealthContext);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  // UI-005 fix: store options in ref so connect/reconnect always reads latest values
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const clearAlerts = useCallback(() => {
    setAlerts([]);
    seenIdsRef.current.clear();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    retriesRef.current = 0;

    const resolveWsUrl = () => {
      if (optionsRef.current.customUrl) return optionsRef.current.customUrl;

      // Prefer explicit env override so the UI can target a remote API even when served from Vite.
      if (WS_PORTFOLIO_URL) return WS_PORTFOLIO_URL;

      if (typeof window !== 'undefined' && window.location) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/ws/risk`;
      }

      return 'ws://127.0.0.1:8011/ws/risk';
    };

    const buildUrlWithToken = (baseUrl: string) => {
      // Prefer explicit authToken option; fall back to localStorage session token.
      const token = optionsRef.current.authToken ?? (typeof window !== 'undefined' ? localStorage.getItem(AUTH_TOKEN_KEY) : null);
      if (!token) return baseUrl;
      const separator = baseUrl.includes('?') ? '&' : '?';
      return `${baseUrl}${separator}token=${encodeURIComponent(token)}`;
    };

    const connect = () => {
      if (!mountedRef.current) return;

      try {
        const baseUrl = resolveWsUrl();
        const url = buildUrlWithToken(baseUrl);
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mountedRef.current) { ws.close(); return; }
          retriesRef.current = 0;
          setConnected(true);

          // Subscribe to risk channels
          ws.send(JSON.stringify({
            subscribe: ['risk_summary', 'risk_alert', 'kill_switch', 'portfolio_breach', 'agent_rollback']
          }));
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
              const summaryData = {
                total_equity: data.total_equity ?? 0,
                total_pnl: data.total_pnl ?? 0,
                unrealized_pnl: data.unrealized_pnl ?? 0,
                position_count: data.position_count ?? 0,
                exposure: data.exposure ?? 0,
                timestamp: data.timestamp ?? Date.now() / 1000,
              };
              // Data validation happens in the hook consuming this data
              setSummary(summaryData);
              setSummaryReceivedAt(Date.now());
              return;
            }

            // Risk alert events
            if (data.event_type === 'kill_switch') {
              const alert: WsRiskAlert = {
                id: `kill-${data.timestamp}`,
                ts: new Date(data.timestamp * 1000).toISOString(),
                level: 'critical',
                type: 'kill_switch',
                message: data.reason || 'Trading halted due to kill switch activation',
                source_agent_id: data.agent_id,
                source: 'ws',
              };
              setAlerts(prev => [alert, ...prev.slice(0, MAX_WS_ALERTS - 1)]);
            } else if (data.event_type === 'portfolio_breach') {
              const alert: WsRiskAlert = {
                id: `breach-${data.timestamp}`,
                ts: new Date(data.timestamp * 1000).toISOString(),
                level: 'error',
                type: 'portfolio_breach',
                message: data.reason || 'Portfolio risk limits breached',
                source: 'ws',
              };
              setAlerts(prev => [alert, ...prev.slice(0, MAX_WS_ALERTS - 1)]);
            } else if (data.event_type === 'agent_rollback') {
              const alert: WsRiskAlert = {
                id: `rollback-${data.timestamp}`,
                ts: new Date(data.timestamp * 1000).toISOString(),
                level: 'warning',
                type: 'agent_rollback',
                message: data.reason || 'Agent rolled back due to performance issues',
                source_agent_id: data.agent_id,
                source: 'ws',
              };
              setAlerts(prev => [alert, ...prev.slice(0, MAX_WS_ALERTS - 1)]);
            } else if (data.event_type === 'risk_alert') {
              const alertId = data.extra?.event_id || `ws-${data.signal}-${Math.floor(data.timestamp)}`;

              // Deduplicate
              if (seenIdsRef.current.has(alertId)) return;
              seenIdsRef.current.add(alertId);

              // Cap seen IDs set
              if (seenIdsRef.current.size > MAX_WS_ALERTS * 2) {
                const arr = Array.from(seenIdsRef.current);
                seenIdsRef.current = new Set(arr.slice(-MAX_WS_ALERTS));
              }

              const level: WsRiskAlert['level'] = data.status === 'critical'
                ? 'critical'
                : data.status === 'error'
                  ? 'error'
                  : data.status === 'warning'
                    ? 'warning'
                    : 'info';
              const severity: WsRiskAlert['severity'] = data.status === 'critical'
                ? 'critical'
                : data.status === 'warning'
                  ? 'warning'
                  : 'info';

              const alert: WsRiskAlert = {
                id: alertId,
                ts: new Date(data.timestamp * 1000).toISOString(),
                level,
                type: 'general',
                message: data.reasoning || 'Risk alert',
                market_id: data.extra?.market_id,
                source: 'ws',
                severity,
                category: data.extra?.category || 'general',
                title: data.extra?.title ?? data.reasoning,
                detail: data.extra?.detail,
              };

              setAlerts(prev => [alert, ...prev.slice(0, MAX_WS_ALERTS - 1)]);
            }
          } catch (e) {
            // Risk stream parse errors are critical - log via telemetry
            // but don't spam console in production
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
      const ws = wsRef.current;
      if (ws) {
        if (ws.readyState === WebSocket.OPEN) {
          try { ws.close(); } catch { /* ignore */ }
        } else if (ws.readyState === WebSocket.CONNECTING) {
          // Defer close until open to avoid "closed before established" console warning
          wsRef.current = null;
          ws.onopen = () => { try { ws.close(); } catch { /* ignore */ } };
          ws.onclose = null;
        }
      }
    };
  }, []);

  return { alerts, summary, summaryReceivedAt, connected, clearAlerts, backendOffline };
}
