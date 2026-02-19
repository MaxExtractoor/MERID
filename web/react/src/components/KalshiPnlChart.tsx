/**
 * KalshiPnlChart — PnL / equity curve chart for Kalshi portfolio.
 *
 * Features:
 *   - Area chart of cumulative PnL over time
 *   - Asset filter toggle (All / BTC / ETH / SOL)
 *   - Breach markers overlaid on chart
 *   - Responsive container, dark-themed
 */

import React, { useState, useMemo } from 'react';
import {
  ComposedChart, Area, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, Legend,
} from 'recharts';
import { TrendingUp, TrendingDown, BarChart3, LineChart } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface PnlPoint {
  ts: string;
  equity: number;
  daily_pnl: number;
  cumulative_pnl: number;
  category?: string;
}

interface PnlHistoryResponse {
  points: PnlPoint[];
  breaches?: Array<{ ts: string; check: string; reason: string }>;
}

interface PnlChartProps {
  riskAlerts?: Array<{ ts: string; title: string; severity: string }>;
}

type CategoryFilter = '' | 'crypto' | 'politics' | 'sports' | 'culture' | 'climate' | 'economics' | 'mentions' | 'companies' | 'financials' | 'tech' | 'science';
type ChartMode = 'equity' | 'daily';

const CATEGORY_TABS: { id: CategoryFilter; label: string }[] = [
  { id: '',           label: 'All' },
  { id: 'crypto',     label: 'Crypto' },
  { id: 'politics',   label: 'Politics' },
  { id: 'sports',     label: 'Sports' },
  { id: 'culture',    label: 'Culture' },
  { id: 'climate',    label: 'Climate' },
  { id: 'economics',  label: 'Economics' },
  { id: 'mentions',   label: 'Mentions' },
  { id: 'companies',  label: 'Companies' },
  { id: 'financials', label: 'Financials' },
  { id: 'tech',       label: 'Tech & Science' },
];

