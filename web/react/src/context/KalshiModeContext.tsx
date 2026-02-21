import React, { createContext, useContext } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface KalshiModeData {
  mode: string;
  is_live: boolean;
  live_enabled: boolean;
}

interface KalshiModeContextValue {
  data: KalshiModeData | null;
  loading: boolean;
  isLive: boolean;
}

const KalshiModeContext = createContext<KalshiModeContextValue>({
  data: null,
  loading: true,
  isLive: false,
});

export function KalshiModeProvider({ children }: { children: React.ReactNode }) {
  const { data, loading } = useApiData<KalshiModeData>(API_ENDPOINTS.KALSHI_GRID_MODE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });

  return (
    <KalshiModeContext.Provider value={{ data, loading, isLive: data?.is_live ?? false }}>
      {children}
    </KalshiModeContext.Provider>
  );
}

export function useKalshiMode(): KalshiModeContextValue {
  return useContext(KalshiModeContext);
}
