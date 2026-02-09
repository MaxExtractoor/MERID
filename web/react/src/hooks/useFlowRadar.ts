/**
 * useFlowRadar — hooks for the flow domain (memecoins, whales, KOLs, snipers).
 *
 * Exports:
 *   useFlowRadar()   — polls /api/v1/flow/radar for full radar data
 *   useFlowMetrics() — polls /api/v1/flow/metrics for domain metrics
 *   useFlowSniper()  — polls /api/v1/flow/sniper/status + /fills
 *   useFlowRisk()    — polls /api/v1/flow/risk for risk status
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { API_ENDPOINTS } from "../config/constants";

// ── Types ────────────────────────────────────────────────────────────

export interface FlowEventSummary {
  total: number;
  whale_buys: number;
  whale_sells: number;
  kol_buys: number;
  kol_mentions: number;
  lp_adds: number;
  lp_removes: number;
}

export interface FlowOpinionSummary {
  total: number;
  stance_distribution: Record<string, number>;
  dominant_stance: string;
  avg_confidence: number;
}

export interface FlowPlanSummary {
  meme_plans: number;
  whale_plans: number;
  kol_plans: number;
  active_plans: number;
}

export interface FlowTokenConsensus {
  token_id: string;
  symbol: string;
  name: string;
  chain: string;
  contract_address: string;
  liquidity_usd: number;
  price_usd: number;
  age_hours: number;
  flow_score: number;
  event_summary: FlowEventSummary;
  opinion_summary: FlowOpinionSummary;
  plan_summary: FlowPlanSummary;
}

export interface FlowEntity {
  id: string;
  address: string;
  chain: string;
  entity_type: string;
  label: string;
  tags: string[];
  social_handle: string;
  follower_count: number;
  historical_pnl_usd: number;
  hit_rate: number;
  trade_count: number;
  quality: string;
}

export interface FlowEvent {
  id: string;
  event_type: string;
  chain: string;
  token_id: string;
  token_symbol: string;
  entity_id: string;
  entity_address: string;
  entity_type: string;
  size_usd: number;
  direction: string;
  timestamp: number;
  mention_text: string;
  mention_sentiment: number;
}

export interface RadarData {
  tokens: FlowTokenConsensus[];
  entities: FlowEntity[];
  recent_events: FlowEvent[];
  source: string;
  token_count: number;
  entity_count: number;
  event_count: number;
}

export interface FlowMetrics {
  tokens_tracked: number;
  entities_tracked: number;
  whale_count: number;
  kol_count: number;
  events_24h: number;
  opinions_total: number;
  plans: {
    meme: Record<string, number>;
    whale: Record<string, number>;
    kol: Record<string, number>;
  };
  sniper: {
    total_fills: number;
    success_rate: number;
    total_volume_usd: number;
    avg_slippage_bps: number;
    avg_latency_ms: number;
    mev_incidents: number;
    mev_loss_usd: number;
  };
}

export interface SniperFill {
  id: string;
  order_id: string;
  token_symbol: string;
  chain: string;
  direction: string;
  filled_size_usd: number;
  fill_price_usd: number;
  expected_price_usd: number;
  actual_slippage_bps: number;
  gas_used_usd: number;
  latency_ms: number;
  route_type_used: string;
  mev_detected: boolean;
  mev_loss_usd: number;
  tx_hash: string;
  success: boolean;
  error: string;
  timestamp: number;
}

export interface RouteHealth {
  dex_router: string;
  route_type: string;
  mev_relay: string;
  is_healthy: boolean;
  avg_latency_ms: number;
  failure_rate: number;
}

export interface SniperStatus {
  is_live: boolean;
  route_health: Record<string, {
    chain: string;
    routes: RouteHealth[];
    has_mev_protection: boolean;
    healthy_count: number;
    total_count: number;
  }>;
}

export interface FlowRiskStatus {
  config: Record<string, number>;
  state: {
    domain_exposure_usd: number;
    daily_pnl_usd: number;
    daily_loss_usd: number;
    is_throttled: boolean;
    is_halted: boolean;
    halt_reason: string;
    active_plan_count: number;
  };
  nav_usd: number;
  effective_max_domain_usd: number;
  utilization_pct: number;
}

// ── Generic poller ───────────────────────────────────────────────────

function usePolledData<T>(
  url: string,
  intervalMs: number = 8000,
  defaultValue: T,
): { data: T; loading: boolean; error: string | undefined; rawResponse: unknown } {
  const [data, setData] = useState<T>(defaultValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | undefined>(undefined);
  const [rawResponse, setRawResponse] = useState<unknown>(null);
  const mounted = useRef(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (mounted.current) {
        setData(json as T);
        setRawResponse(json);
        setError(undefined);
        setLoading(false);
      }
    } catch (err: unknown) {
      if (mounted.current) {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    }
  }, [url]);

  useEffect(() => {
    mounted.current = true;
    fetchData();
    const id = setInterval(fetchData, intervalMs);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [fetchData, intervalMs]);

  return { data, loading, error, rawResponse };
}

// ── Hooks ────────────────────────────────────────────────────────────

const EMPTY_RADAR: RadarData = {
  tokens: [], entities: [], recent_events: [],
  source: "loading", token_count: 0, entity_count: 0, event_count: 0,
};

export function useFlowRadar(chain?: string) {
  const url = chain
    ? `${API_ENDPOINTS.FLOW_RADAR}?chain=${chain}`
    : API_ENDPOINTS.FLOW_RADAR;

  const { data, loading, error, rawResponse } = usePolledData<RadarData>(url, 8000, EMPTY_RADAR);

  return {
    tokens: data.tokens,
    entities: data.entities,
    recentEvents: data.recent_events,
    source: data.source,
    tokenCount: data.token_count,
    entityCount: data.entity_count,
    eventCount: data.event_count,
    loading,
    error,
    rawResponse,
  };
}

const EMPTY_METRICS: FlowMetrics = {
  tokens_tracked: 0, entities_tracked: 0,
  whale_count: 0, kol_count: 0,
  events_24h: 0, opinions_total: 0,
  plans: { meme: {}, whale: {}, kol: {} },
  sniper: {
    total_fills: 0, success_rate: 0, total_volume_usd: 0,
    avg_slippage_bps: 0, avg_latency_ms: 0, mev_incidents: 0, mev_loss_usd: 0,
  },
};

export function useFlowMetrics() {
  const { data, loading, error, rawResponse } = usePolledData<FlowMetrics>(
    API_ENDPOINTS.FLOW_METRICS, 15000, EMPTY_METRICS,
  );
  return { metrics: data, loading, error, rawResponse };
}

const EMPTY_SNIPER: SniperStatus = { is_live: false, route_health: {} };

export function useFlowSniper() {
  const { data: status, loading: statusLoading, error: statusError } = usePolledData<SniperStatus>(
    API_ENDPOINTS.FLOW_SNIPER_STATUS, 10000, EMPTY_SNIPER,
  );
  const { data: fillsData, loading: fillsLoading } = usePolledData<{ fills: SniperFill[]; count: number }>(
    API_ENDPOINTS.FLOW_SNIPER_FILLS, 10000, { fills: [], count: 0 },
  );

  return {
    status,
    fills: fillsData.fills,
    fillCount: fillsData.count,
    loading: statusLoading || fillsLoading,
    error: statusError,
  };
}

export function useFlowRisk() {
  const EMPTY: FlowRiskStatus = {
    config: {}, state: {
      domain_exposure_usd: 0, daily_pnl_usd: 0, daily_loss_usd: 0,
      is_throttled: false, is_halted: false, halt_reason: "",
      active_plan_count: 0,
    },
    nav_usd: 0, effective_max_domain_usd: 0, utilization_pct: 0,
  };
  const { data, loading, error } = usePolledData<FlowRiskStatus>(
    API_ENDPOINTS.FLOW_RISK, 10000, EMPTY,
  );
  return { risk: data, loading, error };
}
