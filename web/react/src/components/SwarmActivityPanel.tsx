/**
 * SwarmActivityPanel - Real-time Agent Activity Monitor
 * 
 * Displays live agent health metrics:
 * - Last heartbeat
 * - Last input/output
 * - Current mode
 * - Error counts
 * - Processing lag
 */

import { useState, useEffect } from 'react';
import { useMeridSocket } from '../hooks/useMeridSocket';

interface AgentMetric {
  agent_id: string;
  agent_type: string;
  status: string;
  last_heartbeat: number;
  messages_processed: number;
  error_count: number;
  input_lag_ms: number;
  p99_latency_ms: number;
}

interface SwarmStats {
  swarm: {
    opinions_per_minute: number;
    consensus_per_minute: number;
    trades_per_minute: number;
    consensus_success_rate: number;
    disagreement_rate: number;
    active_agents: number;
    total_agents: number;
    participation_rate: number;
    avg_pipeline_latency_ms: number;
  };
  agents: AgentMetric[];
  health_issues: Record<string, string>;
}

export function SwarmActivityPanel() {
  const [stats, setStats] = useState<SwarmStats | null>(null);
  const { socket } = useMeridSocket();

  useEffect(() => {
    if (!socket) return;

    // Subscribe to swarm telemetry updates
    const handleTelemetry = (data: SwarmStats) => {
      setStats(data);
    };

    socket.on('swarm_telemetry', handleTelemetry);

    // Request initial state
    socket.emit('get_swarm_telemetry');

    return () => {
      socket.off('swarm_telemetry', handleTelemetry);
    };
  }, [socket]);

  if (!stats) {
    return (
      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-lg font-semibold mb-2">Swarm Activity</h3>
        <p className="text-slate-400">Loading agent metrics...</p>
      </div>
    );
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'text-green-400';
      case 'degraded': return 'text-yellow-400';
      case 'error': return 'text-red-400';
      case 'offline': return 'text-slate-500';
      default: return 'text-slate-400';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy': return '●';
      case 'degraded': return '◐';
      case 'error': return '✖';
      case 'offline': return '○';
      default: return '?';
    }
  };

  const formatTimeSince = (timestamp: number) => {
    const seconds = Math.floor(Date.now() / 1000 - timestamp);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  };

  return (
    <div className="bg-slate-800 rounded-lg p-4">
      {/* Header with mode indicator */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Swarm Activity</h3>
        <div className="flex items-center gap-4">
          <div className="text-xs bg-blue-900/30 text-blue-300 px-2 py-1 rounded">
            PAPER / SIM ONLY
          </div>
          <div className="text-sm text-slate-300">
            {stats.swarm.active_agents}/{stats.swarm.total_agents} active
          </div>
        </div>
      </div>

      {/* Swarm-level metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="bg-slate-900/50 rounded p-3">
          <div className="text-xs text-slate-400">Opinions/min</div>
          <div className="text-xl font-bold text-green-400">
            {stats.swarm.opinions_per_minute.toFixed(1)}
          </div>
        </div>
        <div className="bg-slate-900/50 rounded p-3">
          <div className="text-xs text-slate-400">Consensus/min</div>
          <div className="text-xl font-bold text-blue-400">
            {stats.swarm.consensus_per_minute.toFixed(1)}
          </div>
        </div>
        <div className="bg-slate-900/50 rounded p-3">
          <div className="text-xs text-slate-400">Success Rate</div>
          <div className="text-xl font-bold text-emerald-400">
            {(stats.swarm.consensus_success_rate * 100).toFixed(0)}%
          </div>
        </div>
        <div className="bg-slate-900/50 rounded p-3">
          <div className="text-xs text-slate-400">Pipeline Latency</div>
          <div className="text-xl font-bold text-purple-400">
            {stats.swarm.avg_pipeline_latency_ms.toFixed(0)}ms
          </div>
        </div>
      </div>

      {/* Health issues alert */}
      {Object.keys(stats.health_issues).length > 0 && (
        <div className="bg-red-900/20 border border-red-700/30 rounded p-3 mb-4">
          <div className="text-sm font-semibold text-red-400 mb-2">
            ⚠ Health Issues Detected
          </div>
          <div className="text-xs space-y-1">
            {Object.entries(stats.health_issues).map(([agent_id, issue]) => (
              <div key={agent_id} className="text-red-300">
                {agent_id}: {issue}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400 border-b border-slate-700">
              <th className="pb-2">Agent</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">Heartbeat</th>
              <th className="pb-2">Messages</th>
              <th className="pb-2">Errors</th>
              <th className="pb-2">Lag</th>
              <th className="pb-2">P99</th>
            </tr>
          </thead>
          <tbody>
            {stats.agents.map((agent) => (
              <tr
                key={agent.agent_id}
                className="border-b border-slate-700/50 hover:bg-slate-700/30"
              >
                <td className="py-2 font-mono text-xs">{agent.agent_id}</td>
                <td className="py-2 text-slate-300">{agent.agent_type}</td>
                <td className={`py-2 ${getStatusColor(agent.status)}`}>
                  <span className="mr-1">{getStatusIcon(agent.status)}</span>
                  {agent.status}
                </td>
                <td className="py-2 text-slate-400">
                  {agent.last_heartbeat > 0 
                    ? formatTimeSince(agent.last_heartbeat)
                    : 'never'}
                </td>
                <td className="py-2 text-slate-300">
                  {agent.messages_processed.toLocaleString()}
                </td>
                <td className={`py-2 ${agent.error_count > 0 ? 'text-red-400' : 'text-slate-500'}`}>
                  {agent.error_count}
                </td>
                <td className={`py-2 ${agent.input_lag_ms > 1000 ? 'text-yellow-400' : 'text-slate-300'}`}>
                  {agent.input_lag_ms.toFixed(0)}ms
                </td>
                <td className="py-2 text-slate-300">
                  {agent.p99_latency_ms.toFixed(0)}ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {stats.agents.length === 0 && (
        <div className="text-center py-8 text-slate-400">
          No agents reporting yet...
        </div>
      )}
    </div>
  );
}
