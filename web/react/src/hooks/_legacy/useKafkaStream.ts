/**
 * useKafkaStream - WebSocket hook for streaming Kafka-backed events.
 * 
 * Provides a unified interface for subscribing to MERID's streaming topics
 * via WebSocket, with automatic reconnection, message deduplication,
 * and state management keyed by symbol or custom key.
 * 
 * Usage:
 *   const { events, connected, subscribe } = useKafkaStream('/ws/trades');
 *   
 * Or with keyed state:
 *   const { eventsByKey } = useKafkaStream('/ws/prices', { keyBy: 'symbol' });
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { logUiError } from '../utils/logger';

// ============================================
// TYPES
// ============================================

export interface StreamEvent {
  event_id: string;
  event_type: string;
  timestamp: number;
  source: string;
  topic?: string;
  partition_key?: string;
  payload: Record<string, unknown>;
  schema_version?: string;
  correlation_id?: string;
}

export type StreamStatus = 
  | 'connecting' 
  | 'connected' 
  | 'disconnected' 
  | 'unavailable' 
  | 'max_retries_exceeded';

export interface UseKafkaStreamOptions {
  /** Field to use as key for eventsByKey map (e.g., 'symbol') */
  keyBy?: string;
  /** Maximum events to retain in state */
  maxEvents?: number;
  /** Auto-connect on mount */
  autoConnect?: boolean;
  /** Initial reconnect delay in ms (default: 2000) */
  reconnectDelay?: number;
  /** Maximum reconnect attempts (default: 5, 0 = infinite) */
  maxReconnectAttempts?: number;
  /** Maximum reconnect delay in ms (default: 30000) */
  maxReconnectDelay?: number;
  /** Filter events by type */
  filterTypes?: string[];
  /** Deduplicate by event_id */
  deduplicate?: boolean;
  /** Custom message parser */
  parseMessage?: (data: unknown) => StreamEvent | null;
}

export interface UseKafkaStreamResult<T = StreamEvent> {
  /** All events in arrival order (newest first) */
  events: T[];
  /** Events grouped by key (if keyBy option provided) */
  eventsByKey: Record<string, T[]>;
  /** Latest event per key */
  latestByKey: Record<string, T>;
  /** WebSocket connection status */
  connected: boolean;
  /** Stream status (more detailed than connected) */
  status: StreamStatus;
  /** Connection error if any */
  error: Error | null;
  /** Reason if stream is unavailable */
  unavailableReason?: string;
  /** Manually connect */
  connect: () => void;
  /** Manually disconnect */
  disconnect: () => void;
  /** Send a message to the server */
  send: (message: unknown) => void;
  /** Clear all events */
  clear: () => void;
  /** Reconnect attempt count */
  reconnectCount: number;
}

// ============================================
// HOOK IMPLEMENTATION
// ============================================

/**
 * Subscribe to a streaming WebSocket endpoint and manage event state.
 */
