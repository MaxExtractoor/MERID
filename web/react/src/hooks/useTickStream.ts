/**
 * useTickStream — subscribes to /ws/live and maintains a rolling buffer
 * of TickSummary and TickEvent objects for the OperatorDashboard timeline.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL } from '../config/constants';

export type TickEventName =
  | 'tick_started'
  | 'data_snapshot_taken'
  | 'agent_cycle_completed'
  | 'risk_checked'
  | 'order_submitted'
  | 'order_rejected'
  | 'fill_received'
  | 'tick_summary'
  | 'tick_error'
  | 'stop_loss_triggered'
  | 'session_gated'
  | 'heartbeat';

export interface TickSummary {
  event: 'tick_summary';
  tick_id: string;
  agent_id: string;
  ts: number;
  ts_started: number;
  ts_ended: number;
  duration_ms: number;
  venue: string;
  mode: string;
  cycle_number: number;
  markets_resolved: number;
  markets_in_window: number;
  session_allowed: boolean;
  signals_evaluated: number;
  signals_actionable: number;
  signals_consensus_blocked: number;
  risk_allowed: number;
  risk_blocked: number;
  orders_submitted: number;
  orders_rejected: number;
  fills_confirmed: number;
  stop_losses_triggered: number;
  error: string;
}

export interface TickEvent {
  event: TickEventName;
  tick_id: string;
  agent_id: string;
  ts: number;
  venue?: string;
  mode?: string;
  [key: string]: unknown;
}

export interface TickStreamState {
  summaries: TickSummary[];
  events: TickEvent[];
  connected: boolean;
  lastTs: number | null;
}

const WS_BASE = API_BASE_URL.replace(/^http/, 'ws');
const MAX_SUMMARIES = 100;
const MAX_EVENTS = 300;

export function useTickStream(): TickStreamState {
  const [summaries, setSummaries] = useState<TickSummary[]>([]);
  const [events, setEvents] = useState<TickEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastTs, setLastTs] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (wsRef.current && wsRef.current.readyState < 2) return;

    const ws = new WebSocket(`${WS_BASE}/ws/live`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as TickEvent | TickSummary;
        if (data.event === 'heartbeat') return;
        setLastTs(data.ts);

        if (data.event === 'tick_summary') {
          setSummaries((prev) => {
            const next = [...prev, data as TickSummary];
            return next.length > MAX_SUMMARIES ? next.slice(-MAX_SUMMARIES) : next;
          });
        }

        setEvents((prev) => {
          const next = [...prev, data as TickEvent];
          return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
        });
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (mountedRef.current) {
        reconnectTimer.current = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
          wsRef.current.close();
        }
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { summaries, events, connected, lastTs };
}
