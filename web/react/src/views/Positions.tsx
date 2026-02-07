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
    const fetchPositions = async () => {
      try {
        const res = await fetch('/api/v1/trading/portfolio/summary');
        if (res.ok) {
          const data = await res.json();
          if (data.positions && data.positions.length > 0) {
            setPositions(data.positions.map((p: any) => ({
              symbol: p.asset || p.symbol || 'Unknown',
              quantity: p.size || p.quantity || 0,
              avgPrice: p.avg_price || p.avgPrice || 0,
              currentPrice: p.current_price || p.currentPrice || 0,
              marketValue: p.size_usd || p.marketValue || Math.abs(p.size || 0) * (p.current_price || 0),
              unrealizedPnl: p.pnl || p.unrealizedPnl || 0,
              unrealizedPnlPct: p.pnl_pct || p.unrealizedPnlPct || 0,
              side: (p.side || 'long').toLowerCase() as 'long' | 'short',
              venue: p.venue || 'Paper',
            })));
            setLoading(false);
            return;
          }
        }
      } catch (err) {
        console.warn('Failed to fetch positions from API, showing empty state');
      }
      setPositions([]);
      setLoading(false);
    };

    fetchPositions();
    const interval = setInterval(fetchPositions, 5000);
    return () => clearInterval(interval);
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
