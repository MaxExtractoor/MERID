/**
 * useKalshiData - Unified Kalshi data fetching hook
 * 
 * Consolidates multiple Kalshi-specific hooks into one configurable primitive:
 * - useKalshiCryptoSignals (REST API with polling)
 * - useKalshiRiskStream (WebSocket)
 * - useKalshiEquitySeries (REST API)
 * - useKalshiExecutionTelemetry (REST API)
 * - useKalshiOrderbookStream (WebSocket)
 * - useKalshiPaperVsShadow (REST API)
 * 
 * Uses useApiData for REST and custom WebSocket logic for real-time streams.
 * Integrates with useVisibility for intelligent polling.
 * 
 * Tier 3: Kalshi Hooks Consolidation
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useApiData } from './useApiData';
import { useVisibility } from './useVisibility';
import { API_ENDPOINTS, DEFAULTS, WS_PORTFOLIO_URL, AUTH_TOKEN_KEY } from '../config/constants';

export interface UseKalshiDataOptions {
  /**
   * Data source type
   */
  source: 'crypto-signals' | 'risk-stream' | 'equity-series' | 'execution-telemetry' | 'orderbook-stream' | 'paper-vs-shadow' | 'custom';
  
  /**
   * Custom endpoint (for 'custom' source)
   */
  endpoint?: string;
  
  /**
   * Polling interval in milliseconds (for REST API sources)
   */
  pollingInterval?: number;
  
  /**
   * Whether polling is enabled
   */
  enabled?: boolean;
  
  /**
   * Custom WebSocket URL (for WebSocket sources)
   */
  wsUrl?: string;
  
  /**
   * Data transformation function
   */
  transform?: (data: any) => any;
  
  /**
   * Error handler
   */
  onError?: (error: Error) => void;
}

/**
 * useKalshiData hook - Unified Kalshi data fetching
 */
export function useKalshiData<T>(options: UseKalshiDataOptions) {
  const {
    source,
    endpoint,
    pollingInterval = DEFAULTS.POLLING_INTERVALS.PORTFOLIO,
    enabled = true,
    wsUrl,
    transform,
    onError,
  } = options;
  
  const [wsData, setWsData] = useState<T | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsError, setWsError] = useState<Error | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isVisible = useVisibility();
  
  // Resolve endpoint based on source type
  const resolveEndpoint = useCallback((): string => {
    if (endpoint) return endpoint;
    
    switch (source) {
      case 'crypto-signals':
        return '/api/v1/kalshi-grid/crypto/edge';
      case 'equity-series':
        return API_ENDPOINTS.KALSHI_EQUITY_SERIES;
      case 'execution-telemetry':
        return '/api/v1/kalshi/execution-telemetry';
      case 'paper-vs-shadow':
        return '/api/v1/kalshi/paper-vs-shadow';
      default:
        return endpoint || '';
    }
  }, [source, endpoint]);
  
  // Resolve WebSocket URL based on source type
  const resolveWsUrl = useCallback((): string => {
    if (wsUrl) return wsUrl;
    
    switch (source) {
      case 'risk-stream':
        return WS_PORTFOLIO_URL || 'ws://127.0.0.1:8011/ws/risk';
      case 'orderbook-stream':
        return 'ws://127.0.0.1:8011/ws/orderbook';
      default:
        return '';
    }
  }, [source, wsUrl]);
  
  // WebSocket connection logic
  useEffect(() => {
    if (!enabled || source !== 'risk-stream' && source !== 'orderbook-stream') {
      return;
    }
    
    const url = resolveWsUrl();
    if (!url) return;
    
    const connect = () => {
      if (!mountedRef.current) return;
      
      try {
        const token = localStorage.getItem(AUTH_TOKEN_KEY);
        const wsUrlWithToken = token ? `${url}?token=${encodeURIComponent(token)}` : url;
        const ws = new WebSocket(wsUrlWithToken);
        wsRef.current = ws;
        
        ws.onopen = () => {
          if (!mountedRef.current) { ws.close(); return; }
          retriesRef.current = 0;
          setWsConnected(true);
          setWsError(null);
          
          // Subscribe to relevant channels
          if (source === 'risk-stream') {
            ws.send(JSON.stringify({
              subscribe: ['risk_summary', 'risk_alert', 'kill_switch', 'portfolio_breach', 'agent_rollback']
            }));
          } else if (source === 'orderbook-stream') {
            ws.send(JSON.stringify({ subscribe: ['orderbook'] }));
          }
        };
        
        ws.onclose = () => {
          if (!mountedRef.current) return;
          setWsConnected(false);
          wsRef.current = null;
          // Reconnect with exponential backoff
          retriesRef.current += 1;
          const jitter = Math.random() * 1000;
          const timeout = Math.min(1000 * 2 ** Math.min(retriesRef.current, 8), 30_000) + jitter;
          reconnectTimerRef.current = setTimeout(connect, timeout);
        };
        
        ws.onerror = () => {
          if (!mountedRef.current) return;
          const error = new Error('WebSocket error');
          setWsError(error);
          onError?.(error);
          ws.close();
        };
        
        ws.onmessage = (event) => {
          if (!mountedRef.current) return;
          try {
            const data = JSON.parse(event.data);
            
            // Handle pong/heartbeat
            if (data.event === 'pong' || data.type === 'pong' || data.event_type === 'heartbeat') {
              return;
            }
            
            // Transform and set data
            const transformedData = transform ? transform(data) : data;
            setWsData(transformedData);
          } catch (error) {
            const err = error instanceof Error ? error : new Error('Failed to parse WebSocket message');
            setWsError(err);
            onError?.(err);
          }
        };
      } catch (error) {
        const err = error instanceof Error ? error : new Error('Failed to create WebSocket');
        setWsError(err);
        onError?.(err);
        // Retry
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
        try { ws.close(); } catch { /* ignore */ }
      }
    };
  }, [enabled, source, resolveWsUrl, transform, onError]);
  
  // REST API data fetching (useApiData)
  const apiData = useApiData<T>(
    resolveEndpoint(),
    {
      enabled: enabled && source !== 'risk-stream' && source !== 'orderbook-stream',
      pollingInterval: isVisible ? pollingInterval : undefined, // Only poll when visible
      transform,
    }
  );
  
  // Return appropriate data based on source type
  if (source === 'risk-stream' || source === 'orderbook-stream') {
    return {
      data: wsData,
      loading: !wsData && !wsError,
      error: wsError,
      connected: wsConnected,
      refetch: () => {
        // WebSocket doesn't have refetch, but we can reconnect
        if (wsRef.current) {
          try { wsRef.current.close(); } catch { /* ignore */ }
        }
      },
    };
  }
  
  return apiData;
}

/**
 * Convenience hooks for common Kalshi data sources
 */
export function useKalshiCryptoSignals() {
  return useKalshiData({
    source: 'crypto-signals',
    pollingInterval: 5000,
  });
}

export function useKalshiRiskStream() {
  return useKalshiData({
    source: 'risk-stream',
  });
}

export function useKalshiEquitySeries() {
  return useKalshiData({
    source: 'equity-series',
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
}
