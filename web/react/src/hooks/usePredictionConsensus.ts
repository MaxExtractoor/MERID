/**
 * usePredictionConsensus — polls GET /api/v1/prediction/consensus/summary
 * and exposes per-symbol prediction market consensus data: swarm_prob vs
 * market_prob, edge, stance, agent counts, and active plan counts.
 *
 * Consumer: PredictionConsensusView, PredictionEdgePill.
 */

import { useMemo } from "react";
import { useApiData } from "./useApiData";
import { API_ENDPOINTS } from "../config/constants";

/* ── Types ─────────────────────────────────────────────────────── */

export type PredictionStance =
  | "strong_yes"
  | "weak_yes"
  | "neutral"
  | "weak_no"
  | "strong_no";

export interface PredictionSymbolSummary {
  symbol: string;
  venue: string;
  event_id: string;
  ticker: string;
  outcome: string;
  category: string;
  title: string;
  expiry: string | null;
  swarm_prob: number;
  market_prob: number;
  edge: number;
  stance: PredictionStance;
  confidence: number;
  supporting_agents: number;
  opposing_agents: number;
  active_plans: {
    proposed: number;
    approved: number;
    executing: number;
  };
  opinion_count: number;
  volume: number;
}

interface PredictionSummaryResponse {
  symbols: PredictionSymbolSummary[];
  count: number;
}

export interface BrierData {
  swarm_brier: number | null;
  market_brier: number | null;
  swarm_vs_market: string;
  agent_ranking: { agent_id: string; brier: number }[];
  resolved_count: number;
  total_pnl_usd: number;
  calibration: { bucket: string; expected_rate: number; actual_rate: number; count: number }[];
}

export interface PredictionMetricsResponse {
  brier: BrierData;
  universe: { total_instruments: number; active_instruments: number };
  plans: { proposed: number; approved: number; executing: number; closed: number };
}

export interface UsePredictionConsensusResult {
  symbols: PredictionSymbolSummary[];
  bySymbol: Record<string, PredictionSymbolSummary>;
  rawResponse: unknown;
  loading: boolean;
  error?: Error;
  refetch: () => void;
}

export interface UsePredictionMetricsResult {
  metrics: PredictionMetricsResponse | null;
  rawResponse: unknown;
  loading: boolean;
  error?: Error;
}

/* ── Hook: consensus summary ──────────────────────────────────── */

export function usePredictionConsensus(
  pollingInterval = 15_000,
): UsePredictionConsensusResult {
  const { data, loading, error, rawResponse, refetch } =
    useApiData<PredictionSummaryResponse>(
      API_ENDPOINTS.PREDICTION_CONSENSUS_SUMMARY,
      { pollingInterval },
    );

  const symbols = useMemo(() => data?.symbols ?? [], [data?.symbols]);

  const bySymbol = useMemo(() => {
    const map: Record<string, PredictionSymbolSummary> = {};
    for (const s of symbols) {
      map[s.symbol] = s;
    }
    return map;
  }, [symbols]);

  return {
    symbols,
    bySymbol,
    rawResponse,
    loading,
    error: error ?? undefined,
    refetch,
  };
}

/* ── Hook: prediction metrics ─────────────────────────────────── */

export function usePredictionMetrics(
  pollingInterval = 30_000,
): UsePredictionMetricsResult {
  const { data, loading, error, rawResponse } =
    useApiData<PredictionMetricsResponse>(
      API_ENDPOINTS.PREDICTION_METRICS,
      { pollingInterval },
    );

  return {
    metrics: data ?? null,
    rawResponse,
    loading,
    error: error ?? undefined,
  };
}
