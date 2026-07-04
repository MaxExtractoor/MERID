/**
 * Trade — Order Entry and Position Management
 * 
 * Purpose: Consolidated trading view for order entry and position management
 * 
 * Content:
 * - Market discovery (15m crypto markets only)
 * - Order entry (trade ticket)
 * - Orderbook (real-time)
 * - Orders management (resting, filled, cancelled)
 * - Positions summary (exposure, unrealized PnL)
 * 
 * Data: Markets, orders, positions (from store)
 * 
 * TODO: Integrate with store once orders/positions are available via WebSocket
 */

import { useState } from 'react';
import { useKalshiStore, selectPortfolio } from '../store';
import { Monitor, Search, Briefcase, ClipboardList } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { API_BASE_URL } from '../config/constants';
import { useApiQuery } from '../hooks/useTanStackQuery';
import KalshiTradeTicket from '../components/KalshiTradeTicket';

interface KalshiMarket {
  ticker: string;
  title: string;
  subtitle: string;
  close_time: string;
  yes_price: number;
  no_price: number;
  volume: number;
}

const Trade = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const positions = portfolio.positions;
  const [selectedMarket, setSelectedMarket] = useState<KalshiMarket | null>(null);
  const [activeTab, setActiveTab] = useState<'markets' | 'positions' | 'orders'>('markets');

  // Fetch Kalshi market catalog for 15m crypto using TanStack Query
  const { data: marketsData, isLoading, error } = useApiQuery<{ markets: KalshiMarket[] }>(
    `${API_BASE_URL}/api/v1/kalshi/markets`,
    {
      refetchInterval: 30_000, // Refresh every 30 seconds
      staleTime: 10_000,
    }
  );

  // Filter for 15m crypto markets (BTC, ETH, SOL, XRP, DOGE)
  const markets = marketsData?.markets?.filter((m: KalshiMarket) => 
    ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'].some(asset => m.ticker.includes(asset)) &&
    m.ticker.includes('15m')
  ) || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Monitor className="w-8 h-8 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Trade</h1>
            <p className="text-sm text-slate-400">Order entry and position management</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit" role="tablist" aria-label="Trade view tabs">
        <button 
          onClick={() => setActiveTab('markets')}
          role="tab"
          aria-selected={activeTab === 'markets'}
          aria-controls="markets-panel"
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium ${
            activeTab === 'markets' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          <Search className="w-4 h-4" aria-hidden="true" />
          Markets
        </button>
        <button 
          onClick={() => setActiveTab('positions')}
          role="tab"
          aria-selected={activeTab === 'positions'}
          aria-controls="positions-panel"
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium ${
            activeTab === 'positions' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          <Briefcase className="w-4 h-4" aria-hidden="true" />
          Positions
        </button>
        <button 
          onClick={() => setActiveTab('orders')}
          role="tab"
          aria-selected={activeTab === 'orders'}
          aria-controls="orders-panel"
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium ${
            activeTab === 'orders' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
          }`}
        >
          <ClipboardList className="w-4 h-4" aria-hidden="true" />
          Orders
        </button>
      </div>

      {/* Markets Tab */}
      {activeTab === 'markets' && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>15m Crypto Markets (BTC, ETH, SOL, XRP, DOGE)</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="text-center py-8 text-slate-500" role="status" aria-live="polite">Loading markets...</div>
              ) : error ? (
                <div className="text-center py-8 text-red-400" role="alert">{String(error)}</div>
              ) : markets.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  <Search className="w-12 h-12 mx-auto mb-3 opacity-50" aria-hidden="true" />
                  <p>No 15m crypto markets available</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" role="table" aria-label="15m crypto markets">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                        <th className="text-left p-3" scope="col">Market</th>
                        <th className="text-right p-3" scope="col">Yes Price</th>
                        <th className="text-right p-3" scope="col">No Price</th>
                        <th className="text-right p-3" scope="col">Volume</th>
                        <th className="text-right p-3" scope="col">Closes</th>
                        <th className="text-right p-3" scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {markets.map((market: KalshiMarket) => (
                        <tr key={market.ticker} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-3">
                            <div className="font-medium text-white">{market.ticker}</div>
                            <div className="text-xs text-slate-500">{market.title}</div>
                          </td>
                          <td className="p-3 text-right font-mono text-green-400">{(market.yes_price * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right font-mono text-red-400">{(market.no_price * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right">{market.volume}</td>
                          <td className="p-3 text-right text-xs text-slate-400">
                            {new Date(market.close_time).toLocaleTimeString()}
                          </td>
                          <td className="p-3 text-right">
                            <button
                              onClick={() => setSelectedMarket(market)}
                              aria-label={`Trade ${market.ticker}`}
                              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white text-xs rounded"
                            >
                              Trade
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trade Ticket */}
          {selectedMarket && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Trade: {selectedMarket.ticker}</CardTitle>
                  <button
                    onClick={() => setSelectedMarket(null)}
                    className="text-slate-400 hover:text-white text-sm"
                  >
                    Close
                  </button>
                </div>
              </CardHeader>
              <CardContent>
                <KalshiTradeTicket
                  ticker={selectedMarket.ticker}
                  question={selectedMarket.title}
                  outcomes={[
                    { id: 'yes', name: 'Yes', price: selectedMarket.yes_price, bid: null, ask: null },
                    { id: 'no', name: 'No', price: selectedMarket.no_price, bid: null, ask: null }
                  ]}
                  mode="paper"
                  onOrderPlaced={() => {
                    // Refresh positions after order
                  }}
                />
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Positions Tab */}
      {activeTab === 'positions' && (
        <Card>
          <CardHeader>
            <CardTitle>Positions Summary</CardTitle>
          </CardHeader>
          <CardContent>
            {positions.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <Briefcase className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>No open positions</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                      <th className="text-left p-3">Market</th>
                      <th className="text-left p-3">Side</th>
                      <th className="text-right p-3">Contracts</th>
                      <th className="text-right p-3">Avg Price</th>
                      <th className="text-right p-3">Unrealized PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((pos: any, idx: number) => (
                      <tr key={pos.ticker || idx} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="p-3">
                          <div className="font-medium text-white">{pos.ticker}</div>
                          <div className="text-xs text-slate-500">{pos.outcome}</div>
                        </td>
                        <td className="p-3">
                          <Badge variant={pos.side === 'yes' ? 'success' : 'danger'}>
                            {pos.side.toUpperCase()}
                          </Badge>
                        </td>
                        <td className="p-3 text-right">{pos.quantity}</td>
                        <td className="p-3 text-right font-mono">¢{pos.avg_entry_price_cents}</td>
                        <td
                          className={`p-3 text-right font-mono ${
                            pos.unrealized_pnl_cents >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}
                        >
                          ${(pos.unrealized_pnl_cents / 100).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Orders Tab */}
      {activeTab === 'orders' && (
        <Card>
          <CardHeader>
            <CardTitle>Orders</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-center py-8 text-slate-500">
              <ClipboardList className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>Order management coming soon</p>
              <p className="text-sm mt-2">This tab will show resting, filled, and cancelled orders.</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default Trade;
