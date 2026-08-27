import React, { useState, useEffect } from "react";
import { API_ENDPOINTS } from "../config/constants";

export default function KalshiPortfolioView() {
  const [positions, setPositions] = useState<any[]>([]);

  useEffect(() => {
    fetch(`${API_ENDPOINTS.KALSHI_POSITIONS}`)
      .then((r) => r.json())
      .then((data) => setPositions(data?.positions || []))
      .catch(() => setPositions([]));
  }, []);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-slate-100">Kalshi Portfolio</h1>
      <p className="text-slate-400">Portfolio overview and positions.</p>
      <pre className="bg-slate-900 p-4 rounded text-xs text-slate-300">
        {JSON.stringify({ endpoint: API_ENDPOINTS.KALSHI_POSITIONS, count: positions.length }, null, 2)}
      </pre>
    </div>
  );
}
