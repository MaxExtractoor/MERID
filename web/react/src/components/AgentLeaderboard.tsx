import { useState, useEffect } from 'react';
import { API_BASE_URL } from "../config/constants";
import { authHeaders } from '../api/auth';
import { log } from '../ui/logger';

interface LeaderboardEntry {
  agent_id: string;
  pnl: number;
  accuracy: number;
  calibration_error: number;
  edge: number;
  rounds: number;
}

interface AgentWeightHistory {
  agent_id: string;
  weight: number;
  timestamp: string;
}

export function AgentLeaderboard() {
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topN, setTopN] = useState(10);

  useEffect(() => {
    fetchLeaderboard();
  }, [topN]);

  const fetchLeaderboard = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/api/v1/incentives/leaderboard?top_n=${topN}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('Failed to fetch leaderboard');
      const data = await response.json();
      setLeaderboard(data.leaderboard || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-slate-700 rounded w-1/3"></div>
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 bg-slate-800 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-900/20 rounded-lg border border-red-700">
        <p className="text-red-400">Error loading leaderboard: {error}</p>
        <button 
          onClick={fetchLeaderboard}
          className="mt-2 px-3 py-1 bg-red-700 text-white rounded text-sm hover:bg-red-600"
        >
          Retry
        </button>
      </div>
    );
  }

  const getRankColor = (rank: number) => {
    switch (rank) {
      case 0: return 'text-yellow-400';
      case 1: return 'text-slate-300';
      case 2: return 'text-amber-600';
      default: return 'text-slate-500';
    }
  };

  const getPnlColor = (pnl: number) => {
    return pnl >= 0 ? 'text-green-400' : 'text-red-400';
  };

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      <div className="p-4 border-b border-slate-700 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Agent Leaderboard</h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Top</span>
          <select 
            value={topN} 
            onChange={(e) => setTopN(Number(e.target.value))}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded px-2 py-1"
          >
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={25}>25</option>
          </select>
        </div>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-slate-800">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-slate-400 uppercase">Rank</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-slate-400 uppercase">Agent</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-slate-400 uppercase">PnL</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-slate-400 uppercase">Accuracy</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-slate-400 uppercase">Calibration</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-slate-400 uppercase">Edge</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-slate-400 uppercase">Rounds</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {leaderboard.map((entry, index) => (
              <tr key={entry.agent_id} className="hover:bg-slate-800/50 transition-colors">
                <td className="px-4 py-3">
                  <span className={`font-bold ${getRankColor(index)}`}>
                    {index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : `#${index + 1}`}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm font-medium text-white font-mono">
                    {entry.agent_id}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className={`text-sm font-medium ${getPnlColor(entry.pnl)}`}>
                    ${(entry.pnl ?? 0).toFixed(2)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-sm text-slate-300">
                    {((entry.accuracy ?? 0) * 100).toFixed(1)}%
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className={`text-sm ${(entry.calibration_error ?? 0) < 0.2 ? 'text-green-400' : (entry.calibration_error ?? 0) < 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {(entry.calibration_error ?? 0).toFixed(3)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-sm text-blue-400">
                    {(entry.edge ?? 0).toFixed(3)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-sm text-slate-400">
                    {entry.rounds}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      
      {leaderboard.length === 0 && (
        <div className="p-8 text-center text-slate-500">
          No agent data available yet. Run some consensus rounds first.
        </div>
      )}
    </div>
  );
}

export function AgentWeightTimeline() {
  const [weightHistory, setWeightHistory] = useState<AgentWeightHistory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchWeightHistory();
    const interval = setInterval(fetchWeightHistory, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchWeightHistory = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/incentives/weight-history`, { headers: authHeaders() });
      if (!response.ok) throw new Error('Failed to fetch weight history');
      const data = await response.json();
      setWeightHistory(data.history || []);
    } catch (err) {
      log.error('Failed to fetch weight history', err, 'AgentLeaderboard');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="text-slate-500 text-sm">Loading weight history...</div>;
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 p-4">
      <h4 className="text-sm font-semibold text-white mb-3">Recent Weight Adjustments</h4>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {weightHistory.map((entry, i) => (
          <div key={i} className="flex items-center justify-between text-sm py-1 border-b border-slate-800 last:border-0">
            <span className="font-mono text-slate-300">{entry.agent_id}</span>
            <span className="text-blue-400 font-medium">{(entry.weight ?? 0).toFixed(3)}</span>
            <span className="text-xs text-slate-500">{new Date(entry.timestamp).toLocaleTimeString()}</span>
          </div>
        ))}
        {weightHistory.length === 0 && (
          <div className="text-slate-500 text-sm">No weight adjustments recorded yet.</div>
        )}
      </div>
    </div>
  );
}

export default AgentLeaderboard;
