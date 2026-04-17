// web/react/src/hooks/useKalshiCryptoSignals.ts
import { useEffect, useState, useCallback } from "react";
import { AUTH_TOKEN_KEY } from "../config/constants";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}`, "X-Session-ID": token, "merid-access": "O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8" } : { "merid-access": "O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8" };
}

type EdgeSignal = {
  implied_prob: number;
  model_prob: number;
  ev_cents: number;
  edge_pct: number;
  confidence: number;
  confidence_bucket: string;
  sizing_tier: string;
  product?: string;
  agent_id?: string;
  market_id?: string;
  bid?: number;
  ask?: number;
};

type EdgeResponse = {
  signals: Record<string, EdgeSignal>;
  count: number;
  kelly_fraction: number;
  effective_fraction: number;
  drawdown_pct: number;
};

export const useKalshiCryptoEdgeSignals = () => {
  const [data, setData] = useState<EdgeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/kalshi-grid/crypto/edge", { headers: authHeaders() });
      if (!resp.ok) throw new Error(await resp.text());
      const json = await resp.json();
      setData(json);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => clearInterval(id);
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
};
