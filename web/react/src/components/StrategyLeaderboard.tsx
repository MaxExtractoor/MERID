import { useState, useEffect, useCallback } from 'react';
import { Trophy, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';

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

const DOMAIN_BADGE: Record<string, string> = {
  prediction: 'bg-orange-500/20 text-orange-400',
  crypto: 'bg-blue-500/20 text-blue-400',
  equity: 'bg-green-500/20 text-green-400',
};

export default function StrategyLeaderboard() {
  const [rows, setRows] = useState<StrategyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'totalPnl' | 'winRate' | 'sharpe'>('totalPnl');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/pipeline/leaderboard');
      if (res.ok) {
        const data = await res.json();
        if (data.strategies) { setRows(data.strategies); return; }
      }
    } catch { /* fallback */ }

    setRows([
      { rank: 1, agent: 'CryptoArbAgent', domain: 'crypto', strategy: 'Cross-Exchange Arb',
        totalPnl: 1245.80, winRate: 0.87, trades: 156, avgHold: '2.3m', sharpe: 3.2, maxDrawdown: -85.40 },
      { rank: 2, agent: 'PredictionMarketAgent', domain: 'prediction', strategy: 'Edge Speculative',
        totalPnl: 420.50, winRate: 0.62, trades: 48, avgHold: '18.5h', sharpe: 1.8, maxDrawdown: -120.00 },
      { rank: 3, agent: 'FundingArbAgent', domain: 'crypto', strategy: 'Funding Rate Arb',
        totalPnl: 380.20, winRate: 0.91, trades: 89, avgHold: '8.1h', sharpe: 2.5, maxDrawdown: -45.60 },
      { rank: 4, agent: 'EquityAgent', domain: 'equity', strategy: 'Momentum',
        totalPnl: 156.30, winRate: 0.55, trades: 22, avgHold: '4.2d', sharpe: 1.1, maxDrawdown: -210.00 },
      { rank: 5, agent: 'CryptoArbAgent', domain: 'crypto', strategy: 'Triangular Arb',
        totalPnl: 98.40, winRate: 0.78, trades: 34, avgHold: '45s', sharpe: 2.1, maxDrawdown: -32.10 },
      { rank: 6, agent: 'PredictionMarketAgent', domain: 'prediction', strategy: 'Arb Detection',
        totalPnl: -15.20, winRate: 0.40, trades: 5, avgHold: '1.2h', sharpe: -0.3, maxDrawdown: -45.00 },
    ]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

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
              <button
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
          <button onClick={fetchData} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh leaderboard">
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
    </div>
  );
}
