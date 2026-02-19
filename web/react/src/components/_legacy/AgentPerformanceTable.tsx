import { useState } from 'react';
import { 
  Bot, 
  TrendingUp, 
  TrendingDown, 
  Award,
  Shield,
  BarChart3,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  Filter
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface AgentMetrics {
  agent_id: string;
  role: string;
  current_equity: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown: number;
  current_drawdown: number;
  sortino_ratio: number;
  calmar_ratio: number;
  prediction_accuracy: number;
  consensus_weight: number;
  average_latency_ms?: number;
  p95_latency_ms?: number;
  last_updated: number;
}

type SortKey = 'sharpe_ratio' | 'total_pnl' | 'win_rate' | 'max_drawdown' | 'consensus_weight' | 'prediction_accuracy' | 'p95_latency_ms';

interface AgentPerformanceTableProps {
  agents?: AgentMetrics[];
  onAgentSelect?: (agentId: string) => void;
  compact?: boolean;
}

const ROLE_COLORS: Record<string, string> = {
  bull_analyst: 'text-green-400',
  bear_analyst: 'text-red-400',
  arbitrage: 'text-purple-400',
  sentiment: 'text-blue-400',
  technical: 'text-orange-400',
  fundamental: 'text-cyan-400',
  risk_manager: 'text-yellow-400',
  trader: 'text-pink-400',
  analyst: 'text-gray-400',
};

export default function AgentPerformanceTable({
  agents: propAgents,
  onAgentSelect,
  compact = false,
}: AgentPerformanceTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('sharpe_ratio');
  const [sortDesc, setSortDesc] = useState(true);
  const [roleFilter, setRoleFilter] = useState<string>('all');

  const { data: rawData, loading: fetchLoading, error: fetchError, refetch } = useApiData<{ agents: AgentMetrics[] }>(
    API_ENDPOINTS.RISK_AGENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM, enabled: !propAgents },
  );
  const agents = propAgents ?? rawData?.agents ?? [];
  const loading = !propAgents && fetchLoading;

  if (fetchError && !rawData && !propAgents) {
    return <ErrorBar label="Agent performance" error={fetchError} onRetry={refetch} />;
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  const sortedAgents = [...agents]
    .filter(a => roleFilter === 'all' || a.role === roleFilter)
    .sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      // For drawdown, lower is better
      if (sortKey === 'max_drawdown') {
        return sortDesc ? aVal - bVal : bVal - aVal;
      }
      return sortDesc ? bVal - aVal : aVal - bVal;
    });

  const uniqueRoles = [...new Set(agents.map(a => a.role))];

  const formatPercent = (value: number) => `${((value ?? 0) * 100).toFixed(1)}%`;
  const formatCurrency = (value: number) => {
    const v = value ?? 0;
    const sign = v >= 0 ? '+' : '';
    return `${sign}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };
  const formatSharpe = (value: number) => (value ?? 0).toFixed(2);
  const formatLatency = (ms?: number) => {
    if (ms == null || ms === 0) return '—';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };
  const getLatencyColor = (ms?: number) => {
    if (ms == null || ms === 0) return 'text-gray-500';
    if (ms < 1000) return 'text-green-400';
    if (ms < 3000) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getSharpeColor = (sharpe: number) => {
    if (sharpe < 0) return 'text-red-400';
    if (sharpe < 1) return 'text-yellow-400';
    if (sharpe < 2) return 'text-green-400';
    return 'text-emerald-400';
  };

  const getDrawdownColor = (dd: number) => {
    if (dd >= 0.2) return 'text-red-400';
    if (dd >= 0.1) return 'text-yellow-400';
    return 'text-green-400';
  };

  const getPnlColor = (pnl: number) => pnl >= 0 ? 'text-green-400' : 'text-red-400';

  const SortHeader = ({ label, sortKey: key }: { label: string; sortKey: SortKey }) => (
    <th
      className="p-3 cursor-pointer hover:bg-slate-700/50 transition-colors"
      onClick={() => handleSort(key)}
    >
      <div className="flex items-center gap-1">
        {label}
        {sortKey === key && (
          sortDesc ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />
        )}
      </div>
    </th>
  );

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-slate-700 rounded w-48"></div>
          <div className="h-64 bg-slate-700/50 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Agent Performance</h2>
          <span className="text-sm text-gray-400">({sortedAgents.length} agents)</span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Role Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              id="agent-role-filter"
              name="roleFilter"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-gray-300"
              aria-label="Filter by role"
            >
              <option value="all">All Roles</option>
              {uniqueRoles.map(role => (
                <option key={role} value={role}>{role.replace('_', ' ')}</option>
              ))}
            </select>
          </div>
          
          <button type="button"
            onClick={() => refetch()}
            className="p-1.5 hover:bg-slate-700/50 rounded transition-colors"
            title="Refresh"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-slate-800/50">
            <tr className="text-left text-sm text-gray-400">
              <th className="p-3">Agent</th>
              <th className="p-3">Role</th>
              <SortHeader label="Sharpe" sortKey="sharpe_ratio" />
              <SortHeader label="Max DD" sortKey="max_drawdown" />
              <SortHeader label="P&L" sortKey="total_pnl" />
              <SortHeader label="Win Rate" sortKey="win_rate" />
              <SortHeader label="Accuracy" sortKey="prediction_accuracy" />
              <SortHeader label="Weight" sortKey="consensus_weight" />
              <SortHeader label="P95 Lat" sortKey="p95_latency_ms" />
              {!compact && <th className="p-3">Status</th>}
            </tr>
          </thead>
          <tbody>
            {sortedAgents.length === 0 ? (
              <tr>
                <td colSpan={compact ? 9 : 10} className="p-8 text-center text-gray-500">
                  <Bot className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p>No agents tracked yet</p>
                  <p className="text-sm">Agents will appear here as they trade</p>
                </td>
              </tr>
            ) : (
              sortedAgents.map((agent, idx) => (
                <tr 
                  key={agent.agent_id}
                  className={`border-t border-slate-700/30 hover:bg-slate-800/50 cursor-pointer ${
                    idx === 0 && sortKey === 'sharpe_ratio' ? 'bg-emerald-500/5' : ''
                  }`}
                  onClick={() => onAgentSelect?.(agent.agent_id)}
                >
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      {idx === 0 && sortKey === 'sharpe_ratio' && (
                        <Award className="w-4 h-4 text-yellow-400" />
                      )}
                      <Bot className="w-4 h-4 text-purple-400" />
                      <span className="font-mono text-sm text-white">{agent.agent_id}</span>
                    </div>
                  </td>
                  <td className={`p-3 text-sm ${ROLE_COLORS[agent.role] || 'text-gray-400'}`}>
                    {agent.role.replace('_', ' ')}
                  </td>
                  <td className={`p-3 font-medium ${getSharpeColor(agent.sharpe_ratio)}`}>
                    {formatSharpe(agent.sharpe_ratio)}
                  </td>
                  <td className={`p-3 ${getDrawdownColor(agent.max_drawdown)}`}>
                    -{formatPercent(agent.max_drawdown)}
                  </td>
                  <td className={`p-3 font-medium ${getPnlColor(agent.total_pnl)}`}>
                    {formatCurrency(agent.total_pnl)}
                  </td>
                  <td className="p-3 text-gray-300">
                    {formatPercent(agent.win_rate)}
                    <span className="text-xs text-gray-500 ml-1">
                      ({agent.winning_trades ?? 0}/{agent.total_trades ?? 0})
                    </span>
                  </td>
                  <td className="p-3 text-gray-300">
                    {formatPercent(agent.prediction_accuracy)}
                  </td>
                  <td className="p-3">
                    <div className="flex items-center gap-1">
                      <div 
                        className="h-2 bg-purple-500/50 rounded"
                        style={{ width: `${(agent.consensus_weight ?? 0) * 40}px` }}
                      />
                      <span className="text-sm text-gray-400">{(agent.consensus_weight ?? 0).toFixed(2)}x</span>
                    </div>
                  </td>
                  <td className={`p-3 font-mono text-sm ${getLatencyColor(agent.p95_latency_ms)}`}>
                    {formatLatency(agent.p95_latency_ms)}
                  </td>
                  {!compact && (
                    <td className="p-3">
                      {(agent.current_drawdown ?? 0) >= 0.1 ? (
                        <span className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs flex items-center gap-1 w-fit">
                          <TrendingDown className="w-3 h-3" />
                          Drawdown
                        </span>
                      ) : agent.sharpe_ratio >= 1.5 ? (
                        <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs flex items-center gap-1 w-fit">
                          <TrendingUp className="w-3 h-3" />
                          Strong
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 bg-slate-500/20 text-gray-400 rounded text-xs">
                          Active
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Summary Footer */}
      {agents.length > 0 && (
        <div className="p-3 border-t border-slate-700/50 bg-slate-800/30 flex items-center justify-between text-sm">
          <div className="flex items-center gap-4 text-gray-400">
            <span>Avg Sharpe: <span className={getSharpeColor(agents.reduce((s, a) => s + a.sharpe_ratio, 0) / agents.length)}>
              {formatSharpe(agents.reduce((s, a) => s + a.sharpe_ratio, 0) / agents.length)}
            </span></span>
            <span>Total P&L: <span className={getPnlColor(agents.reduce((s, a) => s + a.total_pnl, 0))}>
              {formatCurrency(agents.reduce((s, a) => s + a.total_pnl, 0))}
            </span></span>
          </div>
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-yellow-400" />
            <span className="text-gray-400">
              {agents.filter(a => a.max_drawdown >= 0.2).length} agents in high risk
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
