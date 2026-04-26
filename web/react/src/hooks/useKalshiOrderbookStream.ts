import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';
import { log } from '../ui/logger';

// Debug logging flag - disabled in production
const DEBUG = process.env.NODE_ENV === 'development';

interface OrderbookLevel {
  price: number;
  quantity: number;
}

interface OrderbookData {
  ticker: string;
  yes_bids: OrderbookLevel[];
  yes_asks: OrderbookLevel[];
  no_bids: OrderbookLevel[];
  no_asks: OrderbookLevel[];
  spread_cents: number | null;
  midpoint: number | null;
  source?: string;
}

interface UseKalshiOrderbookStreamOptions {
  depth?: number;
  maxUpdates?: number;
  heartbeatInterval?: number;
}

interface StreamState {
  data: OrderbookData | null;
  connected: boolean;
  error: string | null;
  updates: number;
  lastUpdate: number;
}

export function useKalshiOrderbookStream(
  ticker: string | null,
  options: UseKalshiOrderbookStreamOptions = {}
): StreamState {
  const { depth = 5, maxUpdates = 1000, heartbeatInterval = 30 } = options;
  
  const [state, setState] = useState<StreamState>({
    data: null,
    connected: false,
    error: null,
    updates: 0,
    lastUpdate: 0,
  });

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const updateCountRef = useRef(0);

  const connect = useCallback(() => {
    if (!ticker) return;

    // Cleanup existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const streamUrl = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERBOOK_STREAM(ticker)}?max_updates=${maxUpdates}&heartbeat_interval=${heartbeatInterval}`;
    
    try {
      const eventSource = new EventSource(streamUrl);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        log.info(`Orderbook stream connected for ${ticker}`, null, 'useKalshiOrderbookStream');
        setState(prev => ({
          ...prev,
          connected: true,
          error: null,
        }));
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          setState(prev => ({
            ...prev,
            data: {
              ...data,
              // Limit depth for performance
              yes_bids: data.yes_bids?.slice(0, depth) || [],
              yes_asks: data.yes_asks?.slice(0, depth) || [],
              no_bids: data.no_bids?.slice(0, depth) || [],
              no_asks: data.no_asks?.slice(0, depth) || [],
            },
            updates: ++updateCountRef.current,
            lastUpdate: Date.now(),
            error: null,
          }));
        } catch (error) {
          log.error('Failed to parse orderbook stream data', error, 'useKalshiOrderbookStream');
          setState(prev => ({
            ...prev,
            error: 'Failed to parse stream data',
          }));
        }
      };

      eventSource.addEventListener('snapshot', (event) => {
        try {
          const data = JSON.parse(event.data);
          if (DEBUG) log.debug('Orderbook snapshot received', { ticker });
          setState(prev => ({
            ...prev,
            data: {
              ...data,
              yes_bids: data.yes_bids?.slice(0, depth) || [],
              yes_asks: data.yes_asks?.slice(0, depth) || [],
              no_bids: data.no_bids?.slice(0, depth) || [],
              no_asks: data.no_asks?.slice(0, depth) || [],
            },
            updates: ++updateCountRef.current,
            lastUpdate: Date.now(),
          }));
        } catch (error) {
          log.error('Failed to parse orderbook snapshot', { error: String(error), ticker });
        }
      });

      eventSource.addEventListener('delta', (event) => {
        try {
          const delta = JSON.parse(event.data);
          if (DEBUG) log.debug('Orderbook delta received', { ticker, levels: delta.yes_bids?.length });
          
          setState(prev => {
            if (!prev.data) return prev;
            
            // Apply delta to current orderbook
            const updatedData = { ...prev.data };
            
            // This is a simplified delta application - in production,
            // you'd want more sophisticated orderbook merging
            if (delta.side && delta.price && delta.size_delta !== undefined) {
              // Map side and bid/ask to correct array
              // side: 'yes' or 'no', bid_ask: 'bid' or 'ask'
              const isYes = delta.side === 'yes';
              const isBid = delta.bid_ask === 'bid' || delta.bid_ask === 'yes_bid';
              
              const sideKey = isYes 
                ? (isBid ? 'yes_bids' : 'yes_asks')
                : (isBid ? 'no_bids' : 'no_asks');
              
              const levels = [...(updatedData[sideKey] || [])];
              
              // Find existing price level or add new one
              const existingIndex = levels.findIndex(l => l.price === delta.price);
              if (existingIndex >= 0) {
                const newQuantity = levels[existingIndex].quantity + delta.size_delta;
                if (newQuantity <= 0) {
                  levels.splice(existingIndex, 1);
                } else {
                  levels[existingIndex] = { ...levels[existingIndex], quantity: newQuantity };
                }
              } else if (delta.size_delta > 0) {
                levels.push({ price: delta.price, quantity: delta.size_delta });
                // Sort bids descending (highest first), asks ascending (lowest first)
                const isBidSide = sideKey.includes('bids');
                levels.sort((a, b) => isBidSide ? b.price - a.price : a.price - b.price);
              }
              
              updatedData[sideKey] = levels.slice(0, depth);
            }
            
            return {
              ...prev,
              data: updatedData,
              updates: ++updateCountRef.current,
              lastUpdate: Date.now(),
            };
          });
        } catch (error) {
          log.error('Failed to parse orderbook delta', { error: String(error), ticker });
        }
      });

      eventSource.addEventListener('heartbeat', (event) => {
        try {
          const data = JSON.parse(event.data);
          // Heartbeat received - no action needed
        } catch (error) {
          // Heartbeat parsing errors are not critical
        }
      });

      eventSource.addEventListener('error', (event) => {
        log.error('Orderbook stream error', { ticker, type: 'sse' });
        setState(prev => ({
          ...prev,
          connected: false,
          error: 'Stream connection error',
        }));
        
        // Auto-reconnect after delay
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          if (DEBUG) log.debug('Reconnecting orderbook stream', { ticker });
          connect();
        }, 5000);
      });

      eventSource.addEventListener('closed', (event) => {
        if (DEBUG) log.debug('Orderbook stream closed', { ticker });
        setState(prev => ({
          ...prev,
          connected: false,
        }));
      });

    } catch (error) {
      log.error('Failed to create EventSource', { error: String(error), ticker });
      setState(prev => ({
        ...prev,
        connected: false,
        error: 'Failed to create stream connection',
      }));
    }
  }, [ticker, depth, maxUpdates, heartbeatInterval]);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    setState(prev => ({
      ...prev,
      connected: false,
    }));
  }, []);

  // Auto-connect when ticker changes
  useEffect(() => {
    if (ticker) {
      connect();
    } else {
      disconnect();
    }

    return disconnect;
  }, [ticker, connect, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return disconnect;
  }, [disconnect]);

  return state;
}
