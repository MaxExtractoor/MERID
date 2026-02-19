/**
 * useLoopOrchestration — Hooks for MERID loop orchestration data.
 *
 * Provides:
 *   - useLoopOrchestration: polls orchestrator summary + history for pipeline
 *     status, cycle cadence, and phase-level metrics
 *   - useStageMetrics: polls system observability + health to derive per-stage
 *     health, wiring status, and throughput indicators
 */

import { useState, useEffect, useCallback } from "react";
import { API_ENDPOINTS } from "../config/constants";

/* ── Types ─────────────────────────────────────────────────────── */

export interface PhaseAgent {
  name: string;
  status: "success" | "error";
  outputSummary: string;
  durationMs: number;
}

export interface CyclePhase {
  name: string;
  status: string;
  agentCount: number;
  outputCount: number;
  durationMs: number;
  agents: PhaseAgent[];
}

export interface LatestCycle {
  cycleId: number;
  startedAt: string;
  completedAt: string;
  totalDurationMs: number;
  phases: CyclePhase[];
  proposalsGenerated: number;
  spikesDetected: number;
  verdictsIssued: number;
}

export interface CycleHistoryEntry {
  cycleId: number;
  startedAt: string;
  completedAt: string;
  totalDurationMs: number;
  phaseCount: number;
  proposalsGenerated: number;
}

export interface LoopOrchestrationData {
  status: string;
  summary: Record<string, unknown> | null;
  latestCycle: LatestCycle | null;
  history: CycleHistoryEntry[];
  avgCycleDurationMs: number;
  cyclesPerMinute: number;
  totalProposals: number;
}

/* ── Stage / Wiring types ──────────────────────────────────────── */

export type StageStatus = "healthy" | "degraded" | "down" | "unknown";

export interface StageHealth {
  name: string;
  displayName: string;
  status: StageStatus;
  latencyMs: number;
  throughput: number;
  errorRate: number;
  lastActive: number;
  detail: Record<string, unknown>;
}

export interface WiringLink {
  from: string;
  to: string;
  status: StageStatus;
  dataFlowRate: number;
  lastSeen: number;
}

export interface StageMetricsData {
  stages: StageHealth[];
  wiring: WiringLink[];
  overallStatus: StageStatus;
  services: Record<string, { status: string; last_check: number }>;
}

/* ── Pipeline stage definitions (canonical order) ──────────────── */

const PIPELINE_STAGES = [
  { name: "signal", displayName: "Signal Layer" },
  { name: "consensus", displayName: "Consensus" },
  { name: "debate", displayName: "Debate" },
  { name: "risk", displayName: "Risk" },
  { name: "execution", displayName: "Execution" },
  { name: "betting", displayName: "Betting" },
] as const;

const PIPELINE_WIRING: Array<[string, string]> = [
  ["signal", "consensus"],
  ["consensus", "debate"],
  ["debate", "risk"],
  ["risk", "execution"],
  ["execution", "betting"],
];

/* ── useLoopOrchestration ──────────────────────────────────────── */

