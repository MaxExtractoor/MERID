/**
 * Trade — Order Entry and Position Management
 * 
 * Purpose: Consolidated trading view for order entry and position management
 * 
 * Content:
 * - Market discovery (15m crypto markets only)
 * - Order entry (trade ticket)
 * - Orders management (resting + cancel, backed by /api/v1/kalshi/orders)
 * - Positions summary (exposure, unrealized PnL)
 * 
 * Data: Markets/positions/orders — all from verified backend endpoints.
 */

import { useEffect, useRef, useState } from 'react';
import { useKalshiStore, selectPortfolio, selectSystem } from '../store';
import { Monitor, Search, Briefcase, ClipboardList } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { apiUrl } from '../config/apiBase';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { ConfirmModal } from '../components/ConfirmModal';
import KalshiTradeTicket from '../components/KalshiTradeTicket';

// Real market row shape from GET /api/v1/kalshi/markets (verified in kalshi_api.py).
interface MarketOutcome {
  name?: string;
  id?: string;
  price?: number | null;
  bid?: number | null;
  ask?: number | null;
}

interface KalshiMarket {
  ticker: string;
  question: string;
  category?: string;
  asset?: string;
  timeframe?: string;
  market_type?: string;
  active?: boolean;
  volume?: number;
  expires_at?: string | null;
  minutes_to_expiry?: number | null;
  outcomes?: MarketOutcome[];
}

interface OrderRow {
  order_id: string;
  ticker: string;
  side?: string;
  size?: number;
  price?: number;      // dollars (0-1)
  filled?: number;
  remaining?: number | null;
  status?: string;
  created_at?: string | null;
}

const ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
// 15m tickers look like KXBTC15M-... — match case-insensitively on the ticker
// itself plus structured asset/timeframe fields when present.
const is15mCrypto = (m: KalshiMarket): boolean => {
  const tickerHit = /15m/i.test(m.ticker ?? '');
  const tfHit = String(m.timeframe ?? '').toLowerCase() === '15m';
  const mtHit = /15m/i.test(String(m.market_type ?? ''));
  const assetHit = m.asset
    ? ASSETS.includes(m.asset.toUpperCase())
    : ASSETS.some(a => (m.ticker ?? '').toUpperCase().includes(a));
  return (tickerHit || tfHit || mtHit) && assetHit;
};

const outcomePrice = (m: KalshiMarket, name: 'yes' | 'no'): number => {
  const o = m.outcomes?.find(x => (x.name ?? x.id ?? '').toLowerCase() === name);
  const p = o?.price;
  return typeof p === 'number' && Number.isFinite(p) ? p : name === 'yes' ? 0.5 : 0.5;
};

