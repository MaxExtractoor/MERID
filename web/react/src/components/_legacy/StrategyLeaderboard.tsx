import { useState } from 'react';
import { Trophy, RefreshCw, TrendingUp, TrendingDown, Star } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface StrategyRow {
  rank: number;
  agent: string;
  domain: string;
  strategy: string;
  totalPnl: number;
  winRate: number;
  trades: number;
  avgHold: string;
  sharpe: number;
  maxDrawdown: number;
}

interface XpEntry {
  user: string;
  xp: number;
}

const DOMAIN_BADGE: Record<string, string> = {
  prediction: 'bg-orange-500/20 text-orange-400',
  crypto: 'bg-blue-500/20 text-blue-400',
  equity: 'bg-green-500/20 text-green-400',
};

export default function StrategyLeaderboard() {
  const [sortBy, setSortBy] = useState<'totalPnl' | 'winRate' | 'sharpe'>('totalPnl');

  const { data: xpData } = useApiData<{ items: XpEntry[] }>(
    `${API_ENDPOINTS.REWARDS_LEADERBOARD}?limit=10`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );
  const { data: lbData, loading, error: lbError, refetch } = useApiData<{ strategies: StrategyRow[] }>(
    API_ENDPOINTS.PIPELINE_LEADERBOARD,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );
  const rows = lbData?.strategies ?? [];

  if (lbError && !lbData) {
    return <ErrorBar label="Leaderboard" error={lbError} onRetry={refetch} />;
  }
  const xpEntries = xpData?.items ?? [];

  const sorted = [...rows].sort((a, b) => {
    if (sortBy === 'totalPnl') return b.totalPnl - a.totalPnl;
    if (sortBy === 'winRate') return b.winRate - a.winRate;
    return b.sharpe - a.sharpe;
  });

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading leaderboard...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trophy className="w-5 h-5 text-yellow-400" />
          <h3 className="text-lg font-bold text-white">Strategy Leaderboard</h3>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['totalPnl', 'winRate', 'sharpe'] as const).map(s => (
              <button type="button"
                key={s}
                onClick={() => setSortBy(s)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  sortBy === s ? 'bg-yellow-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {s === 'totalPnl' ? 'PnL' : s === 'winRate' ? 'Win%' : 'Sharpe'}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => refetch()} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh leaderboard" aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-2 py-2 text-slate-500 font-medium w-8">#</th>
              <th className="text-left px-2 py-2 text-slate-500 font-medium">Agent / Strategy</th>
              <th className="text-left px-2 py-2 text-slate-500 font-medium">Domain</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">PnL</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">Win%</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">Trades</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">Avg Hold</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">Sharpe</th>
              <th className="text-right px-2 py-2 text-slate-500 font-medium">Max DD</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={`${row.agent}-${row.strategy}`} className="border-b border-slate-800/50 hover:bg-slate-700/20 transition-colors">
                <td className="px-2 py-2 text-gray-500 font-mono">
                  {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1}
                </td>
                <td className="px-2 py-2">
                  <div className="text-white font-medium">{row.agent}</div>
                  <div className="text-gray-500 text-[10px]">{row.strategy}</div>
                </td>
                <td className="px-2 py-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${DOMAIN_BADGE[row.domain] || 'bg-gray-500/20 text-gray-400'}`}>
                    {row.domain}
                  </span>
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  <span className={`flex items-center justify-end gap-1 ${row.totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {row.totalPnl >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                    {row.totalPnl >= 0 ? '+' : ''}${row.totalPnl.toFixed(2)}
                  </span>
                </td>
                <td className="px-2 py-2 text-right font-mono">
                  <span className={row.winRate >= 0.6 ? 'text-green-400' : row.winRate >= 0.5 ? 'text-amber-400' : 'text-red-400'}>
                    {(row.winRate * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="px-2 py-2 text-right text-gray-400 font-mono">{row.trades}</td>
                <td className="px-2 py-2 text-right text-gray-400">{row.avgHold}</td>
                <td className="px-2 py-2 text-right font-mono">
                  <span className={row.sharpe >= 2 ? 'text-green-400' : row.sharpe >= 1 ? 'text-amber-400' : 'text-red-400'}>
                    {row.sharpe.toFixed(1)}
                  </span>
                </td>
                <td className="px-2 py-2 text-right font-mono text-red-400">
                  ${Math.abs(row.maxDrawdown).toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* XP Leaderboard from Rewards API */}
      {xpEntries.length > 0 && (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <Star className="w-4 h-4 text-amber-400" />
            <h4 className="text-sm font-semibold text-white">XP Leaderboard</h4>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {xpEntries.slice(0, 10).map((entry, i) => (
              <div key={entry.user} className="flex items-center gap-2 bg-slate-700/30 rounded px-2.5 py-1.5">
                <span className={`text-xs font-bold w-4 ${i === 0 ? 'text-yellow-400' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-amber-600' : 'text-slate-500'}`}>
                  {i + 1}
                </span>
                <span className="text-xs text-white truncate flex-1">{entry.user}</span>
                <span className="text-xs font-semibold text-amber-400">{entry.xp.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
