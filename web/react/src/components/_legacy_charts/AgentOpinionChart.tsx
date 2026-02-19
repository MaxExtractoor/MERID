/**
 * MERID Agent Opinion Chart - Section 12: UI, Graphs, Charts, and Heatmaps
 * 
 * Real-time visualization of agent opinions from agent.opinions.* topics.
 * Shows Bull/Bear/Risk agent scores over time per symbol.
 */

import { useState, useMemo } from 'react';
import { TrendingUp, TrendingDown, Minus, Users, RefreshCw } from 'lucide-react';

interface AgentOpinion {
  opinion_id: string;
  agent_id: string;
  agent_role: string;
  symbol: string;
  stance: 'strong_bull' | 'bull' | 'neutral' | 'bear' | 'strong_bear';
  score: number;
  confidence: number;
  timestamp: number;
  rationale?: string;
}

interface AgentOpinionChartProps {
  symbol: string;
  opinions: AgentOpinion[];
  maxItems?: number;
  showRationale?: boolean;
  onRefresh?: () => void;
}

const stanceColors: Record<string, string> = {
  strong_bull: 'text-green-400 bg-green-400/20',
  bull: 'text-green-300 bg-green-300/20',
  neutral: 'text-gray-400 bg-gray-400/20',
  bear: 'text-red-300 bg-red-300/20',
  strong_bear: 'text-red-400 bg-red-400/20',
};

const roleColors: Record<string, string> = {
  bull_analyst: 'border-green-500',
  bear_analyst: 'border-red-500',
  risk_manager: 'border-yellow-500',
  sentiment_analyst: 'border-purple-500',
  technical_analyst: 'border-blue-500',
  execution_agent: 'border-cyan-500',
};

function getStanceIcon(stance: string) {
  if (stance.includes('bull')) return <TrendingUp className="w-4 h-4" />;
  if (stance.includes('bear')) return <TrendingDown className="w-4 h-4" />;
  return <Minus className="w-4 h-4" />;
}

function formatTimestamp(ts: number): string {
  const date = new Date(ts * 1000);
  return date.toLocaleTimeString();
}

