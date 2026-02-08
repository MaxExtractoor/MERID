import { useState, useEffect } from 'react';
import { Bot, Brain, Shield, TrendingUp, AlertTriangle, CheckCircle, Clock } from 'lucide-react';
import { api } from '../services/api';

interface AgentActivity {
  agent_id: string;
  agent_name: string;
  status: 'active' | 'idle' | 'error';
  last_action: string;
  last_action_time: string;
  tasks_completed: number;
  current_task?: string;
}

const AGENT_ICONS: Record<string, any> = {
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
  const [agents, setAgents] = useState<AgentActivity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchAgentActivity() {
      try {
        const data = await api.getAgentActivity();
        setAgents((data as any).agents || []);
      } catch (e) {
        console.error('Failed to fetch agent activity:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchAgentActivity();
    const interval = setInterval(fetchAgentActivity, 15000); // Update every 15s
    return () => clearInterval(interval);
  }, []);

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

  const activeCount = agents.filter(a => a.status === 'active').length;
  const totalTasks = agents.reduce((sum, a) => sum + a.tasks_completed, 0);

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
          <div className="text-xs text-slate-500">Total Tasks</div>
        </div>
      </div>

      <div className="space-y-3">
        {agents.map((agent) => {
          const Icon = getAgentIcon(agent.agent_name);
          const statusColor = 
            agent.status === 'active' ? 'text-emerald-400' :
            agent.status === 'error' ? 'text-rose-400' :
            'text-slate-500';
          
          const StatusIcon = 
            agent.status === 'active' ? CheckCircle :
            agent.status === 'error' ? AlertTriangle :
            Clock;

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
                    <span className="text-sm font-medium text-slate-200">
                      {agent.agent_name}
                    </span>
                    <StatusIcon className={`w-3 h-3 ${statusColor}`} />
                  </div>
                  
                  {agent.current_task && (
                    <div className="text-xs text-blue-400 mb-1">
                      → {agent.current_task}
                    </div>
                  )}
                  
                  <div className="text-xs text-slate-500">
                    {agent.last_action} • {agent.last_action_time}
                  </div>
                </div>
                
                <div className="text-right shrink-0">
                  <div className="text-sm font-semibold text-slate-300">
                    {agent.tasks_completed}
                  </div>
                  <div className="text-xs text-slate-500">tasks</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
