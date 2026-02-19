import { useState, useEffect, useMemo } from 'react';
import { useApiData } from './useApiData';
import { useMeridSocket } from './useMeridSocket';
import { API_ENDPOINTS } from '../config/constants';
import { logUiError } from '../utils/logger';
import { useFeatureFlags } from '../config/featureFlags';
import type {
  RiskMetricsResponse,
  RiskAlert,
  RiskThresholdBreachedPayload,
  RiskExposureChangedPayload,
  RiskPnlUpdatedPayload,
  ExposureSide,
} from '../types/risk';

interface UseRiskMetricsReturn {
  metrics: {
    totalPnL: number;
    dailyDrawdown: number;
    maxDrawdown: number;
    marginUsed: number;
    marginAvailable: number;
    marginUtilizationPercent: number;
    exposure: Record<string, ExposureSide>;
  };
  alerts: RiskAlert[];
  loading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
}

/**
 * Validate risk payload has required fields
 */
function isValidRiskPayload(payload: unknown): payload is { type: string } {
  return typeof payload === 'object' && payload !== null && 'type' in payload;
}

/**
 * useRiskMetrics Hook
 *
 * Fetches risk metrics via REST and receives live updates via WebSocket.
 * REST: GET /api/v1/risk/metrics
 * WS Events: risk:threshold_breached, risk:exposure_changed, risk:pnl_updated
 */
export function useRiskMetrics(): UseRiskMetricsReturn {
  const { kalshiOnly } = useFeatureFlags();
  
  // Track metrics state
  const [metrics, setMetrics] = useState<RiskMetricsResponse | null>(null);
  const [alerts, setAlerts] = useState<RiskAlert[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Fetch initial data via REST - use Kalshi risk in Kalshi mode
  const { data, loading, error } = useApiData<RiskMetricsResponse>(
    kalshiOnly ? API_ENDPOINTS.KALSHI_RISK : API_ENDPOINTS.RISK_METRICS,
    { pollingInterval: 10000 } // Poll every 10 seconds as fallback
  );

  // Initialize from REST data
  useEffect(() => {
    if (data) {
      setMetrics(data);
      setAlerts(Array.isArray(data.alerts) ? data.alerts : []);
      setLastUpdated(new Date());
    }
  }, [data]);

  // WebSocket for real-time updates
  const { socket } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // Threshold breached - add new alert
    const handleThresholdBreached = (payload: RiskThresholdBreachedPayload) => {
      if (!isValidRiskPayload(payload)) {
        console.warn('[useRiskMetrics] Invalid threshold_breached payload:', payload);
        return;
      }
      console.info('[useRiskMetrics] Threshold breached:', payload.metric, payload.severity);
      const newAlert: RiskAlert = {
        id: `${Date.now()}-${payload.metric}`,
        metric: payload.metric,
        value: payload.value,
        threshold: payload.threshold,
        severity: payload.severity,
        createdAt: new Date().toISOString(),
      };
      setAlerts((prev) => [newAlert, ...prev].slice(0, 50)); // Keep last 50 alerts
      setLastUpdated(new Date());
    };

    // Exposure changed - update exposure for symbol
    const handleExposureChanged = (payload: RiskExposureChangedPayload) => {
      if (!isValidRiskPayload(payload)) {
        console.warn('[useRiskMetrics] Invalid exposure_changed payload:', payload);
        return;
      }
      console.info('[useRiskMetrics] Exposure changed:', payload.symbol, payload.side, payload.newExposure);
      setMetrics((prev) => {
        if (!prev) return prev;
        const currentExposure = prev.exposure[payload.symbol] || { long: 0, short: 0 };
        return {
          ...prev,
          exposure: {
            ...prev.exposure,
            [payload.symbol]: {
              ...currentExposure,
              [payload.side.toLowerCase()]: payload.newExposure,
            },
          },
        };
      });
      setLastUpdated(new Date());
    };

    // PnL updated - update PnL values
    const handlePnlUpdated = (payload: RiskPnlUpdatedPayload) => {
      if (!isValidRiskPayload(payload)) {
        console.warn('[useRiskMetrics] Invalid pnl_updated payload:', payload);
        return;
      }
      console.info('[useRiskMetrics] PnL updated:', payload.total);
      setMetrics((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          totalPnL: payload.total,
        };
      });
      setLastUpdated(new Date());
    };

    const handleError = (error: Error) => {
      logUiError('useRiskMetrics', 'WebSocket error', error);
    };

    socket.on('risk:threshold_breached', handleThresholdBreached);
    socket.on('risk:exposure_changed', handleExposureChanged);
    socket.on('risk:pnl_updated', handlePnlUpdated);
    socket.on('error', handleError);

    return () => {
      socket.off('risk:threshold_breached', handleThresholdBreached);
      socket.off('risk:exposure_changed', handleExposureChanged);
      socket.off('risk:pnl_updated', handlePnlUpdated);
      socket.off('error', handleError);
    };
  }, [socket]);

  // Compute derived metrics
  const computedMetrics = useMemo(() => {
    const safeMetrics = metrics || {
      totalPnL: 0,
      dailyDrawdown: 0,
      maxDrawdown: 0,
      marginUsed: 0,
      marginAvailable: 0,
      exposure: {},
    };

    const marginTotal = safeMetrics.marginUsed + safeMetrics.marginAvailable;
    const marginUtilizationPercent = marginTotal > 0
      ? (safeMetrics.marginUsed / marginTotal) * 100
      : 0;

    return {
      totalPnL: safeMetrics.totalPnL,
      dailyDrawdown: safeMetrics.dailyDrawdown,
      maxDrawdown: safeMetrics.maxDrawdown,
      marginUsed: safeMetrics.marginUsed,
      marginAvailable: safeMetrics.marginAvailable,
      marginUtilizationPercent,
      exposure: safeMetrics.exposure,
    };
  }, [metrics]);

  return {
    metrics: computedMetrics,
    alerts,
    loading,
    error,
    lastUpdated,
  };
}
