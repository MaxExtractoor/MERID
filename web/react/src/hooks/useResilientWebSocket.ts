/**
 * Enhanced WebSocket hook with error recovery and HTTP fallback
 * Automatically degrades to HTTP polling when WebSocket fails repeatedly
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { AUTH_TOKEN_KEY } from '../config/constants';

interface UseResilientWebSocketOptions {
  url: string;
  protocols?: string | string[];
  autoConnect?: boolean;
  heartbeatMs?: number;
  pongTimeoutMs?: number;
  autoReconnect?: boolean;
  maxReconnectMs?: number;
  maxReconnectAttempts?: number;
  /** HTTP fallback endpoint for polling when WebSocket fails */
  fallbackHttpEndpoint?: string;
  /** Enable HTTP fallback after N WebSocket failures (default: 3) */
  fallbackAfterFailures?: number;
  /** Polling interval when using HTTP fallback (default: 5000) */
  fallbackPollInterval?: number;
  onMessage?: (data: unknown) => void;
  onError?: (error: Error) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onFallback?: () => void;
}

interface ResilientWebSocketState<T = unknown> {
  socket: WebSocket | null;
  connected: boolean;
  lastMessage: T | null;
  error: Error | null;
  isFallback: boolean;
  fallbackActive: boolean;
  reconnectAttempts: number;
  send: (data: string) => void;
  disconnect: () => void;
  reconnect: () => void;
}

type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'fallback';