const Trade = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const system = useKalshiStore(selectSystem);
  const refreshAll = useKalshiStore(s => s.refreshAll);
  const positions = portfolio.positions;
  const [selectedMarket, setSelectedMarket] = useState<KalshiMarket | null>(null);
  const [activeTab, setActiveTab] = useState<'markets' | 'positions' | 'orders'>('markets');

  // Store refresh — positions/orders/system come from refreshAll probes.
  useEffect(() => {
    void refreshAll();
    const interval = setInterval(() => { void refreshAll(); }, 30_000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  // Order-management state (guarded mutations).
  const cancelRef = useRef(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<
    { kind: 'single'; orderId: string; ticker: string } | { kind: 'all' } | null
  >(null);

  // Fetch Kalshi market catalog for 15m crypto using TanStack Query
  const { data: marketsData, isLoading, error } = useApiQuery<{ markets: KalshiMarket[] }>(
    apiUrl('/api/v1/kalshi/markets'),
    {
      refetchInterval: 30_000, // Refresh every 30 seconds
      staleTime: 10_000,
    }
  );

  // Orders — real resting/working orders from the venue.
  const {
    data: ordersData,
    error: ordersError,
    refetch: refetchOrders,
  } = useApiQuery<{ count: number; orders: OrderRow[] }>(
    apiUrl('/api/v1/kalshi/orders'),
    { refetchInterval: 15_000, staleTime: 5_000 }
  );
  const orders = ordersData?.orders ?? [];

  const runCancel = async (target: { kind: 'single'; orderId: string } | { kind: 'all' }) => {
    if (cancelRef.current) return;
    cancelRef.current = true;
    setCancelBusy(true);
    setCancelError(null);
    try {
      const url = target.kind === 'single'
        ? apiUrl(`/api/v1/kalshi/orders/${encodeURIComponent(target.orderId)}`)
        : apiUrl('/api/v1/kalshi/orders');
      const res = await fetch(url, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = (body as { detail?: unknown }).detail;
        throw new Error(
          typeof detail === 'string' ? detail : `Cancel failed (HTTP ${res.status})`
        );
      }
      await refetchOrders();
      await refreshAll();
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      cancelRef.current = false;
      setCancelBusy(false);
    }
  };

  // Filter for 15m crypto markets (BTC, ETH, SOL, XRP, DOGE)
  const markets = (marketsData?.markets ?? []).filter((m: KalshiMarket) => is15mCrypto(m) && m.active !== false);

  const expiryLabel = (m: KalshiMarket): string => {
    if (m.minutes_to_expiry != null) return `${Math.round(m.minutes_to_expiry)}m`;
    if (m.expires_at) return new Date(m.expires_at).toLocaleTimeString();
    return '—';
  };

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
          Orders {orders.length > 0 && <span className="text-xs text-slate-500">({orders.length})</span>}
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
                        <th className="text-right p-3" scope="col">Expires</th>
                        <th className="text-right p-3" scope="col">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {markets.map((market: KalshiMarket) => (
                        <tr key={market.ticker} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                          <td className="p-3">
                            <div className="font-medium text-white">{market.ticker}</div>
                            <div className="text-xs text-slate-500">{market.question}</div>
                          </td>
                          <td className="p-3 text-right font-mono text-green-400">{(outcomePrice(market, 'yes') * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right font-mono text-red-400">{(outcomePrice(market, 'no') * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right">{market.volume ?? '—'}</td>
                          <td className="p-3 text-right text-xs text-slate-400">
                            {expiryLabel(market)}
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
                  question={selectedMarket.question}
                  outcomes={(selectedMarket.outcomes ?? []).map(o => ({
                    id: o.id ?? o.name ?? '',
                    name: o.name ?? o.id ?? '',
                    price: o.price ?? 0.5,
                    bid: o.bid ?? null,
                    ask: o.ask ?? null,
                  }))}
                  mode={system.mode}
                  lastUpdated={marketsData ? Date.now() : undefined}
                  onOrderPlaced={() => {
                    void refreshAll();
                    void refetchOrders();
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
                    {positions.map((pos, idx: number) => (
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
            <div className="flex items-center justify-between">
              <CardTitle>Orders</CardTitle>
              {orders.length > 0 && (
                <Button
                  size="sm"
                  variant="danger"
                  disabled={cancelBusy}
                  onClick={() => setConfirmCancel({ kind: 'all' })}
                  title="Cancel all resting orders (backend may reject batch cancel — error shown inline)"
                >
                  Cancel All
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {cancelError && (
              <div className="mb-3 text-xs text-red-400 break-words" role="alert">
                Error: {cancelError}
              </div>
            )}
            {ordersError ? (
              <div className="text-center py-8 text-red-400" role="alert">{String(ordersError)}</div>
            ) : orders.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <ClipboardList className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>No open orders</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                      <th className="text-left p-3">Order</th>
                      <th className="text-left p-3">Side</th>
                      <th className="text-right p-3">Size</th>
                      <th className="text-right p-3">Price</th>
                      <th className="text-right p-3">Filled/Remaining</th>
                      <th className="text-left p-3">Status</th>
                      <th className="text-right p-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o: OrderRow) => (
                      <tr key={o.order_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="p-3">
                          <div className="font-medium text-white">{o.ticker}</div>
                          <div className="text-xs text-slate-500 font-mono">{o.order_id.slice(0, 18)}</div>
                        </td>
                        <td className="p-3">
                          <Badge variant={o.side === 'yes' ? 'success' : 'danger'}>
                            {(o.side ?? '?').toUpperCase()}
                          </Badge>
                        </td>
                        <td className="p-3 text-right">{o.size ?? '—'}</td>
                        <td className="p-3 text-right font-mono">
                          {o.price != null ? `${Math.round(o.price * 100)}¢` : '—'}
                        </td>
                        <td className="p-3 text-right">
                          {o.filled ?? 0}/{o.remaining ?? '—'}
                        </td>
                        <td className="p-3 text-xs text-slate-400">{o.status ?? '—'}</td>
                        <td className="p-3 text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={cancelBusy}
                            onClick={() => setConfirmCancel({ kind: 'single', orderId: o.order_id, ticker: o.ticker })}
                          >
                            Cancel
                          </Button>
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

      <ConfirmModal
        isOpen={confirmCancel !== null}
        title={confirmCancel?.kind === 'all' ? 'Cancel All Orders' : 'Cancel Order'}
        message={
          confirmCancel?.kind === 'all'
            ? `Cancel ALL ${orders.length} resting order(s)?`
            : confirmCancel?.kind === 'single'
              ? `Cancel order on ${confirmCancel.ticker}?`
              : ''
        }
        confirmText="Cancel Order"
        confirmVariant="danger"
        onConfirm={() => {
          const target = confirmCancel;
          setConfirmCancel(null);
          if (target?.kind === 'single') void runCancel({ kind: 'single', orderId: target.orderId });
          else if (target?.kind === 'all') void runCancel({ kind: 'all' });
        }}
        onCancel={() => setConfirmCancel(null)}
      />
    </div>
  );
};

export default Trade;
