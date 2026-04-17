/**
 * useCryptoVenueStatus Hook
 * 
 * Hook for accessing Kalshi crypto venue status and capabilities.
 * Connects to the new venue API endpoints for state-driven crypto UI.
 */

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '../config/constants';
import { authHeaders } from '../api/auth';

export interface VenueStatus {
  venue_id: string;
  status: 'ok' | 'error' | 'no_markets_visible' | 'degraded';
  crypto_available: boolean;
  total_markets: number;
  crypto_markets: number;
  last_checked: string;
  error_type?: string;
  error_message?: string;
  connectivity: {
    primary_endpoint: {
      url: string;
      status: string;
      error_type?: string;
      error_message?: string;
    };
    fallback_endpoint: {
      url: string;
      status: string;
      error_type?: string;
      error_message?: string;
    };
  };
  capabilities: string[];
}

export interface CryptoVenueStatus {
  status: VenueStatus;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  isHealthy: boolean;
  hasCryptoMarkets: boolean;
  lastUpdate: Date | null;
}

const DEFAULT_STATUS: VenueStatus = {
  venue_id: 'kalshi',
  status: 'error',
  crypto_available: false,
  total_markets: 0,
  crypto_markets: 0,
  last_checked: new Date().toISOString(),
  connectivity: {
    primary_endpoint: { url: '', status: 'error' },
    fallback_endpoint: { url: '', status: 'error' }
  },
  capabilities: []
};

/**
 * Hook for accessing Kalshi crypto venue status
 * Provides state-driven information for crypto UI components
 */
export function useCryptoVenueStatus(pollInterval: number = 30000): CryptoVenueStatus {
  const [status, setStatus] = useState<VenueStatus>(DEFAULT_STATUS);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      
      const response = await fetch(`${API_BASE_URL}/api/v1/crypto/status`, {
        headers: authHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: VenueStatus = await response.json();
      
      // Validate response structure
      if (!data.venue_id || !data.status || typeof data.crypto_available !== 'boolean') {
        throw new Error('Invalid venue status response format');
      }

      setStatus(data);
      setLastUpdate(new Date());
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMessage);
      
      // Set fallback status on error
      setStatus({
        ...DEFAULT_STATUS,
        status: 'error',
        error_type: 'api_error',
        error_message: errorMessage,
        last_checked: new Date().toISOString()
      });
      
      console.error('Failed to fetch crypto venue status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    await fetchStatus();
  }, [fetchStatus]);

  // Initial fetch
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Polling
  useEffect(() => {
    if (pollInterval > 0) {
      const interval = setInterval(fetchStatus, pollInterval);
      return () => clearInterval(interval);
    }
  }, [fetchStatus, pollInterval]);

  // Computed properties
  const isHealthy = status.status === 'ok' && status.crypto_available;
  const hasCryptoMarkets = status.crypto_markets > 0;

  return {
    status,
    loading,
    error,
    refresh,
    isHealthy,
    hasCryptoMarkets,
    lastUpdate
  };
}

/**
 * Hook for crypto market data from venue
 */
export function useCryptoMarkets() {
  const [markets, setMarkets] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCryptoMarkets = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(`${API_BASE_URL}/api/v1/markets/kalshi/crypto`, {
        headers: authHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      if (!data.markets || !Array.isArray(data.markets)) {
        throw new Error('Invalid markets response format');
      }

      setMarkets(data.markets);
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMessage);
      console.error('Failed to fetch crypto markets:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCryptoMarkets();
  }, [fetchCryptoMarkets]);

  return {
    markets,
    loading,
    error,
    refresh: fetchCryptoMarkets
  };
}

/**
 * Hook for venue registry information
 */
export function useVenueRegistry() {
  const [venues, setVenues] = useState<Record<string, any>>({});
  const [capabilities, setCapabilities] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchVenues = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(`${API_BASE_URL}/api/v1/venues`, {
        headers: authHeaders(),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      if (!data.venues || !data.capabilities) {
        throw new Error('Invalid venues response format');
      }

      setVenues(data.venues);
      setCapabilities(data.capabilities);
      
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      setError(errorMessage);
      console.error('Failed to fetch venue registry:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchVenues();
  }, [fetchVenues]);

  const getVenuesByCapability = useCallback((capability: string) => {
    return capabilities[capability] || [];
  }, [capabilities]);

  const hasCapability = useCallback((venueId: string, capability: string) => {
    const venue = venues[venueId];
    return venue && venue.capabilities && venue.capabilities.includes(capability);
  }, [venues]);

  return {
    venues,
    capabilities,
    loading,
    error,
    refresh: fetchVenues,
    getVenuesByCapability,
    hasCapability
  };
}

export default useCryptoVenueStatus;
