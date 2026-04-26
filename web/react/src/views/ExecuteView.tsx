/**
 * ExecuteView — Unified Trading Execution (Stage 5)
 * 
 * Consolidates: KalshiTerminalView + OrdersView + PositionsView
 * 
 * Tabs:
 *   - "Terminal": Order entry with orderbook and quick trade
 *   - "Orders": Resting orders management with cancel/modify
 *   - "Positions": Current positions and exposure
 * 
 * Features:
 *   - Unified trade ticket with market selection
 *   - Real-time order status tracking
 *   - Position exposure summary
 *   - Batch order operations
 */

import React, { useState, useCallback, useMemo } from 'react';
import {
  Terminal, ClipboardList, TrendingUp,
  X, RefreshCw, AlertTriangle
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { authHeaders } from '../api/auth';

// Sub-components
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
import KalshiOrderbookPanel from '../components/KalshiOrderbookPanel';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

// ── Types ────────────────────────────────────────────────────────────────────

interface Order {
  order_id: string;
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  type: 'limit' | 'market';
  price_cents: number;
  contracts: number;
  status: 'resting' | 'filled' | 'cancelled' | 'rejected';
  filled_contracts: number;
  placed_at: string;
  agent_name?: string;
  client_tag?: string;
}

interface Position {
  id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  avg_price_cents: number;
  current_price_cents: number;
  unrealized_pnl_cents: number;
  realized_pnl_cents: number;
  opened_at: string;
  market_question?: string;
  initiated_by?: string;
}

interface Market {
  ticker: string;
  question: string;
  yes_price: number;
  no_price: number;
  status: string;
}

type ExecuteTab = 'terminal' | 'orders' | 'positions';

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatPrice(cents: number): string {
  return `¢${cents}`;
}

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

// ── Sub-Components ───────────────────────────────────────────────────────────

interface OrderStatusBadgeProps {
  status: Order['status'];
  filled: number;
  total: number;
}

const OrderStatusBadge: React.FC<OrderStatusBadgeProps> = ({ status, filled, total }) => {
  const isPartial = filled > 0 && filled < total;
  const displayStatus = isPartial ? 'partial' : status;
  
  const variants: Record<string, { variant: Parameters<typeof Badge>[0]['variant']; label: string }> = {
    resting: { variant: 'default', label: 'Resting' },
    filled: { variant: 'success', label: 'Filled' },
    partial: { variant: 'warning', label: `Partial ${filled}/${total}` },
    cancelled: { variant: 'ghost', label: 'Cancelled' },
    rejected: { variant: 'danger', label: 'Rejected' },
  };
  
  const config = variants[displayStatus] || variants.resting;
  return <Badge variant={config.variant}>{config.label}</Badge>;
};

// ── Main Component ───────────────────────────────────────────────────────────

interface ExecuteViewProps {
  initialTicker?: string;
}

const ExecuteView: React.FC<ExecuteViewProps> = ({ 
  initialTicker 
}) => {
  const [activeTab, setActiveTab] = useState<ExecuteTab>('terminal');
  const [selectedTicker, setSelectedTicker] = useState<string | null>(initialTicker || null);
  const [orderFilter, setOrderFilter] = useState<'all' | 'resting' | 'filled'>('all');
  const [cancellingOrders, setCancellingOrders] = useState<Set<string>>(new Set());
  
  // Data fetching
  const ordersRes = useApiData<{ orders: Order[] }>(
    API_ENDPOINTS.KALSHI_ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const positionsRes = useApiData<{ positions: Position[] }>(
    API_ENDPOINTS.KALSHI_POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const marketsRes = useApiData<{ markets: Market[] }>(
    `${API_ENDPOINTS.KALSHI_MARKETS}?limit=100`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  // Derived data
  const orders = ordersRes.data?.orders || [];
  const positions = positionsRes.data?.positions || [];
  const markets = marketsRes.data?.markets || [];
  
  const selectedMarket = useMemo(() => 
    markets.find(m => m.ticker === selectedTicker),
    [markets, selectedTicker]
  );
  
  const filteredOrders = useMemo(() => {
    if (orderFilter === 'all') return orders;
    return orders.filter(o => o.status === orderFilter);
  }, [orders, orderFilter]);
  
  const totalExposure = useMemo(() => {
    return positions.reduce((acc, p) => acc + Math.abs(p.contracts), 0);
  }, [positions]);
  
  const totalUnrealizedPnl = useMemo(() => {
    return positions.reduce((acc, p) => acc + p.unrealized_pnl_cents, 0);
  }, [positions]);

  // Cancel order handler
  const cancelOrder = useCallback(async (orderId: string) => {
    setCancellingOrders(prev => new Set(prev).add(orderId));
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_CANCEL(orderId)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error('Cancel failed');
      ordersRes.refetch();
    } catch (err) {
      console.error('Failed to cancel order:', err);
    } finally {
      setCancellingOrders(prev => {
        const next = new Set(prev);
        next.delete(orderId);
        return next;
      });
    }
  }, [ordersRes]);

  // Cancel all resting orders
  const cancelAllResting = useCallback(async () => {
    const resting = orders.filter(o => o.status === 'resting');
    if (resting.length === 0) return;
    
    if (!confirm(`Cancel all ${resting.length} resting orders?`)) return;
    
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS_BATCH_CANCEL}`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_ids: resting.map(o => o.order_id) }),
      });
      if (!res.ok) throw new Error('Batch cancel failed');
      ordersRes.refetch();
    } catch (err) {
      console.error('Failed to cancel orders:', err);
    }
  }, [orders, ordersRes]);

  const tabs = [
    { id: 'terminal' as const, label: 'Terminal', icon: Terminal },
    { id: 'orders' as const, label: `Orders (${orders.filter(o => o.status === 'resting').length})`, icon: ClipboardList },
    { id: 'positions' as const, label: `Positions (${positions.length})`, icon: TrendingUp },
  ];

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Terminal className="w-6 h-6 text-emerald-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Execute <KalshiModeBadge />
            </h1>
            <p className="text-sm text-slate-400">
              Trade execution and order management
            </p>
          </div>
        </div>
        
        {/* Summary Stats */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-slate-500">Exposure</div>
            <div className="text-lg font-bold text-white">{totalExposure} ct</div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Unrealized PnL</div>
            <div className={`text-lg font-bold ${totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatUsd(totalUnrealizedPnl)}
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[500px]">
        {/* Terminal Tab */}
        {activeTab === 'terminal' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Market Selector & Orderbook */}
            <div className="space-y-4">
              {/* Market Selector */}
              <Card>
                <CardHeader>
                  <CardTitle size="sm">Select Market</CardTitle>
                </CardHeader>
                <CardContent>
                  <select
                    value={selectedTicker || ''}
                    onChange={(e) => setSelectedTicker(e.target.value || null)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="">Choose a market...</option>
                    {markets.map(m => (
                      <option key={m.ticker} value={m.ticker}>
                        {m.ticker} — {m.question.slice(0, 50)}...
                      </option>
                    ))}
                  </select>
                </CardContent>
              </Card>
              
              {/* Orderbook */}
              {selectedTicker && (
                <KalshiOrderbookPanel ticker={selectedTicker} />
              )}
            </div>
            
            {/* Trade Ticket */}
            <div className="lg:col-span-2">
              {selectedMarket && selectedMarket.status === 'active' ? (
                <KalshiTradeTicket
                  ticker={selectedMarket.ticker}
                  question={selectedMarket.question}
                  outcomes={[
                    { id: 'yes', name: 'YES', price: selectedMarket.yes_price / 100, bid: null, ask: null },
                    { id: 'no', name: 'NO', price: selectedMarket.no_price / 100, bid: null, ask: null }
                  ]}
                  onOrderPlaced={() => {
                    ordersRes.refetch();
                    setActiveTab('orders');
                  }}
                />
              ) : selectedMarket ? (
                <Card>
                  <CardContent className="p-8 text-center">
                    <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-3" />
                    <p className="text-slate-400">This market is not currently active for trading</p>
                  </CardContent>
                </Card>
              ) : (
                <Card>
                  <CardContent className="p-8 text-center">
                    <Terminal className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                    <p className="text-slate-400">Select a market to begin trading</p>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        )}

        {/* Orders Tab */}
        {activeTab === 'orders' && (
          <Card>
            <CardHeader
              action={
                <div className="flex items-center gap-2">
                  <select
                    value={orderFilter}
                    onChange={(e) => setOrderFilter(e.target.value as typeof orderFilter)}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-white"
                  >
                    <option value="all">All Orders</option>
                    <option value="resting">Resting</option>
                    <option value="filled">Filled</option>
                  </select>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => ordersRes.refetch()}
                    icon={<RefreshCw className="w-4 h-4" />}
                  >
                    Refresh
                  </Button>
                  {orders.filter(o => o.status === 'resting').length > 0 && (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={cancelAllResting}
                    >
                      Cancel All
                    </Button>
                  )}
                </div>
              }
            >
              <CardTitle>Order Management</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                      <th className="text-left p-3">Market</th>
                      <th className="text-left p-3">Side</th>
                      <th className="text-right p-3">Price</th>
                      <th className="text-right p-3">Size</th>
                      <th className="text-center p-3">Status</th>
                      <th className="text-right p-3">Filled</th>
                      <th className="text-center p-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOrders.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="text-center py-8 text-slate-500">
                          No orders found
                        </td>
                      </tr>
                    ) : (
                      filteredOrders.map(order => (
                        <tr key={order.order_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-3">
                            <div className="font-medium text-white">{order.ticker}</div>
                            {order.agent_name && (
                              <div className="text-xs text-slate-500">via {order.agent_name}</div>
                            )}
                          </td>
                          <td className="p-3">
                            <span className={`font-medium ${
                              order.side === 'yes' ? 'text-green-400' : 'text-red-400'
                            }`}>
                              {order.action.toUpperCase()} {order.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="p-3 text-right font-mono">
                            {formatPrice(order.price_cents)}
                          </td>
                          <td className="p-3 text-right">
                            {order.contracts}
                          </td>
                          <td className="p-3 text-center">
                            <OrderStatusBadge 
                              status={order.status} 
                              filled={order.filled_contracts}
                              total={order.contracts}
                            />
                          </td>
                          <td className="p-3 text-right">
                            {order.filled_contracts > 0 ? (
                              <span className="text-green-400">
                                {order.filled_contracts}/{order.contracts}
                              </span>
                            ) : (
                              <span className="text-slate-500">—</span>
                            )}
                          </td>
                          <td className="p-3 text-center">
                            {order.status === 'resting' && (
                              <Button
                                variant="ghost"
                                size="sm"
                                loading={cancellingOrders.has(order.order_id)}
                                onClick={() => cancelOrder(order.order_id)}
                                icon={<X className="w-4 h-4" />}
                              >
                                Cancel
                              </Button>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Positions Tab */}
        {activeTab === 'positions' && (
          <Card>
            <CardHeader
              action={
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => positionsRes.refetch()}
                  icon={<RefreshCw className="w-4 h-4" />}
                >
                  Refresh
                </Button>
              }
            >
              <CardTitle>Position Summary</CardTitle>
            </CardHeader>
            <CardContent>
              {/* Position Summary Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
                <div className="bg-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 mb-1">Total Positions</div>
                  <div className="text-2xl font-bold text-white">{positions.length}</div>
                </div>
                <div className="bg-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 mb-1">Total Contracts</div>
                  <div className="text-2xl font-bold text-white">{totalExposure}</div>
                </div>
                <div className="bg-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 mb-1">Unrealized PnL</div>
                  <div className={`text-2xl font-bold ${totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatUsd(totalUnrealizedPnl)}
                  </div>
                </div>
                <div className="bg-slate-800 rounded-lg p-4">
                  <div className="text-xs text-slate-500 mb-1">Realized PnL (Today)</div>
                  <div className="text-2xl font-bold text-white">
                    {formatUsd(positions.reduce((acc, p) => acc + p.realized_pnl_cents, 0))}
                  </div>
                </div>
              </div>
              
              {/* Positions Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                      <th className="text-left p-3">Market</th>
                      <th className="text-left p-3">Side</th>
                      <th className="text-right p-3">Contracts</th>
                      <th className="text-right p-3">Avg Price</th>
                      <th className="text-right p-3">Mark</th>
                      <th className="text-right p-3">Unrealized PnL</th>
                      <th className="text-left p-3">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="text-center py-8 text-slate-500">
                          No open positions
                        </td>
                      </tr>
                    ) : (
                      positions.map(pos => (
                        <tr 
                          key={pos.id} 
                          className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
                          onClick={() => {
                            setSelectedTicker(pos.ticker);
                            setActiveTab('terminal');
                          }}
                        >
                          <td className="p-3">
                            <div className="font-medium text-white">{pos.ticker}</div>
                            {pos.market_question && (
                              <div className="text-xs text-slate-500 line-clamp-1">
                                {pos.market_question}
                              </div>
                            )}
                          </td>
                          <td className="p-3">
                            <span className={`font-medium ${
                              pos.side === 'yes' ? 'text-green-400' : 'text-red-400'
                            }`}>
                              {pos.side.toUpperCase()}
                            </span>
                          </td>
                          <td className="p-3 text-right">
                            {pos.contracts}
                          </td>
                          <td className="p-3 text-right font-mono">
                            {formatPrice(pos.avg_price_cents)}
                          </td>
                          <td className="p-3 text-right font-mono">
                            {formatPrice(pos.current_price_cents)}
                          </td>
                          <td className={`p-3 text-right font-mono ${
                            pos.unrealized_pnl_cents >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {formatUsd(pos.unrealized_pnl_cents)}
                          </td>
                          <td className="p-3">
                            {pos.initiated_by ? (
                              <span className="text-xs text-slate-400">{pos.initiated_by}</span>
                            ) : (
                              <span className="text-xs text-slate-500">Manual</span>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default ExecuteView;
