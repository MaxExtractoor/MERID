import { useState, useMemo, useEffect, useCallback } from 'react';
import { Icon, type IconName } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { KalshiPosition, KalshiRiskSummary } from '../types/kalshi';
import type { View } from '../types/views';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';

export default function PositionsView({ onNavigate }: { onNavigate?: (view: View) => void } = {}) {
  const pollOpts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const posResult = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, pollOpts);
  const riskResult = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, pollOpts);
  const gridPortfolioResult = useApiData<{ equity_usd: number; daily_pnl_usd: number; open_interest: number; position_count: number }>(
    API_ENDPOINTS.KALSHI_GRID_PORTFOLIO, pollOpts
  );

  const { summary } = useKalshiRiskStream();
  const posRefetch = posResult.refetch;
  useEffect(() => { if (summary) posRefetch(); }, [summary, posRefetch]);

  const [assetFilter, setAssetFilter] = useState('');
  const [sortField, setSortField] = useState<'ticker' | 'size' | 'unrealized' | 'realized'>('unrealized');
  const [sortAsc, setSortAsc] = useState(false);

  const allPositions = useMemo(() => posResult.data?.positions ?? [], [posResult.data]);
  const risk = riskResult.data;
  const gridPortfolio = gridPortfolioResult.data;

  const positionAssets = useMemo(() => {
    const assets = new Set<string>();
    for (const p of allPositions) {
      const asset = p.ticker.split('-')[0]?.toUpperCase() || p.ticker;
      assets.add(asset);
    }
    return Array.from(assets).sort();
  }, [allPositions]);

  const positions = useMemo(() => {
    const filtered = assetFilter
      ? allPositions.filter(p => {
          const segment = p.ticker.split('-')[0]?.toUpperCase() ?? '';
          return segment === assetFilter;
        })
      : allPositions;

    return [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'ticker': cmp = a.ticker.localeCompare(b.ticker); break;
        case 'size': cmp = (a.size ?? 0) - (b.size ?? 0); break;
        case 'unrealized': cmp = (a.unrealized_pnl ?? 0) - (b.unrealized_pnl ?? 0); break;
        case 'realized': cmp = (a.realized_pnl ?? 0) - (b.realized_pnl ?? 0); break;
      }
      return sortAsc ? cmp : -cmp;
    });
  }, [allPositions, assetFilter, sortField, sortAsc]);

  const handleSort = useCallback((field: typeof sortField) => {
    if (sortField === field) setSortAsc(prev => !prev);
    else { setSortField(field); setSortAsc(false); }
  }, [sortField]);

  // Aggregated stats
  const stats = useMemo(() => {
    const totalUnrealized = allPositions.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);
    const totalRealized = allPositions.reduce((sum, p) => sum + (p.realized_pnl ?? 0), 0);
    const totalSize = allPositions.reduce((sum, p) => sum + (p.size ?? 0), 0);
    const yesCount = allPositions.filter(p => p.outcome === 'yes').length;
    const noCount = allPositions.filter(p => p.outcome === 'no').length;
    return { totalUnrealized, totalRealized, totalSize, yesCount, noCount, total: allPositions.length };
  }, [allPositions]);

  const renderSortIcon = (field: typeof sortField) => {
    if (sortField !== field) return <Icon name="chevronDown" size={10} className="w-2.5 h-2.5 opacity-30" />;
    return sortAsc
      ? <Icon name="chevronUp" size={10} className="w-2.5 h-2.5 text-blue-400" />
      : <Icon name="chevronDown" size={10} className="w-2.5 h-2.5 text-blue-400" />;
  };

  if (posResult.loading && !allPositions.length) {
    return (
      <div className="p-6 flex items-center gap-2 text-slate-400">
        <Icon name="loader" size={16} className="animate-spin" />
        Loading positions...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10">
            <Icon name="target" size={24} className="w-6 h-6 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              Positions
              <KalshiModeBadge />
            </h1>
            <p className="text-xs text-gray-500">
              {stats.total} open · {stats.yesCount} YES / {stats.noCount} NO · {totalContracts(stats.totalSize)} contracts
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => posRefetch()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-xs border border-slate-700"
        >
          <Icon name="refresh" size={14} className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Quick Stats Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Unrealized PnL"
          value={`$${stats.totalUnrealized.toFixed(2)}`}
          color={stats.totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}
          icon="trendingUp"
        />
        <StatCard
          label="Realized PnL"
          value={`$${stats.totalRealized.toFixed(2)}`}
          color={stats.totalRealized >= 0 ? 'text-green-400' : 'text-red-400'}
          icon="barChart"
        />
        <StatCard
          label="Notional (risk src)"
          value={`$${(risk?.total_notional_usd ?? 0).toFixed(2)}`}
          color="text-white"
          icon="activity"
        />
        <StatCard
          label="Equity"
          value={gridPortfolio?.equity_usd != null ? `$${gridPortfolio.equity_usd.toFixed(2)}` : '—'}
          color="text-white"
          icon="dollarSign"
        />
      </div>

      {/* Asset Filter */}
      {positionAssets.length > 1 && (
        <div className="flex items-center gap-2 flex-wrap">
          <Icon name="filter" size={12} className="w-3 h-3 text-gray-500" />
          <button
            type="button"
            onClick={() => setAssetFilter('')}
            className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-all ${
              !assetFilter ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/50' : 'text-gray-500 bg-slate-800 hover:text-white'
            }`}
          >All</button>
          {positionAssets.map(asset => (
            <button
              type="button"
              key={asset}
              onClick={() => setAssetFilter(assetFilter === asset ? '' : asset)}
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-all ${
                assetFilter === asset ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/50' : 'text-gray-500 bg-slate-800 hover:text-white'
              }`}
            >{asset}</button>
          ))}
        </div>
      )}

      {/* Positions Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-gray-500 text-[11px] uppercase tracking-wider">
              <th className="text-left p-3 cursor-pointer select-none hover:text-gray-300" onClick={() => handleSort('ticker')}>
                <span className="flex items-center gap-1">Ticker {renderSortIcon('ticker')}</span>
              </th>
              <th className="text-left p-3">Side</th>
              <th className="text-right p-3 cursor-pointer select-none hover:text-gray-300" onClick={() => handleSort('size')}>
                <span className="flex items-center gap-1 justify-end">Size {renderSortIcon('size')}</span>
              </th>
              <th className="text-right p-3">Avg Price</th>
              <th className="text-right p-3 cursor-pointer select-none hover:text-gray-300" onClick={() => handleSort('unrealized')}>
                <span className="flex items-center gap-1 justify-end">Unrealized {renderSortIcon('unrealized')}</span>
              </th>
              <th className="text-right p-3 cursor-pointer select-none hover:text-gray-300" onClick={() => handleSort('realized')}>
                <span className="flex items-center gap-1 justify-end">Realized {renderSortIcon('realized')}</span>
              </th>
              <th className="text-center p-3">Agent</th>
              <th className="text-center p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-12 text-gray-600">
                  <Icon name="inbox" size={32} className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  No open positions
                </td>
              </tr>
            ) : (
              positions.map((p, i) => (
                <tr key={`${p.ticker}-${i}`} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="p-3 font-mono text-white text-xs">{p.ticker}</td>
                  <td className="p-3">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      p.outcome === 'yes' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                    }`}>
                      {(p.outcome ?? '—').toUpperCase()}
                    </span>
                  </td>
                  <td className="p-3 text-right text-white font-mono text-xs">{p.size}</td>
                  <td className="p-3 text-right text-gray-400 font-mono text-xs">{((p.avg_price ?? 0) * 100).toFixed(1)}¢</td>
                  <td className={`p-3 text-right font-medium text-xs ${(p.unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${(p.unrealized_pnl ?? 0).toFixed(2)}
                  </td>
                  <td className={`p-3 text-right text-xs ${(p.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${(p.realized_pnl ?? 0).toFixed(2)}
                  </td>
                  <td className="p-3 text-center">
                    {(p.initiated_by || p.agent_name) ? (
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-blue-500/20 text-blue-400">
                        {p.initiated_by || p.agent_name}
                      </span>
                    ) : (
                      <span className="text-[10px] text-gray-600">Manual</span>
                    )}
                  </td>
                  <td className="p-3 text-center">
                    {(p.initiated_by || p.agent_name) && onNavigate && (
                      <button
                        type="button"
                        onClick={() => {
                          const agentName = p.initiated_by || p.agent_name;
                          if (agentName) {
                            sessionStorage.setItem('merid:focus-agent', agentName);
                            onNavigate('promote-grid');
                          }
                        }}
                        className="text-[10px] text-blue-400 hover:text-blue-300 underline"
                        title="View agent in Grid"
                      >
                        View decision
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Footer summary */}
        {positions.length > 0 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-slate-800 bg-slate-900/50 text-[11px] text-gray-500">
            <span>{positions.length} position{positions.length !== 1 ? 's' : ''} shown{assetFilter ? ` (filtered: ${assetFilter})` : ''}</span>
            <span>
              Total unrealized: <span className={stats.totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}>${stats.totalUnrealized.toFixed(2)}</span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function totalContracts(n: number): string {
  return n.toLocaleString();
}

function StatCard({ label, value, color, icon }: { label: string; value: string; color: string; icon: IconName }) {
  return (
    <div className="bg-slate-900 rounded-lg p-3 border border-slate-800">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon name={icon} size={12} className="w-3 h-3 text-gray-500" />
        <span className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</span>
      </div>
      <p className={`text-sm font-bold ${color}`}>{value}</p>
    </div>
  );
}
