import { useState } from 'react';
import { Network, Users, Zap, Brain, RefreshCw, AlertCircle, TrendingUp, Activity } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface SwarmAgent {
  id: string;
  name: string;
  role: string;
  status: 'active' | 'idle' | 'coordinating';
  tasks_completed: number;
  current_task?: string;
  connections: string[];
  confidence: number;
}

interface SwarmTask {
  id: string;
  title: string;
  type: 'analysis' | 'trading' | 'research' | 'coordination';
  status: 'pending' | 'in_progress' | 'completed';
  assigned_agents: string[];
  priority: 'high' | 'medium' | 'low';
  progress: number;
  created_at: string;
}

interface SwarmMetrics {
  total_agents: number;
  active_agents: number;
  coordinating_agents: number;
  tasks_in_progress: number;
  consensus_rate: number;
  avg_response_time: number;
}

interface SwarmPanelProps {
  className?: string;
}

export default function SwarmPanel({ className = '' }: SwarmPanelProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const { data: swarmData, loading, error, refetch } = useApiData<{
    agents: SwarmAgent[];
    tasks: SwarmTask[];
    metrics: SwarmMetrics;
  }>(
    API_ENDPOINTS.SWARM_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'bg-green-500';
      case 'coordinating': return 'bg-blue-500';
      case 'idle': return 'bg-gray-500';
      default: return 'bg-gray-500';
    }
  };

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'high': return 'text-red-400 bg-red-500/20';
      case 'medium': return 'text-yellow-400 bg-yellow-500/20';
      case 'low': return 'text-green-400 bg-green-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'analysis': return <Brain className="w-4 h-4" />;
      case 'trading': return <TrendingUp className="w-4 h-4" />;
      case 'research': return <Activity className="w-4 h-4" />;
      case 'coordination': return <Network className="w-4 h-4" />;
      default: return <Zap className="w-4 h-4" />;
    }
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading swarm intelligence...</span>
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
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Swarm Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Users className="w-4 h-4 text-blue-400" />
            <p className="text-xs text-gray-400">Total Agents</p>
          </div>
          <p className="text-2xl font-bold text-white">{swarmData?.metrics.total_agents}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-green-400" />
            <p className="text-xs text-gray-400">Active</p>
          </div>
          <p className="text-2xl font-bold text-green-400">{swarmData?.metrics.active_agents}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Network className="w-4 h-4 text-purple-400" />
            <p className="text-xs text-gray-400">Coordinating</p>
          </div>
          <p className="text-2xl font-bold text-purple-400">{swarmData?.metrics.coordinating_agents}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4 text-yellow-400" />
            <p className="text-xs text-gray-400">Tasks Active</p>
          </div>
          <p className="text-2xl font-bold text-white">{swarmData?.metrics.tasks_in_progress}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Brain className="w-4 h-4 text-cyan-400" />
            <p className="text-xs text-gray-400">Consensus</p>
          </div>
          <p className="text-2xl font-bold text-cyan-400">
            {((swarmData?.metrics.consensus_rate || 0) * 100).toFixed(0)}%
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <RefreshCw className="w-4 h-4 text-orange-400" />
            <p className="text-xs text-gray-400">Avg Response</p>
          </div>
          <p className="text-2xl font-bold text-white">{swarmData?.metrics.avg_response_time}s</p>
        </div>
      </div>

      {/* Agent Network Visualization */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Network className="w-6 h-6 text-purple-400" />
            <h3 className="text-lg font-bold text-white">Agent Network</h3>
          </div>
          <button type="button"
            onClick={() => refetch()}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh swarm data"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {swarmData?.agents.map(agent => (
            <div
              key={agent.id}
              onClick={() => setSelectedAgent(agent.id === selectedAgent ? null : agent.id)}
              className={`p-4 rounded-lg border transition-all cursor-pointer ${
                selectedAgent === agent.id
                  ? 'bg-blue-500/20 border-blue-500'
                  : 'bg-slate-700/30 border-slate-700/50 hover:border-slate-600'
              }`}
             role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setSelectedAgent(agent.id === selectedAgent ? null : agent.id))(); } }}>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-3 h-3 rounded-full ${getStatusColor(agent.status)}`} />
                  <p className="text-white font-bold">{agent.name}</p>
                </div>
                <span className="text-xs text-gray-400">{agent.tasks_completed} tasks</span>
              </div>

              <p className="text-sm text-gray-400 mb-2">{agent.role}</p>

              {agent.current_task && (
                <div className="mb-3 p-2 bg-slate-900/50 rounded text-xs text-gray-300">
                  {agent.current_task}
                </div>
              )}

              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1">
                  <Network className="w-3 h-3 text-purple-400" />
                  <span className="text-gray-400">{agent.connections.length} connections</span>
                </div>
                <div className="flex items-center gap-1">
                  <Brain className="w-3 h-3 text-cyan-400" />
                  <span className="text-cyan-400">{(agent.confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Swarm Tasks */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Zap className="w-6 h-6 text-yellow-400" />
          <h3 className="text-lg font-bold text-white">Coordinated Tasks</h3>
        </div>

        <div className="space-y-4">
          {swarmData?.tasks.map(task => (
            <div key={task.id} className="p-4 bg-slate-700/30 rounded-lg border border-slate-700/50">
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="p-2 bg-slate-800 rounded">
                      {getTypeIcon(task.type)}
                    </div>
                    <div>
                      <h4 className="text-white font-medium">{task.title}</h4>
                      <p className="text-xs text-gray-400 capitalize">{task.type}</p>
                    </div>
                  </div>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${getPriorityColor(task.priority)}`}>
                  {task.priority}
                </span>
              </div>

              <div className="mb-3">
                <div className="flex items-center justify-between text-sm mb-1">
                  <span className="text-gray-400">Progress</span>
                  <span className="text-white font-medium">{task.progress}%</span>
                </div>
                <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-500"
                    style={{ width: `${task.progress}%` }}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <Users className="w-3 h-3 text-gray-400" />
                  <span className="text-gray-400">{task.assigned_agents.length} agents assigned</span>
                </div>
                <span className={`px-2 py-1 rounded text-xs ${
                  task.status === 'in_progress' ? 'bg-blue-500/20 text-blue-400' :
                  task.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {task.status.replace('_', ' ')}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
