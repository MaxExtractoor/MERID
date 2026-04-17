import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

export interface DiscoverHealthData {
  timestamp: string;
  since_hours: number;
  fills: {
    rows: number;
    incomplete_rows: number;
    complete_rows: number;
    error?: string;
  };
  positions: {
    count: number;
    by_asset: Record<string, number>;
    error?: string;
  };
  portfolio_empty_or_uninitialized: boolean;
  portfolio_discover_green: boolean;
  message: string | null;
}

interface UseDiscoverHealthOptions {
  sinceHours?: number;
  pollIntervalMs?: number;
  enabled?: boolean;
}

/**
 * Centralized polling hook for portfolio discover health.
 * Replaces individual polling of /fills, /positions, /risk, /pnl
 * with a single consolidated endpoint that reduces server load.
 */
export function useDiscoverHealth(options: UseDiscoverHealthOptions = {}) {
  const {
    sinceHours = 24,
    pollIntervalMs = 2000, // 2s default (reduced from multiple parallel 500ms polls)
    enabled = true,
  } = options;

  const [data, setData] = useState<DiscoverHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const lastFetchRef = useRef<number>(0);

  const fetchDiscoverHealth = useCallback(async () => {
    // Debounce: don't fetch more than once per interval
    const now = Date.now();
    if (now - lastFetchRef.current < pollIntervalMs) {
      return;
    }
    lastFetchRef.current = now;

    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_DISCOVER_HEALTH}?since_hours=${sinceHours}`;
      const response = await fetch(url, {
        credentials: "include",
        headers: { "Accept": "application/json" },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result: DiscoverHealthData = await response.json();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [sinceHours, pollIntervalMs]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    // Initial fetch
    fetchDiscoverHealth();

    // Set up polling interval
    const intervalId = setInterval(fetchDiscoverHealth, pollIntervalMs);

    return () => clearInterval(intervalId);
  }, [enabled, fetchDiscoverHealth, pollIntervalMs]);

  return {
    data,
    loading,
    error,
    refetch: fetchDiscoverHealth,
    // Derived flags for UI convenience
    isPortfolioEmpty: data?.portfolio_empty_or_uninitialized ?? true,
    isDiscoverGreen: data?.portfolio_discover_green ?? false,
    hasCompleteFills: (data?.fills?.complete_rows ?? 0) > 0,
    hasRealPositions: (data?.positions?.count ?? 0) > 0,
  };
}

export default useDiscoverHealth;
