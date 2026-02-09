import { useState, useEffect } from 'react';
import { Coins, TrendingUp, Users, Vote, DollarSign, ArrowUpRight, RefreshCw, AlertCircle, CheckCircle } from 'lucide-react';
import QuadraticFundingPanel from '../components/QuadraticFundingPanel';

interface TreasuryBalance {
  currency: string;
  amount: number;
  value_usd: number;
}

interface Proposal {
  id: string;
  title: string;
  description: string;
  proposer: string;
  status: 'active' | 'passed' | 'rejected' | 'executed';
  votes_for: number;
  votes_against: number;
  total_votes: number;
  amount_requested: number;
  category: string;
  created_at: string;
  ends_at: string;
}

interface FundingRound {
  id: string;
  name: string;
  total_pool: number;
  contributions: number;
  projects: number;
  status: 'active' | 'completed' | 'upcoming';
  ends_at: string;
}

interface TreasuryData {
  total_value_usd: number;
  balances: TreasuryBalance[];
  proposals: Proposal[];
  funding_rounds: FundingRound[];
  governance_stats: {
    total_holders: number;
    total_voting_power: number;
    active_proposals: number;
    participation_rate: number;
  };
  source?: 'live' | 'stub';
}

export default function Treasury() {
  const [treasuryData, setTreasuryData] = useState<TreasuryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<'overview' | 'proposals' | 'funding'>('overview');

  useEffect(() => {
    fetchTreasuryData();
    const interval = setInterval(fetchTreasuryData, 60000);
    return () => clearInterval(interval);
  }, []);

  const fetchTreasuryData = async () => {
    try {
      const response = await fetch('/api/v1/treasury/overview');
      if (response.ok) {
        const data = await response.json();
        setTreasuryData(data);
        setError(null);
      } else {
        throw new Error('Failed to fetch treasury data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback data when API is unreachable
      setTreasuryData({
        total_value_usd: 2450000,
        balances: [
          { currency: 'USDC', amount: 1500000, value_usd: 1500000 },
          { currency: 'ETH', amount: 150, value_usd: 577500 },
          { currency: 'BTC', amount: 3.5, value_usd: 367500 },
          { currency: 'MERID', amount: 50000, value_usd: 5000 },
        ],
        proposals: [
          {
            id: '1',
            title: 'Expand Trading Infrastructure to 5 New Venues',
            description: 'Integrate Bybit, Gate.io, and 3 other exchanges to increase market coverage',
            proposer: '0x1234...5678',
            status: 'active',
            votes_for: 125000,
            votes_against: 15000,
            total_votes: 140000,
            amount_requested: 50000,
            category: 'Infrastructure',
            created_at: new Date(Date.now() - 172800000).toISOString(),
            ends_at: new Date(Date.now() + 259200000).toISOString(),
          },
          {
            id: '2',
            title: 'Fund AI Research for Prediction Market Analysis',
            description: 'Develop advanced ML models for prediction market arbitrage',
            proposer: '0x8765...4321',
            status: 'active',
            votes_for: 98000,
            votes_against: 42000,
            total_votes: 140000,
            amount_requested: 75000,
            category: 'Research',
            created_at: new Date(Date.now() - 86400000).toISOString(),
            ends_at: new Date(Date.now() + 432000000).toISOString(),
          },
          {
            id: '3',
            title: 'Community Grants Program Q1 2026',
            description: 'Allocate funds for community-driven development projects',
            proposer: '0xabcd...ef01',
            status: 'passed',
            votes_for: 180000,
            votes_against: 20000,
            total_votes: 200000,
            amount_requested: 100000,
            category: 'Community',
            created_at: new Date(Date.now() - 604800000).toISOString(),
            ends_at: new Date(Date.now() - 86400000).toISOString(),
          },
        ],
        funding_rounds: [
          {
            id: '1',
            name: 'Quadratic Funding Round #5',
            total_pool: 250000,
            contributions: 1250,
            projects: 23,
            status: 'active',
            ends_at: new Date(Date.now() + 604800000).toISOString(),
          },
          {
            id: '2',
            name: 'Agent Development Fund',
            total_pool: 150000,
            contributions: 890,
            projects: 15,
            status: 'active',
            ends_at: new Date(Date.now() + 1209600000).toISOString(),
          },
        ],
        governance_stats: {
          total_holders: 5420,
          total_voting_power: 10000000,
          active_proposals: 2,
          participation_rate: 0.68,
        },
        source: 'stub' as const,
      });
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount: number) => {
    return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatNumber = (num: number) => {
    return num.toLocaleString('en-US');
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active': return 'text-blue-400 bg-blue-500/20';
      case 'passed': return 'text-green-400 bg-green-500/20';
      case 'rejected': return 'text-red-400 bg-red-500/20';
      case 'executed': return 'text-purple-400 bg-purple-500/20';
      case 'completed': return 'text-green-400 bg-green-500/20';
      case 'upcoming': return 'text-yellow-400 bg-yellow-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getVotePercentage = (votesFor: number, totalVotes: number) => {
    return totalVotes > 0 ? (votesFor / totalVotes) * 100 : 0;
  };

  const formatTimeRemaining = (endDate: string) => {
    const now = new Date();
    const end = new Date(endDate);
    const diffMs = end.getTime() - now.getTime();
    const diffDays = Math.floor(diffMs / 86400000);
    const diffHours = Math.floor((diffMs % 86400000) / 3600000);
    
    if (diffDays > 0) return `${diffDays}d ${diffHours}h remaining`;
    if (diffHours > 0) return `${diffHours}h remaining`;
    return 'Ending soon';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading treasury...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Coins className="w-8 h-8 text-yellow-500" />
          <div>
            <h1 className="text-2xl font-bold text-white">Treasury & Governance</h1>
            <div className="flex items-center gap-2">
              <p className="text-sm text-gray-400">DAO funds, proposals, and quadratic funding</p>
              {treasuryData?.source === 'live' && (
                <span className="flex items-center gap-1 text-xs text-green-400">
                  <CheckCircle className="w-3 h-3" /> Live
                </span>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={fetchTreasuryData}
          className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg flex items-center gap-2 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Treasury Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gradient-to-br from-yellow-600 to-orange-600 rounded-xl p-6 shadow-lg">
          <div className="flex items-center justify-between mb-2">
            <DollarSign className="w-6 h-6 text-white" />
            <ArrowUpRight className="w-5 h-5 text-white/70" />
          </div>
          <p className="text-white/80 text-sm mb-1">Total Treasury Value</p>
          <p className="text-3xl font-bold text-white">
            {formatCurrency(treasuryData?.total_value_usd || 0)}
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
          <div className="flex items-center justify-between mb-2">
            <Vote className="w-6 h-6 text-blue-400" />
          </div>
          <p className="text-gray-400 text-sm mb-1">Active Proposals</p>
          <p className="text-3xl font-bold text-white">
            {treasuryData?.governance_stats.active_proposals || 0}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            {(treasuryData?.governance_stats.participation_rate || 0) * 100}% participation
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
          <div className="flex items-center justify-between mb-2">
            <Users className="w-6 h-6 text-purple-400" />
          </div>
          <p className="text-gray-400 text-sm mb-1">Token Holders</p>
          <p className="text-3xl font-bold text-white">
            {formatNumber(treasuryData?.governance_stats.total_holders || 0)}
          </p>
          <p className="text-sm text-gray-500 mt-2">
            {formatNumber(treasuryData?.governance_stats.total_voting_power || 0)} voting power
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
          <div className="flex items-center justify-between mb-2">
            <TrendingUp className="w-6 h-6 text-green-400" />
          </div>
          <p className="text-gray-400 text-sm mb-1">Funding Rounds</p>
          <p className="text-3xl font-bold text-white">
            {treasuryData?.funding_rounds.length || 0}
          </p>
          <p className="text-sm text-gray-500 mt-2">Active rounds</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['overview', 'proposals', 'funding'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setSelectedTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              selectedTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {selectedTab === 'overview' && (
        <div className="space-y-6">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
            <div className="p-4 border-b border-slate-700/50">
              <h2 className="text-lg font-bold text-white">Treasury Balances</h2>
            </div>
            <div className="p-4 space-y-3">
              {treasuryData?.balances.map(balance => (
                <div key={balance.currency} className="flex items-center justify-between p-3 bg-slate-700/30 rounded-lg">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-slate-700 rounded-full flex items-center justify-center">
                      <span className="text-white font-bold">{balance.currency.slice(0, 2)}</span>
                    </div>
                    <div>
                      <p className="text-white font-medium">{balance.currency}</p>
                      <p className="text-sm text-gray-400">{balance.amount.toLocaleString()} tokens</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-white font-bold">{formatCurrency(balance.value_usd)}</p>
                    <p className="text-sm text-gray-400">
                      {((balance.value_usd / (treasuryData?.total_value_usd || 1)) * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Proposals Tab */}
      {selectedTab === 'proposals' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-gray-400">{treasuryData?.proposals.length || 0} proposals</p>
            <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors">
              Create Proposal
            </button>
          </div>

          {treasuryData?.proposals.map(proposal => {
            const votePercentage = getVotePercentage(proposal.votes_for, proposal.total_votes);
            return (
              <div key={proposal.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-bold text-white">{proposal.title}</h3>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(proposal.status)}`}>
                        {proposal.status}
                      </span>
                    </div>
                    <p className="text-gray-400 text-sm mb-3">{proposal.description}</p>
                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      <span>By {proposal.proposer}</span>
                      <span>•</span>
                      <span>{proposal.category}</span>
                      <span>•</span>
                      <span>{formatCurrency(proposal.amount_requested)} requested</span>
                    </div>
                  </div>
                </div>

                {proposal.status === 'active' && (
                  <>
                    <div className="mb-4">
                      <div className="flex items-center justify-between text-sm mb-2">
                        <span className="text-gray-400">
                          {formatNumber(proposal.votes_for)} FOR ({votePercentage.toFixed(1)}%)
                        </span>
                        <span className="text-gray-400">
                          {formatNumber(proposal.votes_against)} AGAINST
                        </span>
                      </div>
                      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-green-500 to-emerald-500"
                          style={{ width: `${votePercentage}%` }}
                        />
                      </div>
                      <p className="text-xs text-gray-500 mt-2">{formatTimeRemaining(proposal.ends_at)}</p>
                    </div>

                    <div className="flex gap-2">
                      <button className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors">
                        Vote For
                      </button>
                      <button className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors">
                        Vote Against
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Funding Tab — live from /api/v1/quadratic-funding */}
      {selectedTab === 'funding' && <QuadraticFundingPanel />}
    </div>
  );
}
