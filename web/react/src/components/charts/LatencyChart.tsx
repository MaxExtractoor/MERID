/**
 * Latency Chart Widget
 *
 * Shows backend endpoint latency percentiles (p50/p95/p99) as a bar chart.
 * Polls /api/metrics/latency. Targets: p95 < 200-300ms per Deephaven guidance.
 */

import { useState, useEffect, useCallback } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import { Timer } from 'lucide-react';
import { API_BASE_URL } from '../../config/constants';

interface LatencyStats {
  aggregate: { p50: number; p95: number; p99: number; count: number };
  by_endpoint: Record<string, { p50: number; p95: number; count: number }>;
}

interface LatencyChartProps {
  className?: string;
  height?: number;
}

export function LatencyChart({ className = '', height = 200 }: LatencyChartProps) {
  const [data, setData] = useState<LatencyStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/metrics/latency?window=300`);
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 15000);
    return () => clearInterval(id);
  }, [fetchData]);

  // Transform by_endpoint into chart data
  const chartData = data?.by_endpoint
    ? Object.entries(data.by_endpoint)
        .map(([endpoint, stats]) => ({
          name: endpoint.replace('/api/', '').replace('/v1/', '').slice(0, 20),
          p50: stats.p50,
          p95: stats.p95,
          count: stats.count,
        }))
        .sort((a, b) => b.p95 - a.p95)
        .slice(0, 10)
    : [];

  const agg = data?.aggregate;

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Timer className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">API Latency</h3>
        </div>
        {agg && agg.count > 0 && (
          <div className="flex items-center gap-3 text-[10px]">
            <span className="text-slate-500">p50: <span className="text-slate-300">{agg.p50}ms</span></span>
            <span className={agg.p95 > 300 ? 'text-amber-400' : 'text-slate-500'}>
              p95: <span className={agg.p95 > 300 ? 'text-amber-300 font-semibold' : 'text-slate-300'}>{agg.p95}ms</span>
            </span>
            <span className={agg.p99 > 500 ? 'text-red-400' : 'text-slate-500'}>
              p99: <span className={agg.p99 > 500 ? 'text-red-300 font-semibold' : 'text-slate-300'}>{agg.p99}ms</span>
            </span>
            <span className="text-slate-600">{agg.count} samples</span>
          </div>
        )}
      </div>

      {loading && !data ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="animate-pulse text-sm text-slate-600">Collecting latency data...</div>
        </div>
      ) : chartData.length === 0 ? (
        <div className="flex items-center justify-center text-sm text-slate-600" style={{ height }}>
          No latency samples yet — endpoints will be tracked as they are called
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="name"
              tick={{ fill: '#64748b', fontSize: 9 }}
              tickLine={false}
              angle={-20}
              textAnchor="end"
              height={40}
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 10 }}
              tickLine={false}
              width={45}
              label={{ value: 'ms', position: 'insideTopLeft', fill: '#64748b', fontSize: 10 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '8px',
                fontSize: '11px',
              }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number, name: string) => [`${value}ms`, name]}
            />
            {/* Target line at 300ms */}
            <ReferenceLine
              y={300}
              stroke="#f59e0b"
              strokeDasharray="4 4"
              strokeWidth={1}
              label={{ value: 'target 300ms', fill: '#f59e0b', fontSize: 9, position: 'right' }}
            />
            <Bar dataKey="p50" fill="#3b82f6" radius={[2, 2, 0, 0]} name="p50" />
            <Bar dataKey="p95" fill="#f97316" radius={[2, 2, 0, 0]} name="p95" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
