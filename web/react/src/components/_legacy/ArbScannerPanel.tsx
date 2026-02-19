import { useState } from 'react';
import {
  Zap, ArrowRightLeft, Clock, CheckCircle, XCircle,
  RefreshCw
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS, ARB_STATUS} from '../config/constants';

interface ArbOpportunity {
  id: string;
  pair: string;
  type: 'cross_exchange' | 'funding' | 'triangular' | 'prediction';
  buyVenue: string;
  sellVenue: string;
  buyPrice: number;
  sellPrice: number;
  spreadBps: number;
  estimatedPnl: number;
  confidence: number;
  detectedAt: string;
  status: 'live' | 'executing' | 'filled' | 'expired' | 'failed';
  legs: ArbLeg[];
}

interface ArbLeg {
  venue: string;
  side: 'buy' | 'sell';
  price: number;
  qty: number;
  status: 'pending' | 'submitted' | 'filled' | 'failed';
  fillPrice?: number;
}

interface ArbStats {
  totalOpportunities24h: number;
  executedCount: number;
  realizedPnl: number;
  avgSpreadBps: number;
  hitRate: number;
}

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  cross_exchange: { label: 'Cross-Ex', color: 'bg-blue-500/20 text-blue-400' },
  funding: { label: 'Funding', color: 'bg-purple-500/20 text-purple-400' },
  triangular: { label: 'Tri-Arb', color: 'bg-amber-500/20 text-amber-400' },
  prediction: { label: 'PM Arb', color: 'bg-green-500/20 text-green-400' },
};

const STATUS_CONFIG: Record<string, { icon: typeof CheckCircle; color: string }> = {
  live: { icon: Zap, color: 'text-green-400' },
  executing: { icon: Clock, color: 'text-blue-400' },
  filled: { icon: CheckCircle, color: 'text-emerald-400' },
  expired: { icon: Clock, color: 'text-gray-400' },
  failed: { icon: XCircle, color: 'text-red-400' },
};

