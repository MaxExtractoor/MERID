/**
 * Markets Overview Component
 * Displays stocks, forex, and commodities in real-time
 */

import React from 'react';
import { useStocks, useForex, useCommodities } from '../hooks/useMarketsData';

function MarketsOverview() {
  const { data: stocks, loading: stocksLoading } = useStocks();
  const { data: forex, loading: forexLoading } = useForex();
  const { data: commodities, loading: commoditiesLoading } = useCommodities();

  return (
    <div className="space-y-6">
      {/* Stocks Section */}
      <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <h3 className="text-xl font-bold text-white mb-4 flex items-center">
          📈 Stocks & Equities
          {stocksLoading && <span className="ml-2 text-sm text-slate-400 animate-pulse">Loading...</span>}
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {stocks.slice(0, 12).map((stock) => (
            <div key={stock.symbol} className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-sm font-semibold text-slate-300">{stock.symbol}</div>
              <div className="text-lg font-bold text-white">${stock.price.toFixed(2)}</div>
              <div className={`text-sm ${stock.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct.toFixed(2)}%
              </div>
              <div className="text-xs text-slate-500">{stock.source}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Forex Section */}
      <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <h3 className="text-xl font-bold text-white mb-4 flex items-center">
          💱 Forex & Currencies
          {forexLoading && <span className="ml-2 text-sm text-slate-400 animate-pulse">Loading...</span>}
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {forex.slice(0, 12).map((rate) => (
            <div key={rate.pair} className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-sm font-semibold text-slate-300">{rate.pair}</div>
              <div className="text-lg font-bold text-white">{rate.rate.toFixed(4)}</div>
              <div className="text-xs text-slate-500">
                Bid: {rate.bid.toFixed(4)} | Ask: {rate.ask.toFixed(4)}
              </div>
              <div className="text-xs text-slate-500">{rate.source}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Commodities Section */}
      <div className="bg-slate-900/70 rounded-xl p-6 border border-slate-800">
        <h3 className="text-xl font-bold text-white mb-4 flex items-center">
          🪙 Commodities & Metals
          {commoditiesLoading && <span className="ml-2 text-sm text-slate-400 animate-pulse">Loading...</span>}
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {commodities.map((commodity) => (
            <div key={commodity.symbol} className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-sm font-semibold text-slate-300">{commodity.name}</div>
              <div className="text-lg font-bold text-white">${commodity.price.toFixed(2)}</div>
              <div className={`text-sm ${commodity.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {commodity.change_pct >= 0 ? '+' : ''}{commodity.change_pct.toFixed(2)}%
              </div>
              <div className="text-xs text-slate-500">{commodity.unit}</div>
              <div className="text-xs text-slate-500">{commodity.source}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const MemoizedMarketsOverview = React.memo(MarketsOverview);
MemoizedMarketsOverview.displayName = 'MarketsOverview';
export default MemoizedMarketsOverview;
