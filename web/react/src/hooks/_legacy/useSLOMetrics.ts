/**
 * useSLOMetrics — Hooks for SLO burn-down, error budget, and subsystem health.
 *
 * Provides:
 *   - useSLOMetrics: polls observability endpoint and extracts SLO subsystem
 *     data with error budget computation
 *   - useSportsSLO: polls sports betting SLO metrics (latency, acceptance)
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

/* ── Types ─────────────────────────────────────────────────────── */

export interface SubsystemSLO {
  name: string;
  threshold_ms: number;
  p95_ms: number | null;
  ok: boolean;
  samples: number;
}

export interface SLOBurnPoint {
  timestamp: number;
  budget_remaining_pct: number;
  violations: number;
  total_checks: number;
}

export interface SLOMetricsData {
  subsystems: SubsystemSLO[];
  overall_ok: boolean;
  overall_p95_ms: number | null;
  overall_threshold_ms: number;
  error_budget_pct: number;
  burn_history: SLOBurnPoint[];
  firing_alerts: number;
  total_alerts: number;
  status: string;
  uptime_s: number;
}

export interface SportsSLOData {
  p95_acceptance_latency_ms: number;
  total_bets: number;
  slo_breaches: number;
  acceptance_rate: number;
  reprice_rate: number;
  slo_target_ms: number;
  budget_remaining_pct: number;
}

/* ── SLO budget computation ────────────────────────────────────── */

const MAX_BURN_POINTS = 60;
const ERROR_BUDGET_TOTAL = 100; // 100% budget

function computeErrorBudget(subsystems: SubsystemSLO[]): number {
  if (subsystems.length === 0) return 100;
  const okCount = subsystems.filter((s) => s.ok).length;
  return Math.round((okCount / subsystems.length) * ERROR_BUDGET_TOTAL);
}

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

/* ── useSLOMetrics ─────────────────────────────────────────────── */

export function useSLOMetrics(pollMs = 20_000) {
  const [data, setData] = useState<SLOMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const burnRef = useRef<SLOBurnPoint[]>([]);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OBSERVABILITY_SUMMARY}`, {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const raw = await res.json();

      // Extract SLO data from signal_metrics_slo
      const sloData = raw.signal_metrics_slo ?? {};
      const subsystemsMap = sloData.subsystems ?? {};
      const subsystems: SubsystemSLO[] = Object.entries(subsystemsMap)
        .filter(([name]) => !name.startsWith("_"))
        .map(([name, v]) => {
          const val = v as Record<string, unknown>;
          return {
            name,
            threshold_ms: (val.threshold_ms as number) ?? 0,
            p95_ms: (val.p95_ms as number) ?? null,
            ok: (val.ok as boolean) ?? false,
            samples: (val.samples as number) ?? 0,
          };
        });

      const overallEntry = subsystemsMap._overall ?? {};
      const overallOk = sloData.all_ok ?? false;

      const budget = computeErrorBudget(subsystems);

      // Accumulate burn history
      const now = Date.now() / 1000;
      const violations = subsystems.filter((s) => !s.ok).length;
      burnRef.current.push({
        timestamp: now,
        budget_remaining_pct: budget,
        violations,
        total_checks: subsystems.length,
      });
      while (burnRef.current.length > MAX_BURN_POINTS) burnRef.current.shift();

      // Alert summary
      const alerts = raw.alerts ?? {};
      const alertSummary = alerts.summary ?? {};

      setData({
        subsystems,
        overall_ok: overallOk,
        overall_p95_ms: overallEntry.p95_ms ?? null,
        overall_threshold_ms: overallEntry.threshold_ms ?? 2000,
        error_budget_pct: budget,
        burn_history: [...burnRef.current],
        firing_alerts: alertSummary.firing ?? 0,
        total_alerts: alertSummary.total_rules ?? 0,
        status: alertSummary.status ?? "unknown",
        uptime_s: raw.uptime_s ?? 0,
      });
    } catch {
      // Silently fail
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

/* ── useSportsSLO ──────────────────────────────────────────────── */

export function useSportsSLO(pollMs = 30_000) {
  const [data, setData] = useState<SportsSLOData | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SPORTS_SLO_METRICS}`, {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const raw = await res.json();

      const totalBets = raw.total_bets ?? 0;
      const breaches = raw.slo_breaches ?? 0;
      const budgetPct =
        totalBets > 0
          ? Math.round(((totalBets - breaches) / totalBets) * 100)
          : 100;

      setData({
        p95_acceptance_latency_ms: raw.p95_acceptance_latency_ms ?? 0,
        total_bets: totalBets,
        slo_breaches: breaches,
        acceptance_rate: raw.acceptance_rate ?? 0,
        reprice_rate: raw.reprice_rate ?? 0,
        slo_target_ms: raw.slo_target_ms ?? 300,
        budget_remaining_pct: budgetPct,
      });
    } catch {
      // Silently fail
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