export default function ArbScannerPanel() {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('all');

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ opportunities: ArbOpportunity[]; stats: ArbStats }>(
    API_ENDPOINTS.ARBITRAGE_SCANNER,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Arb scanner" error={fetchError} onRetry={refetch} />;
  }
  const opportunities = rawData?.opportunities ?? [];
  const stats = rawData?.stats ?? null;

  const filtered = filter === 'all'
    ? opportunities
    : opportunities.filter(o => o.type === filter);

  const formatTime = (ts: string) => {
    const ms = Date.now() - new Date(ts).getTime();
    if (ms < 60000) return `${Math.floor(ms / 1000)}s`;
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m`;
    return `${Math.floor(ms / 3600000)}h`;
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Scanning for arbitrage opportunities...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ArrowRightLeft className="w-5 h-5 text-green-400" />
          <h3 className="text-lg font-bold text-white">Arb Scanner</h3>
          <span className="text-xs px-2 py-0.5 rounded bg-green-500/20 text-green-400">
            {opportunities.filter(o => o.status === ARB_STATUS.LIVE).length} live
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {['all', 'cross_exchange', 'funding', 'prediction'].map(f => (
              <button type="button"
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  filter === f ? 'bg-blue-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {f === 'all' ? 'All' : TYPE_LABELS[f]?.label || f}
              </button>
            ))}
          </div>
          <button type="button"
            onClick={() => refetch()}
            className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh scanner"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Stats Row */}
      {stats && (
        <div className="grid grid-cols-5 gap-3">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.totalOpportunities24h}</p>
            <p className="text-xs text-gray-400">Opps (24h)</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.executedCount}</p>
            <p className="text-xs text-gray-400">Executed</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
            <p className={`text-xl font-bold ${stats.realizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${stats.realizedPnl.toFixed(2)}
            </p>
            <p className="text-xs text-gray-400">Realized PnL</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.avgSpreadBps.toFixed(1)}</p>
            <p className="text-xs text-gray-400">Avg Spread (bps)</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
            <p className="text-xl font-bold text-white">{stats.hitRate.toFixed(1)}%</p>
            <p className="text-xs text-gray-400">Hit Rate</p>
          </div>
        </div>
      )}

      {/* Opportunities Table */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-2 text-gray-400 font-medium">Pair</th>
              <th className="text-left px-4 py-2 text-gray-400 font-medium">Type</th>
              <th className="text-left px-4 py-2 text-gray-400 font-medium">Route</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Spread</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Est. PnL</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Conf</th>
              <th className="text-center px-4 py-2 text-gray-400 font-medium">Status</th>
              <th className="text-right px-4 py-2 text-gray-400 font-medium">Age</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((opp) => {
              const typeInfo = TYPE_LABELS[opp.type] || { label: opp.type, color: 'bg-gray-500/20 text-gray-400' };
              const statusCfg = STATUS_CONFIG[opp.status] || STATUS_CONFIG.expired;
              const StatusIcon = statusCfg.icon;
              const isExpanded = expandedId === opp.id;

              return (
                <>
                  <tr
                    key={opp.id}
                    className={`border-b border-slate-700/30 cursor-pointer hover:bg-slate-700/30 ${
                      opp.status === ARB_STATUS.LIVE ? 'bg-green-500/5' : ''
                    }`}
                    onClick={() => setExpandedId(isExpanded ? null : opp.id)}
                  >
                    <td className="px-4 py-2 font-medium text-white">{opp.pair}</td>
                    <td className="px-4 py-2">
                      <span className={`px-2 py-0.5 text-xs rounded ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-300">
                      {opp.buyVenue} → {opp.sellVenue}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <span className={`font-mono ${opp.spreadBps > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {opp.spreadBps.toFixed(1)} bps
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <span className={`font-mono ${opp.estimatedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        ${opp.estimatedPnl.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <span className={`font-mono ${opp.confidence >= 0.8 ? 'text-green-400' : opp.confidence >= 0.6 ? 'text-amber-400' : 'text-red-400'}`}>
                        {(opp.confidence * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="px-4 py-2 text-center">
                      <StatusIcon className={`w-4 h-4 mx-auto ${statusCfg.color}`} />
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400 font-mono">
                      {formatTime(opp.detectedAt)}
                    </td>
                  </tr>
                  {/* Expanded Leg Detail */}
                  {isExpanded && (
                    <tr key={`${opp.id}-detail`}>
                      <td colSpan={8} className="px-4 py-3 bg-slate-900/50">
                        <div className="space-y-2">
                          <span className="text-xs font-medium text-gray-400">Legs</span>
                          {opp.legs.map((leg, i) => (
                            <div
                              key={i}
                              className="flex items-center justify-between px-3 py-1.5 bg-slate-800/50 rounded text-xs"
                            >
                              <div className="flex items-center gap-3">
                                <span className={`font-medium ${leg.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                                  {leg.side.toUpperCase()}
                                </span>
                                <span className="text-gray-300">{leg.venue}</span>
                                <span className="text-gray-400">
                                  {leg.qty} @ ${leg.price.toLocaleString()}
                                </span>
                              </div>
                              <div className="flex items-center gap-2">
                                {leg.fillPrice && (
                                  <span className="text-gray-400">
                                    Fill: ${leg.fillPrice.toLocaleString()}
                                  </span>
                                )}
                                <span className={`px-1.5 py-0.5 rounded ${
                                  leg.status === ARB_STATUS.FILLED ? 'bg-green-500/20 text-green-400' :
                                  leg.status === ARB_STATUS.SUBMITTED ? 'bg-blue-500/20 text-blue-400' :
                                  leg.status === ARB_STATUS.FAILED ? 'bg-red-500/20 text-red-400' :
                                  'bg-gray-500/20 text-gray-400'
                                }`}>
                                  {leg.status}
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
