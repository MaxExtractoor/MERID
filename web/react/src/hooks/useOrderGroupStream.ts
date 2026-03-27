/**
 * useOrderGroupStream.ts — React hook for real-time order group updates via SSE.
 *
 * Provides:
 * - Real-time order group lifecycle updates (snapshot/delta/triggered)
 * - Automatic reconnection with exponential backoff
 * - Client-side filtering by group IDs
 * - Connection state management
 *
 * Usage:
 *   const { groups, alerts, isConnected, error } = useOrderGroupStream({
 *     groupIds: ['og-1', 'og-2'], // Optional: filter specific groups
 *     autoConnect: true,
 *     onTriggered: (groupId, data) => console.log('Triggered:', groupId),
 *   });
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface OrderGroupUpdate {
  order_group_id: string;
  status: string;
  contracts_limit?: number;
  matched_contracts?: number;
  used_contracts?: number;
  filled_cost?: number;
  remaining_cost?: number;
  update_type: 'snapshot' | 'delta';
  ts: string;
}

export interface OrderGroupAlert {
  level: 'warning' | 'critical' | 'info';
  type: string;
  order_group_id: string;
  message: string;
}

export interface UseOrderGroupStreamOptions {
  /** Specific group IDs to watch (undefined = watch all) */
  groupIds?: string[];
  /** Auto-connect on mount */
  autoConnect?: boolean;
  /** Max reconnection attempts */
  maxReconnectAttempts?: number;
  /** Base delay for exponential backoff (ms) */
  reconnectDelayMs?: number;
  /** Callback when a group is triggered */
  onTriggered?: (groupId: string, data: OrderGroupUpdate) => void;
  /** Callback on connection error */
  onError?: (error: Error) => void;
  /** Callback on successful connection */
  onConnect?: () => void;
}

export interface UseOrderGroupStreamReturn {
  /** Current order group states by ID */
  groups: Record<string, OrderGroupUpdate>;
  /** Active alerts from monitored groups */
  alerts: OrderGroupAlert[];
  /** Whether SSE connection is active */
  isConnected: boolean;
  /** Current connection error if any */
  error: Error | null;
  /** Manual connect function */
  connect: () => void;
  /** Manual disconnect function */
  disconnect: () => void;
  /** Connection attempt count */
  reconnectAttempts: number;
}

/**
 * React hook for real-time order group updates via Server-Sent Events.
 * 
 * Connects to /api/v1/kalshi/order-groups/stream and receives:
 * - snapshot: Full group state (first message per group)
 * - delta: Incremental updates
 * - triggered: Group triggered event (auto-cancel occurred)
 * - heartbeat: Periodic keepalive
 */
export function useOrderGroupStream(
  options: UseOrderGroupStreamOptions = {}
): UseOrderGroupStreamReturn {
  const {
    groupIds,
    autoConnect = true,
    maxReconnectAttempts = 10,
    reconnectDelayMs = 1000,
    onTriggered,
    onError,
    onConnect,
  } = options;

  const [groups, setGroups] = useState<Record<string, OrderGroupUpdate>>({});
  const [alerts, setAlerts] = useState<OrderGroupAlert[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isManualDisconnectRef = useRef(false);

  // Build SSE URL with optional group filter
  const buildUrl = useCallback(() => {
    const params = new URLSearchParams();
    if (groupIds && groupIds.length > 0) {
      params.set('group_ids', groupIds.join(','));
    }
    params.set('max_updates', '10000');
    params.set('heartbeat_interval', '30');
    
    const query = params.toString();
    return `${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_GROUP_STREAM}${query ? `?${query}` : ''}`;
  }, [groupIds]);

  // Clear all alerts for a specific group
  const clearAlertsForGroup = useCallback((groupId: string) => {
    setAlerts(prev => prev.filter(a => a.order_group_id !== groupId));
  }, []);

  // Connect to SSE endpoint
  const connect = useCallback(() => {
    if (eventSourceRef.current?.readyState === EventSource.OPEN) {
      return; // Already connected
    }

    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    isManualDisconnectRef.current = false;
    setError(null);

    const url = buildUrl();
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
      setReconnectAttempts(0);
      onConnect?.();
    };

    es.addEventListener('snapshot', (event) => {
      try {
        const data: OrderGroupUpdate = JSON.parse(event.data);
        setGroups(prev => ({
          ...prev,
          [data.order_group_id]: data,
        }));
        clearAlertsForGroup(data.order_group_id);
      } catch (e) {
        console.error('Failed to parse snapshot:', e);
      }
    });

    es.addEventListener('delta', (event) => {
      try {
        const data: OrderGroupUpdate = JSON.parse(event.data);
        setGroups(prev => ({
          ...prev,
          [data.order_group_id]: {
            ...prev[data.order_group_id],
            ...data,
          },
        }));
      } catch (e) {
        console.error('Failed to parse delta:', e);
      }
    });

    es.addEventListener('triggered', (event) => {
      try {
        const data: OrderGroupUpdate = JSON.parse(event.data);
        setGroups(prev => ({
          ...prev,
          [data.order_group_id]: data,
        }));
        
        // Add alert
        const alert: OrderGroupAlert = {
          level: 'critical',
          type: 'group_triggered',
          order_group_id: data.order_group_id,
          message: `Order group ${data.order_group_id} triggered - orders auto-canceled`,
        };
        setAlerts(prev => [alert, ...prev].slice(0, 50)); // Keep last 50

        // Call callback
        onTriggered?.(data.order_group_id, data);
      } catch (e) {
        console.error('Failed to parse triggered event:', e);
      }
    });

    es.addEventListener('heartbeat', (event) => {
      // Heartbeat received - connection is alive
      try {
        const data = JSON.parse(event.data);
        // Could track last heartbeat time here if needed
      } catch {
        // Heartbeat doesn't have JSON payload, just an event
      }
    });

    es.addEventListener('error', (event) => {
      const err = new Error('SSE connection error');
      setError(err);
      setIsConnected(false);
      onError?.(err);

      // Attempt reconnection with exponential backoff
      if (!isManualDisconnectRef.current && reconnectAttempts < maxReconnectAttempts) {
        const delay = Math.min(
          reconnectDelayMs * Math.pow(2, reconnectAttempts),
          30000 // Max 30s delay
        );
        
        setReconnectAttempts(prev => prev + 1);
        
        reconnectTimeoutRef.current = setTimeout(() => {
          if (!isManualDisconnectRef.current) {
            connect();
          }
        }, delay);
      }
    });

    es.addEventListener('closed', () => {
      setIsConnected(false);
    });

  }, [buildUrl, onConnect, onError, onTriggered, clearAlertsForGroup, reconnectAttempts, maxReconnectAttempts, reconnectDelayMs]);

  // Disconnect from SSE
  const disconnect = useCallback(() => {
    isManualDisconnectRef.current = true;
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(false);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  // Reconnect when groupIds change
  useEffect(() => {
    if (isConnected && groupIds) {
      disconnect();
      connect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupIds?.join(',')]);

  return {
    groups,
    alerts,
    isConnected,
    error,
    connect,
    disconnect,
    reconnectAttempts,
  };
}

export default useOrderGroupStream;