export function useKafkaStream<T extends StreamEvent = StreamEvent>(
  endpoint: string,
  options: UseKafkaStreamOptions = {}
): UseKafkaStreamResult<T> {
  const {
    keyBy,
    maxEvents = 500,
    autoConnect = true,
    reconnectDelay = 2000,
    maxReconnectAttempts = 5,
    maxReconnectDelay = 30000,
    filterTypes,
    deduplicate = true,
    parseMessage,
  } = options;

  // State
  const [events, setEvents] = useState<T[]>([]);
  const [eventsByKey, setEventsByKey] = useState<Record<string, T[]>>({});
  const [latestByKey, setLatestByKey] = useState<Record<string, T>>({});
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<StreamStatus>('disconnected');
  const [error, setError] = useState<Error | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<string | undefined>();
  const [reconnectCount, setReconnectCount] = useState(0);

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const mountedRef = useRef(true);
  const hasLoggedErrorRef = useRef(false);
  const currentRetryRef = useRef(0);
  const isUnavailableRef = useRef(false);
  const connectCalledRef = useRef(false);

  // Build WebSocket URL
  const getWsUrl = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port || (protocol === 'wss:' ? '443' : '80');
    return `${protocol}//${host}:${port}${endpoint}`;
  }, [endpoint]);

  // Parse incoming message
  const handleMessage = useCallback((data: unknown): T | null => {
    let event: T | null = null;

    if (parseMessage) {
      event = parseMessage(data) as T | null;
    } else {
      // Default parsing
      if (typeof data === 'string') {
        try {
          event = JSON.parse(data) as T;
        } catch {
          return null;
        }
      } else if (typeof data === 'object' && data !== null) {
        event = data as T;
      } else {
        return null;
      }
    }

    if (!event || typeof event !== 'object') {
      return null;
    }

    // Filter by type
    if (filterTypes && filterTypes.length > 0) {
      if (!filterTypes.includes(event.event_type)) {
        return null;
      }
    }

    // Skip heartbeats by default
    if (event.event_type === 'heartbeat' || event.event_type === 'ping') {
      return null;
    }

    // Deduplicate
    if (deduplicate && event.event_id) {
      if (seenIdsRef.current.has(event.event_id)) {
        return null;
      }
      seenIdsRef.current.add(event.event_id);
      
      // Limit seen IDs set size
      if (seenIdsRef.current.size > maxEvents * 2) {
        const idsArray = Array.from(seenIdsRef.current);
        seenIdsRef.current = new Set(idsArray.slice(-maxEvents));
      }
    }

    return event;
  }, [parseMessage, filterTypes, deduplicate, maxEvents]);

  // Update state with new event
  const addEvent = useCallback((event: T) => {
    if (!mountedRef.current) return;

    // Add to events list
    setEvents(prev => {
      const updated = [event, ...prev];
      return updated.slice(0, maxEvents);
    });

    // Add to keyed collections if keyBy provided
    if (keyBy) {
      const eventRecord = event as unknown as Record<string, unknown>;
      const payloadRecord = (event as StreamEvent).payload as Record<string, unknown> | undefined;
      const keyValue = eventRecord[keyBy] ?? payloadRecord?.[keyBy];
      const key = typeof keyValue === 'string' ? keyValue : keyValue != null ? String(keyValue) : null;
      if (key) {
        setEventsByKey(prev => {
          const keyEvents = prev[key] || [];
          const updated = [event, ...keyEvents].slice(0, 100);
          return { ...prev, [key]: updated };
        });

        setLatestByKey(prev => ({
          ...prev,
          [key]: event,
        }));
      }
    }
  }, [keyBy, maxEvents]);

  // Calculate backoff delay with jitter
  const calculateBackoffDelay = useCallback((attempt: number): number => {
    const baseDelay = Math.min(
      reconnectDelay * Math.pow(2, attempt),
      maxReconnectDelay
    );
    // Add up to 30% jitter
    const jitter = baseDelay * 0.3 * Math.random();
    return Math.floor(baseDelay + jitter);
  }, [reconnectDelay, maxReconnectDelay]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    // Don't connect if unavailable or max retries exceeded
    if (isUnavailableRef.current || currentRetryRef.current >= maxReconnectAttempts) {
      return;
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const url = getWsUrl();
    
    // Only log on first attempt or after successful connection
    if (currentRetryRef.current === 0) {
      console.debug(`[useKafkaStream] Connecting to ${endpoint}`);
    }

    setStatus('connecting');

    try {
      const ws = new WebSocket(url);
      let opened = false;

      ws.onopen = () => {
        opened = true;
        console.debug(`[useKafkaStream] Connected to ${endpoint}`);
        setConnected(true);
        setStatus('connected');
        setError(null);
        setReconnectCount(0);
        currentRetryRef.current = 0;
        hasLoggedErrorRef.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
          
          // Check for feature_unavailable message from server
          if (data.type === 'feature_unavailable') {
            const reason = data.reason || 'Feature not available';
            console.debug(`[useKafkaStream] ${endpoint} unavailable: ${reason}`);
            isUnavailableRef.current = true;
            setStatus('unavailable');
            setUnavailableReason(reason);
            ws.close(1000, 'Feature unavailable');
            return;
          }

          const parsed = handleMessage(event.data);
          if (parsed) {
            addEvent(parsed);
          }
        } catch {
          const parsed = handleMessage(event.data);
          if (parsed) {
            addEvent(parsed);
          }
        }
      };

      ws.onerror = () => {
        // Only log error once per session to reduce noise
        if (!hasLoggedErrorRef.current) {
          hasLoggedErrorRef.current = true;
          console.warn(`[useKafkaStream] Connection failed for ${endpoint} - stream may not be available`);
        }
        setError(new Error('WebSocket error'));
      };

      ws.onclose = () => {
        wsRef.current = null;
        setConnected(false);

        // Don't reconnect if unavailable
        if (isUnavailableRef.current) {
          return;
        }

        // Check if we've exceeded max retries
        if (maxReconnectAttempts > 0 && currentRetryRef.current >= maxReconnectAttempts) {
          console.debug(`[useKafkaStream] ${endpoint} - max retries (${maxReconnectAttempts}) exceeded, stopping`);
          setStatus('max_retries_exceeded');
          return;
        }

        // Schedule reconnect with exponential backoff
        if (mountedRef.current) {
          // If WS never opened, connection itself failed — give up faster
          if (!opened) {
            currentRetryRef.current += 2;
          }
          currentRetryRef.current++;
          setReconnectCount(currentRetryRef.current);
          const delay = calculateBackoffDelay(currentRetryRef.current);
          
          // Only log first few reconnects
          if (currentRetryRef.current <= 3) {
            console.debug(`[useKafkaStream] Reconnecting to ${endpoint} in ${delay}ms (attempt ${currentRetryRef.current}/${maxReconnectAttempts})`);
          }

          setStatus('disconnected');
          reconnectTimeoutRef.current = setTimeout(connect, delay);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      if (!hasLoggedErrorRef.current) {
        hasLoggedErrorRef.current = true;
        logUiError('useKafkaStream', `Failed to connect to ${endpoint}`, err);
      }
      setError(err as Error);
      setStatus('disconnected');
    }
  }, [getWsUrl, endpoint, handleMessage, addEvent, maxReconnectAttempts, calculateBackoffDelay]);

  // Disconnect
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      wsRef.current = null;
    }

    setConnected(false);
  }, []);

  // Send message
  const send = useCallback((message: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const payload = typeof message === 'string' ? message : JSON.stringify(message);
      wsRef.current.send(payload);
    } else {
      console.warn('[useKafkaStream] Cannot send - not connected');
    }
  }, []);

  // Clear events
  const clear = useCallback(() => {
    setEvents([]);
    setEventsByKey({});
    setLatestByKey({});
    seenIdsRef.current.clear();
  }, []);

  // Stable ref for connect so the effect doesn't re-fire on every render
  const connectRef = useRef(connect);
  connectRef.current = connect;
  const disconnectRef = useRef(disconnect);
  disconnectRef.current = disconnect;

  // Auto-connect on mount only (stable deps — no infinite loop)
  useEffect(() => {
    mountedRef.current = true;

    if (autoConnect && !connectCalledRef.current) {
      connectCalledRef.current = true;
      connectRef.current();
    }

    return () => {
      mountedRef.current = false;
      connectCalledRef.current = false;
      disconnectRef.current();
    };
  }, [autoConnect, endpoint]);

  return {
    events,
    eventsByKey,
    latestByKey,
    connected,
    status,
    error,
    unavailableReason,
    connect,
    disconnect,
    send,
    clear,
    reconnectCount,
  };
}

