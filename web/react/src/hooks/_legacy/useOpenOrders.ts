import { useState, useEffect, useMemo } from 'react';
import { useApiData } from './useApiData';
import { useMeridSocket } from './useMeridSocket';
import { API_ENDPOINTS } from '../config/constants';
import { logUiError } from '../utils/logger';
import type {
  OrderRow,
  OpenOrdersResponse,
  OrderCreatedPayload,
  OrderUpdatedPayload,
  OrderCanceledPayload,
  OrderCompletedPayload,
} from '../types/orders';

interface UseOpenOrdersReturn {
  rows: OrderRow[];
  meta: {
    total: number;
    pending: number;
    partiallyFilled: number;
    totalNotional: number;
  };
  loading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
}

/**
 * Validate order payload has required fields
 */
function isValidOrderPayload(payload: unknown): payload is { id: string } {
  return typeof payload === 'object' && payload !== null && 'id' in payload;
}

/**
 * useOpenOrders Hook
 * 
 * Fetches open orders via REST and receives live updates via WebSocket.
 * REST: GET /api/v1/orders/open
 * WS Events: order:created, order:updated, order:canceled, order:completed
 */
export function useOpenOrders(): UseOpenOrdersReturn {
  // Track orders as a map for O(1) updates
  const [orders, setOrders] = useState<Record<string, OrderRow>>({});
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Fetch initial data via REST
  const { data, loading, error } = useApiData<OpenOrdersResponse>(
    `${API_ENDPOINTS.ORDERS}/open`,
    { pollingInterval: 5000 } // Poll every 5 seconds as fallback
  );

  // Initialize orders from REST data
  useEffect(() => {
    if (data?.orders) {
      const ordersMap: Record<string, OrderRow> = {};
      data.orders.forEach((order) => {
        ordersMap[order.id] = order;
      });
      setOrders(ordersMap);
      setLastUpdated(new Date());
    }
  }, [data]);

  // WebSocket for real-time updates
  const { socket } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // New order created
    const handleCreated = (payload: OrderCreatedPayload) => {
      if (!isValidOrderPayload(payload)) {
        console.warn('[useOpenOrders] Invalid created payload:', payload);
        return;
      }
      console.info('[useOpenOrders] Order created:', payload.id);
      setOrders((prev) => ({
        ...prev,
        [payload.id]: payload,
      }));
      setLastUpdated(new Date());
    };

    // Order updated (fill or status change)
    const handleUpdated = (payload: OrderUpdatedPayload) => {
      if (!isValidOrderPayload(payload)) {
        console.warn('[useOpenOrders] Invalid updated payload:', payload);
        return;
      }
      setOrders((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          console.warn('[useOpenOrders] Update for unknown order:', payload.id);
          return prev;
        }
        console.info('[useOpenOrders] Order updated:', payload.id, payload.status);
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: {
            ...existing,
            status: payload.status,
            filledSize: payload.filledSize,
            remainingSize: payload.remainingSize,
            ...(payload.price !== undefined && { price: payload.price }),
          },
        };
      });
    };

    // Order canceled
    const handleCanceled = (payload: OrderCanceledPayload) => {
      if (!isValidOrderPayload(payload)) {
        console.warn('[useOpenOrders] Invalid canceled payload:', payload);
        return;
      }
      setOrders((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          console.warn('[useOpenOrders] Cancel for unknown order:', payload.id);
          return prev;
        }
        console.info('[useOpenOrders] Order canceled:', payload.id);
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: {
            ...existing,
            status: payload.status,
          },
        };
      });
    };

    // Order completed (fully filled)
    const handleCompleted = (payload: OrderCompletedPayload) => {
      if (!isValidOrderPayload(payload)) {
        console.warn('[useOpenOrders] Invalid completed payload:', payload);
        return;
      }
      setOrders((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          console.warn('[useOpenOrders] Complete for unknown order:', payload.id);
          return prev;
        }
        console.info('[useOpenOrders] Order completed:', payload.id);
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: {
            ...existing,
            status: payload.status,
            filledSize: payload.filledSize,
          },
        };
      });
    };

    const handleError = (error: Error) => {
      logUiError('useOpenOrders', 'WebSocket error', error);
    };

    socket.on('order:created', handleCreated);
    socket.on('order:updated', handleUpdated);
    socket.on('order:canceled', handleCanceled);
    socket.on('order:completed', handleCompleted);
    socket.on('error', handleError);

    return () => {
      socket.off('order:created', handleCreated);
      socket.off('order:updated', handleUpdated);
      socket.off('order:canceled', handleCanceled);
      socket.off('order:completed', handleCompleted);
      socket.off('error', handleError);
    };
  }, [socket]);

  // Convert map to sorted array and compute meta
  const { rows, meta } = useMemo(() => {
    const orderList = Object.values(orders);

    // Sort by createdAt desc (newest first)
    orderList.sort((a, b) => {
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });

    // Compute meta from current orders (fallback to REST meta if no WS updates yet)
    const metaFromOrders = {
      total: orderList.length,
      pending: orderList.filter((o) => o.status === 'PENDING').length,
      partiallyFilled: orderList.filter((o) => o.status === 'PARTIALLY_FILLED').length,
      totalNotional: orderList.reduce((sum, o) => sum + o.notional, 0),
    };

    return {
      rows: orderList,
      meta: data?.meta && Object.keys(orders).length === 0 ? data.meta : metaFromOrders,
    };
  }, [orders, data?.meta]);

  return {
    rows,
    meta,
    loading,
    error,
    lastUpdated,
  };
}
