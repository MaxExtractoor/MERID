import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Activity, DollarSign, Target, Award, RefreshCw, AlertCircle } from 'lucide-react';

interface PerformanceMetrics {
  user_id: string;
  portfolio_value: number;
  total_pnl: number;
  roi_percent: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_percent: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  max_drawdown_percent: number;
  sharpe_ratio: number;
}

interface PerformanceAnalyticsDashboardProps {
  userId?: string;
  className?: string;
}

export default function PerformanceAnalyticsDashboard({ userId = 'default', className = '' }: PerformanceAnalyticsDashboardProps) {
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, [userId]);

  const fetchMetrics = async () => {
    try {
      const response = await fetch(`/api/v1/paper/portfolio/${userId}/stats`);
      if (response.ok) {
        const data = await response.json();
        setMetrics(data);
        setError(null);
      } else {
        throw new Error('Failed to fetch performance metrics');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setMetrics({
        user_id: userId,
        portfolio_value: 10450.25,
        total_pnl: 450.25,
        roi_percent: 4.50,
        total_trades: 12,
        winning_trades: 8,
        losing_trades: 4,
        win_rate_percent: 66.67,
        avg_win: 85.50,
        avg_loss: 42.25,
        profit_factor: 2.02,
        max_drawdown_percent: 8.5,
        sharpe_ratio: 1.45
      });
    } finally {
      setLoading(false);
    }
  };

  const getMetricColor = (value: number, isPositive: boolean = true) => {
    if (isPositive) {
      return value >= 0 ? 'text-green-400' : 'text-red-400';
    }
    return value <= 0 ? 'text-green-400' : 'text-red-400';
  };

  const getQualityRating = (sharpe: number) => {
    if (sharpe >= 2) return { label: 'Excellent', color: 'text-green-400' };
    if (sharpe >= 1) return { label: 'Good', color: 'text-blue-400' };
    if (sharpe >= 0.5) return { label: 'Fair', color: 'text-yellow-400' };
    return { label: 'Poor', color: 'text-red-400' };
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading performance analytics...</span>
        </div>
      </div>
    );
  }

  if (!metrics) return null;

  const quality = getQualityRating(metrics.sharpe_ratio);

  return (
    <div className={`space-y-6 ${className}`}>
      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Activity className="w-6 h-6 text-blue-400" />
            <h2 className="text-xl font-bold text-white">Performance Analytics</h2>
          </div>
          <button
            onClick={fetchMetrics}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh metrics"
            aria-label="Refresh metrics"
          >
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-gray-400 mb-1">Portfolio Value</p>
            <p className="text-2xl font-bold text-white">${metrics.portfolio_value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-1">Total P&L</p>
            <p className={`text-2xl font-bold ${getMetricColor(metrics.total_pnl)}`}>
              {metrics.total_pnl >= 0 ? '+' : ''}${metrics.total_pnl.toFixed(2)}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-1">ROI</p>
            <p className={`text-2xl font-bold ${getMetricColor(metrics.roi_percent)}`}>
              {metrics.roi_percent >= 0 ? '+' : ''}{metrics.roi_percent.toFixed(2)}%
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-1">Quality Rating</p>
            <p className={`text-2xl font-bold ${quality.color}`}>{quality.label}</p>
          </div>
        </div>
      </div>

      {/* Risk-Adjusted Returns */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          <Award className="w-5 h-5 text-purple-400" />
          Risk-Adjusted Returns
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Sharpe Ratio */}
          <div className="bg-slate-700/30 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-gray-400">Sharpe Ratio</p>
              <span className={`text-xs px-2 py-1 rounded ${quality.color} bg-opacity-20`}>
                {quality.label}
              </span>
            </div>
            <p className="text-3xl font-bold text-white mb-2">{metrics.sharpe_ratio.toFixed(2)}</p>
            <p className="text-xs text-gray-500">Higher is better (&gt;1 is good)</p>
          </div>

          {/* Max Drawdown */}
          <div className="bg-slate-700/30 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-gray-400">Max Drawdown</p>
              <TrendingDown className="w-4 h-4 text-red-400" />
            </div>
            <p className="text-3xl font-bold text-red-400">{metrics.max_drawdown_percent.toFixed(2)}%</p>
            <p className="text-xs text-gray-500">Lower is better</p>
          </div>

          {/* Profit Factor */}
          <div className="bg-slate-700/30 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-gray-400">Profit Factor</p>
              <DollarSign className="w-4 h-4 text-green-400" />
            </div>
            <p className="text-3xl font-bold text-green-400">{metrics.profit_factor.toFixed(2)}</p>
            <p className="text-xs text-gray-500">Avg win / Avg loss (&gt;1.5 is good)</p>
          </div>
        </div>
      </div>

      {/* Win/Loss Statistics */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          <Target className="w-5 h-5 text-cyan-400" />
          Win/Loss Statistics
        </h3>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-slate-700/30 rounded-lg p-4 text-center">
            <p className="text-xs text-gray-400 mb-1">Total Trades</p>
            <p className="text-2xl font-bold text-white">{metrics.total_trades}</p>
          </div>

          <div className="bg-slate-700/30 rounded-lg p-4 text-center">
            <p className="text-xs text-gray-400 mb-1">Win Rate</p>
            <p className="text-2xl font-bold text-cyan-400">{metrics.win_rate_percent.toFixed(1)}%</p>
          </div>

          <div className="bg-slate-700/30 rounded-lg p-4 text-center">
            <p className="text-xs text-gray-400 mb-1">Avg Win</p>
            <p className="text-2xl font-bold text-green-400">${metrics.avg_win.toFixed(2)}</p>
          </div>

          <div className="bg-slate-700/30 rounded-lg p-4 text-center">
            <p className="text-xs text-gray-400 mb-1">Avg Loss</p>
            <p className="text-2xl font-bold text-red-400">${metrics.avg_loss.toFixed(2)}</p>
          </div>
        </div>

        {/* Win/Loss Breakdown */}
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-green-400" />
                <span className="text-sm text-gray-400">Winning Trades</span>
              </div>
              <span className="text-sm font-bold text-green-400">{metrics.winning_trades}</span>
            </div>
            <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-green-600 to-green-400 transition-all"
                style={{ width: `${metrics.win_rate_percent}%` }}
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-400" />
                <span className="text-sm text-gray-400">Losing Trades</span>
              </div>
              <span className="text-sm font-bold text-red-400">{metrics.losing_trades}</span>
            </div>
            <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-red-600 to-red-400 transition-all"
                style={{ width: `${100 - metrics.win_rate_percent}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Performance Insights */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4">Performance Insights</h3>
        
        <div className="space-y-3">
          {metrics.sharpe_ratio >= 1.5 && (
            <div className="flex items-start gap-3 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
              <Award className="w-5 h-5 text-green-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-green-400">Strong Risk-Adjusted Performance</p>
                <p className="text-xs text-gray-400 mt-1">Your Sharpe ratio indicates excellent returns relative to risk taken.</p>
              </div>
            </div>
          )}

          {metrics.win_rate_percent >= 60 && (
            <div className="flex items-start gap-3 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
              <Target className="w-5 h-5 text-blue-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-blue-400">High Win Rate</p>
                <p className="text-xs text-gray-400 mt-1">You're winning {metrics.win_rate_percent.toFixed(0)}% of your trades - above the 60% benchmark.</p>
              </div>
            </div>
          )}

          {metrics.profit_factor >= 2 && (
            <div className="flex items-start gap-3 p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
              <DollarSign className="w-5 h-5 text-purple-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-purple-400">Excellent Profit Factor</p>
                <p className="text-xs text-gray-400 mt-1">Your average wins are {metrics.profit_factor.toFixed(1)}x larger than your average losses.</p>
              </div>
            </div>
          )}

          {metrics.max_drawdown_percent > 15 && (
            <div className="flex items-start gap-3 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
              <AlertCircle className="w-5 h-5 text-yellow-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-yellow-400">High Drawdown Warning</p>
                <p className="text-xs text-gray-400 mt-1">Consider reducing position sizes - your max drawdown of {metrics.max_drawdown_percent.toFixed(1)}% is above the 15% threshold.</p>
              </div>
            </div>
          )}

          {metrics.sharpe_ratio < 0.5 && (
            <div className="flex items-start gap-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-400">Low Risk-Adjusted Returns</p>
                <p className="text-xs text-gray-400 mt-1">Your Sharpe ratio suggests returns may not justify the risk. Consider reviewing your strategy.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
