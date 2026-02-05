import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, DollarSign, X, RefreshCw, AlertCircle, Activity, Clock, Target } from 'lucide-react';

interface PaperPosition {
  position_id: string;
  asset: string;
  side: string;
  size_usd: number;
  entry_price: number;
  current_price: number;
  leverage: number;
  unrealized_pnl: number;
  opened_at: number;
  market_type: string;
}

interface PaperOrder {
  order_id: string;
  asset: string;
  side: string;
  order_type: string;
  size_usd: number;
  price?: number;
  status: string;
  created_at: number;
}

interface PortfolioStats {
  user_id: string;
  starting_balance: number;
  current_balance: number;
  total_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  positions: PaperPosition[];
  orders: PaperOrder[];
}

interface PaperTradingPanelProps {
  className?: string;
  userId?: string;
}

export default function PaperTradingPanel({ className = '', userId = 'default' }: PaperTradingPanelProps) {
  const [stats, setStats] = useState<PortfolioStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<'positions' | 'orders' | 'history'>('positions');

  useEffect(() => {
    fetchPortfolioData();
    const interval = setInterval(fetchPortfolioData, 5000);
    return () => clearInterval(interval);
  }, [userId]);

  const fetchPortfolioData = async () => {
    try {
      const response = await fetch(`/api/v1/paper-trading/portfolio/${userId}`);
      if (response.ok) {
        const data = await response.json();
        setStats(data);
        setError(null);
      } else {
        throw new Error('Failed to fetch portfolio data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      // Fallback mock data
      setStats({
        user_id: userId,
        starting_balance: 10000,
        current_balance: 10450.25,
        total_pnl: 450.25,
        total_trades: 12,
        winning_trades: 8,
        losing_trades: 4,
        positions: [
          {
            position_id: 'pos_1',
            asset: 'BTC-USD',
            side: 'long',
            size_usd: 1000,
            entry_price: 105000,
            current_price: 105500,
            leverage: 2,
            unrealized_pnl: 9.52,
            opened_at: Date.now() - 3600000,
            market_type: 'perp'
          },
          {
            position_id: 'pos_2',
            asset: 'ETH-USD',
            side: 'long',
            size_usd: 500,
            entry_price: 3850,
            current_price: 3880,
            leverage: 1,
            unrealized_pnl: 3.90,
            opened_at: Date.now() - 7200000,
            market_type: 'perp'
          }
        ],
        orders: [
          {
            order_id: 'order_1',
            asset: 'SOL-USD',
            side: 'long',
            order_type: 'limit',
            size_usd: 300,
            price: 144.50,
            status: 'pending',
            created_at: Date.now() - 1800000
          }
        ]
      });
    } finally {
      setLoading(false);
    }
  };

  const closePosition = async (positionId: string) => {
    try {
      const response = await fetch(`/api/v1/paper-trading/positions/${positionId}/close`, {
        method: 'POST'
      });
      if (response.ok) {
        fetchPortfolioData();
      }
    } catch (err) {
      console.error('Failed to close position:', err);
    }
  };

  const cancelOrder = async (orderId: string) => {
    try {
      const response = await fetch(`/api/v1/paper-trading/orders/${orderId}/cancel`, {
        method: 'POST'
      });
      if (response.ok) {
        fetchPortfolioData();
      }
    } catch (err) {
      console.error('Failed to cancel order:', err);
    }
  };

  const formatTime = (timestamp: number) => {
    const diff = Date.now() - timestamp;
    const hours = Math.floor(diff / 3600000);
    if (hours < 1) return `${Math.floor(diff / 60000)}m`;
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  };

  const winRate = stats ? (stats.total_trades > 0 ? (stats.winning_trades / stats.total_trades) * 100 : 0) : 0;
  const pnlPercent = stats ? ((stats.total_pnl / stats.starting_balance) * 100) : 0;

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading portfolio...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Using fallback data</p>
            <p className="text-sm text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Portfolio Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="w-4 h-4 text-blue-400" />
            <p className="text-xs text-gray-400">Balance</p>
          </div>
          <p className="text-2xl font-bold text-white">${stats?.current_balance.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</p>
          <p className="text-xs text-gray-500">Start: ${stats?.starting_balance.toLocaleString()}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            {(stats?.total_pnl || 0) >= 0 ? (
              <TrendingUp className="w-4 h-4 text-green-400" />
            ) : (
              <TrendingDown className="w-4 h-4 text-red-400" />
            )}
            <p className="text-xs text-gray-400">Total P&L</p>
          </div>
          <p className={`text-2xl font-bold ${(stats?.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {(stats?.total_pnl || 0) >= 0 ? '+' : ''}${stats?.total_pnl.toFixed(2)}
          </p>
          <p className={`text-xs ${pnlPercent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-purple-400" />
            <p className="text-xs text-gray-400">Trades</p>
          </div>
          <p className="text-2xl font-bold text-white">{stats?.total_trades || 0}</p>
          <p className="text-xs text-gray-500">
            <span className="text-green-400">{stats?.winning_trades || 0}W</span> / 
            <span className="text-red-400 ml-1">{stats?.losing_trades || 0}L</span>
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4 text-cyan-400" />
            <p className="text-xs text-gray-400">Win Rate</p>
          </div>
          <p className="text-2xl font-bold text-cyan-400">{winRate.toFixed(1)}%</p>
          <p className="text-xs text-gray-500">
            {stats?.positions.length || 0} open positions
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
        <div className="border-b border-slate-700/50 px-4">
          <div className="flex gap-4">
            {(['positions', 'orders', 'history'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setSelectedTab(tab)}
                className={`py-3 px-2 text-sm font-medium border-b-2 transition-colors ${
                  selectedTab === tab
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-gray-400 hover:text-gray-300'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div className="p-4">
          {/* Positions Tab */}
          {selectedTab === 'positions' && (
            <div className="space-y-3">
              {stats?.positions.length === 0 ? (
                <div className="text-center py-8">
                  <Activity className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                  <p className="text-gray-400">No open positions</p>
                </div>
              ) : (
                stats?.positions.map(position => (
                  <div key={position.position_id} className="bg-slate-700/30 rounded-lg p-4 border border-slate-700/50">
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <p className="text-white font-bold text-lg">{position.asset}</p>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            position.side === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                          }`}>
                            {position.side.toUpperCase()}
                          </span>
                          {position.leverage > 1 && (
                            <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded text-xs font-medium">
                              {position.leverage}x
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-gray-400">
                          <Clock className="w-3 h-3 inline mr-1" />
                          {formatTime(position.opened_at)} ago
                        </p>
                      </div>
                      <button
                        onClick={() => closePosition(position.position_id)}
                        className="p-2 hover:bg-red-500/20 rounded transition-colors"
                        title="Close position"
                        aria-label="Close position"
                      >
                        <X className="w-4 h-4 text-red-400" />
                      </button>
                    </div>

                    <div className="grid grid-cols-3 gap-3 mb-3">
                      <div>
                        <p className="text-xs text-gray-500">Size</p>
                        <p className="text-sm text-white font-medium">${position.size_usd.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Entry</p>
                        <p className="text-sm text-white font-medium">${position.entry_price.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-500">Current</p>
                        <p className="text-sm text-white font-medium">${position.current_price.toLocaleString()}</p>
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-3 border-t border-slate-700/50">
                      <span className="text-xs text-gray-400">Unrealized P&L</span>
                      <span className={`text-lg font-bold ${position.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Orders Tab */}
          {selectedTab === 'orders' && (
            <div className="space-y-3">
              {stats?.orders.length === 0 ? (
                <div className="text-center py-8">
                  <Activity className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                  <p className="text-gray-400">No pending orders</p>
                </div>
              ) : (
                stats?.orders.map(order => (
                  <div key={order.order_id} className="bg-slate-700/30 rounded-lg p-4 border border-slate-700/50">
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="flex items-center gap-2 mb-1">
                          <p className="text-white font-bold">{order.asset}</p>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            order.side === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                          }`}>
                            {order.side.toUpperCase()}
                          </span>
                          <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs font-medium">
                            {order.order_type.toUpperCase()}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400">{formatTime(order.created_at)} ago</p>
                      </div>
                      <button
                        onClick={() => cancelOrder(order.order_id)}
                        className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded transition-colors"
                      >
                        Cancel
                      </button>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-gray-500">Size</p>
                        <p className="text-sm text-white font-medium">${order.size_usd.toLocaleString()}</p>
                      </div>
                      {order.price && (
                        <div>
                          <p className="text-xs text-gray-500">Price</p>
                          <p className="text-sm text-white font-medium">${order.price.toLocaleString()}</p>
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* History Tab */}
          {selectedTab === 'history' && (
            <div className="text-center py-8">
              <Activity className="w-12 h-12 text-slate-600 mx-auto mb-3" />
              <p className="text-gray-400">Trade history coming soon</p>
              <p className="text-sm text-gray-500 mt-1">View detailed trade history and analytics</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
