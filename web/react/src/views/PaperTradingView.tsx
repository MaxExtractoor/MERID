/**
 * PaperTradingView — Dedicated paper trading dashboard.
 *
 * Shows:
 *   - Portfolio summary (equity, cash, PnL, win rate)
 *   - PnL equity curve (area chart)
 *   - Per-domain breakdown (crypto, prediction, equity)
 *   - Open positions table with unrealized PnL
 *   - Recent orders with status
 *   - Domain allocation donut
 */

import { useState, useMemo } from 'react';
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { usePaperTrading } from '../hooks/usePaperTrading';
import { CHART_COLORS } from "../config/constants";
import {
  Wallet, TrendingUp, TrendingDown,
  BarChart3, RefreshCw, ArrowUpRight, ArrowDownRight,
  Briefcase, Clock, Target, Layers, Minus,
} from 'lucide-react';

/* ── Tooltip wrapper ──────────────────────────────────────── */

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="relative group cursor-help">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 text-xs bg-slate-800 text-slate-200 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50 border border-slate-700">
        {text}
      </span>
    </span>
  );
}

/* ── Stat card ────────────────────────────────────────────── */

function StatCard({ label, value, sub, Icon, color, tooltip }: {
  label: string; value: string; sub?: string; Icon: React.ElementType; color: string; tooltip: string;
}) {
  return (
    <Tip text={tooltip}>
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-colors">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 uppercase tracking-wider">{label}</span>
          <Icon className={`w-4 h-4 ${color}`} />
        </div>
        <div className="text-2xl font-bold text-white">{value}</div>
        {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
      </div>
    </Tip>
  );
}

/* ── PnL color helper ─────────────────────────────────────── */

function pnlColor(v: number) {
  if (v > 0) return 'text-emerald-400';
  if (v < 0) return 'text-rose-400';
  return 'text-slate-400';
}

function pnlIcon(v: number) {
  if (v > 0) return <ArrowUpRight className="w-3 h-3 text-emerald-400 inline" />;
  if (v < 0) return <ArrowDownRight className="w-3 h-3 text-rose-400 inline" />;
  return <Minus className="w-3 h-3 text-slate-400 inline" />;
}

function fmt$(v: number) {
  return `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* ── Domain allocation bar ────────────────────────────────── */

const DOMAIN_COLORS: Record<string, string> = {
  crypto: 'bg-orange-500',
  prediction: 'bg-blue-500',
  equity: 'bg-emerald-500',
  betting: 'bg-purple-500',
};

function DomainBar({ domains }: { domains: Record<string, { equity: number; pnl: number; positions: number }> }) {
  const entries = Object.entries(domains);
  const total = entries.reduce((s, [, d]) => s + Math.abs(d.equity), 0) || 1;

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Layers className="w-4 h-4 text-blue-400" /> Domain Allocation
      </h3>
      <div className="flex h-3 rounded-full overflow-hidden mb-3">
        {entries.map(([k, d]) => (
          <div
            key={k}
            className={`${DOMAIN_COLORS[k] ?? 'bg-slate-500'} transition-all duration-500`}
            style={{ width: `${(Math.abs(d.equity) / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {entries.map(([k, d]) => (
          <div key={k} className="flex items-center gap-2">
            <div className={`w-2.5 h-2.5 rounded-full ${DOMAIN_COLORS[k] ?? 'bg-slate-500'}`} />
            <div>
              <div className="text-xs text-slate-400 capitalize">{k}</div>
              <div className="text-sm font-medium text-white">{fmt$(d.equity)}</div>
              <div className={`text-xs ${pnlColor(d.pnl)}`}>{d.pnl >= 0 ? '+' : ''}{fmt$(d.pnl)} · {d.positions} pos</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main View ────────────────────────────────────────────── */

export default function PaperTradingView() {
  const { portfolio, positions, orders, pnlHistory, loading, error, refresh } = usePaperTrading();
  const [tab, setTab] = useState<'positions' | 'orders'>('positions');

  const chartData = useMemo(() => {
    return pnlHistory.map(p => ({
      time: new Date(p.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      equity: p.equity,
      pnl: p.pnl,
    }));
  }, [pnlHistory]);

  if (loading && !portfolio) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading paper trading...</span>
        </div>
      </div>
    );
  }

  if (error && !portfolio) {
    return (
      <div className="p-6">
        <div className="bg-rose-900/20 border border-rose-500/30 rounded-xl p-4">
          <h3 className="text-rose-400 font-semibold mb-1">Paper Trading API Error</h3>
          <p className="text-rose-300 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const p = portfolio;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Wallet className="w-8 h-8 text-blue-400" />
            Paper Trading
          </h1>
          <p className="text-slate-400 mt-1">Simulated portfolio across crypto, prediction markets, and equities</p>
        </div>
        <button type="button" onClick={refresh} className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh" aria-label="Refresh">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Equity" value={fmt$(p?.equity ?? 0)} Icon={Wallet} color="text-blue-400" tooltip="Total portfolio value including unrealized PnL" />
        <StatCard
          label="Total PnL"
          value={`${(p?.total_pnl ?? 0) >= 0 ? '+' : ''}${fmt$(p?.total_pnl ?? 0)}`}
          Icon={(p?.total_pnl ?? 0) >= 0 ? TrendingUp : TrendingDown}
          color={pnlColor(p?.total_pnl ?? 0)}
          tooltip="Cumulative realized + unrealized profit/loss"
        />
        <StatCard
          label="Daily PnL"
          value={`${(p?.daily_pnl ?? 0) >= 0 ? '+' : ''}${fmt$(p?.daily_pnl ?? 0)}`}
          Icon={BarChart3}
          color={pnlColor(p?.daily_pnl ?? 0)}
          tooltip="Today's profit/loss across all domains"
        />
        <StatCard
          label="Win Rate"
          value={`${((p?.win_rate ?? 0) * 100).toFixed(1)}%`}
          sub={`${p?.total_trades ?? 0} trades`}
          Icon={Target}
          color="text-amber-400"
          tooltip="Percentage of trades closed in profit"
        />
      </div>

      {/* Equity curve */}
      {chartData.length > 1 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-emerald-400" /> Equity Curve
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART_COLORS.GREEN} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={CHART_COLORS.GREEN} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.GRID_STROKE} />
              <XAxis dataKey="time" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
              <YAxis tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
              <Tooltip
                contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: CHART_COLORS.AXIS_TICK }}
              />
              <Area type="monotone" dataKey="equity" stroke={CHART_COLORS.GREEN} fill="url(#eqGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Domain allocation */}
      {p?.domains && Object.keys(p.domains).length > 0 && (
        <DomainBar domains={p.domains} />
      )}

      {/* Tab bar */}
      <div className="flex items-center gap-2 border-b border-slate-700/50 pb-2">
        {(['positions', 'orders'] as const).map(t => (
          <button type="button"
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === t ? 'bg-slate-800 text-white border-b-2 border-blue-500' : 'text-slate-400 hover:text-white'
            }`}
          >
            {t === 'positions' ? `Positions (${positions.length})` : `Orders (${orders.length})`}
          </button>
        ))}
      </div>

      {/* Positions table */}
      {tab === 'positions' && (
        <div className="overflow-x-auto">
          {positions.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Briefcase className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>No open positions</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase border-b border-slate-700/50">
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Domain</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-right py-2 px-3">Size</th>
                  <th className="text-right py-2 px-3">Entry</th>
                  <th className="text-right py-2 px-3">Current</th>
                  <th className="text-right py-2 px-3">PnL</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => (
                  <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                    <td className="py-2 px-3 font-medium text-white">{pos.symbol}</td>
                    <td className="py-2 px-3">
                      <span className="px-2 py-0.5 text-xs rounded-full bg-slate-700/50 text-slate-300 capitalize">{pos.domain}</span>
                    </td>
                    <td className="py-2 px-3">
                      <span className={pos.side === 'long' ? 'text-emerald-400' : 'text-rose-400'}>{pos.side.toUpperCase()}</span>
                    </td>
                    <td className="py-2 px-3 text-right text-white">{pos.size}</td>
                    <td className="py-2 px-3 text-right text-slate-300">{fmt$(pos.entry_price)}</td>
                    <td className="py-2 px-3 text-right text-slate-300">{fmt$(pos.current_price)}</td>
                    <td className={`py-2 px-3 text-right font-medium ${pnlColor(pos.unrealized_pnl)}`}>
                      {pnlIcon(pos.unrealized_pnl)} {pos.unrealized_pnl >= 0 ? '+' : ''}{fmt$(pos.unrealized_pnl)}
                      <span className="text-xs ml-1 opacity-70">({(pos.pnl_pct * 100).toFixed(1)}%)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Orders table */}
      {tab === 'orders' && (
        <div className="overflow-x-auto">
          {orders.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Clock className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>No recent orders</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-500 uppercase border-b border-slate-700/50">
                  <th className="text-left py-2 px-3">Symbol</th>
                  <th className="text-left py-2 px-3">Side</th>
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-right py-2 px-3">Size</th>
                  <th className="text-right py-2 px-3">Price</th>
                  <th className="text-left py-2 px-3">Status</th>
                  <th className="text-left py-2 px-3">Time</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((ord, i) => (
                  <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                    <td className="py-2 px-3 font-medium text-white">{ord.symbol}</td>
                    <td className="py-2 px-3">
                      <span className={ord.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}>{ord.side}</span>
                    </td>
                    <td className="py-2 px-3 text-slate-300">{ord.order_type}</td>
                    <td className="py-2 px-3 text-right text-white">{ord.size}</td>
                    <td className="py-2 px-3 text-right text-slate-300">{ord.price ? fmt$(ord.price) : '—'}</td>
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 text-xs rounded-full ${
                        ord.status === 'filled' ? 'bg-emerald-500/20 text-emerald-400' :
                        ord.status === 'rejected' ? 'bg-rose-500/20 text-rose-400' :
                        'bg-amber-500/20 text-amber-400'
                      }`}>{ord.status}</span>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-500">{new Date(ord.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
