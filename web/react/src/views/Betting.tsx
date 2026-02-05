import { useState, useEffect } from 'react';
import { Trophy, DollarSign, Clock, RefreshCw, AlertCircle } from 'lucide-react';

interface BettingMarket {
  id: string;
  title: string;
  category: 'sports' | 'politics' | 'entertainment' | 'crypto';
  description: string;
  total_volume: number;
  outcomes: BettingOutcome[];
  closes_at: string;
  status: 'open' | 'closed' | 'settled';
}

interface BettingOutcome {
  id: string;
  name: string;
  odds: number;
  probability: number;
  volume: number;
}

interface UserBet {
  id: string;
  market_title: string;
  outcome: string;
  amount: number;
  odds: number;
  potential_payout: number;
  status: 'pending' | 'won' | 'lost' | 'refunded';
  placed_at: string;
  settled_at?: string;
}

interface BettingStats {
  total_bets: number;
  active_bets: number;
  total_wagered: number;
  total_winnings: number;
  win_rate: number;
  roi: number;
}

export default function Betting() {
  const [markets, setMarkets] = useState<BettingMarket[]>([]);
  const [userBets, setUserBets] = useState<UserBet[]>([]);
  const [stats, setStats] = useState<BettingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [activeTab, setActiveTab] = useState<'markets' | 'mybets' | 'stats'>('markets');

  useEffect(() => {
    fetchBettingData();
    const interval = setInterval(fetchBettingData, 30000);
    return () => clearInterval(interval);
  }, [selectedCategory]);

  const fetchBettingData = async () => {
    try {
      const response = await fetch('/api/v1/betting/overview');
      if (response.ok) {
        const data = await response.json();
        setMarkets(data.markets || []);
        setUserBets(data.user_bets || []);
        setStats(data.stats || null);
        setError(null);
      } else {
        throw new Error('Failed to fetch betting data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setMarkets([
        {
          id: '1',
          title: 'Super Bowl 2026 Winner',
          category: 'sports',
          description: 'Which team will win Super Bowl LX?',
          total_volume: 2500000,
          outcomes: [
            { id: '1a', name: 'Kansas City Chiefs', odds: 2.5, probability: 0.40, volume: 1000000 },
            { id: '1b', name: 'San Francisco 49ers', odds: 3.0, probability: 0.33, volume: 825000 },
            { id: '1c', name: 'Buffalo Bills', odds: 4.5, probability: 0.22, volume: 550000 },
            { id: '1d', name: 'Other', odds: 8.0, probability: 0.05, volume: 125000 },
          ],
          closes_at: new Date(Date.now() + 86400000 * 30).toISOString(),
          status: 'open',
        },
        {
          id: '2',
          title: 'BTC Reaches $150K in 2026',
          category: 'crypto',
          description: 'Will Bitcoin reach $150,000 before end of 2026?',
          total_volume: 1800000,
          outcomes: [
            { id: '2a', name: 'Yes', odds: 2.2, probability: 0.45, volume: 810000 },
            { id: '2b', name: 'No', odds: 1.8, probability: 0.55, volume: 990000 },
          ],
          closes_at: new Date(Date.now() + 86400000 * 180).toISOString(),
          status: 'open',
        },
        {
          id: '3',
          title: '2026 Presidential Election',
          category: 'politics',
          description: 'Who will win the 2026 US Presidential Election?',
          total_volume: 5000000,
          outcomes: [
            { id: '3a', name: 'Candidate A', odds: 2.0, probability: 0.50, volume: 2500000 },
            { id: '3b', name: 'Candidate B', odds: 2.5, probability: 0.40, volume: 2000000 },
            { id: '3c', name: 'Other', odds: 10.0, probability: 0.10, volume: 500000 },
          ],
          closes_at: new Date(Date.now() + 86400000 * 90).toISOString(),
          status: 'open',
        },
      ]);
      setUserBets([
        {
          id: '1',
          market_title: 'BTC Reaches $150K in 2026',
          outcome: 'Yes',
          amount: 500,
          odds: 2.2,
          potential_payout: 1100,
          status: 'pending',
          placed_at: new Date(Date.now() - 86400000).toISOString(),
        },
        {
          id: '2',
          market_title: 'Super Bowl 2026 Winner',
          outcome: 'Kansas City Chiefs',
          amount: 250,
          odds: 2.5,
          potential_payout: 625,
          status: 'pending',
          placed_at: new Date(Date.now() - 172800000).toISOString(),
        },
        {
          id: '3',
          market_title: 'NBA Finals 2025',
          outcome: 'Boston Celtics',
          amount: 300,
          odds: 3.0,
          potential_payout: 900,
          status: 'won',
          placed_at: new Date(Date.now() - 2592000000).toISOString(),
          settled_at: new Date(Date.now() - 1296000000).toISOString(),
        },
      ]);
      setStats({
        total_bets: 15,
        active_bets: 2,
        total_wagered: 3750,
        total_winnings: 4200,
        win_rate: 0.60,
        roi: 0.12,
      });
    } finally {
      setLoading(false);
    }
  };

  const placeBet = async (marketId: string, outcomeId: string, amount: number) => {
    try {
      const response = await fetch('/api/v1/betting/place', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ market_id: marketId, outcome_id: outcomeId, amount }),
      });
      
      if (response.ok) {
        fetchBettingData();
      }
    } catch (err) {
      console.error('Failed to place bet:', err);
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'sports': return 'text-green-400 bg-green-500/20';
      case 'politics': return 'text-blue-400 bg-blue-500/20';
      case 'entertainment': return 'text-purple-400 bg-purple-500/20';
      case 'crypto': return 'text-orange-400 bg-orange-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'won': return 'text-green-400 bg-green-500/20';
      case 'lost': return 'text-red-400 bg-red-500/20';
      case 'pending': return 'text-yellow-400 bg-yellow-500/20';
      case 'refunded': return 'text-gray-400 bg-gray-500/20';
      default: return 'text-gray-400 bg-gray-500/20';
    }
  };

  const formatTimeRemaining = (closeDate: string) => {
    const now = new Date();
    const close = new Date(closeDate);
    const diffMs = close.getTime() - now.getTime();
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffDays > 30) return `${Math.floor(diffDays / 30)} months`;
    if (diffDays > 0) return `${diffDays} days`;
    return 'Closing soon';
  };

  const filteredMarkets = selectedCategory === 'all' 
    ? markets 
    : markets.filter(m => m.category === selectedCategory);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-blue-500 mx-auto mb-2" />
          <p className="text-gray-400">Loading betting markets...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Trophy className="w-8 h-8 text-yellow-500" />
          <div>
            <h1 className="text-2xl font-bold text-white">Betting Markets</h1>
            <p className="text-sm text-gray-400">Sports, politics, crypto, and more</p>
          </div>
        </div>
        <button
          onClick={fetchBettingData}
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

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Total Bets</p>
            <p className="text-2xl font-bold text-white">{stats.total_bets}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Active Bets</p>
            <p className="text-2xl font-bold text-yellow-400">{stats.active_bets}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Total Wagered</p>
            <p className="text-2xl font-bold text-white">${stats.total_wagered.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Total Winnings</p>
            <p className="text-2xl font-bold text-green-400">${stats.total_winnings.toLocaleString()}</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">Win Rate</p>
            <p className="text-2xl font-bold text-white">{(stats.win_rate * 100).toFixed(0)}%</p>
          </div>
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
            <p className="text-sm text-gray-400 mb-1">ROI</p>
            <p className="text-2xl font-bold text-green-400">+{(stats.roi * 100).toFixed(1)}%</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {(['markets', 'mybets', 'stats'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-medium transition-colors ${
              activeTab === tab
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab === 'markets' ? 'Markets' : tab === 'mybets' ? 'My Bets' : 'Statistics'}
          </button>
        ))}
      </div>

      {/* Markets Tab */}
      {activeTab === 'markets' && (
        <div className="space-y-6">
          {/* Category Filter */}
          <div className="flex gap-2">
            {['all', 'sports', 'crypto', 'politics', 'entertainment'].map(cat => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  selectedCategory === cat
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
                }`}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>

          {/* Markets List */}
          <div className="space-y-4">
            {filteredMarkets.map(market => (
              <div key={market.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-bold text-white">{market.title}</h3>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${getCategoryColor(market.category)}`}>
                        {market.category}
                      </span>
                    </div>
                    <p className="text-sm text-gray-400 mb-3">{market.description}</p>
                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      <div className="flex items-center gap-1">
                        <DollarSign className="w-4 h-4" />
                        <span>${market.total_volume.toLocaleString()} volume</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Clock className="w-4 h-4" />
                        <span>Closes in {formatTimeRemaining(market.closes_at)}</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="space-y-2">
                  {market.outcomes.map(outcome => (
                    <div key={outcome.id} className="flex items-center justify-between p-3 bg-slate-900/50 rounded-lg hover:bg-slate-900/70 transition-colors">
                      <div className="flex-1">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-white font-medium">{outcome.name}</span>
                          <div className="flex items-center gap-4">
                            <span className="text-sm text-gray-400">{(outcome.probability * 100).toFixed(0)}% prob</span>
                            <span className="text-lg font-bold text-green-400">{outcome.odds.toFixed(2)}x</span>
                          </div>
                        </div>
                        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500"
                            style={{ width: `${outcome.probability * 100}%` }}
                          />
                        </div>
                      </div>
                      <button
                        onClick={() => placeBet(market.id, outcome.id, 100)}
                        className="ml-4 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
                      >
                        Bet
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* My Bets Tab */}
      {activeTab === 'mybets' && (
        <div className="space-y-4">
          {userBets.map(bet => (
            <div key={bet.id} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <h4 className="text-white font-bold mb-1">{bet.market_title}</h4>
                  <p className="text-sm text-gray-400 mb-2">Outcome: {bet.outcome}</p>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="text-gray-400">Wagered: ${bet.amount}</span>
                    <span className="text-gray-400">Odds: {bet.odds}x</span>
                    <span className="text-green-400">Potential: ${bet.potential_payout}</span>
                  </div>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(bet.status)}`}>
                  {bet.status}
                </span>
              </div>
              <p className="text-xs text-gray-500">
                Placed {new Date(bet.placed_at).toLocaleDateString()}
                {bet.settled_at && ` • Settled ${new Date(bet.settled_at).toLocaleDateString()}`}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Stats Tab */}
      {activeTab === 'stats' && stats && (
        <div className="space-y-6">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
            <h3 className="text-lg font-bold text-white mb-4">Performance Overview</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <p className="text-sm text-gray-400 mb-2">Win Rate</p>
                <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-green-500 to-emerald-500"
                    style={{ width: `${stats.win_rate * 100}%` }}
                  />
                </div>
                <p className="text-2xl font-bold text-white mt-2">{(stats.win_rate * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-sm text-gray-400 mb-2">Return on Investment</p>
                <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-purple-500"
                    style={{ width: `${Math.min(stats.roi * 100, 100)}%` }}
                  />
                </div>
                <p className="text-2xl font-bold text-green-400 mt-2">+{(stats.roi * 100).toFixed(1)}%</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <h4 className="text-white font-semibold mb-4">Profit/Loss</h4>
              <p className="text-3xl font-bold text-green-400">
                +${(stats.total_winnings - stats.total_wagered).toLocaleString()}
              </p>
              <p className="text-sm text-gray-400 mt-2">
                ${stats.total_winnings.toLocaleString()} won - ${stats.total_wagered.toLocaleString()} wagered
              </p>
            </div>

            <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
              <h4 className="text-white font-semibold mb-4">Betting Activity</h4>
              <p className="text-3xl font-bold text-white">{stats.total_bets}</p>
              <p className="text-sm text-gray-400 mt-2">
                {stats.active_bets} active • {stats.total_bets - stats.active_bets} settled
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
