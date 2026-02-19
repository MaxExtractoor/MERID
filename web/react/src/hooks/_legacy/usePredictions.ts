import { useState, useEffect, useMemo } from 'react';
import { useApiData } from './useApiData';
import { useMeridSocket } from './useMeridSocket';
import { API_ENDPOINTS } from '../config/constants';
import { logUiError } from '../utils/logger';
import type {
  PredictionMarket,
  PredictionsResponse,
  PredictionPriceChangedPayload,
  PredictionPositionUpdatedPayload,
  PredictionResolvedPayload,
} from '../types/predictions';

interface UsePredictionsReturn {
  markets: PredictionMarket[];
  meta: {
    total: number;
    open: number;
    closed: number;
    totalVolume: number;
    totalPnl: number;
  };
  loading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
}

/**
 * Validate prediction payload has required fields
 */
function isValidPredictionPayload(payload: unknown): payload is { type: string; id: string } {
  return typeof payload === 'object' && payload !== null && 'type' in payload && 'id' in payload;
}

/**
 * usePredictions Hook
 *
 * Fetches prediction markets via REST and receives live updates via WebSocket.
 * REST: GET /api/v1/predictions/markets
 * WS Events: prediction:price_changed, prediction:position_updated, prediction:resolved
 */
export function usePredictions(): UsePredictionsReturn {
  // Track markets state
  const [marketsMap, setMarketsMap] = useState<Map<string, PredictionMarket>>(new Map());
  const [meta, setMeta] = useState({
    total: 0,
    open: 0,
    closed: 0,
    totalVolume: 0,
    totalPnl: 0,
  });
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Fetch initial data via REST
  const { data, loading, error } = useApiData<PredictionsResponse>(
    `${API_ENDPOINTS.PREDICTION_MARKETS}`,
    { pollingInterval: 15000 } // Poll every 15 seconds as fallback
  );

  // Initialize from REST data
  useEffect(() => {
    if (data) {
      // Normalize markets - API may not return all fields
      const normalized = (data.markets || []).map((m: unknown) => ({
        id: m.id || '',
        symbol: m.symbol || '',
        marketType: m.marketType || 'BINARY',
        question: m.question || m.symbol || '',
        endTime: m.endTime || '',
        status: m.status || 'OPEN',
        yesPrice: m.yesPrice ?? 0,
        noPrice: m.noPrice ?? 0,
        volume: m.volume ?? 0,
        liquidity: m.liquidity ?? 0,
        ourPosition: m.ourPosition || 'NONE',
        ourSize: m.ourSize ?? 0,
        ourAvgPrice: m.ourAvgPrice ?? 0,
        ourPnl: m.ourPnl ?? 0,
        modelConfidence: m.modelConfidence ?? 0,
        modelPrediction: m.modelPrediction || 'UNCERTAIN',
        lastUpdated: m.lastUpdated || new Date().toISOString(),
      } as PredictionMarket));
      const newMap = new Map(normalized.map((m) => [m.id, m]));
      setMarketsMap(newMap);
      if (data.meta) {
        setMeta({
          total: data.meta.total ?? 0,
          open: data.meta.open ?? 0,
          closed: data.meta.closed ?? 0,
          totalVolume: data.meta.totalVolume ?? 0,
          totalPnl: data.meta.totalPnl ?? 0,
        });
      }
      setLastUpdated(new Date());
    }
  }, [data]);

  // WebSocket for real-time updates
  const { socket } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // Price changed - update market prices
    const handlePriceChanged = (payload: PredictionPriceChangedPayload) => {
      if (!isValidPredictionPayload(payload)) {
        console.warn('[usePredictions] Invalid price_changed payload:', payload);
        return;
      }
      console.info('[usePredictions] Price changed:', payload.id, payload.yesPrice.toFixed(2));
      setMarketsMap((prev) => {
        const market = prev.get(payload.id);
        if (!market) {
          console.warn('[usePredictions] Unknown market for price update:', payload.id);
          return prev;
        }
        const updated: PredictionMarket = {
          ...market,
          yesPrice: payload.yesPrice,
          noPrice: payload.noPrice,
          volume: payload.volume,
          lastUpdated: payload.timestamp,
        };
        return new Map(prev).set(payload.id, updated);
      });
      setLastUpdated(new Date());
    };

    // Position updated - update our position
    const handlePositionUpdated = (payload: PredictionPositionUpdatedPayload) => {
      if (!isValidPredictionPayload(payload)) {
        console.warn('[usePredictions] Invalid position_updated payload:', payload);
        return;
      }
      console.info('[usePredictions] Position updated:', payload.id, payload.ourPosition, payload.ourSize);
      setMarketsMap((prev) => {
        const market = prev.get(payload.id);
        if (!market) {
          console.warn('[usePredictions] Unknown market for position update:', payload.id);
          return prev;
        }
        const updated: PredictionMarket = {
          ...market,
          ourPosition: payload.ourPosition,
          ourSize: payload.ourSize,
          ourAvgPrice: payload.ourAvgPrice,
          ourPnl: payload.ourPnl,
          lastUpdated: new Date().toISOString(),
        };
        return new Map(prev).set(payload.id, updated);
      });
      setLastUpdated(new Date());
    };

    // Resolved - update market status and final PnL
    const handleResolved = (payload: PredictionResolvedPayload) => {
      if (!isValidPredictionPayload(payload)) {
        console.warn('[usePredictions] Invalid resolved payload:', payload);
        return;
      }
      console.info('[usePredictions] Market resolved:', payload.id, payload.outcome, payload.ourPnl);
      setMarketsMap((prev) => {
        const market = prev.get(payload.id);
        if (!market) {
          console.warn('[usePredictions] Unknown market for resolution:', payload.id);
          return prev;
        }
        const updated: PredictionMarket = {
          ...market,
          status: 'RESOLVED',
          ourPnl: payload.ourPnl,
          lastUpdated: payload.resolvedAt,
        };
        return new Map(prev).set(payload.id, updated);
      });
      // Update meta to reflect resolved status
      setMeta((prev) => ({
        ...prev,
        open: Math.max(0, prev.open - 1),
        closed: prev.closed + 1,
        totalPnl: prev.totalPnl + payload.ourPnl,
      }));
      setLastUpdated(new Date());
    };

    const handleError = (error: Error) => {
      logUiError('usePredictions', 'WebSocket error', error);
    };

    socket.on('prediction:price_changed', handlePriceChanged);
    socket.on('prediction:position_updated', handlePositionUpdated);
    socket.on('prediction:resolved', handleResolved);
    socket.on('error', handleError);

    return () => {
      socket.off('prediction:price_changed', handlePriceChanged);
      socket.off('prediction:position_updated', handlePositionUpdated);
      socket.off('prediction:resolved', handleResolved);
      socket.off('error', handleError);
    };
  }, [socket]);

  // Convert map to array for rendering
  const markets = useMemo(() => Array.from(marketsMap.values()), [marketsMap]);

  return {
    markets,
    meta,
    loading,
    error,
    lastUpdated,
  };
}
