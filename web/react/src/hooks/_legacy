/**
 * useDebateContext - Hook to access debate context from WebSocket data
 */

import { useState, useEffect, useCallback } from 'react';
import { useWebSocket } from './useWebSocket';
import { WS_URL } from '../config/constants';

interface DebateContext {
  status: 'healthy' | 'degraded' | 'critical' | 'unknown';
  alerts_24h: {
    critical: number;
    warnings: number;
    total: number;
  };
  top_alerts: Array<{
    agent_id: string;
    severity: string;
    message: string;
    triggered_at: string;
  }>;
  top_teams: Array<{
    team_id: string;
    team_label: string;
    contribution_pct: number;
    sharpe_delta: number;
  }>;
  last_updated: string;
}

interface PredictionData {
  markets: any[];
  meta: {
    total: number;
    open: number;
    totalVolume: number;
    totalPnl: number;
    debate?: DebateContext;
  };
  timestamp: number;
}

export function useDebateContext() {
  const [debateContext, setDebateContext] = useState<DebateContext | null>(null);
  const [loading, setLoading] = useState(true);
  
  // Use WebSocket to get prediction data with debate context
  const { lastMessage, connected, error } = useWebSocket<PredictionData>({
    url: WS_URL.replace('/ws/trades', '/ws/prediction'),
    autoConnect: true,
    heartbeatMs: 30000,
  });

  useEffect(() => {
    if (lastMessage && lastMessage.meta?.debate) {
      setDebateContext(lastMessage.meta.debate);
      setLoading(false);
    } else if (connected) {
      setLoading(false);
    }
  }, [lastMessage, connected]);

  // Helper functions — memoized so consumers get stable references
  const getDebateStatus = useCallback(() => debateContext?.status || 'unknown', [debateContext]);
  const hasCriticalAlerts = useCallback(() => (debateContext?.alerts_24h?.critical || 0) > 0, [debateContext]);
  const hasWarnings = useCallback(() => (debateContext?.alerts_24h?.warnings || 0) > 0, [debateContext]);
  const getTotalAlerts = useCallback(() => debateContext?.alerts_24h?.total || 0, [debateContext]);
  const getTopAlert = useCallback(() => debateContext?.top_alerts?.[0] || null, [debateContext]);
  const getTopTeam = useCallback(() => debateContext?.top_teams?.[0] || null, [debateContext]);

  return {
    debateContext,
    loading,
    connected,
    error,
    // Helper functions
    getDebateStatus,
    hasCriticalAlerts,
    hasWarnings,
    getTotalAlerts,
    getTopAlert,
    getTopTeam,
  };
}
