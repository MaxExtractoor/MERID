import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Activity, RefreshCw, AlertCircle, Clock, Zap } from 'lucide-react';

interface DriftSignal {
  signal_id: string;
  market_id: string;
  platform: string;
  question: string;
  old_probability: number;
  new_probability: number;
  drift_pct: number;
  direction: 'up' | 'down';
  time_window_seconds: number;
  volume_in_window: number;
  detected_at: string | null;
}

interface DriftDetectionPanelProps {
  className?: string;
}

export default function DriftDetectionPanel({ className = '' }: DriftDetectionPanelProps) {
  const [signals, setSignals] = useState<DriftSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'up' | 'down'>('all');

  useEffect(() => {
    fetchDriftSignals();
    const interval = setInterval(fetchDriftSignals, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchDriftSignals = async () => {
    try {
      const response = await fetch('/api/v1/us-compliant/drift-signals?limit=50');
      if (response.ok) {
        const data = await response.json();
        setSignals(data.signals || []);
        setError(null);
      } else {
        throw new Error('Failed to fetch drift signals');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setSignals([
        {
          signal_id: 'drift_001',
          market_id: 'kalshi_btc_100k',
          platform: 'kalshi',
          question: 'Will Bitcoin reach $100,000 by December 31, 2024?',
          old_probability: 62.5,
          new_probability: 68.2,
          drift_pct: 9.12,
          direction: 'up',
          time_window_seconds: 3600,
          volume_in_window: 125000,
          detected_at: new Date(Date.now() - 1800000).toISOString()
        },
        {
          signal_id: 'drift_002',
          market_id: 'kalshi_fed_rate',
          platform: 'kalshi',
          question: 'Will the Fed cut rates in Q1 2025?',
          old_probability: 48.0,
          new_probability: 42.5,
          drift_pct: -11.46,
          direction: 'down',
          time_window_seconds: 3600,
          volume_in_window: 85000,
          detected_at: new Date(Date.now() - 3600000).toISOString()
        },
        {
          signal_id: 'drift_003',
          market_id: 'kalshi_eth_5k',
          platform: 'kalshi',
          question: 'Will Ethereum reach $5,000 by March 2025?',
          old_probability: 35.0,
          new_probability: 41.2,
          drift_pct: 17.71,
          direction: 'up',
          time_window_seconds: 3600,
          volume_in_window: 62000,
          detected_at: new Date(Date.now() - 7200000).toISOString()
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const formatTimeAgo = (timestamp: string | null) => {
    if (!timestamp) return 'Unknown';
    const diff = Date.now() - new Date(timestamp).getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  const getDriftColor = (drift: number) => {
    const abs = Math.abs(drift);
    if (abs >= 15) return drift > 0 ? 'text-green-400' : 'text-red-400';
    if (abs >= 8) return drift > 0 ? 'text-green-300' : 'text-red-300';
    return drift > 0 ? 'text-green-200' : 'text-red-200';
  };

  const getDriftBg = (drift: number) => {
    const abs = Math.abs(drift);
    if (abs >= 15) return drift > 0 ? 'bg-green-500/20' : 'bg-red-500/20';
    if (abs >= 8) return drift > 0 ? 'bg-green-500/10' : 'bg-red-500/10';
    return 'bg-slate-700/30';
  };

  const filteredSignals = signals.filter(s => {
    if (filter === 'up') return s.direction === 'up';
    if (filter === 'down') return s.direction === 'down';
    return true;
  });

  const upCount = signals.filter(s => s.direction === 'up').length;
  const downCount = signals.filter(s => s.direction === 'down').length;
  const avgDrift = signals.length > 0
    ? signals.reduce((sum, s) => sum + Math.abs(s.drift_pct), 0) / signals.length
    : 0;

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-purple-500" />
          <span className="ml-2 text-gray-400">Loading drift signals...</span>
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
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-purple-400" />
            <p className="text-xs text-gray-400">Total Signals</p>
          </div>
          <p className="text-2xl font-bold text-white">{signals.length}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-green-400" />
            <p className="text-xs text-gray-400">Bullish Drift</p>
          </div>
          <p className="text-2xl font-bold text-green-400">{upCount}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-red-400" />
            <p className="text-xs text-gray-400">Bearish Drift</p>
          </div>
          <p className="text-2xl font-bold text-red-400">{downCount}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4 text-yellow-400" />
            <p className="text-xs text-gray-400">Avg Drift</p>
          </div>
          <p className="text-2xl font-bold text-yellow-400">{avgDrift.toFixed(1)}%</p>
        </div>
      </div>

      {/* Drift Signals List */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
        <div className="p-4 border-b border-slate-700/50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Activity className="w-6 h-6 text-purple-400" />
              <h3 className="text-lg font-bold text-white">Odds Drift Signals</h3>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex gap-2">
                {(['all', 'up', 'down'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`px-3 py-1 text-sm rounded transition-colors ${
                      filter === f
                        ? f === 'up' ? 'bg-green-600 text-white' 
                          : f === 'down' ? 'bg-red-600 text-white'
                          : 'bg-purple-600 text-white'
                        : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
                    }`}
                  >
                    {f === 'all' ? 'All' : f === 'up' ? '↑ Up' : '↓ Down'}
                  </button>
                ))}
              </div>
              <button
                onClick={fetchDriftSignals}
                className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
                title="Refresh drift signals"
                aria-label="Refresh drift signals"
              >
                <RefreshCw className="w-4 h-4 text-gray-400" />
              </button>
            </div>
          </div>
        </div>

        <div className="max-h-96 overflow-y-auto">
          {filteredSignals.length === 0 ? (
            <div className="p-8 text-center">
              <Activity className="w-12 h-12 text-slate-600 mx-auto mb-3" />
              <p className="text-gray-400">No drift signals detected</p>
              <p className="text-sm text-gray-500 mt-1">Signals appear when odds move significantly</p>
            </div>
          ) : (
            filteredSignals.map(signal => (
              <div
                key={signal.signal_id}
                className={`p-4 border-b border-slate-700/50 hover:bg-slate-700/20 transition-colors ${getDriftBg(signal.drift_pct)}`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <p className="text-white font-medium mb-1">{signal.question}</p>
                    <div className="flex items-center gap-3 text-xs text-gray-400">
                      <span className="px-2 py-0.5 bg-slate-700 rounded">{signal.platform}</span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatTimeAgo(signal.detected_at)}
                      </span>
                    </div>
                  </div>
                  <div className="text-right ml-4">
                    <div className={`text-2xl font-bold ${getDriftColor(signal.drift_pct)} flex items-center gap-1`}>
                      {signal.direction === 'up' ? (
                        <TrendingUp className="w-5 h-5" />
                      ) : (
                        <TrendingDown className="w-5 h-5" />
                      )}
                      {signal.drift_pct > 0 ? '+' : ''}{signal.drift_pct.toFixed(1)}%
                    </div>
                    <p className="text-xs text-gray-400">drift</p>
                  </div>
                </div>

                <div className="flex items-center gap-6 text-sm">
                  <div>
                    <span className="text-gray-500">From: </span>
                    <span className="text-white font-mono">{signal.old_probability}%</span>
                  </div>
                  <div className="text-gray-400">→</div>
                  <div>
                    <span className="text-gray-500">To: </span>
                    <span className={`font-mono font-bold ${getDriftColor(signal.drift_pct)}`}>
                      {signal.new_probability}%
                    </span>
                  </div>
                  {signal.volume_in_window > 0 && (
                    <div className="ml-auto">
                      <span className="text-gray-500">Volume: </span>
                      <span className="text-white">${(signal.volume_in_window / 1000).toFixed(0)}K</span>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="p-3 border-t border-slate-700/50 bg-slate-900/50">
          <p className="text-xs text-gray-500 text-center">
            Drift signals from Kalshi (US-compliant) • Auto-refreshing every 30s
          </p>
        </div>
      </div>
    </div>
  );
}
