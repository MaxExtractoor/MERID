import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';

const sentimentHeaders = (): Record<string, string> => {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    h['Authorization'] = `Bearer ${token}`;
    h['X-Session-ID'] = token;
  }
  return h;
};

interface SentimentBundle {
  asset: string;
  twitter: number;
  reddit: number;
  fg_index: number;
  fg_norm: number;
  combined: number;
  confidence: number;
  vader_signal: string;
  kalshi_adjustment: number;
  timestamp: string;
}

// Full lane-snapshot shape — superset of SentimentBundle
export interface LaneSentimentSnapshot {
  // Social sources
  twitter: number;
  reddit: number;
  // Fear & Greed
  fg_index: number;
  fg_regime: string;          // extreme_fear | fear | neutral | greed | extreme_greed
  fg_is_synthetic: boolean;   // true = sin-wave fallback, real API unavailable
  // Smoothed signals
  combined_raw: number;       // raw weighted Twitter+Reddit
  combined_fib: number;       // Fibonacci-smoothed
  combined_smoothed: number;  // Kalman-filtered (primary signal seen by risk engine)
  kalman_gain: number | null;
  // Meta
  confidence: number;
  vader_signal: string;
  kalshi_prob_adj: number;
  timestamp: string;
  // Staleness
  sentiment_age_seconds: number | null;
  sentiment_stale: boolean;
  timestamp_fetched: string;
  // FG clamp breakdown
  fg_clamp_breakdown: {
    per_trade_cap: number;
    max_book_cap: number;
    extreme: boolean;
    conf_mult: number;
    fg_regime: string;
    fg_value: number;
    rules_fired: string[];
    sizing_multiplier: number;
    fg_filter_blocked: boolean;
    fg_filter_reason: string;
    is_synthetic: boolean;
  } | null;
}

interface BundleResponse {
  bundle: SentimentBundle;
  formatted: string;
  is_contrarian: boolean;
  size_multiplier: number;
}


interface UseSentimentBundleReturn {
  bundle: SentimentBundle | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useLaneSentimentSnapshot() {
  const [snapshot, setSnapshot] = useState<LaneSentimentSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSnapshot = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_LANE_SNAPSHOT}`;
      const resp = await fetch(url, { headers: sentimentHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: LaneSentimentSnapshot = await resp.json();
      setSnapshot(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  return { snapshot, loading, error, refetch: fetchSnapshot };
}


export function useSentimentBundle(asset: string): UseSentimentBundleReturn {
  const [bundle, setBundle] = useState<SentimentBundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBundle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_BUNDLE(asset)}`;
      const resp = await fetch(url, { headers: sentimentHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: BundleResponse = await resp.json();
      setBundle(data.bundle);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, [asset]);

  useEffect(() => {
    fetchBundle();
    const interval = setInterval(fetchBundle, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(interval);
  }, [fetchBundle]);

  return { bundle, loading, error, refetch: fetchBundle };
}

