import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Package, AlertTriangle } from 'lucide-react';

interface Position {
  symbol: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number;
  marketValue: number;
  unrealizedPnl: number;
  unrealizedPnlPct: number;
  side: 'long' | 'short';
  venue: string;
}

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Simulated data - replace with real API call
    const mockPositions: Position[] = [
      { symbol: 'AAPL', quantity: 150, avgPrice: 180.25, currentPrice: 185.50, marketValue: 27825.00, unrealizedPnl: 787.50, unrealizedPnlPct: 2.91, side: 'long', venue: 'Alpaca' },
      { symbol: 'TSLA', quantity: 75, avgPrice: 250.00, currentPrice: 245.00, marketValue: 18375.00, unrealizedPnl: -375.00, unrealizedPnlPct: -2.00, side: 'long', venue: 'Alpaca' },
      { symbol: 'BTC-USD', quantity: 0.75, avgPrice: 42000.00, currentPrice: 42500.00, marketValue: 31875.00, unrealizedPnl: 375.00, unrealizedPnlPct: 1.19, side: 'long', venue: 'Coinbase' },
      { symbol: 'ETH-USD', quantity: 5.5, avgPrice: 2600.00, currentPrice: 2550.00, marketValue: 14025.00, unrealizedPnl: -275.00, unrealizedPnlPct: -1.92, side: 'long', venue: 'Kraken' },
    ];
    
    setTimeout(() => {
      setPositions(mockPositions);
      setLoading(false);
    }, 500);
  }, []);

  const totalValue = positions.reduce((sum, p) => sum + p.marketValue, 0);
  const totalPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0);
  const totalPnlPct = totalValue > 0 ? (totalPnl / (totalValue - totalPnl)) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Positions</h1>
          <p className="text-slate-400">Active portfolio positions across all venues</p>
        </div>
        <div className="flex gap-3">
          <button className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-medium transition-colors">
            Export CSV
          </button>
          <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition-colors">
            Rebalance
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <Package className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-slate-400">Total Market Value</span>
          </div>
          <div className="text-2xl font-semibold">${totalValue.toLocaleString()}</div>
          <div className="text-sm text-slate-400 mt-1">{positions.length} positions</div>
        </div>
        
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            {totalPnl >= 0 ? <TrendingUp className="w-4 h-4 text-emerald-400" /> : <TrendingDown className="w-4 h-4 text-rose-400" />}
            <span className="text-sm text-slate-400">Unrealized P&L</span>
          </div>
          <div className={`text-2xl font-semibold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString()}
          </div>
          <div className={`text-sm mt-1 ${totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%
          </div>
        </div>
        
        <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <span className="text-sm text-slate-400">Risk Exposure</span>
          </div>
          <div className="text-2xl font-semibold text-slate-200">25.0%</div>
          <div className="text-sm text-slate-400 mt-1">of buying power</div>
        </div>
      </div>

      {/* Positions Grid */}
      {loading ? (
        <div className="bg-slate-900/70 rounded-xl p-8 border border-slate-800 text-center">
          <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
          <p className="text-slate-400">Loading positions...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {positions.map((position) => (
            <div key={position.symbol} className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 hover:border-slate-700 transition-colors">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-lg">{position.symbol}</h3>
                  <span className="text-xs text-slate-500 px-2 py-0.5 bg-slate-800 rounded">{position.venue}</span>
                </div>
                <div className={`px-3 py-1 rounded-full text-sm font-medium ${position.unrealizedPnl >= 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                  {position.unrealizedPnl >= 0 ? '+' : ''}{position.unrealizedPnlPct.toFixed(2)}%
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="text-slate-500">Quantity</div>
                  <div className="font-medium">{position.quantity}</div>
                </div>
                <div>
                  <div className="text-slate-500">Market Value</div>
                  <div className="font-medium">${position.marketValue.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-slate-500">Avg Price</div>
                  <div className="font-medium">${position.avgPrice.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-slate-500">Current Price</div>
                  <div className="font-medium">${position.currentPrice.toFixed(2)}</div>
                </div>
              </div>
              
              <div className="mt-4 pt-3 border-t border-slate-800 flex justify-between items-center">
                <span className="text-sm text-slate-500">Unrealized P&L</span>
                <span className={`font-semibold ${position.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {position.unrealizedPnl >= 0 ? '+' : ''}${position.unrealizedPnl.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