export default function AgentOpinionChart({
  symbol,
  opinions,
  maxItems = 20,
  showRationale = false,
  onRefresh,
}: AgentOpinionChartProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // Group opinions by agent
  const agentOpinions = useMemo(() => {
    const grouped: Record<string, AgentOpinion[]> = {};
    
    for (const op of opinions) {
      if (!grouped[op.agent_id]) {
        grouped[op.agent_id] = [];
      }
      grouped[op.agent_id].push(op);
    }
    
    // Sort each agent's opinions by time
    for (const agentId in grouped) {
      grouped[agentId].sort((a, b) => b.timestamp - a.timestamp);
      grouped[agentId] = grouped[agentId].slice(0, maxItems);
    }
    
    return grouped;
  }, [opinions, maxItems]);

  // Calculate consensus
  const consensus = useMemo(() => {
    if (opinions.length === 0) return { score: 0, direction: 'neutral', confidence: 0 };
    
    const recentOpinions = opinions.filter(
      op => op.timestamp > Date.now() / 1000 - 300 // Last 5 minutes
    );
    
    if (recentOpinions.length === 0) return { score: 0, direction: 'neutral', confidence: 0 };
    
    const totalScore = recentOpinions.reduce((sum, op) => sum + op.score * op.confidence, 0);
    const avgScore = totalScore / recentOpinions.length;
    const avgConfidence = recentOpinions.reduce((sum, op) => sum + op.confidence, 0) / recentOpinions.length;
    
    let direction = 'neutral';
    if (avgScore > 0.3) direction = 'bullish';
    if (avgScore > 0.6) direction = 'strong_bullish';
    if (avgScore < -0.3) direction = 'bearish';
    if (avgScore < -0.6) direction = 'strong_bearish';
    
    return { score: avgScore, direction, confidence: avgConfidence };
  }, [opinions]);

  const agentList = Object.keys(agentOpinions);

  return (
    <div className="bg-slate-900/50 rounded-xl border border-slate-700/50 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Users className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-semibold text-white">Agent Opinions</h3>
          <span className="text-sm text-slate-400">- {symbol}</span>
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 hover:bg-slate-700/50 rounded-lg transition-colors"
            title="Refresh opinions"
            aria-label="Refresh opinions"
          >
            <RefreshCw className="w-4 h-4 text-slate-400" />
          </button>
        )}
      </div>

      {/* Consensus Summary */}
      <div className="mb-4 p-3 bg-slate-800/50 rounded-lg">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">Current Consensus</span>
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${
              consensus.score > 0 ? 'text-green-400' : 
              consensus.score < 0 ? 'text-red-400' : 'text-gray-400'
            }`}>
              {consensus.direction.replace('_', ' ').toUpperCase()}
            </span>
            <span className="text-xs text-slate-500">
              ({(consensus.confidence * 100).toFixed(0)}% conf)
            </span>
          </div>
        </div>
        
        {/* Score Bar */}
        <div className="mt-2 h-2 bg-slate-700 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ${
              consensus.score > 0 ? 'bg-green-500' : 'bg-red-500'
            }`}
            style={{ 
              width: `${Math.abs(consensus.score) * 50}%`,
              marginLeft: consensus.score > 0 ? '50%' : `${50 - Math.abs(consensus.score) * 50}%`,
            }}
          />
        </div>
        <div className="flex justify-between text-xs text-slate-500 mt-1">
          <span>Bearish</span>
          <span>Neutral</span>
          <span>Bullish</span>
        </div>
      </div>

      {/* Agent List */}
      <div className="space-y-2">
        {agentList.length === 0 ? (
          <div className="text-center text-slate-500 py-4">
            No opinions yet for {symbol}
          </div>
        ) : (
          agentList.map(agentId => {
            const agentOps = agentOpinions[agentId];
            const latestOp = agentOps[0];
            const roleClass = roleColors[latestOp.agent_role] || 'border-slate-500';
            
            return (
              <button
                key={agentId}
                type="button"
                className={`w-full text-left p-3 bg-slate-800/30 rounded-lg border-l-4 ${roleClass}
                  hover:bg-slate-800/50 transition-colors
                  ${selectedAgent === agentId ? 'ring-1 ring-blue-500' : ''}`}
                onClick={() => setSelectedAgent(selectedAgent === agentId ? null : agentId)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">
                      {latestOp.agent_role.replace('_', ' ')}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs ${stanceColors[latestOp.stance]}`}>
                      {getStanceIcon(latestOp.stance)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-mono ${
                      latestOp.score > 0 ? 'text-green-400' : 
                      latestOp.score < 0 ? 'text-red-400' : 'text-gray-400'
                    }`}>
                      {latestOp.score > 0 ? '+' : ''}{latestOp.score.toFixed(2)}
                    </span>
                    <span className="text-xs text-slate-500">
                      {(latestOp.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                
                {/* Expanded view */}
                {selectedAgent === agentId && showRationale && latestOp.rationale && (
                  <div className="mt-2 pt-2 border-t border-slate-700">
                    <p className="text-xs text-slate-400">{latestOp.rationale}</p>
                    <p className="text-xs text-slate-500 mt-1">
                      {formatTimestamp(latestOp.timestamp)}
                    </p>
                  </div>
                )}
                
                {/* Mini sparkline (last 5 scores) */}
                {selectedAgent === agentId && agentOps.length > 1 && (
                  <div className="mt-2 flex items-center gap-1">
                    {agentOps.slice(0, 5).reverse().map((op, i) => (
                      <div
                        key={i}
                        className={`w-2 h-4 rounded-sm ${
                          op.score > 0.3 ? 'bg-green-500' :
                          op.score > 0 ? 'bg-green-500/50' :
                          op.score < -0.3 ? 'bg-red-500' :
                          op.score < 0 ? 'bg-red-500/50' : 'bg-gray-500'
                        }`}
                        title={`${op.score.toFixed(2)} @ ${formatTimestamp(op.timestamp)}`}
                      />
                    ))}
                    <span className="text-xs text-slate-500 ml-1">history</span>
                  </div>
                )}
              </button>
            );
          })
        )}
      </div>

      {/* Footer */}
      <div className="mt-4 pt-2 border-t border-slate-700/50 flex justify-between text-xs text-slate-500">
        <span>{opinions.length} opinions from {agentList.length} agents</span>
        <span>Updates in real-time</span>
      </div>
    </div>
  );
}
