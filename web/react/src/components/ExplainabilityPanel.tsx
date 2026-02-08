import { useState, useEffect } from 'react';
import { Brain, AlertTriangle, CheckCircle, XCircle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';

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

interface AgentDecision {
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
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string>('all');

  useEffect(() => {
    fetchDecisions();
    const interval = setInterval(fetchDecisions, 20000);
    return () => clearInterval(interval);
  }, [selectedAgent]);

  const fetchDecisions = async () => {
    try {
      const url = selectedAgent === 'all' 
        ? '/api/v1/explainability/decisions'
        : `/api/v1/explainability/decisions?agent=${selectedAgent}`;
      
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setDecisions(data.decisions || []);
        setError(null);
      } else {
        throw new Error('Failed to fetch decisions');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setDecisions([
        {
          id: 'dec-1',
          agent_name: 'Analyst Gemma',
          decision: 'BUY BTC-USD',
          action_taken: 'Executed market buy order for 0.5 BTC at $105,042',
          timestamp: new Date(Date.now() - 1800000).toISOString(),
          confidence: 0.87,
          outcome: 'success',
          reasoning: 'Technical indicators show strong bullish momentum with RSI at 65, MACD crossover confirmed, and volume increasing. Price broke above resistance at $104,800 with strong support at $103,500.',
          factors: [
            {
              name: 'Technical Indicators',
              weight: 0.35,
              value: 0.82,
              impact: 'positive',
              explanation: 'RSI at 65 (bullish), MACD golden cross, increasing volume',
            },
            {
              name: 'Market Sentiment',
              weight: 0.25,
              value: 0.75,
              impact: 'positive',
              explanation: 'Social sentiment positive, fear & greed index at 68 (greed)',
            },
            {
              name: 'Price Action',
              weight: 0.20,
              value: 0.90,
              impact: 'positive',
              explanation: 'Broke resistance at $104,800, strong upward trend',
            },
            {
              name: 'Risk Assessment',
              weight: 0.15,
              value: 0.65,
              impact: 'neutral',
              explanation: 'Portfolio exposure within limits, stop loss at $103,000',
            },
            {
              name: 'Volatility',
              weight: 0.05,
              value: 0.45,
              impact: 'negative',
              explanation: 'Higher than average volatility (18% vs 12% normal)',
            },
          ],
          alternatives: [
            {
              action: 'WAIT',
              confidence: 0.62,
              expected_outcome: 'Wait for pullback to $104,000 support',
              reason_not_chosen: 'Risk of missing breakout momentum, current entry acceptable',
            },
            {
              action: 'BUY_LIMIT',
              confidence: 0.58,
              expected_outcome: 'Set limit order at $104,500',
              reason_not_chosen: 'Price unlikely to retrace, momentum too strong',
            },
          ],
          data_sources: [
            { name: 'Coinbase Advanced', type: 'Price Feed', reliability: 0.98, timestamp: new Date(Date.now() - 60000).toISOString() },
            { name: 'TradingView', type: 'Technical Analysis', reliability: 0.92, timestamp: new Date(Date.now() - 120000).toISOString() },
            { name: 'Sentiment Aggregator', type: 'Social Data', reliability: 0.85, timestamp: new Date(Date.now() - 180000).toISOString() },
          ],
          execution_time_ms: 342,
        },
        {
          id: 'dec-2',
          agent_name: 'Skeptic',
          decision: 'REJECT TRADE',
          action_taken: 'Blocked proposed ETH trade due to high risk',
          timestamp: new Date(Date.now() - 3600000).toISOString(),
          confidence: 0.91,
          outcome: 'success',
          reasoning: 'Proposed ETH trade exceeded risk parameters. Portfolio already has 28% ETH exposure (limit: 30%), and correlation with BTC position too high (0.85). Market volatility elevated.',
          factors: [
            {
              name: 'Portfolio Risk',
              weight: 0.40,
              value: 0.88,
              impact: 'negative',
              explanation: 'ETH exposure at 28%, near 30% limit. Adding position risky.',
            },
            {
              name: 'Correlation Risk',
              weight: 0.30,
              value: 0.85,
              impact: 'negative',
              explanation: 'BTC-ETH correlation at 0.85, too high for diversification',
            },
            {
              name: 'Market Volatility',
              weight: 0.20,
              value: 0.72,
              impact: 'negative',
              explanation: 'VIX elevated at 24, above comfort threshold of 20',
            },
            {
              name: 'Profit Potential',
              weight: 0.10,
              value: 0.65,
              impact: 'positive',
              explanation: 'Expected return of 8% over 7 days',
            },
          ],
          alternatives: [
            {
              action: 'REDUCE_SIZE',
              confidence: 0.73,
              expected_outcome: 'Trade 50% of proposed size',
              reason_not_chosen: 'Still violates correlation limits, not worth the risk',
            },
            {
              action: 'WAIT_FOR_REBALANCE',
              confidence: 0.68,
              expected_outcome: 'Wait until BTC position closes',
              reason_not_chosen: 'Opportunity may pass, but safer approach',
            },
          ],
          data_sources: [
            { name: 'Portfolio Manager', type: 'Internal', reliability: 0.99, timestamp: new Date(Date.now() - 30000).toISOString() },
            { name: 'Risk Calculator', type: 'Internal', reliability: 0.97, timestamp: new Date(Date.now() - 45000).toISOString() },
            { name: 'CBOE VIX', type: 'Market Data', reliability: 0.95, timestamp: new Date(Date.now() - 90000).toISOString() },
          ],
          execution_time_ms: 156,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

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
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
            title="Filter by agent"
          >
            {agents.map(agent => (
              <option key={agent} value={agent}>
                {agent === 'all' ? 'All Agents' : agent}
              </option>
            ))}
          </select>
          <button
            onClick={fetchDecisions}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh decisions"
          >
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
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
            >
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
