import { useState, useEffect } from 'react';
import { TrendingUp, ArrowRight, RefreshCw, AlertCircle, Zap, DollarSign } from 'lucide-react';

interface ArbitrageOpportunity {
  id: string;
  symbol: string;
  buy_venue: string;
  sell_venue: string;
  buy_price: number;
  sell_price: number;
  spread_pct: number;
  profit_usd: number;
  volume_available: number;
  confidence: number;
  expires_in: number;
  status: 'active' | 'executing' | 'expired';
}

interface ArbitragePanelProps {
  className?: string;
}

export default function ArbitragePanel({ className = '' }: ArbitragePanelProps) {
  const [opportunities, setOpportunities] = useState<ArbitrageOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'high' | 'medium'>('all');

  useEffect(() => {
    fetchOpportunities();
    const interval = setInterval(fetchOpportunities, 10000); // Refresh every 10s
    return () => clearInterval(interval);
  }, []);

  const fetchOpportunities = async () => {
    try {
      const response = await fetch('/api/v1/arbitrage/opportunities');
      if (response.ok) {
        const data = await response.json();
        setOpportunities(data.opportunities || []);
        setError(null);
      } else {
        throw new Error('Failed to fetch arbitrage opportunities');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setOpportunities([]);
    } finally {
      setLoading(false);
    }
  };

  const executeArbitrage = async (opportunityId: string) => {
    try {
      const response = await fetch('/api/v1/arbitrage/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opportunity_id: opportunityId }),
      });
      
      if (response.ok) {
        // Update opportunity status
        setOpportunities(opportunities.map(opp => 
          opp.id === opportunityId ? { ...opp, status: 'executing' as const } : opp
        ));
      }
    } catch (err) {
      console.error('Failed to execute arbitrage:', err);
    }
  };

  const getSpreadColor = (spread: number) => {
    if (spread >= 0.3) return 'text-green-400';
    if (spread >= 0.15) return 'text-yellow-400';
    return 'text-gray-400';
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.9) return 'text-green-400';
    if (confidence >= 0.8) return 'text-yellow-400';
    return 'text-orange-400';
  };

  const filteredOpportunities = opportunities.filter(opp => {
    if (filter === 'high') return opp.spread_pct >= 0.3;
    if (filter === 'medium') return opp.spread_pct >= 0.15 && opp.spread_pct < 0.3;
    return true;
  });

  const totalProfit = opportunities.reduce((sum, opp) => sum + opp.profit_usd, 0);
  const avgSpread = opportunities.length > 0 
    ? opportunities.reduce((sum, opp) => sum + opp.spread_pct, 0) / opportunities.length 
    : 0;

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading arbitrage opportunities...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-slate-700/50">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <TrendingUp className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Arbitrage Opportunities</h2>
              <p className="text-sm text-gray-400">Cross-venue price discrepancies</p>
            </div>
          </div>
          <button
            onClick={fetchOpportunities}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh opportunities"
          >
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-yellow-900/20 border border-yellow-600/50 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-yellow-500" />
            <span className="text-sm text-yellow-500">Data unavailable: {error}</span>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center p-3 bg-slate-700/30 rounded-lg">
            <p className="text-2xl font-bold text-white">{opportunities.length}</p>
            <p className="text-xs text-gray-400">Active Opportunities</p>
          </div>
          <div className="text-center p-3 bg-slate-700/30 rounded-lg">
            <p className="text-2xl font-bold text-green-400">${totalProfit.toFixed(2)}</p>
            <p className="text-xs text-gray-400">Total Potential Profit</p>
          </div>
          <div className="text-center p-3 bg-slate-700/30 rounded-lg">
            <p className="text-2xl font-bold text-blue-400">{avgSpread.toFixed(2)}%</p>
            <p className="text-xs text-gray-400">Avg Spread</p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mt-4">
          {(['all', 'high', 'medium'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 text-sm rounded transition-colors ${
                filter === f
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
              }`}
            >
              {f === 'all' ? 'All' : f === 'high' ? 'High (>0.3%)' : 'Medium (0.15-0.3%)'}
            </button>
          ))}
        </div>
      </div>

      {/* Opportunities List */}
      <div className="max-h-96 overflow-y-auto">
        {filteredOpportunities.length === 0 ? (
          <div className="p-8 text-center">
            <Zap className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <p className="text-gray-400">No arbitrage opportunities found</p>
            <p className="text-sm text-gray-500 mt-1">Opportunities appear when price spreads exist</p>
          </div>
        ) : (
          filteredOpportunities.map(opp => (
            <div
              key={opp.id}
              className="p-4 border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="text-left">
                    <p className="text-white font-bold text-lg">{opp.symbol}</p>
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <span>{opp.buy_venue}</span>
                      <ArrowRight className="w-3 h-3" />
                      <span>{opp.sell_venue}</span>
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <p className={`text-2xl font-bold ${getSpreadColor(opp.spread_pct)}`}>
                    {opp.spread_pct.toFixed(2)}%
                  </p>
                  <p className="text-sm text-gray-400">spread</p>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-3 mb-3">
                <div>
                  <p className="text-xs text-gray-500">Buy Price</p>
                  <p className="text-sm text-white font-medium">${opp.buy_price.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Sell Price</p>
                  <p className="text-sm text-white font-medium">${opp.sell_price.toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Profit</p>
                  <p className="text-sm text-green-400 font-medium">
                    <DollarSign className="w-3 h-3 inline" />
                    {opp.profit_usd.toFixed(2)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Volume</p>
                  <p className="text-sm text-white font-medium">{opp.volume_available}</p>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4 text-xs">
                  <div className="flex items-center gap-1">
                    <span className="text-gray-500">Confidence:</span>
                    <span className={`font-medium ${getConfidenceColor(opp.confidence)}`}>
                      {(opp.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-gray-500">Expires:</span>
                    <span className={`font-medium ${opp.expires_in < 30 ? 'text-red-400' : 'text-gray-400'}`}>
                      {opp.expires_in}s
                    </span>
                  </div>
                </div>

                {opp.status === 'active' ? (
                  <button
                    onClick={() => executeArbitrage(opp.id)}
                    className="px-4 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors flex items-center gap-1"
                  >
                    <Zap className="w-3 h-3" />
                    Execute
                  </button>
                ) : opp.status === 'executing' ? (
                  <span className="px-4 py-1.5 bg-blue-600/50 text-blue-300 text-sm rounded flex items-center gap-1">
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    Executing...
                  </span>
                ) : (
                  <span className="px-4 py-1.5 bg-gray-600/50 text-gray-400 text-sm rounded">
                    Expired
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-slate-700/50 bg-slate-900/50">
        <p className="text-xs text-gray-500 text-center">
          Auto-refreshing every 10 seconds • Opportunities expire quickly
        </p>
      </div>
    </div>
  );
}
