/**
 * DebateCorrelationPanel - Shows correlation between debate state and trading performance
 */

import { useState } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface TradePerformance {
  timestamp: string;
  pnl: number;
  debate_status: string;
  debate_alerts: number;
  trade_count: number;
  win_rate: number;
}

interface CorrelationData {
  overall_correlation: number;
  performance_by_status: {
    healthy: { avg_pnl: number; total_trades: number; win_rate: number };
    degraded: { avg_pnl: number; total_trades: number; win_rate: number };
    critical: { avg_pnl: number; total_trades: number; win_rate: number };
  };
  recent_trades: TradePerformance[];
}

const DAYS_MAP: Record<string, number> = { '7d': 7, '30d': 30, '90d': 90 };

export default function DebateCorrelationPanel() {
  const [timeRange, setTimeRange] = useState<'7d' | '30d' | '90d'>('7d');

  const { data: correlationData, loading, error } = useApiData<CorrelationData>(
    `${API_ENDPOINTS.DEBATE_CORRELATION}?days_back=${DAYS_MAP[timeRange]}`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const getCorrelationColor = (correlation: number) => {
    if (correlation < -0.3) return 'text-red-400';
    if (correlation < -0.1) return 'text-yellow-400';
    if (correlation > 0.3) return 'text-green-400';
    return 'text-gray-400';
  };

  const getCorrelationLabel = (correlation: number) => {
    if (correlation < -0.3) return 'Strong Negative';
    if (correlation < -0.1) return 'Moderate Negative';
    if (correlation < 0.1) return 'Weak';
    if (correlation < 0.3) return 'Weak Positive';
    return 'Strong Positive';
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'text-green-400';
      case 'degraded': return 'text-yellow-400';
      case 'critical': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Icon name="trendingUp" size={16} className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-white">Debate-Performance Correlation</h3>
        </div>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value as '7d' | '30d' | '90d')}
          className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-gray-300 focus:border-purple-500 focus:outline-none"
        >
          <option value="7d">7 days</option>
          <option value="30d">30 days</option>
          <option value="90d">90 days</option>
        </select>
      </div>

      {loading && <div className="text-xs text-gray-500 py-4 text-center">Loading correlation data…</div>}
      {error && <div className="text-xs text-red-400 py-4 text-center">Failed to load correlation data</div>}

      {correlationData && (
      <>
      {/* Overall Correlation */}
      <div className="bg-slate-800 rounded-lg p-3 mb-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Overall Correlation</span>
          <div className="flex items-center gap-2">
            <span className={`text-sm font-bold ${getCorrelationColor(correlationData.overall_correlation ?? 0)}`}>
              {(correlationData.overall_correlation ?? 0).toFixed(2)}
            </span>
            <span className={`text-xs ${getCorrelationColor(correlationData.overall_correlation ?? 0)}`}>
              {getCorrelationLabel(correlationData.overall_correlation ?? 0)}
            </span>
          </div>
        </div>
        <div className="text-xs text-gray-500 mt-1">
          Higher debate alerts correlate with lower P&L
        </div>
      </div>

      {/* Performance by Status */}
      <div className="space-y-2 mb-4">
        <h4 className="text-xs font-semibold text-gray-300">Performance by Debate Status</h4>
        
        {Object.entries(correlationData.performance_by_status ?? {}).map(([status, data]) => (
          <div key={status} className="bg-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className={`text-xs font-medium capitalize ${getStatusColor(status)}`}>
                {status}
              </span>
              <span className="text-xs text-gray-400">
                {data.total_trades} trades
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-gray-400">Avg P&L</div>
                <div className={`font-bold ${(data.avg_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${(data.avg_pnl ?? 0).toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-gray-400">Win Rate</div>
                <div className="font-bold text-white">
                  {((data.win_rate ?? 0) * 100).toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-gray-400">Total</div>
                <div className="font-bold text-white">
                  {data.total_trades}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Trades */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-gray-300">Recent Trades with Debate Context</h4>
        <div className="space-y-1 max-h-32 overflow-y-auto">
          {(correlationData.recent_trades ?? []).map((trade, index) => (
            <div key={index} className="flex items-center justify-between text-xs bg-slate-800 rounded p-2">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${getStatusColor(trade.debate_status)}`}></div>
                <span className="text-gray-400">
                  {new Date(trade.timestamp).toLocaleTimeString()}
                </span>
                <span className={`capitalize ${getStatusColor(trade.debate_status)}`}>
                  {trade.debate_status}
                </span>
                <span className="text-gray-500">
                  ({trade.debate_alerts} alerts)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`font-bold ${(trade.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${(trade.pnl ?? 0).toFixed(2)}
                </span>
                <span className="text-gray-500">
                  {(trade.win_rate ?? 0) >= 0.5 ? '✓' : '✗'}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      </>
      )}

      {/* Insights */}
      <div className="mt-4 pt-3 border-t border-slate-700">
        <div className="text-xs text-gray-400">
          <div className="flex items-center gap-1 mb-1">
            <Icon name="info" size={10} className="w-2.5 h-2.5" />
            <span className="font-medium">Key Insight:</span>
          </div>
          <div className="ml-3">
            Trading performance drops significantly during critical debate states. 
            Consider reducing position sizes when alerts exceed 3.
          </div>
        </div>
      </div>
    </div>
  );
}
