import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

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

interface OptimizationResult {
  asset: string;
  lookback_days: number;
  best: {
    pos_th: number;
    neg_th: number;
    sharpe: number;
    max_drawdown: number;
    win_rate: number;
    trades: number;
  };
  top_5: Array<{
    pos_th: number;
    neg_th: number;
    sharpe: number;
    score: number;
  }>;
  timestamp: string;
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

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_LANE_SNAPSHOT}`;
      const resp = await window.fetch(url);
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
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, [fetch]);

  return { snapshot, loading, error, refetch: fetch };
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
      const resp = await fetch(url);
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
    const interval = setInterval(fetchBundle, 30000);
    return () => clearInterval(interval);
  }, [fetchBundle]);

  return { bundle, loading, error, refetch: fetchBundle };
}

export function useMultiSentimentBundle(assets: string[]) {
  const [bundles, setBundles] = useState<Record<string, SentimentBundle>>({});
  const [loading, setLoading] = useState(false);
  const assetsKey = assets.join(',');

  const fetchBundles = useCallback(async () => {
    if (assets.length === 0) return;
    setLoading(true);
    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_BUNDLE_MULTI}?assets=${assetsKey}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setBundles(data.bundles || {});
    } catch (exc) {
      console.error('Failed to fetch bundles:', exc);
    } finally {
      setLoading(false);
    }
  }, [assetsKey, assets.length]);

  useEffect(() => {
    fetchBundles();
    const interval = setInterval(fetchBundles, 30000);
    return () => clearInterval(interval);
  }, [fetchBundles]);

  return { bundles, loading, refetch: fetchBundles };
}

export function useThresholdOptimizer() {
  const [optimizing, setOptimizing] = useState(false);
  const [result, setResult] = useState<OptimizationResult | null>(null);

  const optimize = useCallback(async (asset: string, days = 30) => {
    setOptimizing(true);
    try {
      const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_OPTIMIZE_THRESHOLDS(asset)}?days=${days}`;
      const resp = await fetch(url, { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: OptimizationResult = await resp.json();
      setResult(data);
      return data;
    } catch (exc) {
      console.error('Optimization failed:', exc);
      throw exc;
    } finally {
      setOptimizing(false);
    }
  }, []);

  return { optimize, optimizing, result };
}
