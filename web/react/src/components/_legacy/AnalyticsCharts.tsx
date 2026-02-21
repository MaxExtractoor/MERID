import { useState } from 'react';
import { BarChart3, TrendingUp, Activity, RefreshCw, AlertCircle, PieChart } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface ChartData {
  labels: string[];
  values: number[];
}

interface AnalyticsData {
  trading_volume: ChartData;
  pnl_history: ChartData;
  agent_performance: ChartData;
  market_distribution: ChartData;
  success_rate: number;
  total_trades: number;
  avg_profit: number;
  best_performer: string;
}

interface AnalyticsChartsProps {
  className?: string;
}

export default function AnalyticsCharts({ className = '' }: AnalyticsChartsProps) {
  const [selectedChart, setSelectedChart] = useState<'volume' | 'pnl' | 'agents' | 'distribution'>('volume');

  const { data: analyticsData, loading, error, refetch } = useApiData<AnalyticsData>(
    API_ENDPOINTS.ANALYTICS_OVERVIEW,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );

  const renderBarChart = (data: ChartData, color: string) => {
    const maxValue = Math.max(...data.values);
    return (
      <div className="space-y-3">
        {data.labels.map((label, index) => {
          const percentage = (data.values[index] / maxValue) * 100;
          return (
            <div key={label}>
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-gray-400">{label}</span>
                <span className="text-white font-medium">{data.values[index].toLocaleString()}</span>
              </div>
              <div className="h-6 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full ${color} transition-all duration-500`}
                  style={{ width: `${percentage}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderLineChart = (data: ChartData) => {
    const maxValue = Math.max(...data.values);
    const minValue = Math.min(...data.values);
    const range = maxValue - minValue;
    
    return (
      <div className="relative h-48 flex items-end gap-2">
        {data.values.map((value, index) => {
          const height = range > 0 ? ((value - minValue) / range) * 100 : 50;
          const isPositive = index === 0 || value >= data.values[index - 1];
          
          return (
            <div key={index} className="flex-1 flex flex-col items-center gap-2">
              <div className="flex-1 flex items-end w-full">
                <div
                  className={`w-full rounded-t transition-all duration-500 ${
                    isPositive ? 'bg-green-500' : 'bg-red-500'
                  }`}
                  style={{ height: `${height}%` }}
                />
              </div>
              <div className="text-xs text-gray-400">{data.labels[index]}</div>
              <div className="text-xs text-white font-medium">${value.toLocaleString()}</div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderPieChart = (data: ChartData) => {
    const total = data.values.reduce((sum, val) => sum + val, 0);
    const colors = [
      'bg-blue-500',
      'bg-purple-500',
      'bg-green-500',
      'bg-yellow-500',
      'bg-pink-500',
    ];

    return (
      <div className="space-y-3">
        {data.labels.map((label, index) => {
          const percentage = (data.values[index] / total) * 100;
          return (
            <div key={label} className="flex items-center justify-between">
              <div className="flex items-center gap-3 flex-1">
                <div className={`w-4 h-4 rounded ${colors[index % colors.length]}`} />
                <span className="text-gray-400 text-sm">{label}</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-32 h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${colors[index % colors.length]} transition-all duration-500`}
                    style={{ width: `${percentage}%` }}
                  />
                </div>
                <span className="text-white font-medium text-sm w-12 text-right">
                  {percentage.toFixed(1)}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading analytics...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-blue-400" />
            <p className="text-sm text-gray-400">Total Trades</p>
          </div>
          <p className="text-2xl font-bold text-white">{analyticsData?.total_trades.toLocaleString()}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-green-400" />
            <p className="text-sm text-gray-400">Success Rate</p>
          </div>
          <p className="text-2xl font-bold text-green-400">
            {((analyticsData?.success_rate || 0) * 100).toFixed(1)}%
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <BarChart3 className="w-4 h-4 text-purple-400" />
            <p className="text-sm text-gray-400">Avg Profit</p>
          </div>
          <p className="text-2xl font-bold text-white">${analyticsData?.avg_profit.toFixed(2)}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <PieChart className="w-4 h-4 text-yellow-400" />
            <p className="text-sm text-gray-400">Best Performer</p>
          </div>
          <p className="text-lg font-bold text-white truncate">{analyticsData?.best_performer}</p>
        </div>
      </div>

      {/* Chart Selector */}
      <div className="flex gap-2 border-b border-slate-700">
        {[
          { key: 'volume' as const, label: 'Trading Volume', icon: BarChart3 },
          { key: 'pnl' as const, label: 'P&L History', icon: TrendingUp },
          { key: 'agents' as const, label: 'Agent Performance', icon: Activity },
          { key: 'distribution' as const, label: 'Market Distribution', icon: PieChart },
        ].map(({ key, label, icon: Icon }) => (
          <button type="button"
            key={key}
            onClick={() => setSelectedChart(key)}
            className={`flex items-center gap-2 px-4 py-2 font-medium transition-colors ${
              selectedChart === key
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Chart Display */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold text-white">
            {selectedChart === 'volume' && 'Weekly Trading Volume'}
            {selectedChart === 'pnl' && 'Monthly P&L Performance'}
            {selectedChart === 'agents' && 'Agent Task Completion'}
            {selectedChart === 'distribution' && 'Market Exposure Distribution'}
          </h3>
          <button type="button"
            onClick={() => refetch()}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh data"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {selectedChart === 'volume' && analyticsData && (
          renderBarChart(analyticsData.trading_volume, 'bg-gradient-to-r from-blue-500 to-purple-500')
        )}

        {selectedChart === 'pnl' && analyticsData && (
          renderLineChart(analyticsData.pnl_history)
        )}

        {selectedChart === 'agents' && analyticsData && (
          renderBarChart(analyticsData.agent_performance, 'bg-gradient-to-r from-green-500 to-emerald-500')
        )}

        {selectedChart === 'distribution' && analyticsData && (
          renderPieChart(analyticsData.market_distribution)
        )}
      </div>

      {/* Insights */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4">Key Insights</h3>
        <div className="space-y-3">
          <div className="flex items-start gap-3 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
            <TrendingUp className="w-5 h-5 text-blue-400 mt-0.5" />
            <div>
              <p className="text-white font-medium">Trading volume increased 12% this week</p>
              <p className="text-sm text-gray-400">Peak activity on Thursday with $156K volume</p>
            </div>
          </div>
          <div className="flex items-start gap-3 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
            <Activity className="w-5 h-5 text-green-400 mt-0.5" />
            <div>
              <p className="text-white font-medium">{analyticsData?.best_performer} is top performer</p>
              <p className="text-sm text-gray-400">Completed 156 tasks with 92% success rate</p>
            </div>
          </div>
          <div className="flex items-start gap-3 p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
            <PieChart className="w-5 h-5 text-purple-400 mt-0.5" />
            <div>
              <p className="text-white font-medium">BTC dominates portfolio at 35%</p>
              <p className="text-sm text-gray-400">Consider rebalancing for better diversification</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
