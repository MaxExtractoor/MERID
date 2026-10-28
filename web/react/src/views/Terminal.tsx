/**
 * Trade — Order Entry and Position Management
 *
 * - Market discovery (15m crypto markets only — KX*15M tickers), polled
 *   through usePoll(AGENT_ENDPOINTS.MARKETS).
 * - Order entry via KalshiTradeTicket. Execution gate reads the store's
 *   live runtime state inside the ticket (mode passed down from
 *   store.system); the dead /api/v1/system/execution-gate route is never
 *   called.
 * - Orders management: real resting orders polled through usePoll
 *   (AGENT_ENDPOINTS.ORDERS). Cancel -> DELETE /orders/{id}; cancel-all ->
 *   DELETE /orders (backend may refuse batch cancel — the guard error is
 *   surfaced honestly). All mutations: useRef in-flight guard +
 *   ConfirmModal + authoritative refetch.
 * - Positions summary from store.portfolio.
 */

import { useRef, useState } from 'react';
import { useKalshiStore, selectPortfolio, selectRisk, selectSystem } from '../store';
import { Monitor, Search, Briefcase, ClipboardList } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { usePoll } from '../hooks/usePoll';
import { AGENT_ENDPOINTS, delJson } from '../agents/api';
import { ConfirmModal } from '../components/ConfirmModal';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
import { cx, numOr } from '../agents/format';

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

// GET /api/v1/kalshi/orders row: price arrives in dollars (0-1).
interface ServerOrder {
  order_id?: string;
  ticker?: string;
  side?: string;
  size?: number | string;
  price?: number | string;
  price_cents?: number | string;
  filled?: number | string;
  remaining?: number | string | null;
  status?: string;
  created_at?: string | null;
  synthetic?: boolean;
}

interface OrderRow {
  order_id: string;
  ticker: string;
  side: string;
  size: number;
  price_cents: number | null;
  filled: number;
  remaining: number | null;
  status: string;
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
  return typeof p === 'number' && Number.isFinite(p) ? p : 0.5;
};

const mapMarkets = (raw: unknown): KalshiMarket[] => {
  const arr = (raw as { markets?: KalshiMarket[] } | null)?.markets;
  return Array.isArray(arr) ? arr.filter((m) => m && typeof m === 'object' && m.ticker) : [];
};

const mapOrders = (raw: unknown): OrderRow[] => {
  const arr = (raw as { orders?: ServerOrder[] } | null)?.orders;
  if (!Array.isArray(arr)) return [];
  return arr
    .filter((o) => o && typeof o === 'object' && o.order_id && o.synthetic !== true)
    .map((o) => {
      const priceDollars = numOr(o.price);
      const priceCents = numOr(o.price_cents) ?? (priceDollars != null ? Math.round(priceDollars * 100) : null);
      return {
        order_id: String(o.order_id),
        ticker: String(o.ticker ?? ''),
        side: String(o.side ?? ''),
        size: numOr(o.size) ?? 0,
        price_cents: priceCents,
        filled: numOr(o.filled) ?? 0,
        remaining: numOr(o.remaining) ?? null,
        status: String(o.status ?? ''),
      };
    });
};

