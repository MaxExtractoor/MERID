import { useEffect, useRef, useState, useCallback } from 'react';

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting' | 'error' | 'backend_offline';

type UseWebSocketOptions = {
  url: string;
  protocols?: string | string[];
  autoConnect?: boolean;
  /** Heartbeat ping interval in ms (default 30000). Set 0 to disable. */
  heartbeatMs?: number;
  /** Max time to wait for pong before declaring dead (default 10000). */
  pongTimeoutMs?: number;
  /** Enable auto-reconnect on close/error (default true). */
  autoReconnect?: boolean;
  /** Max backoff between reconnect attempts in ms (default 30000). */
  maxReconnectMs?: number;
  /** Max reconnection retries before giving up (default 10). */
  maxRetries?: number;
  /** Token for authenticated WebSocket connections */
  token?: string;
};

type WebSocketState<TMessage = unknown> = {
  socket: WebSocket | null;
  connected: boolean;
  status: WebSocketStatus;
  lastMessage: TMessage | null;
  error: Error | null;
  send: (data: string) => void;
  disconnect: () => void;
  reconnect: () => void;
};

export function useWebSocket<TMessage = unknown>(
  { url, protocols, autoConnect = true, heartbeatMs = 30_000, pongTimeoutMs = 10_000, autoReconnect = true, maxReconnectMs = 30_000, token }: UseWebSocketOptions
): WebSocketState<TMessage> {
  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const connected = status === 'connected';
  const [lastMessage, setLastMessage] = useState<TMessage | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const mountedRef = useRef(true);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPongRef = useRef<number>(Date.now());
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null; }
    if (pongTimeoutRef.current) { clearTimeout(pongTimeoutRef.current); pongTimeoutRef.current = null; }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    intentionalCloseRef.current = false;
    if (!autoConnect) return;

    const connect = () => {
      if (!mountedRef.current) return;

      try {
        // Build URL with token if provided
        let connectUrl = url;
        if (token) {
          const sep = url.includes('?') ? '&' : '?';
          connectUrl = `${url}${sep}token=${encodeURIComponent(token)}`;
        }
        
        const socket = new WebSocket(connectUrl, protocols);
        socketRef.current = socket;
        
        setStatus('connecting');

        socket.onopen = () => {
          if (!mountedRef.current) { socket.close(); return; }
          retriesRef.current = 0;
          setStatus('connected');
          setError(null);
          lastPongRef.current = Date.now();

          // Start heartbeat ping/pong
          if (heartbeatMs > 0) {
            clearHeartbeat();
            heartbeatRef.current = setInterval(() => {
              if (socket.readyState !== WebSocket.OPEN) return;
              try {
                socket.send(JSON.stringify({ event: 'ping', ts: Date.now() }));
              } catch { /* ignore send errors */ }

              // Set a timeout — if no pong arrives, mark dead
              pongTimeoutRef.current = setTimeout(() => {
                const elapsed = Date.now() - lastPongRef.current;
                if (elapsed >= heartbeatMs + pongTimeoutMs) {
                  if (mountedRef.current) {
                    setStatus('disconnected');
                    setError(new Error('WebSocket heartbeat timeout — connection dead'));
                  }
                  // Force-close — onclose will trigger reconnect
                  try { socket.close(); } catch { /* ignore */ }
                }
              }, pongTimeoutMs);
            }, heartbeatMs);
          }
        };

        socket.onclose = (event) => {
          clearHeartbeat();
          if (mountedRef.current) {
            setStatus(event.wasClean ? 'disconnected' : 'reconnecting');
          }
          socketRef.current = null;
          // Auto-reconnect with exponential backoff (unless intentional close or unmounted)
          // P0-UI-3 FIX: Add max retry limit to prevent reconnection storm
          const maxRetries = 10;
          if (autoReconnect && mountedRef.current && !intentionalCloseRef.current) {
            retriesRef.current += 1;
            if (retriesRef.current > maxRetries) {
              setStatus('error');
              setError(new Error(`WebSocket reconnection failed after ${maxRetries} attempts — service unavailable`));
              return;
            }
            const jitter = Math.random() * 1000;
            const timeout = Math.min(1000 * 2 ** Math.min(retriesRef.current, 10), maxReconnectMs) + jitter;
            reconnectTimerRef.current = setTimeout(connect, timeout);
          }
        };

        socket.onerror = (_err) => {
          if (mountedRef.current) {
            setStatus('error');
            setError(new Error('WebSocket connection error'));
          }
        };

        socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            // Handle pong responses — update last pong time
            if (data && (data.event === 'pong' || data.type === 'pong')) {
              lastPongRef.current = Date.now();
              if (pongTimeoutRef.current) { clearTimeout(pongTimeoutRef.current); pongTimeoutRef.current = null; }
              return;
            }
            // Any message from server counts as "alive"
            lastPongRef.current = Date.now();
            setLastMessage(data as TMessage);
          } catch {
            setStatus('error');
            setError(new Error('Failed to parse WebSocket message'));
          }
        };
      } catch {
        if (mountedRef.current) {
          setStatus('error');
          setError(new Error('Failed to create WebSocket connection'));
        }
        // Retry even on constructor failure
        if (autoReconnect && mountedRef.current) {
          retriesRef.current += 1;
          const timeout = Math.min(1000 * 2 ** retriesRef.current, maxReconnectMs);
          reconnectTimerRef.current = setTimeout(connect, timeout);
        }
      }
    };

    connect();

    return () => {
      mountedRef.current = false;
      clearHeartbeat();
      if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        socketRef.current.close();
      }
      socketRef.current = null;
    };
  }, [url, protocols, autoConnect, heartbeatMs, pongTimeoutMs, autoReconnect, maxReconnectMs, clearHeartbeat]);

  const send = useCallback((data: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(data);
  }, []);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearHeartbeat();
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    if (socketRef.current) socketRef.current.close();
  }, [clearHeartbeat]);

  const reconnect = useCallback(() => {
    intentionalCloseRef.current = false;
    retriesRef.current = 0;
    clearHeartbeat();
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    if (socketRef.current) socketRef.current.close();
    // Re-trigger effect by toggling a dummy state or calling connect directly
    // For simplicity, we'll trigger a re-render by updating status
    setStatus('connecting');
  }, [clearHeartbeat]);

  return {
    socket: socketRef.current,
    connected,
    status,
    lastMessage,
    error,
    send,
    disconnect,
    reconnect,
  };
}

