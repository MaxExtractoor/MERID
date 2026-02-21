/**
 * React hooks for the Signal Layer — features, arbs, drift, CQI, decay.
 *
 * useSignalFeatures(symbol)  — decay-aware features for a symbol
 * useSignalCQI()             — CQI per domain
 * useSignalArbs()            — active arb/dislocation signals
 * useSignalMetrics()         — aggregate signal layer metrics
 */

import { useEffect, useState, useCallback } from "react";
import { API_ENDPOINTS } from "../config/constants";

// ── Generic polling hook ─────────────────────────────────────────────

function usePolled<T>(url: string, interval = 10000, initial: T): {
  data: T; loading: boolean; error: string | undefined;
} {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
      setError(undefined);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData, interval]);

  return { data, loading, error };
}

// ── Feature hooks ────────────────────────────────────────────────────

export function useSignalFeatures(symbol: string) {
  return usePolled<unknown>(
    `${API_ENDPOINTS.SIGNAL_FEATURES}/${symbol}`,
    15000,
    null,
  );
}

export function useSignalSocial(symbol: string) {
  return usePolled<unknown>(
    `${API_ENDPOINTS.SIGNAL_SOCIAL}/${symbol}`,
    8000,
    null,
  );
}

// ── CQI hook ─────────────────────────────────────────────────────────

export interface CQIDomain {
  domain: string;
  quality_index: number;
  band: string;
  window: string;
  components: {
    brier: number;
    pnl: number;
    drift: number;
    decay: number;
  };
  timestamp: number;
}

export interface CQIResponse {
  domains: Record<string, CQIDomain>;
  domain_count: number;
}

export function useSignalCQI() {
  return usePolled<CQIResponse>(
    API_ENDPOINTS.SIGNAL_CQI,
    20000,
    { domains: {}, domain_count: 0 },
  );
}

// ── Arb hook ─────────────────────────────────────────────────────────

export interface ArbSignal {
  signal_id: string;
  domain: string;
  arb_type: string;
  symbol: string;
  gross_edge_bps: number;
  net_edge_bps: number;
  edge_usd: number;
  ttl_seconds: number;
  age_seconds: number;
  is_actionable: boolean;
  decay_weight: number;
  status: string;
  venues: unknown[];
}

export interface ArbResponse {
  signals: ArbSignal[];
  count: number;
  metrics: unknown;
}

export function useSignalArbs() {
  return usePolled<ArbResponse>(
    API_ENDPOINTS.SIGNAL_ARBS,
    10000,
    { signals: [], count: 0, metrics: {} },
  );
}

// ── Metrics hook ─────────────────────────────────────────────────────

export function useSignalMetrics() {
  return usePolled<unknown>(
    API_ENDPOINTS.SIGNAL_METRICS,
    20000,
    null,
  );
}

// ── Decay configs hook ───────────────────────────────────────────────

export function useDecayConfigs() {
  return usePolled<Record<string, unknown>>(
    API_ENDPOINTS.SIGNAL_DECAY_CONFIGS,
    60000,
    {},
  );
}
