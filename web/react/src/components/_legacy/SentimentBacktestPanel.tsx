import React, { useState } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

interface BacktestResult {
  asset: string;
  source: string;
  accuracy: number;
  precision: number;
  recall: number;
  f1_score: number;
  total_predictions: number;
  bullish_accuracy: number;
  bearish_accuracy: number;
}

export const SentimentBacktestPanel: React.FC = () => {
  const [asset, setAsset] = useState('BTC');
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<BacktestResult[] | null>(null);

  const runBacktest = async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_SENTIMENT_BACKTEST(asset, days)}`
      );
      if (response.ok) {
        const data = await response.json();
        setResults(data.results);
      }
    } catch (error) {
      console.error('Backtest failed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700">
      <h3 className="font-semibold text-white mb-4">Sentiment Backtest</h3>
      
      <div className="flex gap-4 mb-4">
        <div className="flex-1">
          <label htmlFor="backtest-asset" className="text-xs text-gray-500 block mb-1">Asset</label>
          <input
            id="backtest-asset"
            type="text"
            value={asset}
            onChange={(e) => setAsset(e.target.value.toUpperCase())}
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
            placeholder="BTC"
          />
        </div>
        <div className="flex-1">
          <label htmlFor="backtest-days" className="text-xs text-gray-500 block mb-1">Days</label>
          <select
            id="backtest-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
          </select>
        </div>
        <div className="flex items-end">
          <button
            onClick={runBacktest}
            disabled={loading}
            className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:bg-gray-600 text-white rounded text-sm font-medium"
          >
            {loading ? 'Running...' : 'Run Backtest'}
          </button>
        </div>
      </div>

      {results && (
        <div className="space-y-2">
          <div className="grid grid-cols-4 gap-2 text-xs font-medium text-gray-400 border-b border-gray-700 pb-2">
            <span>Source</span>
            <span>Accuracy</span>
            <span>F1 Score</span>
            <span>Trades</span>
          </div>
          {results.map((result, idx) => (
            <div key={idx} className="grid grid-cols-4 gap-2 text-sm py-2 border-b border-gray-700/50">
              <span className="text-white capitalize">{result.source}</span>
              <span className={result.accuracy > 0.5 ? 'text-green-400' : 'text-red-400'}>
                {(result.accuracy * 100).toFixed(1)}%
              </span>
              <span className="text-gray-300">{result.f1_score.toFixed(3)}</span>
              <span className="text-gray-400">{result.total_predictions}</span>
            </div>
          ))}
        </div>
      )}

      {!results && !loading && (
        <div className="text-xs text-gray-500 text-center py-8">
          Run backtest to evaluate sentiment accuracy on historical data
        </div>
      )}
    </div>
  );
};
