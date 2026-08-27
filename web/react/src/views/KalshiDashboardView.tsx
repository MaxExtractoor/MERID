import React, { useState, useEffect } from "react";
import { API_ENDPOINTS } from "../config/constants";

export default function KalshiDashboardView() {
  const [markets, setMarkets] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${API_ENDPOINTS.KALSHI_MARKETS}`)
      .then((r) => r.json())
      .then((data) => setMarkets(data?.markets || []))
      .catch(() => setMarkets([]));
  }, []);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-slate-100">Kalshi Markets</h1>
      <p className="text-slate-400">Dashboard for Kalshi market discovery.</p>
      <pre className="bg-slate-900 p-4 rounded text-xs text-slate-300">
        {JSON.stringify({ endpoint: API_ENDPOINTS.KALSHI_MARKETS, count: markets.length }, null, 2)}
      </pre>
    </div>
  );
}