/**
 * Hook for Kalshi-specific risk stream WebSocket.
 */
function getWsBaseUrl(): string {
  try {
    const meta = (globalThis as any).import?.meta;
    return meta?.env?.VITE_WS_URL || 'ws://localhost:8011';
  } catch {
    return 'ws://localhost:8011';
  }
}

export function useKalshiRiskStream(token?: string): WebSocketState {
  const WS_BASE_URL = getWsBaseUrl();
  
  return useWebSocket({
    url: `${WS_BASE_URL}/ws/risk`,
    token,
    autoReconnect: true,
    maxReconnectMs: 30000,
    heartbeatMs: 10000,
  });
}

/**
 * Hook for trade events WebSocket.
 */
export function useTradeEventsStream(token?: string): WebSocketState {
  const WS_BASE_URL = getWsBaseUrl();
  
  return useWebSocket({
    url: `${WS_BASE_URL}/ws/trades`,
    token,
    autoReconnect: true,
    maxReconnectMs: 30000,
    heartbeatMs: 15000,
  });
}

/**
 * Hook for live tick stream WebSocket.
 */
export function useLiveTickStream(token?: string): WebSocketState {
  const WS_BASE_URL = getWsBaseUrl();
  
  return useWebSocket({
    url: `${WS_BASE_URL}/ws/live`,
    token,
    autoReconnect: true,
    maxReconnectMs: 30000,
    heartbeatMs: 15000,
  });
}
