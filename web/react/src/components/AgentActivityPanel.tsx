import { useMemo } from 'react';
import { Bot, Brain, Shield, TrendingUp, AlertTriangle, CheckCircle, Clock } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface AgentActivity {
  agent_id: string;
  agent_name?: string;
  status: string;
  last_action?: string;
  last_action_time?: string;
  tasks_completed: number;
  current_task?: string;
  asset?: string;
  active_markets?: number;
  win_rate?: number;
}

const AGENT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  analyst: Brain,
  risk: Shield,
  strategy: TrendingUp,
  default: Bot
};

const getAgentIcon = (agentName: string) => {
  if (agentName.includes('analyst')) return AGENT_ICONS.analyst;
  if (agentName.includes('risk')) return AGENT_ICONS.risk;
  if (agentName.includes('strategy')) return AGENT_ICONS.strategy;
  return AGENT_ICONS.default;
};

export default function AgentActivityPanel() {
  const { data, loading } = useApiData<{ agents: AgentActivity[]; active_agents: number; total_tasks_1h: number }>(
    API_ENDPOINTS.OPERATOR_AGENT_ACTIVITY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const agents = useMemo(() => data?.agents ?? [], [data]);

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-slate-700 rounded w-1/3"></div>
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-16 bg-slate-700 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  const activeCount = data?.active_agents ?? agents.filter(a => a.status === 'running' || a.status === 'active').length;
  const totalTasks = data?.total_tasks_1h ?? agents.reduce((sum, a) => sum + a.tasks_completed, 0);

  return (
    <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">Agent Activity</h2>
          <p className="text-sm text-slate-400">
            {activeCount} of {agents.length} agents active
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-blue-400">{totalTasks}</div>
          <div className="text-xs text-slate-500">Total Cycles</div>
        </div>
      </div>

      <div className="space-y-3">
        {agents.map((agent) => {
          const displayName = agent.agent_name || agent.agent_id;
          const Icon = getAgentIcon(displayName);
          const isActive = agent.status === 'running' || agent.status === 'active';
          const isError = agent.status === 'error';
          const statusColor = isActive ? 'text-emerald-400' : isError ? 'text-rose-400' : 'text-slate-500';
          const StatusIcon = isActive ? CheckCircle : isError ? AlertTriangle : Clock;

          return (
            <div
              key={agent.agent_id}
              className="p-3 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
            >
              <div className="flex items-start gap-3">
                <div className={`p-2 rounded-lg bg-slate-700/50 ${statusColor}`}>
                  <Icon className="w-4 h-4" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      {displayName}
                    </span>
                    <StatusIcon className={`w-3 h-3 ${statusColor} shrink-0`} />
                    {agent.asset && (
                      <span className="text-[10px] text-orange-400 bg-orange-400/10 px-1.5 py-0.5 rounded shrink-0">
                        {agent.asset.toUpperCase()}
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-slate-500">
                    {typeof agent.active_markets === 'number'
                      ? `${agent.active_markets} markets`
                      : agent.current_task || agent.last_action || '—'}
                    {typeof agent.win_rate === 'number' && agent.win_rate > 0 && (
                      <span className="ml-2 text-emerald-500">{agent.win_rate.toFixed(1)}% win</span>
                    )}
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="text-sm font-semibold text-slate-300">
                    {agent.tasks_completed}
                  </div>
                  <div className="text-xs text-slate-500">cycles</div>
                </div>
              </div>
            </div>
          );
        })}
        {agents.length === 0 && !loading && (
          <div className="text-center py-6 text-slate-500 text-sm">
            No agents running — start the Kalshi grid from Overview
          </div>
        )}
      </div>
    </div>
  );
}
