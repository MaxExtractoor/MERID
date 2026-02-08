/**
 * Streaming Equity / PnL Line Chart
 *
 * Recharts-based live-updating chart showing equity and unrealized PnL
 * over a configurable time window. Polls /api/operator/equity-series.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { TrendingUp, Clock } from 'lucide-react';
import { API_BASE_URL } from '../../config/constants';

type Window = '5m' | '15m' | '30m' | '1h' | '4h' | '1d';

interface EquityPoint {
  ts: number;
  equity: number;
  pnl: number;
}

interface EquityPnLChartProps {
  defaultWindow?: Window;
  height?: number;
  className?: string;
}

const WINDOWS: { value: Window; label: string }[] = [
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '4h', label: '4h' },
  { value: '1d', label: '1d' },
];

const MAX_POINTS = 360;

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatCurrency(val: number): string {
  return `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

export function EquityPnLChart({
  defaultWindow = '30m',
  height = 280,
  className = '',
}: EquityPnLChartProps) {
  const [window, setWindow] = useState<Window>(defaultWindow);
  const [data, setData] = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/operator/equity-series?window=${window}`);
      if (res.ok) {
        const json = await res.json();
        const pts = json.points || [];
        setData(pts.length > MAX_POINTS ? pts.slice(-MAX_POINTS) : pts);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [window]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 5000);
    return () => clearInterval(id);
  }, [fetchData]);

  const chartData = data.map((p) => ({
    time: formatTime(p.ts),
    ts: p.ts,
    Equity: p.equity,
    PnL: p.pnl,
  }));

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">Equity & PnL</h3>
        </div>
        <div className="flex items-center gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              onClick={() => { setWindow(w.value); setLoading(true); }}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                window === w.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-500 hover:text-slate-300'
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      {loading && data.length === 0 ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <Clock className="w-5 h-5 text-slate-600 animate-pulse" />
          <span className="ml-2 text-sm text-slate-600">Collecting data...</span>
        </div>
      ) : data.length < 2 ? (
        <div className="flex items-center justify-center text-slate-600 text-sm" style={{ height }}>
          Waiting for data points (need at least 2)...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="time"
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="equity"
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickFormatter={formatCurrency}
              tickLine={false}
              width={70}
            />
            <YAxis
              yAxisId="pnl"
              orientation="right"
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickFormatter={formatCurrency}
              tickLine={false}
              width={60}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number, name: string) => [formatCurrency(value), name]}
            />
            <Legend
              wrapperStyle={{ fontSize: '11px', color: '#94a3b8' }}
            />
            <Line
              yAxisId="equity"
              type="monotone"
              dataKey="Equity"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3 }}
            />
            <Line
              yAxisId="pnl"
              type="monotone"
              dataKey="PnL"
              stroke="#22c55e"
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
              strokeDasharray="4 2"
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
