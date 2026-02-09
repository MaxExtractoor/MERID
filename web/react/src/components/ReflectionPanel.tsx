import { useState, useEffect } from 'react';
import { Brain, TrendingUp, TrendingDown, Target, Lightbulb, RefreshCw, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';

interface AgentStats {
  agent_id: string;
  total_decisions: number;
  accuracy: number;
  avg_reality_gap: number;
  recent_learnings: number;
}

interface Reflection {
  agent_id: string;
  energy_id: string;
  decision: string;
  confidence: number;
  reasoning: string;
  outcome?: string;
  reality_gap?: number;
  timestamp: string;
}

interface ReflectionSummary {
  total_reflections: number;
  active_agents: number;
  agents: AgentStats[];
}

interface ReflectionPanelProps {
  className?: string;
}

export default function ReflectionPanel({ className = '' }: ReflectionPanelProps) {
  const [summary, setSummary] = useState<ReflectionSummary | null>(null);
  const [recentReflections, setRecentReflections] = useState<Reflection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  useEffect(() => {
    fetchReflectionData();
    const interval = setInterval(fetchReflectionData, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchReflectionData = async () => {
    try {
      const [summaryRes, reflectionsRes] = await Promise.all([
        fetch('/api/v1/reflection/summary'),
        fetch('/api/v1/reflection/reflections?limit=20')
      ]);

      if (summaryRes.ok) {
        const summaryData = await summaryRes.json();
        setSummary(summaryData);
      }

      if (reflectionsRes.ok) {
        const reflectionsData = await reflectionsRes.json();
        setRecentReflections(reflectionsData.reflections || []);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch reflection data');
      setSummary(null);
      setRecentReflections([]);
    } finally {
      setLoading(false);
    }
  };

  const getAccuracyColor = (accuracy: number) => {
    if (accuracy >= 80) return 'text-green-400';
    if (accuracy >= 60) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getGapColor = (gap: number) => {
    if (gap <= 10) return 'text-green-400';
    if (gap <= 20) return 'text-yellow-400';
    return 'text-red-400';
  };

  const formatAgentName = (id: string) => {
    return id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  };

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return 'Just now';
    if (hours === 1) return '1 hour ago';
    if (hours < 24) return `${hours} hours ago`;
    return `${Math.floor(hours / 24)} days ago`;
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-purple-500" />
          <span className="ml-2 text-gray-400">Loading reflection data...</span>
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
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Brain className="w-4 h-4 text-purple-400" />
            <p className="text-xs text-gray-400">Total Reflections</p>
          </div>
          <p className="text-2xl font-bold text-white">{summary?.total_reflections || 0}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4 text-blue-400" />
            <p className="text-xs text-gray-400">Active Agents</p>
          </div>
          <p className="text-2xl font-bold text-blue-400">{summary?.active_agents || 0}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4 text-green-400" />
            <p className="text-xs text-gray-400">Avg Accuracy</p>
          </div>
          <p className="text-2xl font-bold text-green-400">
            {summary?.agents?.length 
              ? (summary.agents.reduce((acc, a) => acc + a.accuracy, 0) / summary.agents.length).toFixed(1)
              : 0}%
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Lightbulb className="w-4 h-4 text-yellow-400" />
            <p className="text-xs text-gray-400">New Learnings</p>
          </div>
          <p className="text-2xl font-bold text-yellow-400">
            {summary?.agents?.reduce((acc, a) => acc + a.recent_learnings, 0) || 0}
          </p>
        </div>
      </div>

      {/* Agent Performance Table */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-purple-400" />
            <h3 className="text-lg font-bold text-white">Agent Learning Performance</h3>
          </div>
          <button
            onClick={fetchReflectionData}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh data"
          >
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-slate-700">
                <th className="pb-3 font-medium">Agent</th>
                <th className="pb-3 font-medium text-center">Decisions</th>
                <th className="pb-3 font-medium text-center">Accuracy</th>
                <th className="pb-3 font-medium text-center">Reality Gap</th>
                <th className="pb-3 font-medium text-center">Learnings</th>
              </tr>
            </thead>
            <tbody>
              {summary?.agents?.map((agent) => (
                <tr 
                  key={agent.agent_id} 
                  className="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer"
                  onClick={() => setExpandedAgent(expandedAgent === agent.agent_id ? null : agent.agent_id)}
                >
                  <td className="py-4">
                    <div className="flex items-center gap-2">
                      {expandedAgent === agent.agent_id ? (
                        <ChevronUp className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      )}
                      <span className="text-white font-medium">{formatAgentName(agent.agent_id)}</span>
                    </div>
                  </td>
                  <td className="py-4 text-center text-white">{agent.total_decisions}</td>
                  <td className="py-4 text-center">
                    <span className={`font-bold ${getAccuracyColor(agent.accuracy)}`}>
                      {agent.accuracy.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-4 text-center">
                    <span className={`${getGapColor(agent.avg_reality_gap)}`}>
                      {agent.avg_reality_gap.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-4 text-center">
                    <span className="px-2 py-1 bg-yellow-500/20 text-yellow-400 rounded text-sm">
                      {agent.recent_learnings}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Reflections */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Lightbulb className="w-6 h-6 text-yellow-400" />
          <h3 className="text-lg font-bold text-white">Recent Reflections</h3>
        </div>

        <div className="space-y-4">
          {recentReflections.slice(0, 5).map((reflection, idx) => (
            <div key={idx} className="p-4 bg-slate-700/30 rounded-lg border border-slate-700/50">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                    reflection.decision === 'BULLISH' ? 'bg-green-500/20 text-green-400' :
                    reflection.decision === 'BEARISH' ? 'bg-red-500/20 text-red-400' :
                    'bg-gray-500/20 text-gray-400'
                  }`}>
                    {reflection.decision}
                  </div>
                  <span className="text-white font-medium">{formatAgentName(reflection.agent_id)}</span>
                </div>
                <div className="flex items-center gap-2">
                  {reflection.outcome && (
                    <span className={`px-2 py-1 rounded text-xs ${
                      reflection.outcome === 'CORRECT' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {reflection.outcome === 'CORRECT' ? (
                        <TrendingUp className="w-3 h-3 inline mr-1" />
                      ) : (
                        <TrendingDown className="w-3 h-3 inline mr-1" />
                      )}
                      {reflection.outcome}
                    </span>
                  )}
                  <span className="text-xs text-gray-400">{formatTimeAgo(reflection.timestamp)}</span>
                </div>
              </div>

              <p className="text-sm text-gray-300 mb-2">{reflection.reasoning}</p>

              <div className="flex items-center gap-4 text-xs">
                <div className="flex items-center gap-1">
                  <Target className="w-3 h-3 text-blue-400" />
                  <span className="text-gray-400">Confidence:</span>
                  <span className="text-blue-400 font-medium">{(reflection.confidence * 100).toFixed(0)}%</span>
                </div>
                {reflection.reality_gap !== undefined && (
                  <div className="flex items-center gap-1">
                    <Brain className="w-3 h-3 text-purple-400" />
                    <span className="text-gray-400">Reality Gap:</span>
                    <span className={getGapColor(reflection.reality_gap * 100)}>
                      {(reflection.reality_gap * 100).toFixed(1)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
