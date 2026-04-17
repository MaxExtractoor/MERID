// web/react/src/hooks/useKalshiCryptoRti.ts
import { useEffect, useState, useCallback } from "react";
import { authHeaders } from "../api/auth";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

type VolSpikeEvent = {
  timestamp: number;
  magnitude: number;
};

type AssetRtiData = {
  rti: number;
  sma_60s: number;
  vol_ratio: number;
  vol_spike_events: VolSpikeEvent[];
  rti_sma_deviation: number;
  recent_vol_spikes: number;
  max_recent_spike: number;
};

type CryptoRtiResponse = {
  data: {
    [asset: string]: AssetRtiData;
  };
  timestamp: number;
  source: string;
  error?: string;
};

export const useKalshiCryptoRti = () => {
  const [data, setData] = useState<CryptoRtiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CRYPTO_RTI}`, { headers: authHeaders() });
      if (!resp.ok) throw new Error(await resp.text());
      const json = await resp.json();
      setData(json);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 15000);
    return () => clearInterval(id);
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
};
