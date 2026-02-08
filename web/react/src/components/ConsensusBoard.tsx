import { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  Users, 
  Target,
  Zap,
  Clock
} from 'lucide-react';
import { useConsensusStream } from '../hooks/useConsensusStream';

interface ConsensusStatus {
  symbol: string;
  has_consensus: boolean;
  opinion_count: number;
  consensus_score: number;
  direction: 'long' | 'short' | 'flat';
  confidence: number;
  supporting_agents: string[];
  opposing_agents: string[];
  last_update: number;
}

interface TradePlan {
  plan_id?: string;
  id?: string;
  symbol?: string;
  title?: string;
  direction?: string;
  target_size_usd?: number;
  confidence?: number;
  consensus_score?: number;
  supporting_agents?: string[];
  opposing_agents?: string[];
  status: string;
  timestamp?: number;
}

interface ConsensusData {
  symbols: Record<string, ConsensusStatus>;
  metrics: {
    total_opinions: number;
    total_plans: number;
    consensus_cycles: number;
    active_plans: number;
  };
}

export default function ConsensusBoard() {
  const [data, setData] = useState<ConsensusData | null>(null);
  const [restPlans, setRestPlans] = useState<TradePlan[]>([]);

  // Shared consensus WebSocket — one connection for the entire app
  const { connected: wsConnected, plans: streamPlans, lastEvent } = useConsensusStream();

  // Merge stream plans with REST plans (stream takes priority when available)
  const plans = streamPlans.length > 0
    ? streamPlans.map(p => ({ ...p, status: p.status || 'pending' } as TradePlan))
    : restPlans;

  useEffect(() => {
    // Initial REST fetch
    fetchConsensusStatus();
    fetchActivePlans();

    // Poll fallback at a relaxed interval (stream handles real-time)
    const interval = setInterval(() => {
      fetchConsensusStatus();
      fetchActivePlans();
    }, 15000);

    return () => clearInterval(interval);
  }, []);

  // Re-fetch consensus status when stream delivers a new event
  useEffect(() => {
    if (lastEvent) {
      fetchConsensusStatus();
    }
  }, [lastEvent]);

  const fetchConsensusStatus = async () => {
    try {
      const res = await fetch('/api/v1/consensus/status');
      if (res.ok) {
        const data = await res.json();
        setData(data);
      }
    } catch (err) {
      console.error('Failed to fetch consensus status:', err);
    }
  };

  const fetchActivePlans = async () => {
    try {
      const res = await fetch('/api/v1/consensus/plans');
      if (res.ok) {
        const data = await res.json();
        setRestPlans(data.plans || []);
      }
    } catch (err) {
      console.error('Failed to fetch active plans:', err);
    }
  };

  const getDirectionIcon = (direction: string) => {
    switch (direction) {
      case 'long': return <TrendingUp className="w-5 h-5 text-green-400" />;
      case 'short': return <TrendingDown className="w-5 h-5 text-red-400" />;
      default: return <Minus className="w-5 h-5 text-gray-400" />;
    }
  };

  const getDirectionColor = (direction: string) => {
    switch (direction) {
      case 'long': return 'text-green-400 bg-green-500/20 border-green-500/50';
      case 'short': return 'text-red-400 bg-red-500/20 border-red-500/50';
      default: return 'text-gray-400 bg-gray-500/20 border-gray-500/50';
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'approved':
        return <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">Approved</span>;
      case 'vetoed':
        return <span className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs">Vetoed</span>;
      case 'executing':
        return <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">Executing</span>;
      default:
        return <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">Pending</span>;
    }
  };

  const formatTime = (ts: number) => {
    if (!ts) return '-';
    return new Date(ts * 1000).toLocaleTimeString();
  };

  const symbols = data?.symbols ? Object.values(data.symbols) : [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Target className="w-5 h-5 text-purple-400" />
          Consensus Board
        </h2>
        <div className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${wsConnected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
          <Zap className="w-3 h-3" />
          {wsConnected ? 'Live' : 'Polling'}
        </div>
      </div>

      {/* Metrics Strip */}
      {data?.metrics && (
        <div className="grid grid-cols-4 gap-2">
          <div className="bg-slate-800/50 rounded p-2 text-center">
            <p className="text-xs text-gray-400">Opinions</p>
            <p className="text-lg font-bold text-white">{data.metrics.total_opinions}</p>
          </div>
          <div className="bg-slate-800/50 rounded p-2 text-center">
            <p className="text-xs text-gray-400">Plans</p>
            <p className="text-lg font-bold text-white">{data.metrics.total_plans}</p>
          </div>
          <div className="bg-slate-800/50 rounded p-2 text-center">
            <p className="text-xs text-gray-400">Cycles</p>
            <p className="text-lg font-bold text-white">{data.metrics.consensus_cycles}</p>
          </div>
          <div className="bg-slate-800/50 rounded p-2 text-center">
            <p className="text-xs text-gray-400">Active</p>
            <p className="text-lg font-bold text-purple-400">{data.metrics.active_plans}</p>
          </div>
        </div>
      )}

      {/* Consensus by Symbol */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-gray-400">By Symbol</h3>
        
        {symbols.length === 0 ? (
          <div className="bg-slate-800/30 rounded-lg p-4 text-center text-gray-500">
            <Users className="w-6 h-6 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No active consensus</p>
            <p className="text-xs">Waiting for agent opinions...</p>
          </div>
        ) : (
          <div className="space-y-2">
            {symbols.map((status) => (
              <div 
                key={status.symbol}
                className={`p-3 rounded-lg border ${getDirectionColor(status.direction)}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {getDirectionIcon(status.direction)}
                    <div>
                      <p className="font-medium text-white">{status.symbol}</p>
                      <p className="text-xs text-gray-400">
                        {status.opinion_count} opinions • Score: {status.consensus_score.toFixed(2)}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-bold">{status.direction.toUpperCase()}</p>
                    <p className="text-xs text-gray-400">
                      {(status.confidence * 100).toFixed(0)}% confidence
                    </p>
                  </div>
                </div>
                
                {/* Agent breakdown */}
                <div className="mt-2 flex gap-4 text-xs">
                  <div className="flex items-center gap-1">
                    <TrendingUp className="w-3 h-3 text-green-400" />
                    <span className="text-gray-400">{status.supporting_agents?.length || 0} supporting</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <TrendingDown className="w-3 h-3 text-red-400" />
                    <span className="text-gray-400">{status.opposing_agents?.length || 0} opposing</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Active Trade Plans */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-gray-400">Trade Plans</h3>
        
        {plans.length === 0 ? (
          <div className="bg-slate-800/30 rounded-lg p-4 text-center text-gray-500">
            <Clock className="w-6 h-6 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No active plans</p>
          </div>
        ) : (
          <div className="space-y-2">
            {plans.map((plan) => (
              <div 
                key={plan.plan_id || plan.id || `plan-${plans.indexOf(plan)}`}
                className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/50"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {getDirectionIcon(plan.direction || '')}
                    <span className="font-medium text-white">{plan.symbol || plan.title || 'Unknown'}</span>
                    <span className="text-sm text-gray-400">${(plan.target_size_usd || 0).toLocaleString()}</span>
                  </div>
                  {getStatusBadge(plan.status)}
                </div>
                
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Score: {(plan.consensus_score ?? 0).toFixed(2)}</span>
                  <span>{plan.supporting_agents?.length || 0} for / {plan.opposing_agents?.length || 0} against</span>
                  <span>{formatTime(plan.timestamp || 0)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
