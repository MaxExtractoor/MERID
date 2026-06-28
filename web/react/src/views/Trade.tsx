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

import { useKalshiStore, selectPortfolio } from '../store';
import { Monitor, Search, Briefcase, ClipboardList } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

const Trade = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const positions = portfolio.positions;

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
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit">
        <button className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium bg-slate-700 text-white">
          <Search className="w-4 h-4" />
          Markets
        </button>
        <button className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium text-slate-400 hover:text-white">
          <Briefcase className="w-4 h-4" />
          Positions
        </button>
        <button className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium text-slate-400 hover:text-white">
          <ClipboardList className="w-4 h-4" />
          Orders
        </button>
      </div>

      {/* Markets Tab (placeholder) */}
      <Card>
        <CardHeader>
          <CardTitle>15m Crypto Markets</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-slate-500">
            <Search className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>Market discovery for 15m crypto (BTC, ETH, SOL, XRP, DOGE)</p>
            <p className="text-sm mt-2">TODO: Integrate with Kalshi market catalog</p>
          </div>
        </CardContent>
      </Card>

      {/* Positions Summary */}
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
    </div>
  );
};

export default Trade;