const KalshiPnlChart: React.FC<PnlChartProps> = ({ riskAlerts }) => {
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('');
  const [chartMode, setChartMode] = useState<ChartMode>('equity');

  const { data, loading } = useApiData<PnlHistoryResponse>(
    API_ENDPOINTS.KALSHI_PNL_HISTORY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const chartData = useMemo(() => {
    if (!data?.points?.length) return [];
    let pts = data.points;
    if (categoryFilter) {
      pts = pts.filter(p => (p.category ?? '').toLowerCase().includes(categoryFilter));
    }
    return pts.map(p => ({
      time: new Date(p.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      equity: Number(p.equity.toFixed(2)),
      pnl: Number(p.cumulative_pnl.toFixed(2)),
      dailyPnl: Number(p.daily_pnl.toFixed(2)),
    }));
  }, [data, categoryFilter]);

  const breachTimes = useMemo(() => {
    if (!data?.breaches?.length) return [];
    return data.breaches.map(b => ({
      time: new Date(b.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      label: b.check,
    }));
  }, [data]);

  const latestPnl = chartData.length > 0 ? chartData[chartData.length - 1].pnl : 0;
  const isPositive = latestPnl >= 0;

  const stats = useMemo(() => {
    if (chartData.length < 2) return null;
    const dailyPnls = chartData.map(d => d.dailyPnl);
    const peak = Math.max(...chartData.map(d => d.pnl));
    const trough = Math.min(...chartData.map(d => d.pnl));
    const maxDD = peak > 0 ? peak - trough : 0;
    const winDays = dailyPnls.filter(d => d > 0).length;
    const lossDays = dailyPnls.filter(d => d < 0).length;
    const avg = dailyPnls.reduce((a, b) => a + b, 0) / dailyPnls.length;
    return { peak, maxDD, winDays, lossDays, avgDaily: avg };
  }, [chartData]);

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
        <div className="animate-pulse h-48 bg-slate-800 rounded-lg" />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          {isPositive
            ? <TrendingUp className="w-4 h-4 text-green-400" />
            : <TrendingDown className="w-4 h-4 text-red-400" />}
          <h3 className="text-sm font-medium text-gray-300">PnL Curve</h3>
          <span className={`text-sm font-bold ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${latestPnl.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Chart mode toggle */}
          <div className="flex items-center gap-0.5 bg-slate-800 rounded p-0.5">
            <button
              type="button"
              onClick={() => setChartMode('equity')}
              className={`p-1 rounded transition-all ${chartMode === 'equity' ? 'bg-slate-700 text-orange-300' : 'text-gray-500 hover:text-white'}`}
              title="Equity curve"
            >
              <LineChart className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={() => setChartMode('daily')}
              className={`p-1 rounded transition-all ${chartMode === 'daily' ? 'bg-slate-700 text-orange-300' : 'text-gray-500 hover:text-white'}`}
              title="Daily PnL bars"
            >
              <BarChart3 className="w-3 h-3" />
            </button>
          </div>
          {/* Kalshi category filter tabs */}
          <div className="flex items-center gap-1">
            {CATEGORY_TABS.map(tab => (
              <button
                type="button"
                key={tab.id}
                onClick={() => setCategoryFilter(tab.id)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-all ${
                  categoryFilter === tab.id
                    ? 'bg-orange-500/20 text-orange-300'
                    : 'text-gray-500 hover:text-white hover:bg-slate-800'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Stats strip */}
      {stats && (
        <div className="flex items-center gap-4 px-4 py-1.5 border-b border-slate-800/50 text-[10px]">
          <div><span className="text-gray-500">Peak</span> <span className="text-green-400 font-mono">${stats.peak.toFixed(2)}</span></div>
          <div><span className="text-gray-500">Max DD</span> <span className="text-red-400 font-mono">${stats.maxDD.toFixed(2)}</span></div>
          <div><span className="text-gray-500">Avg Daily</span> <span className={`font-mono ${stats.avgDaily >= 0 ? 'text-green-400' : 'text-red-400'}`}>${stats.avgDaily.toFixed(2)}</span></div>
          <div><span className="text-gray-500">W/L</span> <span className="text-white font-mono">{stats.winDays}/{stats.lossDays}</span></div>
        </div>
      )}

      {/* Chart */}
      <div className="px-2 py-3">
        {chartData.length === 0 ? (
          <div className="flex items-center justify-center h-48 text-gray-500 text-xs">
            No PnL history available yet
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="time"
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <YAxis
                yAxisId="left"
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
                tickFormatter={(v: number) => `$${v}`}
              />
              {chartMode === 'daily' && (
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={{ stroke: '#334155' }}
                  tickLine={false}
                  tickFormatter={(v: number) => `$${v}`}
                />
              )}
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  fontSize: '11px',
                }}
                labelStyle={{ color: '#94a3b8' }}
                formatter={(value: number, name: string) => [
                  `$${value.toFixed(2)}`,
                  name === 'pnl' ? 'Cumulative PnL' : name === 'equity' ? 'Equity' : 'Daily PnL',
                ]}
              />
              <Legend
                wrapperStyle={{ fontSize: '10px', paddingTop: '4px' }}
                iconSize={8}
              />
              <ReferenceLine yAxisId="left" y={0} stroke="#475569" strokeDasharray="3 3" />
              {/* Drawdown tier background bands */}
              {(() => {
                if (!chartData.length) return null;
                const pnls = chartData.map(d => d.pnl);
                const peak = Math.max(...pnls, 0);
                // Tier thresholds as dollar amounts from peak
                const warnLine = peak * 0.95;  // 5% drawdown = warning
                const dsLine = peak * 0.90;    // 10% drawdown = downsize
                return (
                  <>
                    <ReferenceArea yAxisId="left" y1={dsLine} y2={warnLine} fill="#f59e0b" fillOpacity={0.04} />
                    <ReferenceArea yAxisId="left" y1={Number.MIN_SAFE_INTEGER} y2={dsLine} fill="#ef4444" fillOpacity={0.04} />
                    <ReferenceLine yAxisId="left" y={warnLine} stroke="#f59e0b" strokeDasharray="4 4" strokeOpacity={0.3}
                      label={{ value: 'Warn 5%', position: 'right', fill: '#f59e0b', fontSize: 8 }} />
                    <ReferenceLine yAxisId="left" y={dsLine} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity={0.3}
                      label={{ value: 'Halt 10%', position: 'right', fill: '#ef4444', fontSize: 8 }} />
                  </>
                );
              })()}
              {/* Breach event markers */}
              {breachTimes.map((b, i) => (
                <ReferenceLine
                  key={`breach-${i}`}
                  yAxisId="left"
                  x={b.time}
                  stroke="#ef4444"
                  strokeDasharray="2 2"
                  label={{ value: b.label, position: 'top', fill: '#ef4444', fontSize: 9 }}
                />
              ))}
              {/* Risk alert pins from WS */}
              {(riskAlerts ?? []).map((alert, i) => {
                const t = new Date(alert.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                const color = alert.severity === 'critical' ? '#ef4444' : '#f59e0b';
                return (
                  <ReferenceLine
                    key={`alert-${i}`}
                    yAxisId="left"
                    x={t}
                    stroke={color}
                    strokeDasharray="1 3"
                    strokeOpacity={0.6}
                    label={{ value: '●', position: 'top', fill: color, fontSize: 8 }}
                  />
                );
              })}
              {/* Equity / cumulative PnL area — always shown */}
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="pnl"
                name="Cumulative PnL"
                stroke={isPositive ? '#22c55e' : '#ef4444'}
                fill="url(#pnlGradient)"
                strokeWidth={2}
                dot={false}
                animationDuration={500}
              />
              {/* Daily PnL bars — shown in daily mode */}
              {chartMode === 'daily' && (
                <Bar
                  yAxisId="right"
                  dataKey="dailyPnl"
                  name="Daily PnL"
                  fill="#6366f1"
                  opacity={0.6}
                  radius={[2, 2, 0, 0]}
                  maxBarSize={12}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
};

export default KalshiPnlChart;
