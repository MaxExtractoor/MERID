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
        // Use fallback mock data
        setAgents([
            {
              agent_id: 'analyst-gemma-01',
              agent_name: 'Analyst Gemma',
              status: 'active',
              last_action: 'Analyzed BTC market trends',
              last_action_time: '2m ago',
              tasks_completed: 142,
              current_task: 'Processing ETH signals'
            },
            {
              agent_id: 'risk-01',
              agent_name: 'Risk Monitor',
              status: 'active',
              last_action: 'Updated exposure limits',
              last_action_time: '5m ago',
              tasks_completed: 89,
              current_task: 'Monitoring portfolio risk'
            },
            {
              agent_id: 'strategy-agent-01',
              agent_name: 'Strategy Agent',
              status: 'idle',
              last_action: 'Generated trading signals',
              last_action_time: '15m ago',
              tasks_completed: 67
            },
            {
              agent_id: 'analyst-llama-01',
              agent_name: 'Analyst Llama',
              status: 'active',
              last_action: 'Sentiment analysis complete',
              last_action_time: '1m ago',
              tasks_completed: 156,
              current_task: 'Analyzing news feeds'
            },
            {
              agent_id: 'skeptic-01',
              agent_name: 'Skeptic',
              status: 'active',
              last_action: 'Validated trade signals',
              last_action_time: '3m ago',
              tasks_completed: 98,
              current_task: 'Reviewing risk parameters'
            },
            {
              agent_id: 'synthesizer-01',
              agent_name: 'Synthesizer',
              status: 'idle',
              last_action: 'Aggregated agent insights',
              last_action_time: '8m ago',
              tasks_completed: 45
            },
            {
              agent_id: 'archivist-01',
              agent_name: 'Archivist',
              status: 'active',
              last_action: 'Logged system events',
              last_action_time: '30s ago',
              tasks_completed: 234,
              current_task: 'Archiving trade history'
            },
            {
              agent_id: 'meta-audit-01',
              agent_name: 'Meta Auditor',
              status: 'active',
              last_action: 'Performance audit complete',
              last_action_time: '10m ago',
              tasks_completed: 23,
              current_task: 'Monitoring agent health'
            }
          ]);
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
