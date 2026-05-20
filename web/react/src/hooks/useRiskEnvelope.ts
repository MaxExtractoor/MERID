import { useEffect, useState } from 'react';
import { API_ENDPOINTS } from '../config/constants';

export interface RiskEnvelopeData {
  profile: string;
  envelope_enabled: boolean;
  message?: string;
  drawdown?: {
    peak_equity_usd: number;
    current_equity_usd: number;
    current_drawdown_pct: number;
    halt_pct: number;
    unwind_pct: number;
    distance_to_halt_pct: number;
  };
  adaptive_risk?: {
    bands: Array<{
      max_drawdown_pct: number;
      multiplier: number;
    }>;
    current_multiplier: number;
    is_halted: boolean;
  };
  kelly?: {
    kelly_fraction: number;
  };
  effective_risk?: {
    per_trade_risk_pct: number;
    effective_per_trade_risk_usd: number;
  };
}

export function useRiskEnvelope(pollIntervalMs: number = 10000) {
  const [data, setData] = useState<RiskEnvelopeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchEnvelope = async () => {
      try {
        const response = await fetch(API_ENDPOINTS.KALSHI_RISK_ENVELOPE);
        if (!response.ok) {
          throw new Error(`Failed to fetch risk envelope: ${response.statusText}`);
        }
        const result = await response.json();
        setData(result);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchEnvelope();
    const interval = setInterval(fetchEnvelope, pollIntervalMs);

    return () => clearInterval(interval);
  }, [pollIntervalMs]);

  return { data, loading, error };
}
