import React, { useState, useEffect, useCallback } from "react";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

// ── Types ──────────────────────────────────────────────────────────────

interface KalshiContract {
  ticker: string;
  question: string;
  yes_price_cents: number | null;
  no_price_cents: number | null;
  implied_prob: number | null;
  strike: number | null;
  strike_vs_spot_pct: number | null;
  volume: number;
  open_interest: number;
  timeframe: string | null;
  series_ticker: string | null;
  expires_at: string | null;
  minutes_to_expiry: number | null;
}

interface AssetData {
  spot_usd: number | null;
  total_contracts: number;
  nearest_expiry: string | null;
  by_timeframe: Record<string, KalshiContract[]>;
}

interface SpotVsKalshiResponse {
  assets: Record<string, AssetData>;
  timestamp: string;
  latency_ms: number;
}

// ── Constants ──────────────────────────────────────────────────────────

const ASSET_META: Record<string, { color: string; icon: string }> = {
  BTC: { color: "text-orange-400", icon: "₿" },
  ETH: { color: "text-blue-400", icon: "Ξ" },
  SOL: { color: "text-purple-400", icon: "◎" },
  XRP: { color: "text-green-400", icon: "✕" },
  DOGE: { color: "text-yellow-400", icon: "Ð" },
};

const TF_ORDER = ["15m", "1h", "daily", "weekly", "unknown"];

// ── Helpers ────────────────────────────────────────────────────────────

function fmtUsd(val: number | null): string {
  if (val === null || val === undefined) return "—";
  if (val >= 1000) return `$${val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `$${val.toFixed(4)}`;
}

function fmtCents(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `${val.toFixed(0)}¢`;
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;
}

function fmtProb(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `${(val * 100).toFixed(1)}%`;
}

function fmtExpiry(minutes: number | null): string {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)}h`;
  return `${(minutes / 1440).toFixed(1)}d`;
}

function deltaColor(pct: number | null): string {
  if (pct === null) return "text-slate-500";
  const abs = Math.abs(pct);
  if (abs < 0.5) return "text-emerald-400";
  if (abs < 2) return "text-yellow-400";
  return "text-red-400";
}

// ── Component ──────────────────────────────────────────────────────────

