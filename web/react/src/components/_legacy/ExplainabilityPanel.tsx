import { useState } from 'react';
import { Brain, AlertTriangle, CheckCircle, XCircle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface DecisionFactor {
  name: string;
  weight: number;
  value: number;
  impact: 'positive' | 'negative' | 'neutral';
  explanation: string;
}

interface AlternativeOption {
  action: string;
  confidence: number;
  expected_outcome: string;
  reason_not_chosen: string;
}

interface DataSource {
  name: string;
  type: string;
  reliability: number;
  timestamp: string;
}

interface ExplainabilityDecision {
  id: string;
  agent_name: string;
  decision: string;
  action_taken: string;
  timestamp: string;
  confidence: number;
  outcome: 'success' | 'failure' | 'pending';
  reasoning: string;
  factors: DecisionFactor[];
  alternatives: AlternativeOption[];
  data_sources: DataSource[];
  execution_time_ms: number;
}

interface ExplainabilityPanelProps {
  className?: string;
}

export default function ExplainabilityPanel({ className = '' }: ExplainabilityPanelProps) {
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string>('all');

  const endpoint = selectedAgent === 'all'
    ? API_ENDPOINTS.EXPLAINABILITY_DECISIONS
    : `${API_ENDPOINTS.EXPLAINABILITY_DECISIONS}?agent=${selectedAgent}`;
  const { data: rawData, loading, error, refetch } = useApiData<{ decisions: ExplainabilityDecision[] }>(
    endpoint,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.EXPLAINABILITY },
  );
  const decisions = rawData?.decisions ?? [];

  const getOutcomeIcon = (outcome: string) => {
    switch (outcome) {
      case 'success': return <CheckCircle className="w-5 h-5 text-green-400" />;
      case 'failure': return <XCircle className="w-5 h-5 text-red-400" />;
      case 'pending': return <RefreshCw className="w-5 h-5 text-yellow-400 animate-spin" />;
      default: return null;
    }
  };

  const getImpactColor = (impact: string) => {
    switch (impact) {
      case 'positive': return 'text-green-400';
      case 'negative': return 'text-red-400';
      case 'neutral': return 'text-gray-400';
      default: return 'text-gray-400';
    }
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  const agents = ['all', ...Array.from(new Set(decisions.map(d => d.agent_name)))];

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading decision explanations...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-6 h-6 text-purple-400" />
          <div>
            <h2 className="text-lg font-bold text-white">Agent Decision Explainability</h2>
            <p className="text-sm text-gray-400">Understand why agents made specific decisions</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select aria-label="Selected Agent"
            id="explainability-agent-filter"
            name="agentFilter"
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
            title="Filter by agent"
          >
            {agents.map((agent, idx) => (
              <option key={`${agent}-${idx}`} value={agent}>
                {agent === 'all' ? 'All Agents' : agent}
              </option>
            ))}
          </select>
          <button type="button"
            onClick={() => refetch()}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh decisions"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Decisions List */}
      <div className="space-y-4">
        {decisions.map(decision => (
          <div key={decision.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 overflow-hidden">
            {/* Decision Header */}
            <div
              className="p-4 cursor-pointer hover:bg-slate-700/30 transition-colors"
              onClick={() => setExpandedDecision(expandedDecision === decision.id ? null : decision.id)}
             role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpandedDecision(expandedDecision === decision.id ? null : decision.id))(); } }}>
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    {getOutcomeIcon(decision.outcome)}
                    <div>
                      <h3 className="text-white font-bold">{decision.decision}</h3>
                      <p className="text-sm text-gray-400">{decision.agent_name} • {formatTimestamp(decision.timestamp)}</p>
                    </div>
                  </div>
                  <p className="text-sm text-gray-300">{decision.action_taken}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className="text-sm text-gray-400">Confidence</p>
                    <p className="text-lg font-bold text-white">{(decision.confidence * 100).toFixed(0)}%</p>
                  </div>
                  {expandedDecision === decision.id ? (
                    <ChevronUp className="w-5 h-5 text-gray-400" />
                  ) : (
                    <ChevronDown className="w-5 h-5 text-gray-400" />
                  )}
                </div>
              </div>

              {/* Confidence Bar */}
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full ${
                    decision.confidence >= 0.8 ? 'bg-green-500' :
                    decision.confidence >= 0.6 ? 'bg-yellow-500' : 'bg-red-500'
                  }`}
                  style={{ width: `${decision.confidence * 100}%` }}
                />
              </div>
            </div>

            {/* Expanded Details */}
            {expandedDecision === decision.id && (
              <div className="border-t border-slate-700/50 p-4 space-y-6">
                {/* Reasoning */}
                <div>
                  <h4 className="text-white font-semibold mb-2 flex items-center gap-2">
                    <Brain className="w-4 h-4 text-purple-400" />
                    Reasoning
                  </h4>
                  <p className="text-gray-300 text-sm bg-slate-900/50 p-3 rounded">{decision.reasoning}</p>
                </div>

                {/* Decision Factors */}
                <div>
                  <h4 className="text-white font-semibold mb-3">Decision Factors</h4>
                  <div className="space-y-3">
                    {(decision.factors || []).map((factor, idx) => (
                      <div key={idx} className="bg-slate-900/50 p-3 rounded">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-white font-medium">{factor.name}</span>
                          <div className="flex items-center gap-3">
                            <span className="text-sm text-gray-400">Weight: {(factor.weight * 100).toFixed(0)}%</span>
                            <span className={`text-sm font-medium ${getImpactColor(factor.impact)}`}>
                              {factor.impact}
                            </span>
                          </div>
                        </div>
                        <div className="mb-2">
                          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                            <div
                              className={`h-full ${
                                factor.impact === 'positive' ? 'bg-green-500' :
                                factor.impact === 'negative' ? 'bg-red-500' : 'bg-gray-500'
                              }`}
                              style={{ width: `${factor.value * 100}%` }}
                            />
                          </div>
                        </div>
                        <p className="text-sm text-gray-400">{factor.explanation}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Alternative Options */}
                <div>
                  <h4 className="text-white font-semibold mb-3">Alternative Options Considered</h4>
                  <div className="space-y-2">
                    {(decision.alternatives || []).map((alt, idx) => (
                      <div key={idx} className="bg-slate-900/50 p-3 rounded">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-white font-medium">{alt.action}</span>
                          <span className="text-sm text-gray-400">Confidence: {(alt.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <p className="text-sm text-gray-300 mb-1">{alt.expected_outcome}</p>
                        <p className="text-xs text-red-400">Why not chosen: {alt.reason_not_chosen}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Data Sources */}
                <div>
                  <h4 className="text-white font-semibold mb-3">Data Sources Used</h4>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {(decision.data_sources || []).map((source, idx) => (
                      <div key={idx} className="bg-slate-900/50 p-3 rounded">
                        <p className="text-white font-medium text-sm">{source.name}</p>
                        <p className="text-xs text-gray-400 mb-2">{source.type}</p>
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-gray-500">{formatTimestamp(source.timestamp)}</span>
                          <span className={`text-xs font-medium ${
                            source.reliability >= 0.9 ? 'text-green-400' : 'text-yellow-400'
                          }`}>
                            {(source.reliability * 100).toFixed(0)}% reliable
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Execution Time */}
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-400">Execution Time:</span>
                  <span className="text-white font-medium">{decision.execution_time_ms}ms</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
