/**
 * CrossAssetView — Multi-domain portfolio summary dashboard.
 *
 * Shows:
 *   - Aggregated portfolio value across crypto, prediction, equity, betting
 *   - Per-domain allocation breakdown
 *   - Per-domain PnL summary
 *   - Top positions across all domains
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell, PieChart, Pie } from 'recharts';
import { Layers, RefreshCw, TrendingUp, TrendingDown, DollarSign, PieChart as PieIcon, BarChart3, Wallet } from 'lucide-react';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS} from '../config/constants';
import { logUiError } from '../utils/logger';

/* ── Types ──────────────────────────────────────────────────── */

interface DomainSummary {
  domain: string;
  equity_usd: number;
  positions_count: number;
  unrealized_pnl: number;
  daily_pnl: number;
  allocation_pct: number;
}

interface CrossAssetPosition {
  symbol: string;
  domain: string;
  side: string;
  quantity: number;
  market_value: number;
  unrealized_pnl: number;
}

interface CrossAssetData {
  total_equity: number;
  total_pnl: number;
  domains: DomainSummary[];
  top_positions: CrossAssetPosition[];
}

/* ── Helpers ────────────────────────────────────────────────── */

function fmt(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

const DOMAIN_COLORS: Record<string, string> = {
  crypto: CHART_COLORS.BLUE,
  prediction: CHART_COLORS.PURPLE,
  equity: CHART_COLORS.GREEN,
  betting: CHART_COLORS.ORANGE,
  macro: CHART_COLORS.CYAN,
};

function domainColor(d: string): string {
  return DOMAIN_COLORS[d] ?? CHART_COLORS.GRAY_500;
}

/* ── Component ──────────────────────────────────────────────── */

export default function CrossAssetView() {
  const [data, setData] = useState<CrossAssetData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);

      // Fetch paper portfolio as the primary cross-asset source
      const [portfolioRes, positionsRes] = await Promise.all([
        fetch(API_ENDPOINTS.PAPER_PORTFOLIO),
        fetch(API_ENDPOINTS.PAPER_POSITIONS),
      ]);

      const portfolio = portfolioRes.ok ? await portfolioRes.json() : null;
      const positions = positionsRes.ok ? await positionsRes.json() : null;

      // Also try betting metrics
      let bettingMetrics: Record<string, unknown> | null = null;
      try {
        const betRes = await fetch(API_ENDPOINTS.BETTING_CONSENSUS_METRICS);
        if (betRes.ok) bettingMetrics = await betRes.json();
      } catch (err) { logUiError('CrossAssetView', 'Betting metrics fetch failed', err); }

      // Build cross-asset summary from available data
      const domainMap = new Map<string, DomainSummary>();
      const allPositions: CrossAssetPosition[] = [];

      // Process paper trading positions
      const posList = positions?.positions ?? positions ?? [];
      if (Array.isArray(posList)) {
        for (const p of posList) {
          const domain = p.domain ?? 'crypto';
          if (!domainMap.has(domain)) {
            domainMap.set(domain, {
              domain,
              equity_usd: 0,
              positions_count: 0,
              unrealized_pnl: 0,
              daily_pnl: 0,
              allocation_pct: 0,
            });
          }
          const ds = domainMap.get(domain);
          if (!ds) continue;
          const mv = p.market_value ?? p.notional_usd ?? 0;
          ds.equity_usd += mv;
          ds.positions_count += 1;
          ds.unrealized_pnl += p.unrealized_pnl ?? 0;

          allPositions.push({
            symbol: p.symbol ?? p.instrument_id ?? '?',
            domain,
            side: p.side ?? 'long',
            quantity: p.quantity ?? p.size ?? 0,
            market_value: mv,
            unrealized_pnl: p.unrealized_pnl ?? 0,
          });
        }
      }

      // Add betting domain if metrics available
      const betStaked = Number(bettingMetrics?.total_staked_usd) || 0;
      if (bettingMetrics && betStaked > 0) {
        domainMap.set('betting', {
          domain: 'betting',
          equity_usd: betStaked,
          positions_count: Number(bettingMetrics.active_events) || 0,
          unrealized_pnl: Number(bettingMetrics.total_pnl_usd) || 0,
          daily_pnl: 0,
          allocation_pct: 0,
        });
      }

      const domains = Array.from(domainMap.values());
      const totalEquity = portfolio?.total_equity ?? domains.reduce((s, d) => s + d.equity_usd, 0);
      const totalPnl = domains.reduce((s, d) => s + d.unrealized_pnl, 0);

      // Compute allocation percentages
      for (const d of domains) {
        d.allocation_pct = totalEquity > 0 ? d.equity_usd / totalEquity : 0;
      }

      // Sort positions by absolute market value
      allPositions.sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value));

      setData({
        total_equity: totalEquity,
        total_pnl: totalPnl,
        domains,
        top_positions: allPositions.slice(0, 15),
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load cross-asset data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, DEFAULTS.POLLING_INTERVALS.BACKGROUND);
    return () => clearInterval(interval);
  }, [refresh]);

  const pieData = useMemo(() => {
    if (!data) return [];
    return data.domains.map(d => ({
      name: d.domain.charAt(0).toUpperCase() + d.domain.slice(1),
      value: d.equity_usd,
      fill: domainColor(d.domain),
    }));
  }, [data]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading cross-asset data…</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-red-300">
        <p className="font-semibold">Error loading cross-asset data</p>
        <p className="text-sm mt-1 text-red-400">{error ?? 'No data available'}</p>
      </div>
    );
  }

  const pnlColor = data.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Layers className="w-7 h-7 text-blue-400" />
            Cross-Asset Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Multi-domain portfolio overview: crypto, prediction markets, equities, betting
          </p>
        </div>
        <button type="button"
          onClick={() => { setLoading(true); refresh(); }}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Wallet className="w-4 h-4 text-blue-400" />
            <span className="text-xs text-slate-400">Total Equity</span>
          </div>
          <p className="text-xl font-bold text-white">{fmt(data.total_equity)}</p>
        </div>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            {data.total_pnl >= 0 ? <TrendingUp className="w-4 h-4 text-emerald-400" /> : <TrendingDown className="w-4 h-4 text-red-400" />}
            <span className="text-xs text-slate-400">Unrealized PnL</span>
          </div>
          <p className={`text-xl font-bold ${pnlColor}`}>
            {data.total_pnl >= 0 ? '+' : ''}{fmt(data.total_pnl)}
          </p>
        </div>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <PieIcon className="w-4 h-4 text-purple-400" />
            <span className="text-xs text-slate-400">Active Domains</span>
          </div>
          <p className="text-xl font-bold text-white">{data.domains.length}</p>
        </div>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <BarChart3 className="w-4 h-4 text-amber-400" />
            <span className="text-xs text-slate-400">Total Positions</span>
          </div>
          <p className="text-xl font-bold text-white">{data.top_positions.length}</p>
        </div>
      </div>

      {/* Domain allocation + PnL */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Allocation pie */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
            <PieIcon className="w-4 h-4 text-purple-400" /> Domain Allocation
          </h3>
          {pieData.length > 0 ? (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={160} height={160}>
                <PieChart>
                  <Pie data={pieData} dataKey="value" cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={2}>
                    {pieData.map((entry, idx) => (
                      <Cell key={idx} fill={entry.fill} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                    formatter={(value: number) => [fmt(value), 'Value']}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2 flex-1">
                {data.domains.map(d => (
                  <div key={d.domain} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full" style={{ backgroundColor: domainColor(d.domain) }} />
                      <span className="text-xs text-slate-300 capitalize">{d.domain}</span>
                    </div>
                    <span className="text-xs text-white font-medium">{(d.allocation_pct * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500 text-center py-8">No domain data available</p>
          )}
        </div>

        {/* Domain PnL bars */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-emerald-400" /> Domain PnL
          </h3>
          {data.domains.length > 0 ? (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={data.domains.map(d => ({
                name: d.domain.charAt(0).toUpperCase() + d.domain.slice(1),
                pnl: d.unrealized_pnl,
                fill: d.unrealized_pnl >= 0 ? CHART_COLORS.GREEN : CHART_COLORS.RED,
              }))} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis type="number" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 12 }} width={90} />
                <RechartsTooltip
                  contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                  formatter={(value: number) => [fmt(value), 'PnL']}
                />
                <Bar dataKey="pnl" radius={[0, 4, 4, 0]} barSize={16}>
                  {data.domains.map((d, idx) => (
                    <Cell key={idx} fill={d.unrealized_pnl >= 0 ? CHART_COLORS.GREEN : CHART_COLORS.RED} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-slate-500 text-center py-8">No PnL data</p>
          )}
        </div>
      </div>

      {/* Domain detail cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {data.domains.map(d => {
          const pnl = d.unrealized_pnl;
          const color = pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
          return (
            <div key={d.domain} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: domainColor(d.domain) }} />
                <span className="text-sm font-semibold text-white capitalize">{d.domain}</span>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-400">Equity</span>
                  <span className="text-white font-medium">{fmt(d.equity_usd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Positions</span>
                  <span className="text-white font-medium">{d.positions_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">PnL</span>
                  <span className={`font-medium ${color}`}>
                    {pnl >= 0 ? '+' : ''}{fmt(pnl)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Allocation</span>
                  <span className="text-white font-medium">{(d.allocation_pct * 100).toFixed(1)}%</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Top positions table */}
      {data.top_positions.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-700/50">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-400" /> Top Positions
            </h3>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Symbol</th>
                <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Domain</th>
                <th className="text-left text-xs text-slate-400 font-medium px-4 py-2">Side</th>
                <th className="text-right text-xs text-slate-400 font-medium px-4 py-2">Value</th>
                <th className="text-right text-xs text-slate-400 font-medium px-4 py-2">PnL</th>
              </tr>
            </thead>
            <tbody>
              {data.top_positions.map((p, i) => {
                const pColor = p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
                return (
                  <tr key={`${p.symbol}-${i}`} className="border-b border-slate-700/20 hover:bg-slate-700/20 transition-colors">
                    <td className="px-4 py-2 text-sm text-white font-medium">{p.symbol}</td>
                    <td className="px-4 py-2">
                      <span className="text-xs px-2 py-0.5 rounded-full capitalize" style={{ backgroundColor: domainColor(p.domain) + '20', color: domainColor(p.domain) }}>
                        {p.domain}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-300 uppercase">{p.side}</td>
                    <td className="px-4 py-2 text-sm text-white text-right">{fmt(p.market_value)}</td>
                    <td className={`px-4 py-2 text-sm text-right font-medium ${pColor}`}>
                      {p.unrealized_pnl >= 0 ? '+' : ''}{fmt(p.unrealized_pnl)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
