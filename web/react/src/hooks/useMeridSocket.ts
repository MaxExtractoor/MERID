import { useEffect, useRef, useState, useCallback } from "react";
import { useWebSocket } from "./useWebSocket";
import { WS_URL } from "../config/constants";

export function useMeridSocket() {
  const [connected, setConnected] = useState(false);
  const lastMessageRef = useRef<unknown>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- handlers are typed at call-sites; the bus is untyped
  const eventListenersRef = useRef<Map<string, Set<(data: any) => void>>>(new Map());

  // Use our WebSocket hook
  const { socket, send, connected: wsConnected, lastMessage } = useWebSocket({
    url: WS_URL,
    autoConnect: true,
  });

  // Socket.io-like emit method
  const emit = useCallback((event: string, data?: unknown) => {
    const message = JSON.stringify({ event, data });
    send(message);
  }, [send]);

  // Socket.io-like on method
  const on = useCallback((event: string, callback: (data: any) => void) => {
    let listeners = eventListenersRef.current.get(event);
    if (!listeners) {
      listeners = new Set();
      eventListenersRef.current.set(event, listeners);
    }
    listeners.add(callback);
  }, []);

  // Socket.io-like off method
  const off = useCallback((event: string, callback: (data: any) => void) => {
    const listeners = eventListenersRef.current.get(event);
    if (listeners) {
      listeners.delete(callback);
    }
  }, []);

  // Handle incoming messages
  useEffect(() => {
    if (!lastMessage || typeof lastMessage !== 'object') {
      return;
    }

    lastMessageRef.current = lastMessage;
    const payload = lastMessage as Record<string, unknown>;
    const event = (typeof payload.event === 'string' && payload.event)
      || (typeof payload.type === 'string' && payload.type)
      || (typeof payload.event_type === 'string' && payload.event_type)
      || null;

    if (!event) {
      return;
    }

    const data = (payload.data ?? payload.payload ?? payload) as Record<string, unknown>;
    const aliases: Record<string, string[]> = {
      agent_updated: ['agent_update'],
      risk_summary: ['risk_update'],
      risk_alert: ['risk_update'],
      price_update: ['price_tick'],
      order_new: ['order_update'],
      order_cancelled: ['order_update'],
      order_rejected: ['order_update'],
      order_partial: ['order_update', 'fill_update'],
      order_filled: ['order_update', 'fill_update'],
    };

    const events = new Set<string>([event, ...(aliases[event] ?? [])]);
    events.forEach((evt) => {
      const listeners = eventListenersRef.current.get(evt);
      if (listeners) {
        listeners.forEach(listener => listener(data));
      }
    });
  }, [lastMessage]);

  // Update connected state
  useEffect(() => {
    setConnected(wsConnected);
  }, [wsConnected]);

  return { 
    socket: socket ? {
      emit,
      on,
      off,
      connected,
    } : null, 
    connected 
  };
}

// Native WebSocket with infinite backoff reconnect
export function useNativeWebSocket(url: string) {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [disconnectedSince, setDisconnectedSince] = useState<number | null>(null);
  const retriesRef = useRef(0);
  const mountedRef = useRef(true);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const MAX_BACKOFF = 30_000; // cap at 30s between retries

  useEffect(() => {
    mountedRef.current = true;
    retriesRef.current = 0;

    const connect = () => {
      if (!mountedRef.current) return;

      const ws = new WebSocket(url);
      
      ws.onopen = () => {
        if (!mountedRef.current) { ws.close(); return; }
        retriesRef.current = 0;
        setConnected(true);
        setDisconnectedSince(null);
        setSocket(ws);
      };
      
      ws.onclose = () => {
        setConnected(false);
        setSocket(null);
        if (!mountedRef.current) return;
        // Track when we first disconnected (don't overwrite if already set)
        setDisconnectedSince(prev => prev ?? Date.now());
        retriesRef.current += 1;
        const jitter = Math.random() * 1000;
        const timeout = Math.min(1000 * 2 ** Math.min(retriesRef.current, 10), MAX_BACKOFF) + jitter;
        reconnectTimerRef.current = setTimeout(connect, timeout);
      };
      
      ws.onerror = () => ws.close();
    };

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [url]);

  return { socket, connected, disconnectedSince };
}
