/**
 * KalshiTerminalView — Operator-grade live trading terminal for Kalshi.
 *
 * Layout:
 *   Top:    ExecutionGateStrip + account/risk bar (kill-switch, balance, PnL, drawdown, positions, orders)
 *   Left:   Market browser (search/filter/sort) + selected market detail + orderbook
 *   Right:  Trade ticket (live mode) + ALL open orders with cancel + fills + global agent activity
 */

import { useState, useMemo, useCallback } from 'react';
import {
  Search, RefreshCw, X, DollarSign,
  TrendingUp, Shield,
  ShieldAlert, ShieldCheck, Filter,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, API_BASE_URL, DEFAULTS } from '../config/constants';
import type { KalshiBalance, KalshiPosition, KalshiOrder, KalshiFill, KalshiRiskSummary, CatalogMarket, SizingMetrics } from '../types/kalshi';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
import KalshiOrderbookPanel from '../components/KalshiOrderbookPanel';
import KalshiActivityLog from '../components/KalshiActivityLog';
import KalshiModeBadge from '../components/KalshiModeBadge';

/* ══════════════════════════════════════════════════════════════════
   Types
   ══════════════════════════════════════════════════════════════════ */

interface EdgeSignal {
  implied_prob: number;
  model_prob: number;
  ev_cents: number;
  edge_pct: number;
  confidence: number;
  confidence_bucket: 'low' | 'medium' | 'high';
  sizing_tier: 'normal' | 'reduced' | 'boosted' | 'halted';
}

interface EdgeResponse {
  signals: Record<string, EdgeSignal>;
  count: number;
  kelly_fraction: number;
  effective_fraction: number;
}

interface CatalogResponse {
  categories: Record<string, number>;
}

interface KillSwitchState {
  active: boolean;
  reason: string | null;
  can_trade: boolean;
}

/* ══════════════════════════════════════════════════════════════════
   Constants
   ══════════════════════════════════════════════════════════════════ */

const CAT_COLOR: Record<string, string> = {
  crypto: 'text-orange-400 bg-orange-400/10',
  economics: 'text-blue-400 bg-blue-400/10',
  financials: 'text-emerald-400 bg-emerald-400/10',
  politics: 'text-red-400 bg-red-400/10',
  climate: 'text-teal-400 bg-teal-400/10',
  sports: 'text-green-400 bg-green-400/10',
  tech: 'text-violet-400 bg-violet-400/10',
  culture: 'text-pink-400 bg-pink-400/10',
  science: 'text-cyan-400 bg-cyan-400/10',
  fed: 'text-yellow-400 bg-yellow-400/10',
  inflation: 'text-amber-400 bg-amber-400/10',
  rates: 'text-indigo-400 bg-indigo-400/10',
  weather: 'text-sky-400 bg-sky-400/10',
};

type SortKey = 'volume' | 'expiry' | 'edge' | 'position';
type RightTab = 'orders' | 'fills' | 'agents';

/* ══════════════════════════════════════════════════════════════════
   Component
   ══════════════════════════════════════════════════════════════════ */

