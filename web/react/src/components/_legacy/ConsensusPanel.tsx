import { Scale, Users, CheckCircle, XCircle, RefreshCw, Clock, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface Vote {
  agent_id: string;
  proposal: string;
  signal: string;
  confidence: number;
  energy: number;
  trust: number;
  weight: number;
  timestamp: number;
}

interface ConsensusPanelStatus {
  running: boolean;
  pending_votes: number;
  min_votes_required: number;
  quorum_threshold: number;
  consensus_interval: number;
  vote_window: number;
  time_until_next: number;
  vote_distribution: {
    bullish: number;
    bearish: number;
    neutral: number;
  };
  trust_scores: Record<string, number>;
}

interface ConsensusMetrics {
  total_rounds: number;
  successful_consensus: number;
  vetoed_decisions: number;
  rerounds_requested: number;
  avg_vote_count: number;
  avg_confidence: number;
  quorum_rate: number;
}

interface ConsensusPanelProps {
  className?: string;
}

export default function ConsensusPanel({ className = '' }: ConsensusPanelProps) {
  const { data: status, loading: statusLoading, error: statusError, refetch: refetchStatus } = useApiData<ConsensusPanelStatus>(
    API_ENDPOINTS.CONSENSUS_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const { data: votesData } = useApiData<{ votes: Vote[] }>(
    API_ENDPOINTS.CONSENSUS_VOTES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const { data: metrics } = useApiData<ConsensusMetrics>(
    API_ENDPOINTS.CONSENSUS_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const votes = votesData?.votes ?? [];
  const loading = statusLoading && !status;
  const error = statusError?.message ?? null;
  const fetchConsensusData = refetchStatus;

  const formatAgentName = (id: string) => {
    return id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  };

  const getSignalIcon = (signal: string) => {
    switch (signal.toLowerCase()) {
      case 'bullish': return <TrendingUp className="w-4 h-4 text-green-400" />;
      case 'bearish': return <TrendingDown className="w-4 h-4 text-red-400" />;
      default: return <Minus className="w-4 h-4 text-gray-400" />;
    }
  };

  const getSignalColor = (signal: string) => {
    switch (signal.toLowerCase()) {
      case 'bullish': return 'text-green-400 bg-green-500/20';
      case 'bearish': return 'text-red-400 bg-red-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading consensus data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {error && <ErrorBar label="Consensus" error={statusError} onRetry={fetchConsensusData} />}

      {/* Status Bar */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-3 h-3 rounded-full ${status?.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-white font-medium">
              Consensus Engine {status?.running ? 'Active' : 'Stopped'}
            </span>
          </div>
          <div className="flex items-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-400" />
              <span className="text-gray-400">Next resolution in:</span>
              <span className="text-blue-400 font-mono">{status?.time_until_next.toFixed(1)}s</span>
            </div>
            <button type="button"
              onClick={fetchConsensusData}
              className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
              title="Refresh consensus data"
              aria-label="Refresh consensus data"
            >
              <RefreshCw className="w-4 h-4 text-gray-400" />
            </button>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Total Rounds</p>
          <p className="text-2xl font-bold text-white">{metrics?.total_rounds || 0}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Successful</p>
          <p className="text-2xl font-bold text-green-400">{metrics?.successful_consensus || 0}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Vetoed</p>
          <p className="text-2xl font-bold text-red-400">{metrics?.vetoed_decisions || 0}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Re-rounds</p>
          <p className="text-2xl font-bold text-yellow-400">{metrics?.rerounds_requested || 0}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Avg Votes</p>
          <p className="text-2xl font-bold text-white">{metrics?.avg_vote_count.toFixed(1) || 0}</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Avg Confidence</p>
          <p className="text-2xl font-bold text-blue-400">{((metrics?.avg_confidence || 0) * 100).toFixed(0)}%</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <p className="text-xs text-gray-400 mb-1">Quorum Rate</p>
          <p className="text-2xl font-bold text-purple-400">{((metrics?.quorum_rate || 0) * 100).toFixed(0)}%</p>
        </div>
      </div>

      {/* Vote Distribution */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Scale className="w-6 h-6 text-blue-400" />
          <h3 className="text-lg font-bold text-white">Current Vote Distribution</h3>
          <span className="ml-auto text-sm text-gray-400">
            {status?.pending_votes || 0} / {status?.min_votes_required || 3} votes (quorum: {((status?.quorum_threshold || 0.67) * 100).toFixed(0)}%)
          </span>
        </div>

        <div className="space-y-4">
          {/* Bullish */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-green-400" />
                <span className="text-green-400 font-medium">Bullish</span>
              </div>
              <span className="text-white font-bold">{status?.vote_distribution.bullish || 0}%</span>
            </div>
            <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-green-600 to-green-400 transition-all duration-500"
                style={{ width: `${status?.vote_distribution.bullish || 0}%` }}
              />
            </div>
          </div>

          {/* Bearish */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-400" />
                <span className="text-red-400 font-medium">Bearish</span>
              </div>
              <span className="text-white font-bold">{status?.vote_distribution.bearish || 0}%</span>
            </div>
            <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-red-600 to-red-400 transition-all duration-500"
                style={{ width: `${status?.vote_distribution.bearish || 0}%` }}
              />
            </div>
          </div>

          {/* Neutral */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Minus className="w-4 h-4 text-gray-400" />
                <span className="text-gray-400 font-medium">Neutral</span>
              </div>
              <span className="text-white font-bold">{status?.vote_distribution.neutral || 0}%</span>
            </div>
            <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-gray-600 to-gray-400 transition-all duration-500"
                style={{ width: `${status?.vote_distribution.neutral || 0}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Pending Votes Table */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-3 mb-6">
          <Users className="w-6 h-6 text-purple-400" />
          <h3 className="text-lg font-bold text-white">Pending Votes</h3>
          <span className={`ml-auto px-3 py-1 rounded-full text-xs font-medium ${
            (status?.pending_votes || 0) >= (status?.min_votes_required || 3)
              ? 'bg-green-500/20 text-green-400'
              : 'bg-yellow-500/20 text-yellow-400'
          }`}>
            {(status?.pending_votes || 0) >= (status?.min_votes_required || 3) ? (
              <><CheckCircle className="w-3 h-3 inline mr-1" /> Quorum Met</>
            ) : (
              <><XCircle className="w-3 h-3 inline mr-1" /> Awaiting Quorum</>
            )}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-slate-700">
                <th className="pb-3 font-medium">Agent</th>
                <th className="pb-3 font-medium text-center">Signal</th>
                <th className="pb-3 font-medium text-center">Confidence</th>
                <th className="pb-3 font-medium text-center">Trust</th>
                <th className="pb-3 font-medium text-center">Energy</th>
                <th className="pb-3 font-medium text-center">Weight</th>
              </tr>
            </thead>
            <tbody>
              {votes.map((vote, idx) => (
                <tr key={idx} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className="py-4">
                    <span className="text-white font-medium">{formatAgentName(vote.agent_id)}</span>
                  </td>
                  <td className="py-4 text-center">
                    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${getSignalColor(vote.signal)}`}>
                      {getSignalIcon(vote.signal)}
                      {vote.signal.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-4 text-center">
                    <span className="text-blue-400 font-mono">{(vote.confidence * 100).toFixed(0)}%</span>
                  </td>
                  <td className="py-4 text-center">
                    <span className="text-purple-400 font-mono">{(vote.trust * 100).toFixed(0)}%</span>
                  </td>
                  <td className="py-4 text-center">
                    <span className="text-yellow-400 font-mono">{(vote.energy * 100).toFixed(0)}%</span>
                  </td>
                  <td className="py-4 text-center">
                    <span className="text-white font-bold">{vote.weight.toFixed(2)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