export function useResilientWebSocket<T = unknown>(
  options: UseResilientWebSocketOptions
): ResilientWebSocketState<T> {
  const {
    url,
    protocols,
    autoConnect = true,
    heartbeatMs = 30_000,
    pongTimeoutMs = 10_000,
    autoReconnect = true,
    maxReconnectMs = 30_000,
    maxReconnectAttempts: _maxReconnectAttempts = 10,
    fallbackHttpEndpoint,
    fallbackAfterFailures = 3,
    fallbackPollInterval = 5000,
    onMessage,
    onError,
    onConnect,
    onDisconnect,
    onFallback,
  } = options;

  const socketRef = useRef<WebSocket | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [lastMessage, setLastMessage] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isFallback, setIsFallback] = useState(false);

  const mountedRef = useRef(true);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPongRef = useRef<number>(Date.now());
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);
  const fallbackPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    if (pongTimeoutRef.current) {
      clearTimeout(pongTimeoutRef.current);
      pongTimeoutRef.current = null;
    }
  }, []);

  const clearFallback = useCallback(() => {
    if (fallbackPollRef.current) {
      clearInterval(fallbackPollRef.current);
      fallbackPollRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  // HTTP Fallback polling
  const startFallback = useCallback(async () => {
    if (!fallbackHttpEndpoint || !mountedRef.current) return;

    clearFallback();
    setIsFallback(true);
    setConnectionState('fallback');
    onFallback?.();

    const poll = async () => {
      if (!mountedRef.current) return;

      abortControllerRef.current = new AbortController();

      try {
        const token = localStorage.getItem(AUTH_TOKEN_KEY);
        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
        };
        if (token) {
          headers['Authorization'] = `Bearer ${token}`;
        }

        const response = await fetch(fallbackHttpEndpoint, {
          headers,
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (mountedRef.current) {
          setLastMessage(data as T);
          onMessage?.(data);
        }
      } catch (err) {
        if (err instanceof Error && err.name !== 'AbortError') {
          console.error('Fallback poll failed:', err);
        }
      }
    };

    // Initial poll
    poll();

    // Start polling interval
    fallbackPollRef.current = setInterval(poll, fallbackPollInterval);
  }, [fallbackHttpEndpoint, fallbackPollInterval, onMessage, onFallback, clearFallback]);

  // WebSocket connection
  const connect = useCallback(() => {
    if (!mountedRef.current || !url) return;

    // If in fallback mode, don't try WebSocket
    if (isFallback && reconnectAttemptsRef.current >= fallbackAfterFailures) {
      startFallback();
      return;
    }

    setConnectionState('connecting');
    setError(null);

    try {
      const socket = new WebSocket(url, protocols);
      socketRef.current = socket;

      socket.onopen = () => {
        if (!mountedRef.current) {
          socket.close();
          return;
        }

        reconnectAttemptsRef.current = 0;
        setConnectionState('connected');
        setIsFallback(false);
        clearFallback();
        onConnect?.();

        // Start heartbeat
        if (heartbeatMs > 0) {
          heartbeatRef.current = setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'ping' }));

              // Set pong timeout
              pongTimeoutRef.current = setTimeout(() => {
                const elapsed = Date.now() - lastPongRef.current;
                if (elapsed >= heartbeatMs + pongTimeoutMs) {
                  if (mountedRef.current) {
                    setError(new Error('WebSocket heartbeat timeout'));
                    socket.close();
                  }
                }
              }, pongTimeoutMs);
            }
          }, heartbeatMs);
        }
      };

      socket.onmessage = (event) => {
        if (!mountedRef.current) return;

        try {
          const data = JSON.parse(event.data);

          // Handle pong
          if (data.type === 'pong') {
            lastPongRef.current = Date.now();
            return;
          }

          setLastMessage(data as T);
          onMessage?.(data);
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      socket.onclose = () => {
        clearHeartbeat();

        if (!mountedRef.current) return;

        setConnectionState('disconnected');
        onDisconnect?.();
        socketRef.current = null;

        // Auto-reconnect unless intentional close
        if (autoReconnect && !intentionalCloseRef.current) {
          reconnectAttemptsRef.current++;

          // Switch to fallback after max attempts
          if (
            reconnectAttemptsRef.current >= fallbackAfterFailures &&
            fallbackHttpEndpoint
          ) {
            startFallback();
            return;
          }

          // Exponential backoff with jitter
          const jitter = Math.random() * 1000;
          const delay = Math.min(
            1000 * Math.pow(2, Math.min(reconnectAttemptsRef.current, 10)),
            maxReconnectMs
          ) + jitter;

          reconnectTimerRef.current = setTimeout(connect, delay);
        }
      };

      socket.onerror = () => {
        if (!mountedRef.current) return;
        const err = new Error('WebSocket connection error');
        setError(err);
        onError?.(err);
      };
    } catch (err) {
      if (!mountedRef.current) return;

      const error = err instanceof Error ? err : new Error('Failed to create WebSocket');
      setError(error);
      onError?.(error);

      // Try fallback if available
      if (fallbackHttpEndpoint && reconnectAttemptsRef.current >= fallbackAfterFailures) {
        startFallback();
      }
    }
  }, [
    url,
    protocols,
    heartbeatMs,
    pongTimeoutMs,
    autoReconnect,
    maxReconnectMs,
    fallbackAfterFailures,
    fallbackHttpEndpoint,
    isFallback,
    clearHeartbeat,
    startFallback,
    onMessage,
    onError,
    onConnect,
    onDisconnect,
  ]);

  // Initial connection
  useEffect(() => {
    mountedRef.current = true;
    intentionalCloseRef.current = false;

    if (autoConnect) {
      connect();
    }

    return () => {
      mountedRef.current = false;
      clearHeartbeat();
      clearFallback();

      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }

      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        socketRef.current.close();
      }
      socketRef.current = null;
    };
  }, [autoConnect, connect, clearHeartbeat, clearFallback]);

  const send = useCallback((data: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      console.warn('Cannot send: WebSocket not connected');
      return;
    }
    socketRef.current.send(data);
  }, []);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearHeartbeat();
    clearFallback();

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (socketRef.current) {
      socketRef.current.close();
    }

    setConnectionState('disconnected');
    setIsFallback(false);
  }, [clearHeartbeat, clearFallback]);

  const reconnect = useCallback(() => {
    intentionalCloseRef.current = false;
    reconnectAttemptsRef.current = 0;
    setIsFallback(false);
    clearFallback();
    connect();
  }, [connect, clearFallback]);

  return {
    socket: socketRef.current,
    connected: connectionState === 'connected',
    lastMessage,
    error,
    isFallback,
    fallbackActive: connectionState === 'fallback',
    reconnectAttempts: reconnectAttemptsRef.current,
    send,
    disconnect,
    reconnect,
  };
}
