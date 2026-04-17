// web/react/src/hooks/useCryptoPerformance.ts
import { useEffect, useState } from "react";
import { KALSHI_PERF_ENDPOINTS } from "../constants/api";
import { AUTH_TOKEN_KEY } from "../config/constants";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}`, "X-Session-ID": token, "merid-access": "O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8" } : { "merid-access": "O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8" };
}

type EquityPoint = { ts: string; value: number };

type TradeRow = {
  ts: string;
  market_id: string;
  side: string;
  size_pct: number;
  pnl: number;
  reason?: string;
};

type PerformancePayload = {
  agent_id: string;
  summary: Record<string, any>;
  equity_series: EquityPoint[];
  recent_trades: TradeRow[];
};

type UseCryptoPerformanceResult = {
  data: PerformancePayload | null;
  loading: boolean;
  error: string | null;
};

export const useCryptoPerformance = (endpoint: string): UseCryptoPerformanceResult => {
  const [data, setData] = useState<PerformancePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(endpoint, { headers: authHeaders() });
        if (!resp.ok) throw new Error(await resp.text());
        const payload = await resp.json();

        const normalized: PerformancePayload = {
          agent_id: payload.agent_id ?? "unknown",
          summary: {
            total_pnl: payload.summary?.total_pnl ?? payload.summary?.total_pnl_usd ?? 0,
            win_rate: payload.summary?.win_rate ?? 0,
            max_dd: payload.summary?.max_dd ?? payload.summary?.max_drawdown ?? 0,
            trades_today: payload.summary?.trades_today ?? payload.summary?.trades_24h ?? 0,
            trades_7d: payload.summary?.trades_7d ?? payload.summary?.trades_last_7d ?? 0,
            ...payload.summary,
          },
          equity_series:
            payload.equity_series ??
            payload.equity_curve?.map((p: any) => ({
              ts: p.ts ?? p.timestamp,
              value: p.value ?? p.equity ?? p.pnl_cum,
            })) ??
            [],
          recent_trades: (payload.recent_trades ?? []).map((r: any) => ({
            ts: r.ts ?? r.timestamp ?? r.entry_ts,
            market_id: r.market_id ?? "",
            side: r.side ?? (r.direction === "up" ? "buy_yes" : "buy_no"),
            size_pct: r.size_pct ?? 0,
            pnl: r.pnl ?? 0,
            reason: r.reason,
          })),
        };

        if (!cancelled) setData(normalized);
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [endpoint]);

  return { data, loading, error };
};

type BlockedReasonsResult = {
  data: Record<string, number> | null;
  loading: boolean;
  error: string | null;
};

export const useBlockedReasons = (agentId: string, days = 7): BlockedReasonsResult => {
  const [data, setData] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const endpoint = KALSHI_PERF_ENDPOINTS.BLOCKED_REASONS(agentId, days);
        const resp = await fetch(endpoint, { headers: authHeaders() });
        if (!resp.ok) throw new Error(await resp.text());
        const payload = await resp.json();
        if (!cancelled) setData(payload.blocked_reasons ?? {});
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [agentId, days]);

  return { data, loading, error };
};
