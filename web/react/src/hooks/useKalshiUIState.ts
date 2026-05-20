/**
 * useKalshiUIState — Hook for consuming canonical Kalshi UI state
 *
 * Provides single source of truth for all Kalshi operational state.
 * Uses the /api/v1/kalshi/ui-state endpoint for aggregated data.
 * WebSocket integration for real-time updates with reconnection and deduplication.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useApiData } from './useApiData';
import { API_ENDPOINTS, DEFAULTS, WS_URL } from '../config/constants';
import type { KalshiUIState, UIStateEvent } from '../types/kalshiUIState';

interface UseKalshiUIStateOptions {
  enableWebSocket?: boolean;
  pollingInterval?: number;
}

interface UseKalshiUIStateReturn {
  state: KalshiUIState | null;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refetch: () => void;
  connected: boolean;
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
}

// Event deduplication tracking
const eventSequences = new Map<string, number>(); // event_id -> last seen sequence

function shouldProcessEvent(eventId: string, sequence: number): boolean {
  const lastSequence = eventSequences.get(eventId);
  if (lastSequence === undefined || sequence > lastSequence) {
    eventSequences.set(eventId, sequence);
    return true;
  }
  return false;
}

export function useKalshiUIState(options: UseKalshiUIStateOptions = {}): UseKalshiUIStateReturn {
  const {
    enableWebSocket = false,
    pollingInterval = DEFAULTS.POLLING_INTERVALS.STANDARD,
  } = options;

  // HTTP polling state
  const { data, loading, error, refetch } = useApiData<KalshiUIState>(
    API_ENDPOINTS.KALSHI_UI_STATE,
    { pollingInterval }
  );

  // Local state for WebSocket updates
  const [state, setState] = useState<KalshiUIState | null>(null);
  const [connected, setConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Sync HTTP data to local state
  useEffect(() => {
    if (data) {
      setState(data);
    }
  }, [data]);

  // WebSocket connection with exponential backoff reconnection
  const connectWebSocket = useCallback(() => {
    if (!enableWebSocket) return;

    setConnectionStatus('connecting');

    try {
      const wsUrl = WS_URL.replace('/ws/trades', API_ENDPOINTS.KALSHI_UI_STATE_WS);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setConnectionStatus('connected');
        reconnectAttemptsRef.current = 0;
        console.log('[useKalshiUIState] WebSocket connected');

        // Start ping/pong heartbeat (every 30 seconds)
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', timestamp: new Date().toISOString() }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as UIStateEvent;
          
          // Handle ping/pong
          if (message.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', timestamp: new Date().toISOString() }));
            return;
          }
          if (message.type === 'pong') {
            // Reset reconnection attempts on successful pong
            reconnectAttemptsRef.current = 0;
            return;
          }

          // Deduplicate events using event_id and sequence
          const eventId = (message.data as any).event_id || (message.data as any).id || message.type;
          const sequence = (message.data as any).sequence || Date.now();
          
          if (!shouldProcessEvent(eventId, sequence)) {
            console.log('[useKalshiUIState] Skipping duplicate event:', eventId, sequence);
            return;
          }

          // Update state based on event type
          setState((prevState) => {
            if (!prevState) return prevState;

            switch (message.type) {
              case 'fill':
                return {
                  ...prevState,
                  markets: {
                    ...prevState.markets,
                    recent_fills: [message.data, ...prevState.markets.recent_fills].slice(0, 10),
                  },
                };
              case 'order':
                return {
                  ...prevState,
                  markets: {
                    ...prevState.markets,
                    recent_orders: [message.data, ...prevState.markets.recent_orders].slice(0, 10),
                  },
                };
              case 'risk_alert':
                return {
                  ...prevState,
                  risk: {
                    ...prevState.risk,
                    recent_alerts: [message.data, ...prevState.risk.recent_alerts].slice(0, 20),
                    unacknowledged_alert_count: message.data.acknowledged 
                      ? prevState.risk.unacknowledged_alert_count 
                      : prevState.risk.unacknowledged_alert_count + 1,
                  },
                };
              case 'kill_switch':
                return {
                  ...prevState,
                  system: {
                    ...prevState.system,
                    kill_switch_active: message.data.active,
                    kill_switch_reason: message.data.reason,
                  },
                };
              case 'execution_gate':
                return {
                  ...prevState,
                  system: {
                    ...prevState.system,
                    execution_gate: message.data.state as any,
                    execution_gate_reasons: message.data.reasons,
                  },
                };
              case 'grid_status':
                return {
                  ...prevState,
                  grid: { ...prevState.grid, ...message.data },
                };
              case 'capital_update':
                return {
                  ...prevState,
                  capital: { ...prevState.capital, ...message.data },
                };
              default:
                return prevState;
            }
          });
        } catch (err) {
          console.error('[useKalshiUIState] Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = (error) => {
        console.error('[useKalshiUIState] WebSocket error:', error);
        setConnected(false);
        setConnectionStatus('error');
      };

      ws.onclose = () => {
        setConnected(false);
        setConnectionStatus('disconnected');
        console.log('[useKalshiUIState] WebSocket closed');
        
        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Exponential backoff reconnection
        const backoffDelay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current += 1;
        
        console.log(`[useKalshiUIState] Reconnecting in ${backoffDelay}ms (attempt ${reconnectAttemptsRef.current})`);
        
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket();
        }, backoffDelay);
      };
    } catch (err) {
      console.error('[useKalshiUIState] Failed to create WebSocket:', err);
      setConnected(false);
      setConnectionStatus('error');
    }
  }, [enableWebSocket]);

  useEffect(() => {
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
    };
  }, [connectWebSocket]);

  const lastUpdated = state ? new Date(state.timestamp) : null;

  return {
    state,
    loading,
    error: error ? String(error) : null,
    lastUpdated,
    refetch,
    connected,
    connectionStatus,
  };
}

/**
 * Hook for lazy-loaded detail data
 */
export function useKalshiDetail<T>(
  endpoint: string | null,
  enabled = true
) {
  return useApiData<T>(
    endpoint ?? '',
    { pollingInterval: enabled ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 }
  );
}