export const CryptoSpotKalshiPanel: React.FC = () => {
  const [data, setData] = useState<SpotVsKalshiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedAsset, setExpandedAsset] = useState<string | null>("BTC");

  const fetchData = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}${API_ENDPOINTS.CRYPTO_SPOT_VS_KALSHI}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 15_000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-5 bg-slate-800 rounded w-56 mb-4" />
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-16 bg-slate-800 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800/50 p-6">
        <div className="text-red-400 font-semibold mb-1">Spot vs Kalshi Unavailable</div>
        <p className="text-sm text-slate-400">{error}</p>
        <button
          type="button"
          onClick={fetchData}
          className="mt-3 text-sm text-blue-400 hover:text-blue-300 transition"
        >
          Retry
        </button>
      </div>
    );
  }

  const assets = data?.assets ?? {};

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200 tracking-wide uppercase">
          Crypto Spot vs Kalshi
        </h3>
        <div className="flex items-center gap-3">
          {/* P0 Guardrails Status */}
          {data && (
            <div className="flex items-center gap-2">
              {/* P0-001: Spot staleness indicator */}
              {(data as any).spot_staleness_violations > 0 && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30"
                  title={`P0-001: ${(data as any).spot_staleness_violations} staleness violations (merid_pm_spot_staleness_violations_total)`}
                >
                  ⚠ Stale Spot
                </span>
              )}
              {/* P0-003: Settlement guard indicator */}
              {(data as any).settlement_guard_seconds > 0 && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30"
                  title={`P0-003: Settlement guard ${(data as any).settlement_guard_seconds}s (per-timeframe guard active)`}
                >
                  🛡 Guard {(data as any).settlement_guard_seconds}s
                </span>
              )}
              <span className="text-xs text-slate-500">
                {data.latency_ms.toFixed(0)}ms
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={fetchData}
            className="text-xs text-blue-400 hover:text-blue-300 transition"
            title="Refresh"
          >
            ↻
          </button>
        </div>
      </div>

      {/* Asset rows */}
      <div className="divide-y divide-slate-800/60">
        {Object.entries(ASSET_META).map(([asset, meta]) => {
          const ad = assets[asset];
          if (!ad) return null;
          const isExpanded = expandedAsset === asset;
          const timeframes = Object.keys(ad.by_timeframe).sort(
            (a, b) => TF_ORDER.indexOf(a) - TF_ORDER.indexOf(b)
          );

          return (
            <div key={asset}>
              {/* Summary row */}
              <button
                type="button"
                className="w-full flex items-center gap-4 px-5 py-3 hover:bg-slate-800/40 transition text-left"
                onClick={() => setExpandedAsset(isExpanded ? null : asset)}
              >
                {/* Asset icon + name */}
                <div className="flex items-center gap-2 w-24 shrink-0">
                  <span className={`text-lg ${meta.color}`}>{meta.icon}</span>
                  <span className={`font-semibold text-sm ${meta.color}`}>{asset}</span>
                </div>

                {/* Spot price */}
                <div className="w-36 shrink-0">
                  <div className="text-xs text-slate-500 mb-0.5">Spot</div>
                  <div className="text-sm font-mono text-slate-100">
                    {fmtUsd(ad.spot_usd)}
                  </div>
                </div>

                {/* Contract count */}
                <div className="w-20 shrink-0 text-center">
                  <div className="text-xs text-slate-500 mb-0.5">Contracts</div>
                  <div className="text-sm font-mono text-slate-300">
                    {ad.total_contracts}
                  </div>
                </div>

                {/* Timeframes available */}
                <div className="flex-1 flex items-center gap-1.5">
                  {timeframes.map((tf) => (
                    <span
                      key={tf}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase"
                    >
                      {tf} ({ad.by_timeframe[tf].length})
                    </span>
                  ))}
                </div>

                {/* Expand chevron */}
                <span className="text-slate-500 text-xs ml-auto">
                  {isExpanded ? "▾" : "▸"}
                </span>
              </button>

              {/* Expanded contract table */}
              {isExpanded && (
                <div className="bg-slate-950/50 px-5 pb-4">
                  {timeframes.length === 0 ? (
                    <p className="text-xs text-slate-500 py-2">No active markets</p>
                  ) : (
                    timeframes.map((tf) => (
                      <div key={tf} className="mb-3 last:mb-0">
                        <div className="text-[10px] uppercase text-slate-500 font-semibold mb-1.5 tracking-wider">
                          {tf}
                        </div>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-slate-500 border-b border-slate-800/50">
                                <th className="text-left py-1 pr-3 font-medium">Ticker</th>
                                <th className="text-right py-1 px-2 font-medium">Strike</th>
                                <th className="text-right py-1 px-2 font-medium">Δ Spot</th>
                                <th className="text-right py-1 px-2 font-medium">YES</th>
                                <th className="text-right py-1 px-2 font-medium">NO</th>
                                <th className="text-right py-1 px-2 font-medium">Prob</th>
                                <th className="text-right py-1 px-2 font-medium">Vol</th>
                                <th className="text-right py-1 pl-2 font-medium">Expiry</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/30">
                              {ad.by_timeframe[tf].slice(0, 15).map((c) => (
                                <tr key={c.ticker} className="hover:bg-slate-800/20">
                                  <td className="py-1.5 pr-3 font-mono text-slate-300 truncate max-w-[200px]">
                                    {c.ticker}
                                  </td>
                                  <td className="py-1.5 px-2 text-right font-mono text-slate-300">
                                    {c.strike !== null ? fmtUsd(c.strike) : "—"}
                                  </td>
                                  <td className={`py-1.5 px-2 text-right font-mono ${deltaColor(c.strike_vs_spot_pct)}`}>
                                    {fmtPct(c.strike_vs_spot_pct)}
                                  </td>
                                  <td className="py-1.5 px-2 text-right font-mono text-emerald-400">
                                    {fmtCents(c.yes_price_cents)}
                                  </td>
                                  <td className="py-1.5 px-2 text-right font-mono text-red-400">
                                    {fmtCents(c.no_price_cents)}
                                  </td>
                                  <td className="py-1.5 px-2 text-right font-mono text-slate-300">
                                    {fmtProb(c.implied_prob)}
                                  </td>
                                  <td className="py-1.5 px-2 text-right font-mono text-slate-400">
                                    {c.volume > 0 ? c.volume.toLocaleString() : "—"}
                                  </td>
                                  <td className="py-1.5 pl-2 text-right font-mono text-slate-400">
                                    {fmtExpiry(c.minutes_to_expiry)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {ad.by_timeframe[tf].length > 15 && (
                            <p className="text-[10px] text-slate-600 mt-1">
                              +{ad.by_timeframe[tf].length - 15} more contracts
                            </p>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default CryptoSpotKalshiPanel;
