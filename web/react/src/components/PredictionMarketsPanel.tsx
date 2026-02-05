import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { api } from '../services/api';
import type { PredictionMarket } from '../services/api';

export default function PredictionMarketsPanel() {
  const [markets, setMarkets] = useState<PredictionMarket[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchMarkets() {
      try {
        const data = await api.getPredictionMarkets();
        setMarkets(data.markets || []);
      } catch (e) {
        console.error('Failed to fetch prediction markets:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchMarkets();
    const interval = setInterval(fetchMarkets, 30000); // Update every 30s for live data
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-slate-700 rounded w-1/3"></div>
          <div className="h-4 bg-slate-700 rounded"></div>
          <div className="h-4 bg-slate-700 rounded"></div>
          <div className="h-4 bg-slate-700 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-200">Prediction Markets</h2>
          <p className="text-sm text-slate-400">Live from Kalshi</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Activity className="w-4 h-4" />
          <span>{markets.length} markets</span>
        </div>
      </div>

      {markets.length === 0 ? (
        <div className="text-center py-8 text-slate-500">
          No prediction markets available
        </div>
      ) : (
        <div className="space-y-3">
          {markets.slice(0, 5).map((market, index) => (
            <div
              key={market.market_id || `market-${index}`}
              className="p-4 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-slate-200 mb-1 line-clamp-2">
                    {market.question}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                      {market.category}
                    </span>
                    <span>•</span>
                    <span>{market.platform}</span>
                  </div>
                </div>
                
                <div className="flex gap-3 shrink-0">
                  <div className="text-center">
                    <div className="flex items-center gap-1 text-emerald-400 font-semibold">
                      <TrendingUp className="w-3 h-3" />
                      <span>{(market.yes_price * 100).toFixed(0)}¢</span>
                    </div>
                    <div className="text-xs text-slate-500">YES</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center gap-1 text-rose-400 font-semibold">
                      <TrendingDown className="w-3 h-3" />
                      <span>{(market.no_price * 100).toFixed(0)}¢</span>
                    </div>
                    <div className="text-xs text-slate-500">NO</div>
                  </div>
                </div>
              </div>
              
              {market.volume_24h > 0 && (
                <div className="mt-2 text-xs text-slate-500">
                  24h Volume: ${market.volume_24h.toLocaleString()}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {markets.length > 5 && (
        <button className="mt-4 w-full py-2 text-sm text-blue-400 hover:text-blue-300 transition-colors">
          View all {markets.length} markets →
        </button>
      )}
    </div>
  );
}