const Trade = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const risk = useKalshiStore(selectRisk);
  const system = useKalshiStore(selectSystem);
  const refreshAll = useKalshiStore(s => s.refreshAll);
  const positions = portfolio.positions;
  const [selectedMarket, setSelectedMarket] = useState<KalshiMarket | null>(null);
  const [activeTab, setActiveTab] = useState<'markets' | 'positions' | 'orders'>('markets');

  // Markets catalog — usePoll keeps last-good data on failure.
  const marketsPoll = usePoll<KalshiMarket[]>(
    `${AGENT_ENDPOINTS.MARKETS}?limit=500`,
    { ms: 30_000, map: mapMarkets },
  );

  // Resting orders — dedicated 15s poll so cancels refetch promptly.
  const ordersPoll = usePoll<OrderRow[]>(
    AGENT_ENDPOINTS.ORDERS,
    { ms: 15_000, map: mapOrders },
  );
  const orders = ordersPoll.data ?? [];

  // Order-management state (guarded mutations).
  const cancelRef = useRef(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<
    { kind: 'single'; orderId: string; ticker: string } | { kind: 'all' } | null
  >(null);

  const runCancel = async (target: { kind: 'single'; orderId: string } | { kind: 'all' }) => {
    if (cancelRef.current) return;
    cancelRef.current = true;
    setCancelBusy(true);
    setCancelError(null);
    try {
      if (target.kind === 'single') {
        await delJson(`${AGENT_ENDPOINTS.ORDERS}/${encodeURIComponent(target.orderId)}`);
      } else {
        // Batch cancel — the backend may refuse (BATCH_CANCEL guard); the
        // error is surfaced inline rather than hidden.
        await delJson(AGENT_ENDPOINTS.ORDERS);
      }
      ordersPoll.refresh();
      await refreshAll();
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      cancelRef.current = false;
      setCancelBusy(false);
    }
  };

  // Filter for 15m crypto markets (BTC, ETH, SOL, XRP, DOGE)
  const markets = (marketsPoll.data ?? []).filter((m) => is15mCrypto(m) && m.active !== false);

  // Execution-gate state for the header chip (ticket also reads it internally).
  const liveState = system.live?.state ?? 'UNKNOWN';
  const entriesEnabled = system.live?.state === 'LIVE_ENTRIES_ENABLED' && !risk.kill_switch_active;

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
        <div className="flex items-center gap-2">
          {risk.kill_switch_active && (
            <Badge variant="danger">KILL SWITCH</Badge>
          )}
          <Badge variant={entriesEnabled ? 'success' : 'warning'}>
            {liveState}
          </Badge>
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
              <div className="flex items-center justify-between">
                <CardTitle>15m Crypto Markets (BTC, ETH, SOL, XRP, DOGE)</CardTitle>
                {marketsPoll.error && (
                  <span
                    className="text-[9px] font-semibold text-red-400"
                    title={marketsPoll.error}
                    role="alert"
                  >
                    markets source error{marketsPoll.lastOk ? ' — showing last good' : ''}
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {marketsPoll.loading && !marketsPoll.data ? (
                <div className="text-center py-8 text-slate-500" role="status" aria-live="polite">Loading markets...</div>
              ) : marketsPoll.error && !marketsPoll.data ? (
                <div className="text-center py-8 text-red-400" role="alert">{marketsPoll.error}</div>
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
                          <td className="p-3 text-right font-mono tabular-nums text-emerald-400">{(outcomePrice(market, 'yes') * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right font-mono tabular-nums text-red-400">{(outcomePrice(market, 'no') * 100).toFixed(0)}¢</td>
                          <td className="p-3 text-right tabular-nums">{market.volume ?? '—'}</td>
                          <td className="p-3 text-right text-xs text-slate-400 tabular-nums">
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
                  <div className="flex items-center gap-2">
                    <Badge variant={entriesEnabled ? 'success' : 'warning'} size="sm">
                      {entriesEnabled ? 'entries enabled' : 'entries gated'}
                    </Badge>
                    <button
                      onClick={() => setSelectedMarket(null)}
                      className="text-slate-400 hover:text-white text-sm"
                    >
                      Close
                    </button>
                  </div>
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
                  lastUpdated={marketsPoll.lastOk}
                  onOrderPlaced={() => {
                    void refreshAll();
                    ordersPoll.refresh();
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
                        <td className="p-3 text-right tabular-nums">{pos.quantity}</td>
                        <td className="p-3 text-right font-mono tabular-nums">¢{pos.avg_entry_price_cents}</td>
                        <td
                          className={cx(
                            'p-3 text-right font-mono tabular-nums',
                            pos.unrealized_pnl_cents >= 0 ? 'text-emerald-400' : 'text-red-400',
                          )}
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
            {ordersPoll.error && !ordersPoll.data ? (
              <div className="text-center py-8 text-red-400" role="alert">{ordersPoll.error}</div>
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
                            {(o.side || '?').toUpperCase()}
                          </Badge>
                        </td>
                        <td className="p-3 text-right tabular-nums">{o.size}</td>
                        <td className="p-3 text-right font-mono tabular-nums">
                          {o.price_cents != null ? `${o.price_cents}¢` : '—'}
                        </td>
                        <td className="p-3 text-right tabular-nums">
                          {o.filled}/{o.remaining ?? '—'}
                        </td>
                        <td className="p-3 text-xs text-slate-400">{o.status || '—'}</td>
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