export function useLoopOrchestration(pollMs = 15_000) {
  const [data, setData] = useState<LoopOrchestrationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [summaryRes, historyRes] = await Promise.all([
        fetch(API_ENDPOINTS.ORCHESTRATOR_SUMMARY),
        fetch(API_ENDPOINTS.ORCHESTRATOR_HISTORY),
      ]);

      const summaryJson = summaryRes.ok ? await summaryRes.json() : null;
      const historyJson = historyRes.ok ? await historyRes.json() : null;

      const latestCycle: LatestCycle | null =
        summaryJson?.latest_cycle ?? null;

      const history: CycleHistoryEntry[] = (
        historyJson?.cycles ?? []
      ).map((c: unknown) => ({
        cycleId: c.cycleId ?? 0,
        startedAt: c.startedAt ?? "",
        completedAt: c.completedAt ?? "",
        totalDurationMs: c.totalDurationMs ?? 0,
        phaseCount: c.phaseCount ?? 0,
        proposalsGenerated: c.proposalsGenerated ?? 0,
      }));

      // Compute cadence metrics
      const durations = history
        .map((c) => c.totalDurationMs)
        .filter((d) => d > 0);
      const avgCycleDurationMs =
        durations.length > 0
          ? durations.reduce((a, b) => a + b, 0) / durations.length
          : 0;

      // Cycles per minute from last 5 minutes of history
      let cyclesPerMinute = 0;
      if (history.length >= 2) {
        const recent = history.slice(-10);
        const first = new Date(recent[0].startedAt).getTime();
        const last = new Date(recent[recent.length - 1].completedAt).getTime();
        const spanMin = (last - first) / 60_000;
        if (spanMin > 0) cyclesPerMinute = recent.length / spanMin;
      }

      const totalProposals = history.reduce(
        (s, c) => s + c.proposalsGenerated,
        0
      );

      setData({
        status: summaryJson?.status ?? "unknown",
        summary: summaryJson?.summary ?? null,
        latestCycle,
        history,
        avgCycleDurationMs: Math.round(avgCycleDurationMs),
        cyclesPerMinute: Math.round(cyclesPerMinute * 100) / 100,
        totalProposals,
      });
      setError(null);
    } catch (e: unknown) {
      setError(e.message ?? "Failed to fetch orchestrator data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, error, refresh };
}

/* ── useStageMetrics ───────────────────────────────────────────── */

function deriveStageStatus(healthData: Record<string, unknown>): StageStatus {
  if (!healthData || healthData.error) return "unknown";
  // Check for explicit status field
  if (healthData.status === "healthy" || healthData.all_ok === true)
    return "healthy";
  if (healthData.status === "degraded" || healthData.all_ok === false)
    return "degraded";
  if (healthData.status === "down") return "down";
  // If data exists but no explicit status, assume healthy
  if (Object.keys(healthData).length > 0) return "healthy";
  return "unknown";
}

function extractLatency(healthData: Record<string, unknown>): number {
  return (
    healthData?.p95_ms ??
    healthData?.latency_ms ??
    healthData?.avg_latency_ms ??
    0
  );
}

function extractThroughput(healthData: Record<string, unknown>): number {
  return (
    healthData?.throughput ??
    healthData?.total ??
    healthData?.count ??
    healthData?.active_debates ??
    healthData?.total_opinions ??
    0
  );
}

function extractErrorRate(healthData: Record<string, unknown>): number {
  return (
    healthData?.error_rate ??
    healthData?.flip_rate ??
    0
  );
}

export function useStageMetrics(pollMs = 20_000) {
  const [data, setData] = useState<StageMetricsData | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [obsRes, healthRes] = await Promise.all([
        fetch(API_ENDPOINTS.OBSERVABILITY_SUMMARY),
        fetch(API_ENDPOINTS.SYSTEM_HEALTH),
      ]);

      const obs = obsRes.ok ? await obsRes.json() : {};
      const health = healthRes.ok ? await healthRes.json() : {};

      // Map observability subsections to pipeline stages
      const stageDataMap: Record<string, Record<string, unknown>> = {
        signal: obs.signal_metrics_slo ?? {},
        consensus: obs.consensus_store ?? {},
        debate: obs.collaboration_health ?? {},
        risk: obs.reward_engine_health ?? {},
        execution: obs.cognitive_health ?? {},
        betting: {
          ...(obs.betting_health ?? {}),
          ...(obs.sports_betting_health ?? {}),
        },
      };

      const stages: StageHealth[] = PIPELINE_STAGES.map((s) => {
        const d = stageDataMap[s.name] ?? {};
        return {
          name: s.name,
          displayName: s.displayName,
          status: deriveStageStatus(d),
          latencyMs: extractLatency(d),
          throughput: extractThroughput(d),
          errorRate: extractErrorRate(d),
          lastActive: Date.now() / 1000,
          detail: d,
        };
      });

      // Derive wiring links from stage adjacency
      const wiring: WiringLink[] = PIPELINE_WIRING.map(([from, to]) => {
        const fromStage = stages.find((s) => s.name === from);
        const toStage = stages.find((s) => s.name === to);
        const bothOk =
          fromStage?.status === "healthy" && toStage?.status === "healthy";
        const eitherDown =
          fromStage?.status === "down" || toStage?.status === "down";
        return {
          from,
          to,
          status: eitherDown ? "down" : bothOk ? "healthy" : "degraded",
          dataFlowRate: Math.min(
            fromStage?.throughput ?? 0,
            toStage?.throughput ?? 0
          ),
          lastSeen: Date.now() / 1000,
        };
      });

      const overallStatus: StageStatus = stages.some(
        (s) => s.status === "down"
      )
        ? "down"
        : stages.some((s) => s.status === "degraded")
        ? "degraded"
        : stages.every((s) => s.status === "healthy")
        ? "healthy"
        : "unknown";

      setData({
        stages,
        wiring,
        overallStatus,
        services: health.services ?? {},
      });
    } catch {
      // Silently fail — stale data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, refresh };
}
