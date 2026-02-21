import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface EvidenceLink {
  id: string;
  evidence_type: string;
  reference_id: string;
  title: string;
  url: string;
  supports: boolean;
  strength: number;
  added_by: string;
  added_at: number;
  notes: string;
}

export interface RegimeTag {
  category: string;
  label: string;
  description: string;
}

export interface Hypothesis {
  id: string;
  domain: string;
  statement: string;
  confidence: number;
  evidence_count: number;
  last_updated: string;
  status: 'active' | 'confirmed' | 'refuted' | 'stale';
  flip_count: number;
  regime_tag: RegimeTag;
  evidence_links: EvidenceLink[];
  owner: string;
  prior_confidence: number | null;
  broken_at: number | null;
  broken_reason: string;
}

export interface CognitiveMetrics {
  total_hypotheses: number;
  active_hypotheses: number;
  confirmed: number;
  refuted: number;
  stale: number;
  avg_confidence: number;
  flip_rate: number;
  stuck_models: number;
  cognitive_health: 'healthy' | 'degraded' | 'unhealthy';
}

export interface CognitiveSnapshot {
  hypotheses: Hypothesis[];
  metrics: CognitiveMetrics;
  stuck_models: { model_id: string; reason: string; since: string }[];
  last_refresh: string;
}

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

export function useCognitive(pollMs = 15000) {
  const [snapshot, setSnapshot] = useState<CognitiveSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.COGNITIVE_SNAPSHOT}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setSnapshot({
          hypotheses: data.hypotheses ?? data.hypothesis_sets ?? [],
          metrics: data.metrics ?? {
            total_hypotheses: 0, active_hypotheses: 0, confirmed: 0,
            refuted: 0, stale: 0, avg_confidence: 0, flip_rate: 0,
            stuck_models: 0, cognitive_health: 'healthy',
          },
          stuck_models: data.stuck_models ?? [],
          last_refresh: data.last_refresh ?? new Date().toISOString(),
        });
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

  return { snapshot, loading, error, refresh };
}