// ============================================
// SPECIALIZED HOOKS
// ============================================

/** Hook for trade events */
export function useTradeEvents(options?: Omit<UseKafkaStreamOptions, 'filterTypes'>) {
  return useKafkaStream('/ws/trades', {
    ...options,
    keyBy: 'symbol',
    filterTypes: ['order_submitted', 'order_filled', 'order_cancelled', 'agent_decision'],
  });
}

/** Hook for price events */
export function usePriceStream(options?: Omit<UseKafkaStreamOptions, 'keyBy'>) {
  return useKafkaStream('/ws/prices', {
    ...options,
    keyBy: 'symbol',
  });
}

function parseConsensusStreamMessage(data: unknown): StreamEvent | null {
  let message: unknown = data;

  if (typeof data === 'string') {
    try {
      message = JSON.parse(data);
    } catch {
      return null;
    }
  }

  if (!message || typeof message !== 'object') {
    return null;
  }

  const messageRecord = message as Record<string, unknown>;
  const eventType = typeof messageRecord.event_type === 'string' ? messageRecord.event_type : null;
  if (eventType) {
    const payloadRecord = (messageRecord.payload && typeof messageRecord.payload === 'object')
      ? (messageRecord.payload as Record<string, unknown>)
      : messageRecord;
    const timestamp = typeof messageRecord.timestamp === 'number'
      ? messageRecord.timestamp
      : Date.now() / 1000;
    return {
      event_id: String(messageRecord.event_id || messageRecord.id || `${eventType}_${timestamp}`),
      event_type: eventType,
      timestamp,
      source: typeof messageRecord.source === 'string' ? messageRecord.source : 'consensus',
      payload: payloadRecord,
    } as StreamEvent;
  }

  const type = typeof messageRecord.type === 'string' ? messageRecord.type : null;
  const payload = messageRecord.data;
  if (type && payload && typeof payload === 'object') {
    const payloadRecord = payload as Record<string, unknown>;
    const timestamp = typeof messageRecord.ts === 'number'
      ? messageRecord.ts
      : typeof payloadRecord.timestamp === 'number'
        ? payloadRecord.timestamp
        : Date.now() / 1000;

    return {
      event_id: String(payloadRecord.opinion_id || payloadRecord.plan_id || payloadRecord.round_id || `${type}_${timestamp}`),
      event_type: type,
      timestamp,
      source: 'consensus',
      payload: payloadRecord,
    } as StreamEvent;
  }

  return null;
}

/** Hook for agent opinions */
export function useAgentOpinions(options?: UseKafkaStreamOptions) {
  return useKafkaStream('/api/v1/consensus/ws/stream', {
    ...options,
    keyBy: 'agent_id',
    filterTypes: ['opinion'],
    parseMessage: parseConsensusStreamMessage,
  });
}

/** Hook for consensus updates */
export function useConsensusStream(options?: UseKafkaStreamOptions) {
  return useKafkaStream('/api/v1/consensus/ws/stream', {
    ...options,
    parseMessage: parseConsensusStreamMessage,
  });
}

export default useKafkaStream;