export default function KalshiTerminalView() {
  // ── State ──
  const [selectedMarket, setSelectedMarket] = useState<CatalogMarket | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('volume');
  const [rightTab, setRightTab] = useState<RightTab>('orders');
  const [posOnly, setPosOnly] = useState(false);
  const [cancellingAll, setCancellingAll] = useState(false);

  // ── Data ──
  const fast = { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH };
  const std  = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const slow = { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW };

  const ksResult    = useApiData<KillSwitchState>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, fast);
  const venueModeResult = useApiData<{ mode: string; is_live: boolean }>(API_ENDPOINTS.KALSHI_GRID_MODE, std);
  const venueMode: 'paper' | 'live' = (venueModeResult.data?.mode ?? 'paper').toLowerCase().includes('paper') ? 'paper' : 'live';
  const mktsResult  = useApiData<{ markets: CatalogMarket[]; count: number }>(API_ENDPOINTS.KALSHI_MARKETS, slow);
  const catResult   = useApiData<CatalogResponse>(API_ENDPOINTS.KALSHI_CATALOG, slow);
  const balResult   = useApiData<KalshiBalance>(API_ENDPOINTS.KALSHI_BALANCE, std);
  const riskResult  = useApiData<KalshiRiskSummary>(API_ENDPOINTS.KALSHI_RISK, std);
  const posResult   = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, std);
  const ordResult   = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, std);
  const fillResult  = useApiData<{ fills: KalshiFill[] }>(API_ENDPOINTS.KALSHI_FILLS, std);
  const edgeResult  = useApiData<EdgeResponse>(API_ENDPOINTS.KALSHI_EDGE, slow);
  const sizingResult = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, slow);

  // Derive event ticker from selected market (e.g. "KXBTC-25JAN1234" -> "KXBTC")
  const eventTicker = useMemo(() => {
    if (!selectedMarket) return '';
    return selectedMarket.ticker.split('-')[0] ?? '';
  }, [selectedMarket]);
  const eventResult = useApiData<{ ticker: string; title: string; category: string; market_count: number; status: string }>(
    eventTicker ? API_ENDPOINTS.KALSHI_EVENT(eventTicker) : '',
    { pollingInterval: eventTicker ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 }
  );

  // ── Derived ──
  const ks        = ksResult.data;
  const markets   = useMemo(() => mktsResult.data?.markets ?? [], [mktsResult.data]);
  const categories = useMemo(() => catResult.data?.categories ? Object.keys(catResult.data.categories) : [], [catResult.data]);
  const balance   = balResult.data;
  const risk      = riskResult.data;
  const positions = useMemo(() => posResult.data?.positions ?? [], [posResult.data]);
  const orders    = useMemo(() => ordResult.data?.orders ?? [], [ordResult.data]);
  const fills     = useMemo(() => fillResult.data?.fills ?? [], [fillResult.data]);
  const sizing    = sizingResult.data;

  const posTickerSet = useMemo(() => new Set(positions.map(p => p.ticker)), [positions]);

  const filteredMarkets = useMemo(() => {
    let result = markets;
    if (posOnly) result = result.filter(m => posTickerSet.has(m.ticker));
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(m =>
        m.ticker.toLowerCase().includes(q) ||
        m.question.toLowerCase().includes(q) ||
        (m.asset && m.asset.toLowerCase().includes(q))
      );
    }
    if (filterCategory) result = result.filter(m => m.category === filterCategory);
    if (sortKey === 'volume') {
      result = [...result].sort((a, b) => b.volume - a.volume);
    } else if (sortKey === 'expiry') {
      result = [...result].sort((a, b) => (a.minutes_to_expiry ?? 99999) - (b.minutes_to_expiry ?? 99999));
    } else if (sortKey === 'edge') {
      const sigs = edgeResult.data?.signals ?? {};
      result = [...result].sort((a, b) => Math.abs(sigs[b.ticker]?.ev_cents ?? 0) - Math.abs(sigs[a.ticker]?.ev_cents ?? 0));
    } else if (sortKey === 'position') {
      result = [...result].sort((a, b) => (posTickerSet.has(b.ticker) ? 1 : 0) - (posTickerSet.has(a.ticker) ? 1 : 0));
    }
    return result;
  }, [markets, posOnly, searchQuery, filterCategory, sortKey, edgeResult.data, posTickerSet]);

  const selectedPosition = useMemo(() =>
    selectedMarket ? (positions.find(p => p.ticker === selectedMarket.ticker) ?? null) : null
  , [selectedMarket, positions]);

  const selectedEdge = useMemo(() =>
    selectedMarket ? (edgeResult.data?.signals?.[selectedMarket.ticker] ?? null) : null
  , [selectedMarket, edgeResult.data]);

  const kellySuggestion = useMemo(() => {
    if (!selectedEdge || !sizing || !selectedMarket) return null;
    if (selectedEdge.ev_cents <= 0 || selectedEdge.confidence < 0.3) return null;
    const bankroll = balance?.available ?? 100;
    const kellyBet = sizing.effective_fraction * selectedEdge.confidence * bankroll;
    const priceCents = (selectedMarket.outcomes[0]?.price ?? 0.5) * 100;
    const suggestedSide: 'yes' | 'no' = selectedEdge.model_prob > selectedEdge.implied_prob ? 'yes' : 'no';
    return { contracts: Math.max(1, Math.floor(kellyBet / (priceCents / 100))), side: suggestedSide };
  }, [selectedEdge, sizing, selectedMarket, balance]);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  // ── Handlers ──
  const handleCancelOrder = useCallback(async (orderId: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_CANCEL(orderId)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      ordResult.refetch();
    } catch { /* ignore */ }
  }, [authHeaders, ordResult]);

  const handleCancelAll = useCallback(async () => {
    if (!window.confirm(`Cancel ALL ${orders.length} open orders?`)) return;
    setCancellingAll(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS_BATCH_CANCEL}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      ordResult.refetch();
    } catch { /* ignore */ }
    setCancellingAll(false);
  }, [authHeaders, orders.length, ordResult]);

  const refreshAll = useCallback(() => {
    mktsResult.refetch(); balResult.refetch(); riskResult.refetch();
    posResult.refetch(); ordResult.refetch(); fillResult.refetch();
  }, [mktsResult, balResult, riskResult, posResult, ordResult, fillResult]);

  /* ════════════════════════════════════════════════════════════════
     Render
     ════════════════════════════════════════════════════════════════ */

  const ksActive     = ks?.active ?? false;
  const drawdownHalt = sizing?.drawdown_tier === 'halt';

  return (
    <div className="flex flex-col h-full gap-2">

      {/* ── EXECUTION GATE + RISK BANNER ── */}
      <div className="shrink-0 space-y-2">
        <ExecutionGateStrip />

        {(ksActive || drawdownHalt) && (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border bg-red-950/40 border-red-500/50 text-red-400">
            <ShieldAlert className="w-4 h-4 shrink-0 animate-pulse" />
            <span className="text-sm font-bold uppercase tracking-wide">
              {ksActive
                ? `TRADING HALTED — Kill switch active${ks?.reason ? ': ' + ks.reason : ''}`
                : 'TRADING HALTED — Drawdown limit reached'}
            </span>
          </div>
        )}

        {/* ── ACCOUNT BAR ── */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-2 bg-slate-900 rounded-xl border border-slate-800 text-xs">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-bold text-white">Terminal</h1>
            <KalshiModeBadge />
          </div>
          <div className="w-px h-4 bg-slate-700" />

          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full font-semibold ${
            ksActive
              ? 'bg-red-500/20 text-red-400 border border-red-500/40'
              : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
          }`}>
            {ksActive ? <ShieldAlert className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
            <span>{ksActive ? 'HALTED' : 'LIVE'}</span>
          </div>
          <div className="w-px h-4 bg-slate-700" />

          <div className="flex items-center gap-1">
            <DollarSign className="w-3 h-3 text-green-400" />
            <span className="text-gray-400">Avail:</span>
            <span className="font-mono text-white">${balance?.available?.toFixed(2) ?? '—'}</span>
          </div>
          {(balance?.locked ?? 0) > 0 && (
            <span className="text-gray-500 font-mono">Locked: ${(balance?.locked ?? 0).toFixed(2)}</span>
          )}
          <div className="w-px h-4 bg-slate-700" />

          <div className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-blue-400" />
            <span className={`font-mono font-semibold ${(risk?.daily_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {(risk?.daily_pnl_usd ?? 0) >= 0 ? '+' : ''}${(risk?.daily_pnl_usd ?? 0).toFixed(2)}
            </span>
          </div>
          {risk && (
            <span className={`font-mono ${risk.drawdown_pct > 5 ? 'text-orange-400' : 'text-gray-500'}`}>
              DD:{(risk.drawdown_pct ?? 0).toFixed(1)}%
            </span>
          )}
          <div className="w-px h-4 bg-slate-700" />

          <span className="font-mono text-white">{positions.length}<span className="text-gray-500"> pos</span></span>
          <span className="font-mono text-white">{orders.length}<span className="text-gray-500"> ord</span></span>
          <span className="font-mono text-white">{fills.length}<span className="text-gray-500"> fills</span></span>
          {sizing && (
            <span className={`font-mono ${sizing.kelly_utilization_pct > 80 ? 'text-amber-400' : 'text-gray-400'}`}>
              Kelly:{(sizing.kelly_fraction ?? 0).toFixed(2)}
            </span>
          )}

          <button type="button" onClick={refreshAll} className="ml-auto p-1 rounded hover:bg-slate-800 text-gray-500 hover:text-white" aria-label="Refresh">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── MAIN AREA ── */}
      <div className="flex flex-1 gap-3 min-h-0">

        {/* ══ LEFT: Market Browser ══ */}
        <div className="flex flex-col w-[55%] min-h-0 gap-2">

          {/* Controls */}
          <div className="flex items-center gap-1.5 shrink-0">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Ticker / keyword…"
                className="w-full pl-8 pr-7 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-white placeholder-gray-600 focus:border-orange-500 focus:outline-none"
              />
              {searchQuery && (
                <button type="button" onClick={() => setSearchQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white" aria-label="Clear">
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
            <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-gray-300 focus:border-orange-500 focus:outline-none" aria-label="Category">
              <option value="">All</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={sortKey} onChange={e => setSortKey(e.target.value as SortKey)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-gray-300 focus:border-orange-500 focus:outline-none" aria-label="Sort">
              <option value="volume">Vol</option>
              <option value="expiry">Expiry</option>
              <option value="edge">Edge</option>
              <option value="position">My Pos</option>
            </select>
            <button type="button" onClick={() => setPosOnly(v => !v)}
              className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs border transition-colors ${posOnly ? 'bg-purple-500/20 border-purple-500/40 text-purple-300' : 'bg-slate-800 border-slate-700 text-gray-500 hover:text-gray-300'}`}
              title="My positions only">
              <Filter className="w-3 h-3" />{posOnly && <span>Pos</span>}
            </button>
          </div>

          {/* Market list */}
          <div className="flex-1 overflow-y-auto space-y-0.5 min-h-0">
            {filteredMarkets.length === 0 ? (
              <div className="flex items-center justify-center h-24 text-xs text-gray-600">
                {mktsResult.loading ? 'Loading…' : posOnly ? 'No positions' : 'No markets'}
              </div>
            ) : filteredMarkets.map(m => {
              const isSelected = selectedMarket?.ticker === m.ticker;
              const sig        = edgeResult.data?.signals?.[m.ticker];
              const pos        = positions.find(p => p.ticker === m.ticker);
              const yesPrice   = m.outcomes[0]?.price;
              const hasPosOrders = orders.some(o => o.ticker === m.ticker);

              return (
                <button type="button" key={m.ticker} onClick={() => setSelectedMarket(m)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg transition-all ${
                    isSelected ? 'bg-orange-500/10 border border-orange-500/40'
                      : 'bg-slate-900/60 border border-slate-800 hover:border-slate-600'
                  }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className={`text-xs font-medium truncate ${isSelected ? 'text-white' : 'text-gray-300'}`}>
                        {m.question}
                      </p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <span className="text-[10px] font-mono text-gray-600">{m.ticker}</span>
                        {m.category && (
                          <span className={`text-[10px] px-1 py-0.5 rounded ${CAT_COLOR[m.category] ?? 'text-gray-400 bg-slate-800'}`}>
                            {m.category}
                          </span>
                        )}
                        {pos && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-purple-500/15 text-purple-300 font-semibold">
                            {pos.size} {pos.outcome}
                          </span>
                        )}
                        {hasPosOrders && !pos && (
                          <span className="text-[10px] text-blue-400">ord</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      {yesPrice != null && (
                        <span className={`text-sm font-bold font-mono ${yesPrice >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                          {(yesPrice * 100).toFixed(0)}¢
                        </span>
                      )}
                      <div className="flex items-center justify-end gap-1 mt-0.5">
                        <span className="text-[10px] text-gray-600">{m.volume.toLocaleString()}</span>
                        {sig && sig.ev_cents > 0 && (
                          <span className="text-[10px] font-mono font-semibold text-emerald-400">+{sig.ev_cents}¢</span>
                        )}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Selected market detail + orderbook */}
          {selectedMarket && (
            <div className="shrink-0 max-h-[38%] overflow-y-auto border-t border-slate-800 pt-2 space-y-2">
              <div className="bg-slate-800/80 rounded-xl p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-white truncate">{selectedMarket.question}</p>
                    <p className="text-[10px] font-mono text-gray-500">{selectedMarket.ticker}</p>
                  </div>
                  <button type="button" onClick={() => setSelectedMarket(null)} className="p-1 rounded hover:bg-slate-700 text-gray-500 shrink-0" aria-label="Close">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-1.5">
                  {selectedMarket.outcomes.map(o => (
                    <div key={o.id} className="bg-slate-900 rounded-lg px-2.5 py-1.5">
                      <p className="text-[10px] text-gray-500">{o.name}</p>
                      <p className={`text-sm font-bold font-mono ${o.price >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                        {(o.price * 100).toFixed(0)}¢
                      </p>
                      {o.bid != null && o.ask != null && (
                        <p className="text-[10px] text-gray-600">{(o.bid * 100).toFixed(0)}–{(o.ask * 100).toFixed(0)}</p>
                      )}
                    </div>
                  ))}
                </div>

                {eventResult.data && (
                  <div className="flex items-center gap-2 text-[10px] bg-slate-900/60 rounded px-2 py-1">
                    <span className="text-gray-500">Event:</span>
                    <span className="font-mono text-orange-300">{eventResult.data.ticker}</span>
                    <span className="text-gray-400 truncate">{eventResult.data.title}</span>
                    <span className="ml-auto text-gray-600">{eventResult.data.market_count}mkt</span>
                    <span className={`px-1 py-0.5 rounded ${eventResult.data.status === 'open' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700 text-gray-400'}`}>
                      {eventResult.data.status}
                    </span>
                  </div>
                )}

                <div className="flex items-center gap-3 text-[10px] text-gray-500">
                  <span>Vol: <span className="text-gray-300">{selectedMarket.volume.toLocaleString()}</span></span>
                  {selectedMarket.minutes_to_expiry != null && (
                    <span>Exp: <span className="text-gray-300">
                      {selectedMarket.minutes_to_expiry < 60 ? `${selectedMarket.minutes_to_expiry.toFixed(0)}m`
                        : selectedMarket.minutes_to_expiry < 1440 ? `${(selectedMarket.minutes_to_expiry / 60).toFixed(1)}h`
                        : `${(selectedMarket.minutes_to_expiry / 1440).toFixed(1)}d`}
                    </span></span>
                  )}
                  {selectedEdge && (
                    <>
                      <span>EV: <span className={`font-mono ${selectedEdge.ev_cents > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {selectedEdge.ev_cents > 0 ? '+' : ''}{selectedEdge.ev_cents}¢
                      </span></span>
                      <span>Conf: <span className="text-gray-300">{((selectedEdge.confidence ?? 0) * 100).toFixed(0)}%</span></span>
                    </>
                  )}
                </div>

                {selectedPosition && (
                  <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-purple-500/5 border border-purple-500/20 text-xs">
                    <Shield className="w-3 h-3 text-purple-400" />
                    <span className="font-mono text-white">{selectedPosition.size} {selectedPosition.outcome}</span>
                    <span className="text-gray-500">@{((selectedPosition.avg_price ?? 0) * 100).toFixed(0)}¢</span>
                    <span className={`font-mono ml-auto ${selectedPosition.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(selectedPosition.unrealized_pnl ?? 0) >= 0 ? '+' : ''}${(selectedPosition.unrealized_pnl ?? 0).toFixed(2)}
                    </span>
                  </div>
                )}
              </div>
              <KalshiOrderbookPanel ticker={selectedMarket.ticker} depth={5} />
            </div>
          )}
        </div>

        {/* ══ RIGHT: Trade + Operations ══ */}
        <div className="flex flex-col w-[45%] min-h-0 gap-2">

          {/* Trade ticket */}
          {selectedMarket ? (
            <div className="shrink-0">
              <KalshiTradeTicket
                ticker={selectedMarket.ticker}
                question={selectedMarket.question}
                outcomes={selectedMarket.outcomes}
                mode={venueMode}
                onOrderPlaced={() => { ordResult.refetch(); fillResult.refetch(); posResult.refetch(); balResult.refetch(); }}
                suggestedSize={kellySuggestion?.contracts}
                suggestedSide={kellySuggestion?.side}
                kellyFraction={sizing?.effective_fraction}
              />
            </div>
          ) : (
            <div className="bg-slate-800/60 rounded-xl p-5 text-center border border-slate-700/50">
              <Search className="w-6 h-6 text-gray-600 mx-auto mb-1.5" />
              <p className="text-xs text-gray-500">Select a market to place an order</p>
            </div>
          )}

          {/* Orders / Fills / Agents tabs */}
          <div className="flex-1 min-h-0 flex flex-col bg-slate-900 rounded-xl border border-slate-800">
            {/* Tab bar */}
            <div className="flex items-center border-b border-slate-800 shrink-0">
              {(['orders', 'fills', 'agents'] as RightTab[]).map(tab => (
                <button type="button" key={tab} onClick={() => setRightTab(tab)}
                  className={`flex-1 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                    rightTab === tab ? 'text-orange-400 border-b-2 border-orange-400' : 'text-gray-500 hover:text-gray-300'
                  }`}>
                  {tab === 'orders' ? `Orders (${orders.length})` : tab === 'fills' ? `Fills (${fills.length})` : 'Agents'}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto min-h-0">
              {rightTab === 'orders' && (
                <>
                  {orders.length > 1 && (
                    <div className="px-2 pt-2 pb-1">
                      <button type="button" onClick={handleCancelAll} disabled={cancellingAll}
                        className="w-full py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider border border-red-500/30 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50">
                        {cancellingAll ? 'Cancelling…' : `Cancel All ${orders.length} Orders`}
                      </button>
                    </div>
                  )}
                  <div className="p-1.5 space-y-0.5">
                    {orders.length === 0 ? (
                      <p className="text-center text-[10px] text-gray-600 py-6">No open orders</p>
                    ) : orders.map(o => {
                      const isForSelected = selectedMarket?.ticker === o.ticker;
                      return (
                        <div key={o.order_id} className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-[10px] ${
                          isForSelected ? 'bg-orange-500/5 border border-orange-500/20' : 'bg-slate-800'
                        }`}>
                          <span className={`font-bold ${o.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                            {o.side.toUpperCase()}
                          </span>
                          <span className="font-mono text-gray-500 truncate max-w-[80px]">{o.ticker}</span>
                          <span className="font-mono text-white whitespace-nowrap">
                            {o.size}×{o.price != null ? `${(o.price * 100).toFixed(0)}¢` : 'MKT'}
                          </span>
                          <span className={`px-1 py-0.5 rounded ${
                            o.status === 'resting' ? 'bg-blue-500/10 text-blue-400'
                              : o.status === 'filled' ? 'bg-green-500/10 text-green-400'
                              : 'bg-slate-700 text-gray-400'
                          }`}>{o.status}</span>
                          <button type="button" onClick={() => handleCancelOrder(o.order_id)}
                            className="ml-auto text-gray-600 hover:text-red-400 transition-colors" aria-label="Cancel">
                            <X className="w-3 h-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}

              {rightTab === 'fills' && (
                <div className="p-1.5 space-y-0.5">
                  {fills.length === 0 ? (
                    <p className="text-center text-[10px] text-gray-600 py-6">No fills today</p>
                  ) : fills.slice(0, 50).map(f => (
                    <div key={f.trade_id} className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-slate-800 text-[10px]">
                      <span className={`font-bold ${f.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                        {f.side.toUpperCase()}
                      </span>
                      <span className="font-mono text-gray-500 truncate max-w-[90px]">{f.ticker}</span>
                      <span className="font-mono text-white">{f.size}×{(f.price * 100).toFixed(0)}¢</span>
                      <span className="text-gray-600 ml-auto">${f.fee.toFixed(2)} fee</span>
                      <span className="text-gray-600 whitespace-nowrap">
                        {new Date(f.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {rightTab === 'agents' && (
                <div className="p-1.5">
                  <KalshiActivityLog ticker={selectedMarket?.ticker ?? null} maxItems={30} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
