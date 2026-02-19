/**
 * useDebateCalibration — fetches debate metrics, calibration bins,
 * leaderboard, team diversity, and agent badges for the
 * Debate & Agent Calibration Visualization sprint.
 *
 * Consumers: PredictionConsensusView (Calibration tab),
 *            AgentCalibrationProfile, BrierTimeSeriesChart,
 *            CalibrationChart, DebateLiftChart, TeamDiversityCard.
 */

import { useCallback, useEffect, useState } from "react";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

/* ── Types ─────────────────────────────────────────────────────── */

export interface DebateMetrics {
  active_debates: number;
  total_debates: number;
  avg_debate_lift: number;
  avg_disagreement_width?: number;
  total_arguments?: number;
  suppressed_count?: number;
  suppression_rate?: number;
}

export interface CalibrationBin {
  bin_start: number;
  bin_end: number;
  predicted_avg: number;
  actual_rate: number;
  count: number;
}

export interface AgentCalibrationData {
  agent_id: string;
  calibration_score: number | null;
  total_predictions: number;
  bins: CalibrationBin[];
}

export interface LeaderboardAgent {
  agent_id: string;
  total_points: number;
  brier?: number;
  accuracy?: number;
  debate_count?: number;
  badges?: string[];
}

export interface LeaderboardTeam {
  team_id: string;
  name: string;
  total_points: number;
  member_count?: number;
}

export interface LeaderboardData {
  agents: LeaderboardAgent[];
  teams: LeaderboardTeam[];
  debate_impact: Array<{
    agent_id: string;
    avg_lift: number;
    debate_count: number;
  }>;
}

export interface TeamDiversity {
  team_id: string;
  diversity_score: number;
  strategies: string[];
  member_count?: number;
}

export interface AgentBadge {
  name: string;
  tier: string;
  description?: string;
}

export interface AgentProfile {
  agent_id: string;
  calibration: AgentCalibrationData | null;
  badges: AgentBadge[];
  rewards_total: number;
  loading: boolean;
}

/* ── Hook: debate metrics ─────────────────────────────────────── */

export function useDebateMetrics(pollingInterval = 30_000) {
  const [metrics, setMetrics] = useState<DebateMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.DEBATE_METRICS}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        setMetrics(await res.json());
        setError(null);
      }
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "Failed to fetch debate metrics";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, pollingInterval);
    return () => clearInterval(id);
  }, [fetchData, pollingInterval]);

  return { metrics, loading, error, refetch: fetchData };
}

/* ── Hook: leaderboard ────────────────────────────────────────── */

export function useDebateLeaderboard(pollingInterval = 60_000) {
  const [data, setData] = useState<LeaderboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.DEBATE_LEADERBOARD}?limit=20`, {
        headers: authHeaders(),
      });
      if (res.ok) setData(await res.json());
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, pollingInterval);
    return () => clearInterval(id);
  }, [fetchData, pollingInterval]);

  return { data, loading, refetch: fetchData };
}

/* ── Hook: agent calibration (on-demand) ──────────────────────── */

export function useAgentCalibration(agentId: string | null) {
  const [calibration, setCalibration] = useState<AgentCalibrationData | null>(null);
  const [badges, setBadges] = useState<AgentBadge[]>([]);
  const [rewardsTotal, setRewardsTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!agentId) {
      setCalibration(null);
      setBadges([]);
      setRewardsTotal(0);
      return;
    }

    let cancelled = false;
    setLoading(true);

    const opts = { headers: authHeaders() };
    Promise.all([
      fetch(`${API_BASE_URL}${API_ENDPOINTS.AGENT_CALIBRATION(agentId)}`, opts).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE_URL}${API_ENDPOINTS.AGENT_BADGES(agentId)}`, opts).then(r => r.ok ? r.json() : null),
      fetch(`${API_BASE_URL}${API_ENDPOINTS.AGENT_REWARDS(agentId)}`, opts).then(r => r.ok ? r.json() : null),
    ]).then(([calData, badgeData, rewardData]) => {
      if (cancelled) return;
      setCalibration(calData);
      setBadges(badgeData?.badges ?? []);
      setRewardsTotal(rewardData?.total_points ?? 0);
    }).catch(() => undefined).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, [agentId]);

  return { calibration, badges, rewardsTotal, loading };
}

/* ── Hook: team diversity (on-demand) ─────────────────────────── */

export function useTeamDiversity(teamId: string | null) {
  const [diversity, setDiversity] = useState<TeamDiversity | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!teamId) { setDiversity(null); return; }

    let cancelled = false;
    setLoading(true);

    fetch(`${API_BASE_URL}${API_ENDPOINTS.TEAM_DIVERSITY(teamId)}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled) setDiversity(d); })
      .catch(() => undefined)
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [teamId]);

  return { diversity, loading };
}
