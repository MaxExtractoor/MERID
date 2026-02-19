import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface LiveOddsEntry {
  event_id: string;
  outcome_label: string;
  implied_prob: number;
  decimal_odds: number;
  american_odds: number;
  provider: string;
  is_live: boolean;
  age_ms: number;
}

export interface SportEvent {
  event_id: string;
  sport: string;
  league: string;
  home_team: string;
  away_team: string;
  start_time: number;
  is_live: boolean;
  status: string;
  score_home?: number;
  score_away?: number;
}

export interface AnomalyAlert {
  id: string;
  anomaly_type: string;
  severity: string;
  source: string;
  description: string;
  timestamp: number;
  acknowledged: boolean;
}

export interface SportsLiveData {
  events: SportEvent[];
  live_odds: LiveOddsEntry[];
  anomalies: AnomalyAlert[];
  stats: {
    total_events: number;
    live_events: number;
    total_anomalies: number;
    unacknowledged: number;
  };
}

export function useSportsLive(pollMs = 5000) {
  const [data, setData] = useState<SportsLiveData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SPORTS_LIVE_ODDS}`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const raw = await res.json();
        const events = raw.events ?? raw.data?.events ?? [];
        const liveOdds = raw.live_odds ?? raw.data?.live_odds ?? [];
        const anomalies = raw.anomalies ?? raw.data?.anomalies ?? [];
        setData({
          events,
          live_odds: liveOdds,
          anomalies,
          stats: raw.stats ?? {
            total_events: events.length,
            live_events: events.filter((e: SportEvent) => e.is_live).length,
            total_anomalies: anomalies.length,
            unacknowledged: anomalies.filter((a: AnomalyAlert) => !a.acknowledged).length,
          },
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
  }, [authHeaders]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, error, refresh };
}
