import React, { createContext, useContext, useState, useEffect } from 'react';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface KalshiModeData {
  mode: string;
  is_live: boolean;
  live_enabled: boolean;
}

interface KalshiModeContextValue {
  data: KalshiModeData | null;
  loading: boolean;
  isLoading: boolean;
  isLive: boolean;
  error: Error | null;
  refetch: () => void;
  wsKillActive: boolean;
  wsKillAt: number | null;
}

const _noop = () => {};

const KalshiModeContext = createContext<KalshiModeContextValue>({
  data: null,
  loading: true,
  isLoading: true,
  isLive: false,
  error: null,
  refetch: _noop,
  wsKillActive: false,
  wsKillAt: null,
});

export function KalshiModeProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading, error, refetch } = useApiQuery<KalshiModeData>(API_ENDPOINTS.KALSHI_GRID_MODE, {
    refetchInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });

  const [wsKillActive, setWsKillActive] = useState(false);
  const [wsKillAt, setWsKillAt] = useState<number | null>(null);

  const { alerts } = useKalshiRiskStream();

  useEffect(() => {
    for (const alert of alerts) {
      if (alert.type === 'kill_switch') {
        setWsKillActive(true);
        setWsKillAt(Date.now());
        break;
      }
    }
  }, [alerts]);

  return (
    <KalshiModeContext.Provider value={{
      data: data ?? null,
      loading: isLoading,
      isLoading,
      isLive: data?.is_live ?? false,
      error: error ?? null,
      refetch,
      wsKillActive,
      wsKillAt,
    }}>
      {children}
    </KalshiModeContext.Provider>
  );
}

export function useKalshiMode(): KalshiModeContextValue {
  return useContext(KalshiModeContext);
}
