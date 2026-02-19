/**
 * AgentStatusPanel - Real-time agent status and metrics panel.
 * 
 * Displays agents with:
 * - Online/degraded/offline status based on heartbeat
 * - Current Sharpe ratio and max drawdown
 * - Last heartbeat timestamp
 * - Live metrics from WebSocket stream
 */

import { useState, useMemo } from 'react';
import type { RawAgentHeartbeat } from '../types/api';
import { 
  Bot, 
  Activity,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Shield,
  Clock
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface AgentStatus {
  agent_id: string;
  role: string;
  status: 'online' | 'degraded' | 'offline';
  last_heartbeat: number;
  sharpe_ratio: number;
  max_drawdown: number;
  current_drawdown: number;
  total_pnl: number;
  total_trades: number;
  win_rate: number;
  consensus_weight: number;
  prediction_accuracy: number;
}

interface AgentStatusPanelProps {
  compact?: boolean;
  showMetrics?: boolean;
  onAgentSelect?: (agentId: string) => void;
}

const ROLE_COLORS: Record<string, string> = {
  bull_analyst: 'border-green-500/50 bg-green-500/5',
  bear_analyst: 'border-red-500/50 bg-red-500/5',
  arbitrage: 'border-purple-500/50 bg-purple-500/5',
  sentiment: 'border-blue-500/50 bg-blue-500/5',
  technical: 'border-orange-500/50 bg-orange-500/5',
  fundamental: 'border-cyan-500/50 bg-cyan-500/5',
  risk_manager: 'border-yellow-500/50 bg-yellow-500/5',
  trader: 'border-pink-500/50 bg-pink-500/5',
  analyst: 'border-gray-500/50 bg-gray-500/5',
};

const ROLE_TEXT_COLORS: Record<string, string> = {
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

export default function AgentStatusPanel({
  showMetrics = true,
  onAgentSelect,
}: AgentStatusPanelProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ agents: RawAgentHeartbeat[] }>(
    API_ENDPOINTS.RISK_AGENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Agent status" error={fetchError} onRetry={refetch} />;
  }

  const agents: AgentStatus[] = useMemo(() => {
    const now = Date.now() / 1000;
    return (rawData?.agents ?? []).map((a: RawAgentHeartbeat) => {
      const timeSinceUpdate = now - (a.last_updated || 0);
      let status: 'online' | 'degraded' | 'offline' = 'online';
      if (timeSinceUpdate > 300) status = 'offline';
      else if (timeSinceUpdate > 60) status = 'degraded';
      return {
        agent_id: a.agent_id || '',
        role: a.role || 'analyst',
        status,
        last_heartbeat: a.last_updated || 0,
        sharpe_ratio: a.sharpe_ratio || 0,
        max_drawdown: a.max_drawdown || 0,
        current_drawdown: a.current_drawdown || 0,
        total_pnl: a.total_pnl || 0,
        total_trades: a.total_trades || 0,
        win_rate: a.win_rate || 0,
        consensus_weight: a.consensus_weight || 1,
        prediction_accuracy: a.prediction_accuracy || 0.5,
      };
    });
  }, [rawData]);

  const handleAgentClick = (agentId: string) => {
    setSelectedAgent(selectedAgent === agentId ? null : agentId);
    onAgentSelect?.(agentId);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'online':
        return <CheckCircle className="w-4 h-4 text-green-400" />;
      case 'degraded':
        return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
      case 'offline':
        return <XCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Activity className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online':
        return 'bg-green-500/20 text-green-400';
      case 'degraded':
        return 'bg-yellow-500/20 text-yellow-400';
      case 'offline':
        return 'bg-red-500/20 text-red-400';
      default:
        return 'bg-gray-500/20 text-gray-400';
    }
  };

  const formatTime = (ts: number) => {
    if (!ts) return 'Never';
    const now = Date.now() / 1000;
    const diff = now - ts;
    
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return new Date(ts * 1000).toLocaleTimeString();
  };

  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`;
  
  const formatCurrency = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}$${Math.abs(value).toFixed(2)}`;
  };

  const getSharpeColor = (sharpe: number) => {
    if (sharpe < 0) return 'text-red-400';
    if (sharpe < 1) return 'text-yellow-400';
    return 'text-green-400';
  };

  const getDrawdownColor = (dd: number) => {
    if (dd >= 0.2) return 'text-red-400';
    if (dd >= 0.1) return 'text-yellow-400';
    return 'text-green-400';
  };

  // Aggregate stats
  const onlineCount = agents.filter(a => a.status === 'online').length;
  const degradedCount = agents.filter(a => a.status === 'degraded').length;
  const offlineCount = agents.filter(a => a.status === 'offline').length;
  const avgSharpe = agents.length > 0 
    ? agents.reduce((s, a) => s + a.sharpe_ratio, 0) / agents.length 
    : 0;

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 p-4">
        <div className="animate-pulse space-y-3">
          <div className="h-6 bg-slate-700 rounded w-40"></div>
          <div className="space-y-2">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-16 bg-slate-700/50 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bot className="w-5 h-5 text-purple-400" />
          <h2 className="text-lg font-semibold text-white">Agent Status</h2>
        </div>

        <div className="flex items-center gap-3">
          {/* Status Summary */}
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 text-green-400">
              <CheckCircle className="w-3 h-3" />
              {onlineCount}
            </span>
            <span className="flex items-center gap-1 text-yellow-400">
              <AlertTriangle className="w-3 h-3" />
              {degradedCount}
            </span>
            <span className="flex items-center gap-1 text-red-400">
              <XCircle className="w-3 h-3" />
              {offlineCount}
            </span>
          </div>

          <button type="button"
            onClick={() => refetch()}
            className="p-1.5 hover:bg-slate-700/50 rounded transition-colors"
            title="Refresh agent status"
            aria-label="Refresh agent status"
          >
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>

      {/* Agent List */}
      <div className="divide-y divide-slate-700/30 max-h-[500px] overflow-y-auto">
        {agents.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <Bot className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No agents tracked</p>
            <p className="text-sm mt-1">Agents will appear here as they start trading</p>
          </div>
        ) : (
          agents.map(agent => (
            <div
              key={agent.agent_id}
              className={`p-3 hover:bg-slate-800/50 cursor-pointer transition-colors ${
                selectedAgent === agent.agent_id ? 'bg-slate-800/70' : ''
              } ${ROLE_COLORS[agent.role] || ROLE_COLORS.analyst}`}
              onClick={() => handleAgentClick(agent.agent_id)}
             role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => handleAgentClick(agent.agent_id))(); } }}>
              {/* Agent Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {getStatusIcon(agent.status)}
                  <span className="font-mono text-sm text-white">{agent.agent_id}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${getStatusColor(agent.status)}`}>
                    {agent.status}
                  </span>
                </div>
                <span className={`text-xs ${ROLE_TEXT_COLORS[agent.role] || 'text-gray-400'}`}>
                  {agent.role.replace('_', ' ')}
                </span>
              </div>

              {/* Metrics Row */}
              {showMetrics && (
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <span className="text-gray-500">Sharpe</span>
                    <p className={`font-medium ${getSharpeColor(agent.sharpe_ratio)}`}>
                      {agent.sharpe_ratio.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <span className="text-gray-500">Max DD</span>
                    <p className={`font-medium ${getDrawdownColor(agent.max_drawdown)}`}>
                      -{formatPercent(agent.max_drawdown)}
                    </p>
                  </div>
                  <div>
                    <span className="text-gray-500">P&L</span>
                    <p className={`font-medium ${agent.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatCurrency(agent.total_pnl)}
                    </p>
                  </div>
                  <div>
                    <span className="text-gray-500">Weight</span>
                    <p className="font-medium text-purple-400">
                      {agent.consensus_weight.toFixed(2)}x
                    </p>
                  </div>
                </div>
              )}

              {/* Expanded Details */}
              {selectedAgent === agent.agent_id && (
                <div className="mt-3 pt-3 border-t border-slate-700/30 space-y-2">
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <span className="text-gray-500">Win Rate</span>
                      <p className="font-medium text-gray-300">{formatPercent(agent.win_rate)}</p>
                    </div>
                    <div>
                      <span className="text-gray-500">Trades</span>
                      <p className="font-medium text-gray-300">{agent.total_trades}</p>
                    </div>
                    <div>
                      <span className="text-gray-500">Accuracy</span>
                      <p className="font-medium text-gray-300">{formatPercent(agent.prediction_accuracy)}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-gray-500">
                    <Clock className="w-3 h-3" />
                    Last seen: {formatTime(agent.last_heartbeat)}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      {agents.length > 0 && (
        <div className="p-3 border-t border-slate-700/50 bg-slate-800/30 flex items-center justify-between text-xs text-gray-500">
          <span>
            Avg Sharpe: <span className={getSharpeColor(avgSharpe)}>{avgSharpe.toFixed(2)}</span>
          </span>
          <span className="flex items-center gap-1">
            <Shield className="w-3 h-3 text-yellow-400" />
            {agents.filter(a => a.max_drawdown >= 0.1).length} at risk
          </span>
        </div>
      )}
    </div>
  );
}
