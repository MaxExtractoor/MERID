import React, { useState, useCallback, useMemo } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface DecisionEvent {
  id: string;
  timestamp: string;
  agent: string;
  phase: 'RESEARCH' | 'STRATEGY' | 'RISK' | 'EXECUTION' | 'REVIEW';
  action: string;
  reasoning: string;
  inputs: Record<string, string>;
  outcome: 'approved' | 'rejected' | 'modified' | 'pending';
  confidence: number;
  durationMs: number;
  tradeId?: string;
}

interface DecisionAnalytics {
  total_decisions: number;
  approval_rate: number;
  avg_confidence: number;
  avg_duration_ms: number;
  phase_distribution: Record<string, number>;
  outcome_distribution: Record<string, number>;
  agent_performance: Record<string, {
    decisions: number;
    approval_rate: number;
    avg_confidence: number;
  }>;
  confidence_trend: Array<{
    timestamp: string;
    confidence: number;
  }>;
  performance_trend: Array<{
    timestamp: string;
    approval_rate: number;
  }>;
}

const ExplainabilityAnalytics: React.FC = () => {
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  const [selectedPhase, setSelectedPhase] = useState<string>('all');
  const [selectedOutcome, setSelectedOutcome] = useState<string>('all');
  const [timeRange, setTimeRange] = useState<'1h' | '24h' | '7d'>('24h');
  const [expandedDecisions, setExpandedDecisions] = useState<Set<string>>(new Set());

  // Fetch decision data
  const { data: decisions, loading: decisionsLoading, error: decisionsError, refetch: refetchDecisions } = useApiData<{
    decisions: DecisionEvent[];
    analytics: DecisionAnalytics;
  }>(
    API_ENDPOINTS.EXPLAINABILITY_DECISIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.EXPLAINABILITY }
  );

  // Filter decisions based on selected criteria
  const filteredDecisions = useMemo(() => {
    if (!decisions?.decisions) return [];
    
    return decisions.decisions.filter(decision => {
      if (selectedAgent !== 'all' && decision.agent !== selectedAgent) return false;
      if (selectedPhase !== 'all' && decision.phase !== selectedPhase) return false;
      if (selectedOutcome !== 'all' && decision.outcome !== selectedOutcome) return false;
      return true;
    });
  }, [decisions?.decisions, selectedAgent, selectedPhase, selectedOutcome]);

  // Get unique agents, phases, and outcomes for filters
  const filterOptions = useMemo(() => {
    if (!decisions?.decisions) return { agents: [], phases: [], outcomes: [] };
    
    const agents = [...new Set(decisions.decisions.map(d => d.agent))];
    const phases = [...new Set(decisions.decisions.map(d => d.phase))];
    const outcomes = [...new Set(decisions.decisions.map(d => d.outcome))];
    
    return { agents, phases, outcomes };
  }, [decisions?.decisions]);

  const toggleDecisionExpansion = useCallback((decisionId: string) => {
    setExpandedDecisions(prev => {
      const newSet = new Set(prev);
      if (newSet.has(decisionId)) {
        newSet.delete(decisionId);
      } else {
        newSet.add(decisionId);
      }
      return newSet;
    });
  }, []);

  const getOutcomeColor = (outcome: string) => {
    switch (outcome) {
      case 'approved': return 'text-green-400';
      case 'rejected': return 'text-red-400';
      case 'modified': return 'text-amber-400';
      case 'pending': return 'text-slate-400';
      default: return 'text-slate-400';
    }
  };

  const getOutcomeIcon = (outcome: string) => {
    switch (outcome) {
      case 'approved': return 'checkCircle';
      case 'rejected': return 'xCircle';
      case 'modified': return 'alert';
      case 'pending': return 'clock';
      default: return 'helpCircle';
    }
  };

  const getPhaseColor = (phase: string) => {
    switch (phase) {
      case 'RESEARCH': return 'bg-blue-500/20 text-blue-400 border-blue-500';
      case 'STRATEGY': return 'bg-purple-500/20 text-purple-400 border-purple-500';
      case 'RISK': return 'bg-amber-500/20 text-amber-400 border-amber-500';
      case 'EXECUTION': return 'bg-green-500/20 text-green-400 border-green-500';
      case 'REVIEW': return 'bg-gray-500/20 text-gray-400 border-gray-500';
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500';
    }
  };

  if (decisionsLoading && !decisions) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-500">
          <Icon name="loading" size={20} className="w-5 h-5 animate-spin" />
          <span>Loading decision analytics...</span>
        </div>
      </div>
    );
  }

  if (decisionsError) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800/50 p-6">
        <div className="flex items-center gap-2 text-red-400">
          <Icon name="alert" size={20} className="w-5 h-5" />
          <span>Failed to load decision data</span>
        </div>
      </div>
    );
  }

  const analytics = decisions?.analytics;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="brain" size={20} className="w-5 h-5 text-violet-400" />
          <h2 className="text-lg font-bold text-white">Decision Analytics</h2>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Time Range Selector */}
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value as '1h' | '24h' | '7d')}
            className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
            title="Select time range"
          >
            <option value="1h">Last hour</option>
            <option value="24h">Last 24h</option>
            <option value="7d">Last 7 days</option>
          </select>
          
          <button
            onClick={() => refetchDecisions()}
            className="flex items-center gap-1.5 px-2 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
            title="Refresh data"
          >
            <Icon name="refresh" size={12} className="w-3 h-3" />
            Refresh
          </button>
        </div>
      </div>

      {/* Analytics Overview */}
      {analytics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total Decisions</div>
            <div className="text-lg font-bold text-white">{analytics.total_decisions}</div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Approval Rate</div>
            <div className="text-lg font-bold text-green-400">{(analytics.approval_rate * 100).toFixed(1)}%</div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Avg Confidence</div>
            <div className="text-lg font-bold text-blue-400">{(analytics.avg_confidence * 100).toFixed(1)}%</div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Avg Duration</div>
            <div className="text-lg font-bold text-amber-400">{(analytics.avg_duration_ms / 1000).toFixed(1)}s</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by agent"
        >
          <option value="all">All Agents</option>
          {filterOptions.agents.map(agent => (
            <option key={agent} value={agent}>{agent}</option>
          ))}
        </select>
        
        <select
          value={selectedPhase}
          onChange={(e) => setSelectedPhase(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by phase"
        >
          <option value="all">All Phases</option>
          {filterOptions.phases.map(phase => (
            <option key={phase} value={phase}>{phase}</option>
          ))}
        </select>
        
        <select
          value={selectedOutcome}
          onChange={(e) => setSelectedOutcome(e.target.value)}
          className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          title="Filter by outcome"
        >
          <option value="all">All Outcomes</option>
          {filterOptions.outcomes.map(outcome => (
            <option key={outcome} value={outcome}>{outcome}</option>
          ))}
        </select>
      </div>

      {/* Agent Performance */}
      {analytics?.agent_performance && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-300">Agent Performance</h3>
          <div className="grid gap-2">
            {Object.entries(analytics.agent_performance).map(([agent, perf]) => (
              <div key={agent} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-white">{agent}</span>
                  <span className="text-xs text-slate-400">{perf.decisions} decisions</span>
                </div>
                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <span className="text-slate-400">Approval Rate:</span>
                    <span className={`ml-2 font-medium ${perf.approval_rate > 0.8 ? 'text-green-400' : perf.approval_rate > 0.6 ? 'text-amber-400' : 'text-red-400'}`}>
                      {(perf.approval_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Avg Confidence:</span>
                    <span className={`ml-2 font-medium ${perf.avg_confidence > 0.8 ? 'text-green-400' : perf.avg_confidence > 0.6 ? 'text-amber-400' : 'text-red-400'}`}>
                      {(perf.avg_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Decision List */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-300">
          Decisions ({filteredDecisions.length})
        </h3>
        
        {filteredDecisions.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            No decisions match the selected filters
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {filteredDecisions.map((decision) => (
              <div
                key={decision.id}
                className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon 
                      name={getOutcomeIcon(decision.outcome)} 
                      size={16} 
                      className={`w-4 h-4 ${getOutcomeColor(decision.outcome)}`} 
                    />
                    <span className="text-sm text-white">{decision.action}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${getPhaseColor(decision.phase)}`}>
                      {decision.phase}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-slate-400">{decision.agent}</span>
                    <span className={`font-medium ${
                      decision.confidence >= 0.8 ? 'text-green-400' : 
                      decision.confidence >= 0.6 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {(decision.confidence * 100).toFixed(0)}%
                    </span>
                    <button
                      onClick={() => toggleDecisionExpansion(decision.id)}
                      className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
                      title="Toggle details"
                    >
                      <Icon 
                        name="chevronDown" 
                        size={12} 
                        className={`w-3 h-3 transition-transform ${
                          expandedDecisions.has(decision.id) ? 'rotate-180' : ''
                        }`} 
                      />
                    </button>
                  </div>
                </div>
                
                {/* Expanded Details */}
                {expandedDecisions.has(decision.id) && (
                  <div className="mt-3 pt-3 border-t border-slate-700/50 space-y-2">
                    <div className="bg-slate-900/50 rounded p-2">
                      <div className="text-xs font-medium text-gray-400 mb-1">Reasoning</div>
                      <div className="text-sm text-gray-300">{decision.reasoning}</div>
                    </div>
                    
                    <div className="bg-slate-900/50 rounded p-2">
                      <div className="text-xs font-medium text-gray-400 mb-1">Inputs</div>
                      <div className="grid grid-cols-2 gap-1">
                        {Object.entries(decision.inputs ?? {}).map(([k, v]) => (
                          <div key={k} className="flex items-center gap-2 text-xs">
                            <span className="text-gray-500">{k}:</span>
                            <span className="text-gray-300 font-mono">{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span>Duration: {decision.durationMs}ms</span>
                      <span>{new Date(decision.timestamp).toLocaleString()}</span>
                    </div>
                    
                    {decision.tradeId && (
                      <div className="text-xs text-slate-500">
                        Trade ID: <span className="font-mono text-slate-400">{decision.tradeId}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ExplainabilityAnalytics;
