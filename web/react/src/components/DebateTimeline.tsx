import { useState, useEffect } from 'react';
import { 
  MessageSquare,
  TrendingUp,
  TrendingDown,
  Minus,
  Shield,
  Search,
  BarChart3,
  Bot,
  Zap,
  RefreshCw
} from 'lucide-react';
import { useConsensusStream } from '../hooks/useConsensusStream';

interface AgentOpinion {
  opinion_id?: string;
  id?: string;
  agent_id?: string;
  agent?: string;
  role?: string;
  symbol?: string;
  stance?: string;
  position?: string;
  score?: number;
  confidence?: number;
  rationale?: string;
  reasoning?: string;
  horizon?: string;
  timestamp?: number | string;
}

const ROLE_ICONS: Record<string, any> = {
  bull_analyst: TrendingUp,
  bear_analyst: TrendingDown,
  arbitrage: BarChart3,
  sentiment: MessageSquare,
  technical: BarChart3,
  fundamental: Search,
  risk_manager: Shield,
  trader: Zap,
  default: Bot,
};

const ROLE_COLORS: Record<string, string> = {
  bull_analyst: 'text-green-400 bg-green-500/20',
  bear_analyst: 'text-red-400 bg-red-500/20',
  arbitrage: 'text-purple-400 bg-purple-500/20',
  sentiment: 'text-blue-400 bg-blue-500/20',
  technical: 'text-orange-400 bg-orange-500/20',
  fundamental: 'text-cyan-400 bg-cyan-500/20',
  risk_manager: 'text-yellow-400 bg-yellow-500/20',
  trader: 'text-pink-400 bg-pink-500/20',
  default: 'text-gray-400 bg-gray-500/20',
};

const STANCE_COLORS: Record<string, string> = {
  strong_bull: 'text-green-400',
  bull: 'text-green-300',
  neutral: 'text-gray-400',
  bear: 'text-red-300',
  strong_bear: 'text-red-400',
};

export default function DebateTimeline() {
  const [restOpinions, setRestOpinions] = useState<AgentOpinion[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');

  // Shared consensus WebSocket — one connection for the entire app
  const { opinions: streamOpinions } = useConsensusStream();

  // Use stream opinions when available, fall back to REST
  const opinions: AgentOpinion[] = streamOpinions.length > 0
    ? streamOpinions as AgentOpinion[]
    : restOpinions;

  useEffect(() => {
    fetchOpinions();

    // Poll fallback at relaxed interval (stream handles real-time)
    const interval = setInterval(fetchOpinions, 30000);

    return () => clearInterval(interval);
  }, []);

  const fetchOpinions = async () => {
    try {
      const res = await fetch('/api/v1/consensus/opinions?limit=30');
      if (res.ok) {
        const data = await res.json();
        setRestOpinions(data.opinions || []);
      }
    } catch (err) {
      console.error('Failed to fetch opinions:', err);
    } finally {
      setLoading(false);
    }
  };

  const getRoleIcon = (role: string) => {
    const Icon = ROLE_ICONS[role] || ROLE_ICONS.default;
    return Icon;
  };

  const getRoleColor = (role: string) => {
    return ROLE_COLORS[role] || ROLE_COLORS.default;
  };

  const getStanceIcon = (stance: string) => {
    if (stance.includes('bull')) return <TrendingUp className="w-4 h-4" />;
    if (stance.includes('bear')) return <TrendingDown className="w-4 h-4" />;
    return <Minus className="w-4 h-4" />;
  };

  const getStanceColor = (stance: string) => {
    return STANCE_COLORS[stance] || STANCE_COLORS.neutral;
  };

  const formatTime = (ts: number) => {
    if (!ts) return '-';
    const date = new Date(ts * 1000);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    return date.toLocaleTimeString();
  };

  const formatScore = (score?: number) => {
    const s = score ?? 0;
    const sign = s >= 0 ? '+' : '';
    return `${sign}${(s * 100).toFixed(0)}%`;
  };

  const filteredOpinions = filter === 'all' 
    ? opinions 
    : opinions.filter(o => o.role === filter);

  const uniqueRoles = [...new Set(opinions.map(o => o.role).filter((r): r is string => !!r))];

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <MessageSquare className="w-5 h-5 text-blue-400" />
          Agent Debate
        </h2>
        <button 
          onClick={fetchOpinions}
          className="p-1.5 hover:bg-slate-700/50 rounded transition-colors"
          title="Refresh opinions"
          aria-label="Refresh opinions"
        >
          <RefreshCw className="w-4 h-4 text-gray-400" />
        </button>
      </div>

      {/* Role Filters */}
      <div className="flex flex-wrap gap-1">
        <button
          onClick={() => setFilter('all')}
          className={`px-2 py-1 text-xs rounded transition-colors ${
            filter === 'all' 
              ? 'bg-blue-500/20 text-blue-400' 
              : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
          }`}
        >
          All
        </button>
        {uniqueRoles.map((role) => {
          const Icon = getRoleIcon(role);
          return (
            <button
              key={role}
              onClick={() => setFilter(role)}
              className={`px-2 py-1 text-xs rounded flex items-center gap-1 transition-colors ${
                filter === role
                  ? getRoleColor(role)
                  : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
              }`}
            >
              <Icon className="w-3 h-3" />
              {role.replace('_', ' ')}
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      <div className="space-y-2 max-h-[400px] overflow-y-auto">
        {filteredOpinions.length === 0 ? (
          <div className="bg-slate-800/30 rounded-lg p-6 text-center text-gray-500">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No opinions yet</p>
            <p className="text-xs mt-1">Agents will post opinions as they analyze markets</p>
          </div>
        ) : (
          filteredOpinions.map((opinion, idx) => {
            const role = opinion.role || 'analyst';
            const agentId = opinion.agent_id || opinion.agent || 'Unknown';
            const stance = opinion.stance || opinion.position || 'neutral';
            const symbol = opinion.symbol || 'BTC';
            const score = opinion.score ?? 0;
            const confidence = opinion.confidence ?? 0;
            const rationale = opinion.rationale || opinion.reasoning || '';
            const horizon = opinion.horizon || 'short-term';
            const ts = typeof opinion.timestamp === 'string'
              ? new Date(opinion.timestamp).getTime() / 1000
              : (opinion.timestamp || 0);
            const key = opinion.opinion_id || opinion.id || `op-${idx}`;
            const Icon = getRoleIcon(role);
            return (
              <div 
                key={key}
                className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/30 hover:border-slate-600/50 transition-colors"
              >
                {/* Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={`p-1.5 rounded ${getRoleColor(role)}`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white">{agentId}</p>
                      <p className="text-xs text-gray-500">{role.replace('_', ' ')}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-gray-500">{formatTime(ts)}</p>
                  </div>
                </div>

                {/* Opinion Content */}
                <div className="flex items-center gap-3 mb-2">
                  <div className={`flex items-center gap-1 ${getStanceColor(stance)}`}>
                    {getStanceIcon(stance)}
                    <span className="font-medium text-sm">{stance.replace('_', ' ').toUpperCase()}</span>
                  </div>
                  <span className="text-gray-500">on</span>
                  <span className="font-medium text-white">{symbol}</span>
                  <span className={`ml-auto font-mono ${score >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatScore(score)}
                  </span>
                </div>

                {/* Rationale */}
                {rationale && (
                  <p className="text-xs text-gray-400 line-clamp-2 italic">
                    "{rationale}"
                  </p>
                )}

                {/* Footer */}
                <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                  <span>Confidence: {(confidence * 100).toFixed(0)}%</span>
                  <span>Horizon: {horizon}</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
