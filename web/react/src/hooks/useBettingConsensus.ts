/**
 * useBettingConsensus — polls GET /api/v1/betting/consensus/summary
 * and exposes per-event betting consensus: sportsbook + prediction market + swarm.
 *
 * Also: useBettingMetrics for win rate, ROI, PnL.
 */

import { useMemo } from "react";
import { useApiData } from "./useApiData";
import { API_ENDPOINTS } from "../config/constants";

/* ── Types ─────────────────────────────────────────────────────── */

export interface BookOddsData {
  book: string;
  outcome_id: string;
  american_odds: number;
  decimal_odds: number;
  implied_prob: number;
}

export interface BettingEventData {
  id: string;
  sport: string;
  league: string;
  title: string;
  home_team: string;
  away_team: string;
  start_time: number;
  state: "pre" | "live" | "final" | "cancelled";
  score_home: number | null;
  score_away: number | null;
  period: string;
  clock: string;
  outcomes: { id: string; name: string; market_type: string }[];
  market_types: string[];
  kalshi_event_id: string | null;
}

export interface BettingConsensusData {
  event_id: string;
  event: BettingEventData | null;
  sportsbook_consensus_prob: Record<string, number>;
  sharp_book_prob: Record<string, number>;
  best_book_odds: Record<string, BookOddsData>;
  book_count: number;
  prediction_market_prob: Record<string, number>;
  prediction_market_source: string;
  swarm_prob: Record<string, number>;
  swarm_confidence: number;
  swarm_supporting_agents: number;
  swarm_opposing_agents: number;
  swarm_opinion_count: number;
  edge_vs_books: Record<string, number>;
  edge_vs_prediction: Record<string, number>;
  stance: string;
  max_edge: number;
  active_plans: { proposed: number; approved: number; executing: number };
  state: "pre" | "live" | "final";
  last_update_ts: number;
  arbitrage_flag: boolean;
}

interface BettingSummaryResponse {
  events: BettingConsensusData[];
  count: number;
  live_count: number;
}

export interface BettingMetricsData {
  total_bets: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_staked_usd: number;
  total_pnl_usd: number;
  roi: number;
  active_events: number;
  live_events: number;
  plans: Record<string, number>;
}

export interface UseBettingConsensusResult {
  events: BettingConsensusData[];
  byEventId: Record<string, BettingConsensusData>;
  liveCount: number;
  rawResponse: unknown;
  loading: boolean;
  error?: Error;
  refetch: () => void;
}

export interface UseBettingMetricsResult {
  metrics: BettingMetricsData | null;
  rawResponse: unknown;
  loading: boolean;
  error?: Error;
}

/* ── Hook: betting consensus summary ──────────────────────────── */

export function useBettingConsensus(
  pollingInterval = 15_000,
): UseBettingConsensusResult {
  const { data, loading, error, rawResponse, refetch } =
    useApiData<BettingSummaryResponse>(
      API_ENDPOINTS.BETTING_CONSENSUS_SUMMARY,
      { pollingInterval },
    );

  const events = data?.events ?? [];

  const byEventId = useMemo(() => {
    const map: Record<string, BettingConsensusData> = {};
    for (const e of events) map[e.event_id] = e;
    return map;
  }, [events]);

  return {
    events,
    byEventId,
    liveCount: data?.live_count ?? 0,
    rawResponse,
    loading,
    error: error ?? undefined,
    refetch,
  };
}

/* ── Hook: betting metrics ────────────────────────────────────── */

export function useBettingMetrics(
  pollingInterval = 30_000,
): UseBettingMetricsResult {
  const { data, loading, error, rawResponse } =
    useApiData<BettingMetricsData>(
      API_ENDPOINTS.BETTING_CONSENSUS_METRICS,
      { pollingInterval },
    );

  return {
    metrics: data ?? null,
    rawResponse,
    loading,
    error: error ?? undefined,
  };
}
