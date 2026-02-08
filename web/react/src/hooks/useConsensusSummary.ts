/**
 * useConsensusSummary — polls GET /api/v1/consensus/summary and exposes
 * a per-symbol map of consensus stance, confidence, agent counts, and
 * active plan counts.
 *
 * Consumer: Trading (consensus pill), Risk/Operator (cross-market table).
 */

import { useMemo } from "react";
import { useApiData } from "./useApiData";
import { isStub } from "../utils/stub";

/* ── Types ─────────────────────────────────────────────────────── */

export type AssetClass = "crypto" | "equity" | "fx" | "index" | "other";

export type Stance =
  | "strong_long"
  | "weak_long"
  | "neutral"
  | "weak_short"
  | "strong_short";

export interface ConsensusSymbolSummary {
  symbol: string;
  asset_class: AssetClass;
  stance: Stance;
  confidence: number;
  supporting_agents: number;
  opposing_agents: number;
  active_plans: {
    proposed: number;
    approved: number;
    executing: number;
  };
  last_opinion_at?: string;
  last_plan_id?: string;
}

interface SummaryResponse {
  symbols: ConsensusSymbolSummary[];
  stub: boolean;
}

export interface UseConsensusSummaryResult {
  /** All symbol summaries as an array. */
  symbols: ConsensusSymbolSummary[];
  /** Keyed by symbol for O(1) lookup. */
  bySymbol: Record<string, ConsensusSymbolSummary>;
  /** The raw JSON response — pass to isStub() for gate checks. */
  rawResponse: unknown;
  loading: boolean;
  error?: Error;
}

/* ── Hook ──────────────────────────────────────────────────────── */

export function useConsensusSummary(
  pollingInterval = 15_000,
): UseConsensusSummaryResult {
  const { data, loading, error, rawResponse } = useApiData<SummaryResponse>(
    "/api/v1/consensus/summary",
    { pollingInterval },
  );

  const symbols = data?.symbols ?? [];

  const bySymbol = useMemo(() => {
    const map: Record<string, ConsensusSymbolSummary> = {};
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
  };
}
