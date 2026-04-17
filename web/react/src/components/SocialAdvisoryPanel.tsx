import { useState, useEffect } from 'react';
import { API_BASE_URL } from "../config/constants";
import { authHeaders } from '../api/auth';
import { log } from '../ui/logger';

interface SocialSignal {
  source: string;
  agent_id: string;
  score: number;
  confidence: number;
  volume: number;
  timestamp: string;
}

interface SocialBreakdown {
  symbol: string;
  signal_count: number;
  signals: SocialSignal[];
  computed_nudge: number;
}

export function SocialAdvisoryPanel() {
  const [symbol, setSymbol] = useState('BTC');
  const [breakdown, setBreakdown] = useState<SocialBreakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [editingWeight, setEditingWeight] = useState<string | null>(null);
  const [newWeight, setNewWeight] = useState<number>(0.1);

  const symbols = ['BTC', 'ETH', 'SOL', 'SPX', 'NDX'];

  useEffect(() => {
    fetchBreakdown();
    fetchWeights();
  }, [symbol]);

  const fetchBreakdown = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/v1/incentives/social/${symbol}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('Failed to fetch social breakdown');
      const data = await response.json();
      setBreakdown(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const fetchWeights = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/incentives/social-weights`, { headers: authHeaders() });
      if (!response.ok) throw new Error('Failed to fetch weights');
      const data = await response.json();
      setWeights(data.weights || {});
    } catch (err) {
      log.error('Failed to fetch weights', err, 'SocialAdvisoryPanel');
    }
  };

  const updateWeight = async (source: string, weight: number) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/incentives/social-weights`, {
        method: 'PUT',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, weight: Math.max(0, Math.min(1, weight)) }),
      });
      if (!response.ok) throw new Error('Failed to update weight');
      await fetchWeights();
      setEditingWeight(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update weight');
    }
  };

  const getScoreColor = (score: number) => {
    if (score > 0.3) return 'text-green-400';
    if (score > 0) return 'text-green-300';
    if (score < -0.3) return 'text-red-400';
    if (score < 0) return 'text-red-300';
    return 'text-slate-400';
  };

  const getNudgeColor = (nudge: number) => {
    if (nudge > 0.05) return 'text-green-400';
    if (nudge < -0.05) return 'text-red-400';
    return 'text-slate-400';
  };

  const getSourceIcon = (source: string) => {
    switch ((source ?? '').toLowerCase()) {
      case 'twitter': return '🐦';
      case 'reddit': return '👽';
      case 'newsapi': return '📰';
      default: return '📡';
    }
  };

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      <div className="p-4 border-b border-slate-700">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">Social Advisory Breakdown</h3>
          <select 
            value={symbol} 
            onChange={(e) => setSymbol(e.target.value)}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded px-3 py-1"
          >
            {symbols.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        {/* Nudge Summary */}
        {breakdown && (
          <div className="flex items-center justify-between bg-slate-800 rounded p-3">
            <span className="text-sm text-slate-400">Consensus Nudge</span>
            <span className={`text-xl font-bold ${getNudgeColor(breakdown.computed_nudge)}`}>
              {(breakdown.computed_nudge ?? 0) > 0 ? '+' : ''}{(breakdown.computed_nudge ?? 0).toFixed(4)}
            </span>
          </div>
        )}
      </div>

      {/* Weight Controls */}
      <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50">
        <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Source Weights</h4>
        <div className="flex flex-wrap gap-2">
          {Object.entries(weights).map(([source, weight]) => (
            <div key={source} className="flex items-center gap-1 bg-slate-800 rounded px-2 py-1">
              <span className="text-xs text-slate-300 capitalize">{source}</span>
              {editingWeight === source ? (
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={newWeight}
                    onChange={(e) => setNewWeight(Number(e.target.value))}
                    className="w-12 bg-slate-900 border border-slate-600 text-white text-xs rounded px-1 py-0.5"
                  />
                  <button
                    onClick={() => updateWeight(source, newWeight)}
                    className="text-green-400 text-xs hover:text-green-300"
                  >
                    ✓
                  </button>
                  <button
                    onClick={() => setEditingWeight(null)}
                    className="text-red-400 text-xs hover:text-red-300"
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setEditingWeight(source);
                    setNewWeight(weight);
                  }}
                  className="text-xs font-mono text-blue-400 hover:text-blue-300"
                >
                  {(weight ?? 0).toFixed(2)}
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Signal List */}
      <div className="p-4">
        {loading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-16 bg-slate-800 rounded animate-pulse"></div>
            ))}
          </div>
        ) : error ? (
          <div className="text-red-400 text-sm">{error}</div>
        ) : breakdown && breakdown.signals.length > 0 ? (
          <div className="space-y-3">
            {breakdown.signals.map((signal, idx) => (
              <div key={idx} className="bg-slate-800 rounded p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{getSourceIcon(signal.source)}</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white capitalize">{signal.source}</span>
                      <span className="text-xs text-slate-500 font-mono">{signal.agent_id}</span>
                    </div>
                    <div className="text-xs text-slate-400">
                      Vol: {signal.volume} • Conf: {((signal.confidence ?? 0) * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <span className={`text-lg font-bold ${getScoreColor(signal.score)}`}>
                    {(signal.score ?? 0) > 0 ? '+' : ''}{(signal.score ?? 0).toFixed(2)}
                  </span>
                  <div className="text-xs text-slate-500">
                    {new Date(signal.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-slate-500 py-8">
            No social signals available for {symbol}
          </div>
        )}
      </div>

      {/* Refresh Button */}
      <div className="px-4 py-3 border-t border-slate-700 bg-slate-800/30">
        <button
          onClick={fetchBreakdown}
          className="w-full px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm font-medium transition-colors"
        >
          Refresh Signals
        </button>
      </div>
    </div>
  );
}

export default SocialAdvisoryPanel;
