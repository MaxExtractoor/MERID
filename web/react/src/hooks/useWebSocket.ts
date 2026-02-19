import { useEffect, useRef, useState, useCallback } from 'react';

type UseWebSocketOptions = {
  url: string;
  protocols?: string | string[];
  autoConnect?: boolean;
  /** Heartbeat ping interval in ms (default 30000). Set 0 to disable. */
  heartbeatMs?: number;
  /** Max time to wait for pong before declaring dead (default 10000). */
  pongTimeoutMs?: number;
};

type WebSocketState<TMessage = unknown> = {
  socket: WebSocket | null;
  connected: boolean;
  lastMessage: TMessage | null;
  error: Error | null;
  send: (data: string) => void;
  disconnect: () => void;
};

export function useWebSocket<TMessage = unknown>(
  { url, protocols, autoConnect = true, heartbeatMs = 30_000, pongTimeoutMs = 10_000 }: UseWebSocketOptions
): WebSocketState<TMessage> {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<TMessage | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const mountedRef = useRef(true);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPongRef = useRef<number>(Date.now());

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null; }
    if (pongTimeoutRef.current) { clearTimeout(pongTimeoutRef.current); pongTimeoutRef.current = null; }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    if (!autoConnect) return;

    try {
      const socket = new WebSocket(url, protocols);
      socketRef.current = socket;

      socket.onopen = () => {
        if (!mountedRef.current) { socket.close(); return; }
        setConnected(true);
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
                  setConnected(false);
                  setError(new Error('WebSocket heartbeat timeout — connection dead'));
                }
                // Force-close and let onclose handle reconnect if applicable
                try { socket.close(); } catch { /* ignore */ }
              }
            }, pongTimeoutMs);
          }, heartbeatMs);
        }
      };

      socket.onclose = () => {
        clearHeartbeat();
        setConnected(false);
      };

      socket.onerror = () => {
        if (mountedRef.current) {
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
          setError(new Error('Failed to parse WebSocket message'));
        }
      };

      return () => {
        mountedRef.current = false;
        clearHeartbeat();
        if (socket.readyState === WebSocket.OPEN) {
          socket.close();
        }
        socketRef.current = null;
      };
    } catch {
      setError(new Error('Failed to create WebSocket connection'));
    }
  }, [url, protocols, autoConnect, heartbeatMs, pongTimeoutMs, clearHeartbeat]);

  const send = useCallback((data: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(data);
  }, []);

  const disconnect = useCallback(() => {
    if (!socketRef.current) return;
    clearHeartbeat();
    socketRef.current.close();
  }, [clearHeartbeat]);

  return {
    socket: socketRef.current,
    connected,
    lastMessage,
    error,
    send,
    disconnect,
  };
}
