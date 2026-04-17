// web/react/src/hooks/useKalshiPaperPortfolio.ts
import { useEffect, useState, useCallback } from "react";
import { authHeaders } from "../api/auth";

type AgentPerformance = {
  total_trades: number;
  total_pnl: number;
  win_rate: number;
  avg_trade_pnl: number;
};

type AgentComparison = {
  paper: AgentPerformance;
  shadow: AgentPerformance;
  pnl_delta: number;
  trade_rate_delta: number;
  win_rate_delta: number;
};

type PaperVsShadowResponse = {
  comparison: {
    [agentId: string]: AgentComparison;
  };
  paper_summary: {
    portfolio_id: string;
    cash_balance: number;
    margin_used: number;
    total_pnl: number;
    open_positions: number;
    total_trades: number;
    win_rate: number;
    available_margin: number;
  };
  error?: string;
};

export const useKalshiPaperVsShadow = () => {
  const [data, setData] = useState<PaperVsShadowResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/kalshi-grid/crypto/paper-vs-shadow", { headers: authHeaders() });
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
    const id = setInterval(fetchData, 10000);
    return () => clearInterval(id);
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
};
