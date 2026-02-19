/**
 * Drawdown Card with Sparkline
 *
 * Shows current equity, day's PnL, max drawdown, and a tiny sparkline
 * of equity over the session. Uses data from equity-series endpoint.
 */

import React from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  ReferenceLine,
} from 'recharts';
import { TrendingDown, Activity } from 'lucide-react';
import { useApiData } from '../../hooks/useApiData';
import { API_ENDPOINTS } from '../../config/constants';
import { useRiskMetrics } from '../../hooks/useRiskMetrics';

interface DrawdownCardProps {
  className?: string;
}

interface EquityPoint {
  ts: number;
  equity: number;
  pnl: number;
}

export function DrawdownCard({ className = '' }: DrawdownCardProps) {
  const { metrics } = useRiskMetrics();
  const { data: rawData } = useApiData<{ points: EquityPoint[] }>(
    `${API_ENDPOINTS.EQUITY_SERIES}?window=1h`,
    { pollingInterval: 10000 },
  );
  const points = rawData?.points ?? [];

  // Compute session stats from points
  const sessionHigh = points.length > 0 ? Math.max(...points.map((p) => p.equity)) : 0;
  const currentEquity = points.length > 0 ? points[points.length - 1].equity : 0;
  const currentPnl = points.length > 0 ? points[points.length - 1].pnl : 0;
  const sessionDrawdown = sessionHigh > 0 ? ((sessionHigh - currentEquity) / sessionHigh) * 100 : 0;

  const sparkData = points.map((p) => ({ equity: p.equity }));

  const ddThreshold = 10; // 10% drawdown threshold

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center gap-2 mb-3">
        <TrendingDown className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-semibold text-slate-300">Drawdown Monitor</h3>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Equity</div>
          <div className="text-lg font-bold text-slate-100">
            ${currentEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Day PnL</div>
          <div className={`text-lg font-bold ${currentPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {currentPnl >= 0 ? '+' : ''}${currentPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Session DD</div>
          <div className={`text-lg font-bold ${sessionDrawdown > 5 ? 'text-rose-400' : sessionDrawdown > 2 ? 'text-amber-400' : 'text-emerald-400'}`}>
            {sessionDrawdown.toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Max DD (API)</div>
          <div className={`text-lg font-bold ${metrics.maxDrawdown > 5 ? 'text-rose-400' : metrics.maxDrawdown > 2 ? 'text-amber-400' : 'text-emerald-400'}`}>
            {metrics.maxDrawdown.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Sparkline */}
      {sparkData.length >= 2 ? (
        <div className="h-16">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#3b82f6"
                strokeWidth={1.5}
                fill="url(#equityGrad)"
                dot={false}
              />
              {sessionHigh > 0 && (
                <ReferenceLine
                  y={sessionHigh * (1 - ddThreshold / 100)}
                  stroke="#ef4444"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                />
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="h-16 flex items-center justify-center">
          <Activity className="w-4 h-4 text-slate-700 animate-pulse" />
          <span className="ml-1.5 text-[10px] text-slate-700">Collecting...</span>
        </div>
      )}

      {/* Threshold indicator */}
      <div className="flex items-center justify-between mt-2 text-[10px] text-slate-600">
        <span>DD threshold: {ddThreshold}%</span>
        <span className={sessionDrawdown > ddThreshold ? 'text-red-400 font-semibold' : ''}>
          {sessionDrawdown > ddThreshold ? 'BREACHED' : `${(ddThreshold - sessionDrawdown).toFixed(1)}% headroom`}
        </span>
      </div>
    </div>
  );
}
