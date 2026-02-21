import React, { useState } from 'react';
import { useThresholdOptimizer } from '../hooks/useSentimentBundle';

interface ThresholdOptimizerPanelProps {
  asset?: string;
}

export const ThresholdOptimizerPanel: React.FC<ThresholdOptimizerPanelProps> = ({ 
  asset = 'BTC' 
}) => {
  const [days, setDays] = useState(30);
  const { optimize, optimizing, result } = useThresholdOptimizer();

  const handleOptimize = async () => {
    try {
      await optimize(asset, days);
    } catch (exc) {
      // Error handled in hook
    }
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white">VADER Threshold Optimizer</h3>
        <span className="text-xs text-gray-500">{asset}</span>
      </div>

      <div className="flex items-center gap-4 mb-4">
        <div className="flex-1">
          <label htmlFor="lookback-days" className="text-xs text-gray-500 block mb-1">
            Lookback (days)
          </label>
          <select 
            id="lookback-days"
            value={days} 
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
            disabled={optimizing}
            title="Select lookback period in days"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
          </select>
        </div>
        <button
          onClick={handleOptimize}
          disabled={optimizing}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 text-white rounded text-sm font-medium transition-colors"
        >
          {optimizing ? 'Optimizing...' : 'Run Optimization'}
        </button>
      </div>

      {result && (
        <div className="space-y-3">
          <div className="p-3 bg-green-900/20 border border-green-800 rounded">
            <div className="text-xs text-green-400 mb-1">Best Thresholds Found</div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-300">Positive:</span>
              <span className="text-white font-medium">{result.best.pos_th.toFixed(3)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-300">Negative:</span>
              <span className="text-white font-medium">{result.best.neg_th.toFixed(3)}</span>
            </div>
            <div className="flex justify-between text-sm mt-2 pt-2 border-t border-green-800">
              <span className="text-gray-400">Sharpe:</span>
              <span className="text-green-400">{result.best.sharpe.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Win Rate:</span>
              <span className="text-green-400">{(result.best.win_rate * 100).toFixed(1)}%</span>
            </div>
          </div>

          {result.top_5 && result.top_5.length > 1 && (
            <div>
              <div className="text-xs text-gray-500 mb-2">Top 5 Configurations</div>
              <div className="space-y-1">
                {result.top_5.slice(1).map((config, idx) => (
                  <div key={idx} className="flex justify-between text-xs p-2 bg-gray-700 rounded">
                    <span className="text-gray-400">
                      +{config.pos_th.toFixed(2)} / {config.neg_th.toFixed(2)}
                    </span>
                    <span className="text-gray-300">Sharpe: {config.sharpe.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="text-xs text-gray-500 text-right">
            Optimized: {new Date(result.timestamp).toLocaleTimeString()}
          </div>
        </div>
      )}

      {!result && !optimizing && (
        <div className="text-xs text-gray-500 text-center py-4">
          Run optimization to find best VADER thresholds for {asset}
        </div>
      )}
    </div>
  );
};
