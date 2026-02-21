import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

/* ── Stuck Model ──────────────────────────────────────────── */

export interface StuckModel {
  market_id: string;
  brier_score: number;
  last_hypothesis_update: number;
  surprise_at: number;
  lag_seconds: number;
  stale_hypotheses: number;
  owners: string[];
  suggestion: string;
}

/* ── Conceptual Disagreement ──────────────────────────────── */

export interface ConceptualDisagreement {
  market_id: string;
  agents: { agent_id: string; probability: number }[];
  probability_spread: number;
  regime_tags_a: string[];
  regime_tags_b: string[];
  suggestion: string;
}

/* ── Hypothesis Dynamics ──────────────────────────────────── */

export interface HypothesisDynamics {
  market_id: string;
  window_seconds: number;
  total_actions: number;
  flips: number;
  updates: number;
  creations: number;
  retirements: number;
  breakages: number;
  flip_rate_per_day: number;
  mean_lag_after_surprise_s: number | null;
  rigidity_flag: boolean;
  flailing_flag: boolean;
}

/* ── Reality Debug Report ─────────────────────────────────── */

export interface RealityDebugReport {
  stuck_models: StuckModel[];
  conceptual_disagreements: ConceptualDisagreement[];
  hypothesis_dynamics: Record<string, HypothesisDynamics>;
  cognitive_metrics: Record<string, unknown>;
  markets_analyzed: number;
  stuck_count: number;
  disagreement_count: number;
}

/* ── Cognitive Health ─────────────────────────────────────── */

export interface CognitiveHealth {
  pct_surprised_with_updates: number;
  mean_hypothesis_lag_after_surprise_s: number | null;
  hypothesis_flip_rate_per_day: number;
  active_hypotheses: number;
  broken_hypotheses: number;
  total_hypotheses: number;
  markets_covered: number;
  unique_owners: number;
  rigidity_count: number;
  flailing_count: number;
  window_seconds: number;
}

/* ── Cognitive Action ─────────────────────────────────────── */

export interface CognitiveAction {
  id: string;
  hypothesis_id: string;
  snapshot_id: string;
  market_id: string;
  action: string;
  actor: string;
  detail: string;
  old_confidence: number | null;
  new_confidence: number | null;
  created_at: number;
}

/* ── Hook: useRealityDebug ────────────────────────────────── */

export function useRealityDebug(pollMs = 30000) {
  const [report, setReport] = useState<RealityDebugReport | null>(null);
  const [health, setHealth] = useState<CognitiveHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [debugRes, healthRes] = await Promise.all([
        fetch(`${API_BASE_URL}${API_ENDPOINTS.COGNITIVE_REALITY_DEBUG}`, {
          headers: authHeaders(),
        }),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.COGNITIVE_HEALTH}`, {
          headers: authHeaders(),
        }),
      ]);

      if (debugRes.ok) {
        const data = await debugRes.json();
        setReport({
          stuck_models: data.stuck_models ?? [],
          conceptual_disagreements: data.conceptual_disagreements ?? [],
          hypothesis_dynamics: data.hypothesis_dynamics ?? {},
          cognitive_metrics: data.cognitive_metrics ?? {},
          markets_analyzed: data.markets_analyzed ?? 0,
          stuck_count: data.stuck_count ?? 0,
          disagreement_count: data.disagreement_count ?? 0,
        });
      }

      if (healthRes.ok) {
        const hData = await healthRes.json();
        setHealth({
          pct_surprised_with_updates: hData.pct_surprised_with_updates ?? 100,
          mean_hypothesis_lag_after_surprise_s: hData.mean_hypothesis_lag_after_surprise_s ?? null,
          hypothesis_flip_rate_per_day: hData.hypothesis_flip_rate_per_day ?? 0,
          active_hypotheses: hData.active_hypotheses ?? 0,
          broken_hypotheses: hData.broken_hypotheses ?? 0,
          total_hypotheses: hData.total_hypotheses ?? 0,
          markets_covered: hData.markets_covered ?? 0,
          unique_owners: hData.unique_owners ?? 0,
          rigidity_count: hData.rigidity_count ?? 0,
          flailing_count: hData.flailing_count ?? 0,
          window_seconds: hData.window_seconds ?? 604800,
        });
      }

      if (!debugRes.ok && !healthRes.ok) {
        throw new Error(`Debug ${debugRes.status}, Health ${healthRes.status}`);
      }

      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { report, health, loading, error, refresh };
}

/* ── Hook: useCognitiveActions ────────────────────────────── */

export function useCognitiveActions(pollMs = 30000) {
  const [actions, setActions] = useState<CognitiveAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.COGNITIVE_ACTIONS}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setActions(data.actions ?? []);
        setError(null);
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { actions, loading, error, refresh };
}
