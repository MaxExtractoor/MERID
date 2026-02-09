import { useState, useEffect } from 'react';
import { Brain, Search, TrendingUp, AlertCircle, RefreshCw, Clock, Zap, Target } from 'lucide-react';

interface AgentDecision {
  timestamp: number;
  agent_id: string;
  vote: string;
  confidence: number;
  reasoning: string;
  research?: Array<{ source: string; snippet: string }>;
  trust: number;
  energy?: number;
}

interface AgentReasoningPanelProps {
  agentId?: string;
  className?: string;
}

export default function AgentReasoningPanel({ agentId, className = '' }: AgentReasoningPanelProps) {
  const [activity, setActivity] = useState<AgentDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimeout: NodeJS.Timeout;

    const connectWebSocket = () => {
      try {
        ws = new WebSocket(`ws://${window.location.host}/ws/agents`);
        
        ws.onopen = () => {
          setWsConnected(true);
          setError(null);
          setLoading(false);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            
            // Filter by agent if specified
            if (data.type === 'agent:decision' || data.type === 'agent:vote') {
              if (!agentId || data.agent_id === agentId) {
                const decision: AgentDecision = {
                  timestamp: data.timestamp || Date.now(),
                  agent_id: data.agent_id,
                  vote: data.vote || data.signal || 'unknown',
                  confidence: data.confidence || 0,
                  reasoning: data.reasoning || '',
                  research: data.research || [],
                  trust: data.trust || 1.0,
                  energy: data.energy || 1.0
                };
                
                setActivity(prev => [decision, ...prev].slice(0, 20));
              }
            }
          } catch (err) {
            console.error('Failed to parse WebSocket message:', err);
          }
        };

        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          setError('WebSocket connection error');
        };

        ws.onclose = () => {
          setWsConnected(false);
          // Attempt reconnection after 5 seconds
          reconnectTimeout = setTimeout(connectWebSocket, 5000);
        };
      } catch (err) {
        setError('Failed to connect to agent stream');
        setLoading(false);
      }
    };

    connectWebSocket();

    // Stop loading after timeout even if WS never connects
    const loadingTimeout = setTimeout(() => {
      if (!wsConnected && activity.length === 0) {
        setLoading(false);
      }
    }, 3000);

    return () => {
      if (ws) ws.close();
      clearTimeout(reconnectTimeout);
      clearTimeout(loadingTimeout);
    };
  }, [agentId, wsConnected, activity.length]);

  const formatTimeAgo = (timestamp: number) => {
    const diff = Date.now() - timestamp;
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ago`;
  };

  const getVoteColor = (vote: string) => {
    const v = vote.toLowerCase();
    if (v.includes('bull') || v === 'accept' || v === 'yes') return 'text-green-400 bg-green-500/20';
    if (v.includes('bear') || v === 'reject' || v === 'no') return 'text-red-400 bg-red-500/20';
    return 'text-gray-400 bg-gray-500/20';
  };

  const getVoteIcon = (vote: string) => {
    const v = vote.toLowerCase();
    if (v.includes('bull') || v === 'accept' || v === 'yes') return <TrendingUp className="w-4 h-4" />;
    if (v.includes('bear') || v === 'reject' || v === 'no') return <AlertCircle className="w-4 h-4" />;
    return <Target className="w-4 h-4" />;
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-purple-500" />
          <span className="ml-2 text-gray-400">Connecting to agent stream...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Status Bar */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-3 h-3 rounded-full ${wsConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-white font-medium">
              Agent Activity Stream {wsConnected ? 'Connected' : 'Disconnected'}
            </span>
            {agentId && (
              <span className="px-2 py-1 bg-purple-500/20 text-purple-400 rounded text-sm">
                Filtering: {agentId}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Zap className="w-4 h-4" />
            <span>{activity.length} recent decisions</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Connection Issue</p>
            <p className="text-sm text-gray-400">{error} - Using fallback data</p>
          </div>
        </div>
      )}

      {/* Activity Feed */}
      <div className="space-y-4">
        {activity.length === 0 ? (
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-8 text-center">
            <Brain className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <p className="text-gray-400">No agent activity yet</p>
            <p className="text-sm text-gray-500 mt-1">Waiting for agent decisions...</p>
          </div>
        ) : (
          activity.map((decision, idx) => (
            <div key={idx} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4 hover:bg-slate-700/30 transition-colors">
              {/* Header */}
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <Brain className="w-5 h-5 text-purple-400" />
                  <div>
                    <p className="text-white font-medium">{decision.agent_id}</p>
                    <div className="flex items-center gap-2 text-xs text-gray-400">
                      <Clock className="w-3 h-3" />
                      {formatTimeAgo(decision.timestamp)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`px-3 py-1 rounded-full text-sm font-medium flex items-center gap-1 ${getVoteColor(decision.vote)}`}>
                    {getVoteIcon(decision.vote)}
                    {decision.vote.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-3 gap-3 mb-3">
                <div className="bg-slate-700/30 rounded p-2">
                  <p className="text-xs text-gray-500">Confidence</p>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-slate-600 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-blue-500 transition-all"
                        style={{ width: `${decision.confidence * 100}%` }}
                      />
                    </div>
                    <span className="text-sm text-blue-400 font-mono">{(decision.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>

                <div className="bg-slate-700/30 rounded p-2">
                  <p className="text-xs text-gray-500">Trust</p>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 bg-slate-600 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-purple-500 transition-all"
                        style={{ width: `${decision.trust * 100}%` }}
                      />
                    </div>
                    <span className="text-sm text-purple-400 font-mono">{(decision.trust * 100).toFixed(0)}%</span>
                  </div>
                </div>

                {decision.energy !== undefined && (
                  <div className="bg-slate-700/30 rounded p-2">
                    <p className="text-xs text-gray-500">Energy</p>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-slate-600 rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-yellow-500 transition-all"
                          style={{ width: `${decision.energy * 100}%` }}
                        />
                      </div>
                      <span className="text-sm text-yellow-400 font-mono">{(decision.energy * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Reasoning */}
              <div className="mb-3">
                <p className="text-xs text-gray-500 mb-1">Reasoning:</p>
                <p className="text-sm text-gray-300">{decision.reasoning}</p>
              </div>

              {/* Research Sources */}
              {decision.research && decision.research.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Search className="w-4 h-4 text-gray-500" />
                    <p className="text-xs text-gray-500">Research ({decision.research.length} sources):</p>
                  </div>
                  <div className="space-y-2">
                    {decision.research.map((source, i) => (
                      <div key={i} className="bg-slate-700/20 rounded p-2 border-l-2 border-blue-500/50">
                        <p className="text-xs text-blue-400 font-medium">{source.source}</p>
                        <p className="text-xs text-gray-400 mt-1">{source.snippet}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
        <p className="text-xs text-gray-500 text-center">
          Real-time agent reasoning stream • WebSocket connection • Auto-updates
        </p>
      </div>
    </div>
  );
}
