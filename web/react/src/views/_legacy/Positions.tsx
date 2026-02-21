import { useMemo } from 'react';
import { TrendingUp, TrendingDown, Package, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import type { KalshiPosition, KalshiRiskSummary } from '../types/kalshi';

export default function Positions() {
  const { data: rawData, loading, refetch } = useApiData<{ positions: KalshiPosition[] }>(
    API_ENDPOINTS.KALSHI_POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.POSITIONS },
  );
  const { data: risk } = useApiData<KalshiRiskSummary>(
    API_ENDPOINTS.KALSHI_RISK,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const positions = useMemo(() => rawData?.positions ?? [], [rawData]);

  const totalNotional = useMemo(
    () => positions.reduce((sum, p) => sum + p.avg_price * p.size, 0),
    [positions],
  );
  const totalUnrealizedPnl = useMemo(
    () => positions.reduce((sum, p) => sum + p.unrealized_pnl, 0),
    [positions],
  );

  const drawdownPct = risk?.drawdown_pct ?? 0;

  return (
    <div className="space-y-6">
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">Kalshi Positions <KalshiModeBadge /></h1>
          <p className="text-slate-400">Live positions from your Kalshi account</p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-medium text-slate-300 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <Package className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-slate-400">Total Notional</span>
          </div>
          <div className="text-2xl font-semibold text-white">
            ${totalNotional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-sm text-slate-400 mt-1">{positions.length} open position{positions.length !== 1 ? 's' : ''}</div>
        </div>

        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            {totalUnrealizedPnl >= 0
              ? <TrendingUp className="w-4 h-4 text-emerald-400" />
              : <TrendingDown className="w-4 h-4 text-rose-400" />}
            <span className="text-sm text-slate-400">Unrealized P&L</span>
          </div>
          <div className={`text-2xl font-semibold ${totalUnrealizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {totalUnrealizedPnl >= 0 ? '+' : ''}${totalUnrealizedPnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-sm text-slate-400 mt-1">across all markets</div>
        </div>

        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-amber-400" />
            <span className="text-sm text-slate-400">Drawdown</span>
          </div>
          <div className={`text-2xl font-semibold ${drawdownPct > 10 ? 'text-rose-400' : drawdownPct > 5 ? 'text-amber-400' : 'text-slate-200'}`}>
            {drawdownPct.toFixed(1)}%
          </div>
          <div className="text-sm text-slate-400 mt-1">from peak equity</div>
        </div>
      </div>

      {/* Positions Table */}
      {loading ? (
        <div className="bg-slate-900/70 rounded-xl p-8 border border-slate-800 text-center">
          <div className="animate-spin w-8 h-8 border-2 border-orange-500 border-t-transparent rounded-full mx-auto mb-4" />
          <p className="text-slate-400">Loading Kalshi positions...</p>
        </div>
      ) : positions.length === 0 ? (
        <div className="bg-slate-900/70 rounded-xl p-12 border border-slate-800 text-center">
          <Package className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 font-medium">No open positions</p>
          <p className="text-slate-500 text-sm mt-1">Positions will appear here once you have active Kalshi contracts</p>
        </div>
      ) : (
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3">Ticker</th>
                <th className="text-left px-4 py-3">Outcome</th>
                <th className="text-right px-4 py-3">Contracts</th>
                <th className="text-right px-4 py-3">Avg Price</th>
                <th className="text-right px-4 py-3">Notional</th>
                <th className="text-right px-4 py-3">Unrealized P&L</th>
                <th className="text-right px-4 py-3">Realized P&L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {positions.map((p) => {
                const notional = p.avg_price * p.size;
                const pnlPos = p.unrealized_pnl >= 0;
                const rpnlPos = p.realized_pnl >= 0;
                return (
                  <tr key={`${p.ticker}-${p.outcome}`} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-4 py-3 font-mono text-orange-300 font-medium">{p.ticker}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${p.outcome === 'yes' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                        {p.outcome.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200">{p.size}</td>
                    <td className="px-4 py-3 text-right text-slate-200">{Math.round(p.avg_price * 100)}¢</td>
                    <td className="px-4 py-3 text-right text-slate-200">
                      ${notional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pnlPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {pnlPos ? '+' : ''}${p.unrealized_pnl.toFixed(2)}
                    </td>
                    <td className={`px-4 py-3 text-right ${rpnlPos ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {rpnlPos ? '+' : ''}${p.realized_pnl.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
