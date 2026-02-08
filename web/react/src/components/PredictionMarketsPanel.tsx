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
          {markets.slice(0, 5).map((market, index) => {
            const yesPrice = ((market as any).yesPrice ?? market.yes_price ?? 0);
            const noPrice = ((market as any).noPrice ?? market.no_price ?? 0);
            const volume = (market as any).volume || market.volume_24h || 0;
            const endTime = (market as any).endTime || market.close_date;
            const position = (market as any).ourPosition;
            const pnl = (market as any).ourPnl;
            const confidence = (market as any).modelConfidence;

            return (
              <div
                key={(market as any).id || market.market_id || `market-${index}`}
                className="p-4 bg-slate-800/50 rounded-lg border border-slate-700 hover:border-slate-600 transition-colors"
              >
                {/* Question */}
                <p className="text-sm font-medium text-slate-200 mb-2 line-clamp-2 leading-relaxed">
                  {market.question || (market as any).symbol || 'Market'}
                </p>

                {/* Tags row */}
                <div className="flex flex-wrap items-center gap-2 text-xs mb-3">
                  <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                    {market.category || (market as any).symbol || 'Prediction'}
                  </span>
                  <span className="text-slate-500">{market.platform || 'Kalshi'}</span>
                  {endTime && (
                    <>
                      <span className="text-slate-600">•</span>
                      <span className="text-slate-500">Closes {new Date(endTime).toLocaleDateString()}</span>
                    </>
                  )}
                </div>

                {/* Prices + Stats row */}
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex items-center gap-1 text-emerald-400 font-semibold text-sm">
                    <TrendingUp className="w-3.5 h-3.5" />
                    <span>YES {(yesPrice * 100).toFixed(0)}¢</span>
                  </div>
                  <div className="flex items-center gap-1 text-rose-400 font-semibold text-sm">
                    <TrendingDown className="w-3.5 h-3.5" />
                    <span>NO {(noPrice * 100).toFixed(0)}¢</span>
                  </div>

                  {volume > 0 && (
                    <span className="text-xs text-slate-500 ml-auto">Vol ${volume.toLocaleString()}</span>
                  )}
                </div>

                {/* Position row (if we have one) */}
                {position && (
                  <div className="flex items-center gap-3 mt-2 pt-2 border-t border-slate-700/50 text-xs">
                    <span className={`font-semibold ${position === 'YES' ? 'text-emerald-400' : 'text-rose-400'}`}>
                      Our position: {position}
                    </span>
                    {pnl !== undefined && (
                      <span className={pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        P&L: {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                      </span>
                    )}
                    {confidence !== undefined && (
                      <span className="text-slate-400 ml-auto">
                        Confidence: {(confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
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
