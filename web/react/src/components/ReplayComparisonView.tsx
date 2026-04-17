import { useState, useCallback } from 'react';
import { API_BASE_URL } from "../config/constants";
import { authHeaders } from '../api/auth';

interface ReplayResult {
  run_id: string;
  mode: string;
  metrics: {
    total_pnl: number;
    hit_rate: number;
    max_drawdown: number;
    max_drawdown_pct: number;
    total_markets: number;
    resolved_markets: number;
    duration_seconds: number;
  };
  agent_leaderboard: Array<{
    agent_id: string;
    pnl: number;
    accuracy: number;
    edge: number;
    rounds: number;
  }>;
}

interface ComparisonData {
  comparison_id: string;
  status: string;
  scenario: {
    start_time: number;
    end_time: number;
    description: string;
  };
  baseline: ReplayResult;
  incentive_tuned: ReplayResult;
  differences: {
    pnl_diff: number;
    pnl_diff_pct: number;
    hit_rate_diff: number;
    drawdown_diff: number;
  };
}

export function ReplayComparisonView() {
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ComparisonData | null>(null);

  const runComparison = useCallback(async () => {
    if (!startDate || !endDate) {
      setError('Please select both start and end dates');
      return;
    }

    setLoading(true);
    setError(null);
    setComparison(null);

    try {
      const startTime = new Date(startDate).getTime() / 1000;
      const endTime = new Date(endDate).getTime() / 1000;

      const response = await fetch(`${API_BASE_URL}/api/v1/replay/compare`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_time: startTime,
          end_time: endTime,
          description: `Comparison ${startDate} to ${endDate}`,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to run comparison: ${response.statusText}`);
      }

      const data = await response.json();
      setComparison(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate]);

  const runQuickCompare = useCallback(async () => {
    setLoading(true);
    setError(null);
    setComparison(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/replay/quick-compare`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      });

      if (!response.ok) {
        throw new Error(`Failed to run quick comparison: ${response.statusText}`);
      }

      const data = await response.json();
      setComparison(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  };

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(1)}%`;
  };

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-6">
      <h2 className="text-xl font-semibold text-white mb-4">Replay Comparison</h2>
      
      {/* Configuration */}
      <div className="mb-6 p-4 bg-slate-800 rounded-lg">
        <h3 className="text-sm font-medium text-slate-400 uppercase mb-3">Scenario Configuration</h3>
        
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Start Date</label>
            <input
              type="datetime-local"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded px-3 py-2"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">End Date</label>
            <input
              type="datetime-local"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full bg-slate-700 border border-slate-600 text-white rounded px-3 py-2"
            />
          </div>
        </div>

        <div className="flex gap-3">
          <button
            onClick={runComparison}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white rounded font-medium transition-colors"
          >
            {loading ? 'Running...' : 'Run Comparison'}
          </button>
          <button
            onClick={runQuickCompare}
            disabled={loading}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-600 text-white rounded font-medium transition-colors"
          >
            Quick Compare (24h)
          </button>
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-900/30 border border-red-700 rounded text-red-400 text-sm">
            {error}
          </div>
        )}
      </div>

      {/* Results */}
      {comparison && (
        <div className="space-y-6">
          {/* Summary */}
          <div className="p-4 bg-slate-800 rounded-lg">
            <h3 className="text-sm font-medium text-slate-400 uppercase mb-3">Comparison Summary</h3>
            <div className="grid grid-cols-4 gap-4">
              <div className="text-center p-3 bg-slate-700 rounded">
                <div className="text-xs text-slate-400 mb-1">PnL Difference</div>
                <div className={`text-lg font-bold ${comparison.differences.pnl_diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {comparison.differences.pnl_diff >= 0 ? '+' : ''}{formatCurrency(comparison.differences.pnl_diff)}
                </div>
                <div className="text-xs text-slate-500">
                  {comparison.differences.pnl_diff_pct >= 0 ? '+' : ''}{comparison.differences.pnl_diff_pct.toFixed(1)}%
                </div>
              </div>
              <div className="text-center p-3 bg-slate-700 rounded">
                <div className="text-xs text-slate-400 mb-1">Hit Rate Diff</div>
                <div className={`text-lg font-bold ${comparison.differences.hit_rate_diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {comparison.differences.hit_rate_diff >= 0 ? '+' : ''}{formatPercent(comparison.differences.hit_rate_diff)}
                </div>
              </div>
              <div className="text-center p-3 bg-slate-700 rounded">
                <div className="text-xs text-slate-400 mb-1">Drawdown Diff</div>
                <div className={`text-lg font-bold ${comparison.differences.drawdown_diff <= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {comparison.differences.drawdown_diff >= 0 ? '+' : ''}{formatCurrency(comparison.differences.drawdown_diff)}
                </div>
              </div>
              <div className="text-center p-3 bg-slate-700 rounded">
                <div className="text-xs text-slate-400 mb-1">Markets Resolved</div>
                <div className="text-lg font-bold text-white">
                  {comparison.baseline.metrics.resolved_markets}
                </div>
              </div>
            </div>
          </div>

          {/* Side-by-Side Metrics */}
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-2 text-sm font-medium text-slate-400">Metric</th>
                  <th className="text-right py-2 text-sm font-medium text-slate-400">Baseline</th>
                  <th className="text-right py-2 text-sm font-medium text-slate-400">Incentive-Tuned</th>
                  <th className="text-right py-2 text-sm font-medium text-slate-400">Difference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                <tr>
                  <td className="py-3 text-sm text-slate-300">Total PnL</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatCurrency(comparison.baseline.metrics.total_pnl)}</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatCurrency(comparison.incentive_tuned.metrics.total_pnl)}</td>
                  <td className={`py-3 text-right text-sm font-medium ${comparison.differences.pnl_diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {comparison.differences.pnl_diff >= 0 ? '+' : ''}{formatCurrency(comparison.differences.pnl_diff)}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 text-sm text-slate-300">Hit Rate</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatPercent(comparison.baseline.metrics.hit_rate)}</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatPercent(comparison.incentive_tuned.metrics.hit_rate)}</td>
                  <td className={`py-3 text-right text-sm font-medium ${comparison.differences.hit_rate_diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {comparison.differences.hit_rate_diff >= 0 ? '+' : ''}{formatPercent(comparison.differences.hit_rate_diff)}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 text-sm text-slate-300">Max Drawdown</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatCurrency(comparison.baseline.metrics.max_drawdown)}</td>
                  <td className="py-3 text-right text-sm text-slate-300">{formatCurrency(comparison.incentive_tuned.metrics.max_drawdown)}</td>
                  <td className={`py-3 text-right text-sm font-medium ${comparison.differences.drawdown_diff <= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {comparison.differences.drawdown_diff >= 0 ? '+' : ''}{formatCurrency(comparison.differences.drawdown_diff)}
                  </td>
                </tr>
                <tr>
                  <td className="py-3 text-sm text-slate-300">Duration</td>
                  <td className="py-3 text-right text-sm text-slate-300">{comparison.baseline.metrics.duration_seconds.toFixed(1)}s</td>
                  <td className="py-3 text-right text-sm text-slate-300">{comparison.incentive_tuned.metrics.duration_seconds.toFixed(1)}s</td>
                  <td className="py-3 text-right text-sm text-slate-500">-</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Agent Leaderboard Comparison */}
          <div className="p-4 bg-slate-800 rounded-lg">
            <h3 className="text-sm font-medium text-slate-400 uppercase mb-3">Agent Leaderboard Comparison</h3>
            
            <div className="grid grid-cols-2 gap-4">
              {/* Baseline */}
              <div>
                <h4 className="text-xs text-slate-500 uppercase mb-2">Baseline</h4>
                <div className="space-y-2">
                  {comparison.baseline.agent_leaderboard.slice(0, 5).map((agent) => (
                    <div key={agent.agent_id} className="flex items-center justify-between p-2 bg-slate-700 rounded text-sm">
                      <span className="font-mono text-slate-300">{agent.agent_id}</span>
                      <span className="text-slate-400">{formatCurrency(agent.pnl)}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tuned */}
              <div>
                <h4 className="text-xs text-slate-500 uppercase mb-2">Incentive-Tuned</h4>
                <div className="space-y-2">
                  {comparison.incentive_tuned.agent_leaderboard.slice(0, 5).map((agent) => (
                    <div key={agent.agent_id} className="flex items-center justify-between p-2 bg-slate-700 rounded text-sm">
                      <span className="font-mono text-slate-300">{agent.agent_id}</span>
                      <span className="text-slate-400">{formatCurrency(agent.pnl)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Run IDs */}
          <div className="text-xs text-slate-500 text-center">
            Comparison ID: {comparison.comparison_id} | 
            Baseline: {comparison.baseline.run_id} | 
            Tuned: {comparison.incentive_tuned.run_id}
          </div>
        </div>
      )}
    </div>
  );
}

export default ReplayComparisonView;
