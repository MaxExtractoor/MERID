import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import {
  BarChart3, RefreshCw, Search, Filter, Shield,
  Activity, Clock, ChevronRight, AlertTriangle,
  Heart, Zap, DollarSign, X, Star, Briefcase,
  ArrowUpDown, TrendingUp, Bookmark, Gauge,
  Flame, Radio, Layers, Target, Wifi, WifiOff,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, API_BASE_URL, DEFAULTS } from '../config/constants';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import CTStatusPanel from '../components/CTStatusPanel';
import { logUxEvent } from '../utils/uxTelemetry';
import { useKalshiMode } from '../context/KalshiModeContext';
import type { SizingMetrics, CatalogMarket } from '../types/kalshi';

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
  drawdown_pct: number;
}

interface CatalogSummary {
  market_count: number;
  last_refresh: string | null;
  refresh_count: number;
  categories: Record<string, number>;
  assets: Record<string, number>;
  timeframes: Record<string, number>;
  running: boolean;
}

interface HealthStatus {
  status: string;
  issues: string[];
  catalog: { market_count: number; last_refresh: string | null; categories: number };
  risk: { kill_switch: boolean; daily_pnl: number; drawdown_pct: number };
  ws: { running: boolean; events_forwarded: number; subscribed_tickers: number };
  rate_limits: { orders_this_minute: number; max_per_minute: number; orders_this_hour: number; max_per_hour: number };
}

type QuickTab = 'all' | 'trending' | 'live' | 'crypto-hourly' | 'crypto-15m' | 'top-volume' | 'new-markets' | 'my-positions' | 'favorites';
type SortKey = 'volume' | 'expiry' | 'spread';

const QUICK_TABS: { id: QuickTab; label: string; icon: React.ElementType }[] = [
  { id: 'all',          label: 'All Markets',   icon: BarChart3 },
  { id: 'trending',     label: 'Trending',       icon: Flame },
  { id: 'live',         label: '🔴 Live Now',    icon: Radio },
  { id: 'crypto-hourly',label: 'Crypto Hourly',  icon: Clock },
  { id: 'crypto-15m',   label: 'Crypto 15m',     icon: Zap },
  { id: 'top-volume',   label: 'Top Volume',     icon: TrendingUp },
  { id: 'new-markets',  label: 'New Markets',    icon: Star },
  { id: 'my-positions', label: 'My Positions',   icon: Briefcase },
  { id: 'favorites',    label: 'Favorites',      icon: Bookmark },
];

// ── Spread / liquidity badge helpers ────────────────────────────────────
interface LiqBadge { label: string; color: string; tooltip?: string }
function spreadBadge(bid: number | null, ask: number | null): LiqBadge | null {
  if (bid == null || ask == null) return null;
  const spreadCents = Math.round((ask - bid) * 100);
  if (spreadCents <= 2) return { label: `${spreadCents}¢`, color: 'text-green-400 bg-green-400/10', tooltip: `Tight spread: ${spreadCents}¢` };
  if (spreadCents <= 5) return { label: `${spreadCents}¢`, color: 'text-gray-400 bg-slate-800', tooltip: `Normal spread: ${spreadCents}¢` };
  if (spreadCents <= 10) return { label: `Wide ${spreadCents}¢`, color: 'text-yellow-400 bg-yellow-400/10', tooltip: `Wide spread: ${spreadCents}¢ — expect slippage` };
  return { label: `Thin ${spreadCents}¢`, color: 'text-red-400 bg-red-400/10', tooltip: `Very wide spread: ${spreadCents}¢ — thin book, high slippage risk` };
}
function volumeBadge(volume: number): LiqBadge | null {
  if (volume >= 500) return null;  // fine
  if (volume >= 100) return { label: 'Low vol', color: 'text-yellow-500/70 bg-yellow-500/5', tooltip: `Volume: ${volume} — below normal` };
  return { label: 'Illiquid', color: 'text-red-400/70 bg-red-400/5', tooltip: `Volume: ${volume} — very low liquidity` };
}

// ── Edge / EV coloring rules ────────────────────────────────────────────
function edgeColor(ev: number, confidence: string): string {
  if (confidence === 'low') return 'text-gray-600';  // muted when low confidence
  if (ev >= 3) return 'text-emerald-400';             // strong positive EV
  if (ev >= 1) return 'text-green-400/70';             // moderate positive EV
  if (ev <= -3) return 'text-red-400';                 // strong negative EV
  if (ev <= -1) return 'text-red-400/60';              // moderate negative EV
  return 'text-gray-500';                              // negligible
}

const SIZING_TIER_STYLE: Record<string, { label: string; color: string; icon: string }> = {
  normal:  { label: '●', color: 'text-gray-400', icon: '' },
  boosted: { label: '▲', color: 'text-emerald-400', icon: '↑' },
  reduced: { label: '▼', color: 'text-yellow-400', icon: '↓' },
  halted:  { label: '■', color: 'text-red-400', icon: '⏸' },
};

// ── Favorites persistence (localStorage + server sync) ──────────────────
const FAVORITES_KEY = 'merid:kalshi:favorites';
function loadFavoritesLocal(): Set<string> {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function saveFavoritesLocal(favs: Set<string>) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favs]));
}

// ── URL preset helper ───────────────────────────────────────────────────
function getPresetFromURL(): QuickTab {
  try {
    const params = new URLSearchParams(window.location.search);
    const p = params.get('preset');
    if (p && QUICK_TABS.some(t => t.id === p)) return p as QuickTab;
  } catch { /* ignore */ }
  return 'all';
}
function setPresetInURL(tab: QuickTab) {
  try {
    const url = new URL(window.location.href);
    if (tab === 'all') url.searchParams.delete('preset');
    else url.searchParams.set('preset', tab);
    window.history.replaceState({}, '', url.toString());
  } catch { /* ignore */ }
}

const CATEGORY_COLORS: Record<string, string> = {
  trending:          'text-orange-300 bg-orange-300/10',
  crypto:            'text-orange-400 bg-orange-400/10',
  politics:          'text-purple-400 bg-purple-400/10',
  sports:            'text-red-400 bg-red-400/10',
  culture:           'text-pink-400 bg-pink-400/10',
  climate:           'text-teal-400 bg-teal-400/10',
  economics:         'text-blue-400 bg-blue-400/10',
  mentions:          'text-violet-400 bg-violet-400/10',
  companies:         'text-emerald-400 bg-emerald-400/10',
  financials:        'text-green-400 bg-green-400/10',
  tech:              'text-cyan-400 bg-cyan-400/10',
  science:           'text-yellow-400 bg-yellow-400/10',
  'tech & science':  'text-cyan-400 bg-cyan-400/10',
  'tech and science':'text-cyan-400 bg-cyan-400/10',
  live:              'text-red-300 bg-red-300/10',
};

// ── Orderbook mini-panel ─────────────────────────────────────────────────
interface ObLevel { price: number; quantity: number }
interface ObData { ticker: string; yes_bids: ObLevel[]; yes_asks: ObLevel[]; spread_cents: number | null; midpoint: number | null }

function OrderbookPanel({ ticker }: { ticker: string }) {
  const { data, loading } = useApiData<ObData>(
    API_ENDPOINTS.KALSHI_ORDERBOOK(ticker),
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  if (loading && !data) return <div className="animate-pulse h-24 bg-slate-800 rounded-lg" />;
  if (!data) return null;
  const maxQty = Math.max(...[...data.yes_bids, ...data.yes_asks].map(l => l.quantity), 1);
  return (
    <div className="bg-slate-800 rounded-lg p-3 space-y-1">
      <div className="flex justify-between text-[10px] text-gray-500 mb-1">
        <span>YES Bids</span>
        <span className="text-yellow-400">{data.spread_cents != null ? `${data.spread_cents}¢ spread` : '—'}</span>
        <span>YES Asks</span>
      </div>
      <div className="grid grid-cols-2 gap-1">
        <div className="space-y-0.5">
          {data.yes_bids.slice(0, 5).map((l, i) => (
            <div key={i} className="relative flex justify-between text-[10px] px-1">
              <div className="absolute inset-0 bg-green-500/10 rounded" style={{ width: `${(l.quantity / maxQty) * 100}%` }} />
              <span className="relative text-green-400 font-mono">{(l.price * 100).toFixed(0)}¢</span>
              <span className="relative text-gray-400">{l.quantity}</span>
            </div>
          ))}
        </div>
        <div className="space-y-0.5">
          {data.yes_asks.slice(0, 5).map((l, i) => (
            <div key={i} className="relative flex justify-between text-[10px] px-1">
              <div className="absolute inset-0 bg-red-500/10 rounded" style={{ width: `${(l.quantity / maxQty) * 100}%` }} />
              <span className="relative text-red-400 font-mono">{(l.price * 100).toFixed(0)}¢</span>
              <span className="relative text-gray-400">{l.quantity}</span>
            </div>
          ))}
        </div>
      </div>
      {data.midpoint != null && (
        <p className="text-center text-[10px] text-gray-500 pt-1">Mid: {(data.midpoint * 100).toFixed(1)}¢</p>
      )}
    </div>
  );
}

const KalshiDashboardView: React.FC = () => {
  const [selectedMarket, setSelectedMarket] = useState<CatalogMarket | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState<string>('');
  const [filterAsset, setFilterAsset] = useState<string>('');
  const [filterTimeframe, setFilterTimeframe] = useState<string>('');
  const [quickTab, setQuickTab] = useState<QuickTab>(getPresetFromURL);
  const [sortKey, setSortKey] = useState<SortKey>('volume');
  const [favorites, setFavorites] = useState<Set<string>>(loadFavoritesLocal);
  const [sizingHint, setSizingHint] = useState<{ contracts: number; side: 'yes' | 'no' } | null>(null);
  const [showOrderbook, setShowOrderbook] = useState(true);
  const [showPositionsSidebar, setShowPositionsSidebar] = useState(true);
  const [catalogRefreshing, setCatalogRefreshing] = useState(false);
  const autoRefreshedRef = useRef(false);

  const { data: venueModeData } = useKalshiMode();
  const venueMode: 'paper' | 'live' = venueModeData?.is_live ? 'live' : 'paper';

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  // Load favorites from server on mount (merge with localStorage)
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FAVORITES}`, {
          headers: authHeaders(),
        });
        if (res.ok) {
          const data = await res.json();
          const serverFavs: string[] = data.favorites ?? [];
          if (serverFavs.length > 0) {
            setFavorites(prev => {
              const merged = new Set([...prev, ...serverFavs]);
              saveFavoritesLocal(merged);
              return merged;
            });
          }
        }
      } catch { /* server unavailable — use localStorage */ }
    })();
  }, [authHeaders]);

  // Auto-refresh catalog on mount if empty
  useEffect(() => {
    if (autoRefreshedRef.current) return;
    autoRefreshedRef.current = true;
    (async () => {
      setCatalogRefreshing(true);
      try {
        await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CATALOG_REFRESH}`, {
          method: 'POST',
          headers: authHeaders(),
        });
        await Promise.all([mktsResult.refetch(), catResult.refetch()]);
      } catch { /* best effort */ } finally {
        setCatalogRefreshing(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync URL when quick tab changes + log telemetry
  useEffect(() => {
    setPresetInURL(quickTab);
    logUxEvent('tab_change', quickTab);
  }, [quickTab]);

  const toggleFavorite = useCallback((ticker: string, e?: React.MouseEvent) => {
    if (e) { e.stopPropagation(); e.preventDefault(); }
    logUxEvent('favorite_toggle', ticker);
    setFavorites(prev => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker); else next.add(ticker);
      saveFavoritesLocal(next);
      return next;
    });
    // Fire-and-forget server sync
    fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FAVORITES_TOGGLE}?ticker=${encodeURIComponent(ticker)}`, {
      method: 'POST',
      headers: authHeaders(),
    }).catch(() => { /* server sync best-effort */ });
  }, [authHeaders]);

  // Apply quick-tab presets to filter state
  const effectiveCategory = (quickTab === 'crypto-hourly' || quickTab === 'crypto-15m') ? 'crypto' : filterCategory;
  const effectiveAsset = filterAsset;
  const effectiveTimeframe = quickTab === 'crypto-hourly' ? '1h' : quickTab === 'crypto-15m' ? '15m' : filterTimeframe;
  const effectiveLive = quickTab === 'live';
  const effectiveSort = quickTab === 'trending' ? 'volume' : quickTab === 'live' ? 'expiry' : undefined;

  const marketsEndpoint = useMemo(() => {
    const params = new URLSearchParams();
    if (searchQuery) params.set('search', searchQuery);
    if (effectiveCategory) params.set('category', effectiveCategory);
    if (effectiveAsset) params.set('asset', effectiveAsset);
    if (effectiveTimeframe) params.set('timeframe', effectiveTimeframe);
    if (effectiveLive) params.set('live', 'true');
    if (effectiveSort) params.set('sort', effectiveSort);
    params.set('limit', '200');
    return `${API_ENDPOINTS.KALSHI_MARKETS}?${params}`;
  }, [searchQuery, effectiveCategory, effectiveAsset, effectiveTimeframe, effectiveLive, effectiveSort]);

  const mktsResult = useApiData<{ markets: CatalogMarket[] }>(marketsEndpoint, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  // Unfiltered market list used by positions sidebar — always fetches all markets regardless of active filters
  const allMktsResult = useApiData<{ markets: CatalogMarket[] }>(
    `${API_ENDPOINTS.KALSHI_MARKETS}?limit=500`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );
  const catResult = useApiData<CatalogSummary>(API_ENDPOINTS.KALSHI_CATALOG, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
  const healthResult = useApiData<HealthStatus>(API_ENDPOINTS.KALSHI_HEALTH, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
  const posResult = useApiData<{ positions: { ticker: string }[] }>(API_ENDPOINTS.KALSHI_POSITIONS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
  const edgeResult = useApiData<EdgeResponse>(API_ENDPOINTS.KALSHI_EDGE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND,
  });
  const sizingResult = useApiData<SizingMetrics>(API_ENDPOINTS.KALSHI_SIZING_METRICS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND,
  });
  const balResult = useApiData<{ available: number }>(API_ENDPOINTS.KALSHI_BALANCE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
  const consensusResult = useApiData<{
    signals: Array<{ ticker: string; direction: string; confidence: number; vote_count: number }>;
    count: number;
    pending_votes: number;
    consensus_rate: number;
    engine_running: boolean;
  }>(API_ENDPOINTS.KALSHI_CONSENSUS_SIGNALS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND,
  });
  const newsResult = useApiData<{
    signals: Array<{ title: string; source: string; importance: number; published_at: string | null; assets: string[]; categories: string[]; url: string }>;
    count: number;
    monitor_running: boolean;
  }>(API_ENDPOINTS.KALSHI_NEWS_SIGNALS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND,
  });

  // Per-market detail + liquidity health + volume history — only fetched when a market is selected
  const marketDetailResult = useApiData<{ ticker: string; open_interest: number; liquidity_score: number; last_trade_price: number; last_trade_ts: string | null }>(selectedMarket ? API_ENDPOINTS.KALSHI_MARKET_DETAIL(selectedMarket.ticker) : '', { pollingInterval: selectedMarket ? DEFAULTS.POLLING_INTERVALS.STANDARD : 0 });
  const liqHealthResult = useApiData<{ ticker: string; spread_cents: number | null; book_depth: number; thin_book: boolean; wide_spread: boolean; health_score: number; recommendation: string }>(selectedMarket ? API_ENDPOINTS.KALSHI_LIQUIDITY_HEALTH(selectedMarket.ticker) : '', { pollingInterval: selectedMarket ? DEFAULTS.POLLING_INTERVALS.STANDARD : 0 });
  const volHistoryResult = useApiData<{ ticker: string; history: Array<{ ts: string; volume: number }> }>(selectedMarket ? API_ENDPOINTS.KALSHI_VOLUME_HISTORY(selectedMarket.ticker) : '', { pollingInterval: selectedMarket ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 });
  const volSmoothedResult = useApiData<{ ticker: string; smoothed: Array<{ ts: string; volume: number }> }>(selectedMarket ? API_ENDPOINTS.KALSHI_VOLUME_SMOOTHED(selectedMarket.ticker) : '', { pollingInterval: selectedMarket ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 });

  const positionTickers = useMemo(() => {
    const tickers = new Set<string>();
    for (const p of posResult.data?.positions ?? []) tickers.add(p.ticker);
    return tickers;
  }, [posResult.data]);

  // Sort and filter markets based on quick tab and sort key
  const markets = useMemo(() => {
    let filtered = [...(mktsResult.data?.markets ?? [])];

    // My Positions filter
    if (quickTab === 'my-positions') {
      filtered = filtered.filter(m => positionTickers.has(m.ticker));
    }

    // Favorites filter
    if (quickTab === 'favorites') {
      filtered = filtered.filter(m => favorites.has(m.ticker));
    }

    // Trending: top volume, already sorted server-side — just ensure volume > 0
    if (quickTab === 'trending') {
      filtered = filtered.filter(m => m.volume > 0);
    }

    // Live Now: active markets only, sorted by soonest expiry (server does this too)
    if (quickTab === 'live') {
      filtered = filtered.filter(m => m.active !== false);
    }

    // Top Volume: only show markets with volume > 0
    if (quickTab === 'top-volume') {
      filtered = filtered.filter(m => m.volume > 0);
    }

    // New Markets: sort by nearest expiry (soonest first)
    if (quickTab === 'new-markets') {
      filtered.sort((a, b) => {
        const ea = a.expires_at ? new Date(a.expires_at).getTime() : Infinity;
        const eb = b.expires_at ? new Date(b.expires_at).getTime() : Infinity;
        return ea - eb;
      });
      return filtered;
    }

    // Apply sort
    if (sortKey === 'volume') {
      filtered.sort((a, b) => b.volume - a.volume);
    } else if (sortKey === 'expiry') {
      filtered.sort((a, b) => (a.minutes_to_expiry ?? Infinity) - (b.minutes_to_expiry ?? Infinity));
    } else if (sortKey === 'spread') {
      const getSpread = (m: CatalogMarket) => {
        const o = m.outcomes[0];
        if (!o?.bid || !o?.ask) return Infinity;
        return o.ask - o.bid;
      };
      filtered.sort((a, b) => getSpread(a) - getSpread(b));
    }

    return filtered;
  }, [mktsResult.data?.markets, quickTab, sortKey, positionTickers, favorites]);
  const catalog = catResult.data;
  const health = healthResult.data;
  // Only show full loading skeleton when markets have never loaded (first fetch).
  // Subsequent polls keep stale data visible — no flash on every refetch.
  const loading = mktsResult.loading && !mktsResult.data;

  const [refreshError, setRefreshError] = useState<string | null>(null);

  const mktsRefetch = mktsResult.refetch;
  const catRefetch  = catResult.refetch;

  const handleRefreshCatalog = useCallback(async () => {
    setRefreshError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CATALOG_REFRESH}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      await Promise.all([mktsRefetch(), catRefetch()]);
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : 'Catalog refresh failed');
    }
  }, [authHeaders, mktsRefetch, catRefetch]);

  const healthColor = health?.status === 'healthy' ? 'text-green-400' : health?.status === 'degraded' ? 'text-yellow-400' : 'text-red-400';
  const healthBg = health?.status === 'healthy' ? 'bg-green-400/10' : health?.status === 'degraded' ? 'bg-yellow-400/10' : 'bg-red-400/10';
  const isLive = venueMode === 'live';

  return (
    <div className="space-y-4">
      {/* Execution Gate — always visible */}
      <ExecutionGateStrip />

      {/* Live mode banner */}
      {isLive && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-xs font-medium">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          LIVE TRADING ACTIVE — real orders on Kalshi. Kill switch is {health?.risk.kill_switch ? <span className="text-red-400 font-bold ml-1">ENGAGED</span> : <span className="text-green-300 ml-1">clear</span>}.
        </div>
      )}

      {/* Refresh error banner */}
      {refreshError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Catalog refresh failed: {refreshError}</span>
          <button type="button" onClick={() => setRefreshError(null)} className="ml-auto text-red-400 hover:text-red-300" title="Dismiss" aria-label="Dismiss error"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-6 h-6 text-orange-400" />
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              Kalshi Markets
              <KalshiModeBadge />
              {catalogRefreshing && <RefreshCw className="w-3.5 h-3.5 text-gray-500 animate-spin" />}
            </h1>
            <p className="text-xs text-gray-500">
              {catalog ? `${catalog.market_count.toLocaleString()} markets · ${Object.keys(catalog.categories).length} categories` : 'Refreshing catalog...'}
              {catalog?.last_refresh && ` · updated ${new Date(catalog.last_refresh).toLocaleTimeString()}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Balance */}
          {balResult.data && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800">
              <DollarSign className="w-3.5 h-3.5 text-green-400" />
              <span className="text-sm font-bold text-green-400">${(balResult.data.available ?? 0).toFixed(2)}</span>
              <span className="text-[10px] text-gray-500">avail</span>
            </div>
          )}
          {/* Health */}
          {health && (
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg ${healthBg}`}>
              <Heart className={`w-3.5 h-3.5 ${healthColor}`} />
              <span className={`text-xs font-medium ${healthColor}`}>{health.status.toUpperCase()}</span>
            </div>
          )}
          {/* Positions sidebar toggle */}
          <button
            type="button"
            onClick={() => setShowPositionsSidebar(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-all ${showPositionsSidebar ? 'bg-orange-500/10 border-orange-500/30 text-orange-300' : 'bg-slate-900 border-slate-800 text-gray-400 hover:text-white'}`}
            title="Toggle positions sidebar"
          >
            <Briefcase className="w-3.5 h-3.5" />
            {positionTickers.size > 0 && <span className="font-bold">{positionTickers.size}</span>}
          </button>
          <button
            type="button"
            onClick={handleRefreshCatalog}
            disabled={catalogRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-gray-300 text-xs disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${catalogRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
        {/* Markets */}
        <div className="bg-slate-900 rounded-xl p-3 border border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <Activity className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Markets</span>
          </div>
          <p className="text-lg font-bold text-white">{catalog?.market_count ?? 0}</p>
          <p className="text-[10px] text-gray-600">{Object.keys(catalog?.categories ?? {}).length} categories</p>
        </div>
        {/* Daily PnL */}
        <div className="bg-slate-900 rounded-xl p-3 border border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <DollarSign className="w-3.5 h-3.5 text-green-400" />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Daily PnL</span>
          </div>
          <p className={`text-lg font-bold ${(health?.risk.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${health?.risk.daily_pnl?.toFixed(2) ?? '0.00'}
          </p>
          <p className="text-[10px] text-gray-600">DD: {health?.risk.drawdown_pct?.toFixed(1) ?? 0}%</p>
        </div>
        {/* Kelly */}
        <div className="bg-slate-900 rounded-xl p-3 border border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <Gauge className="w-3.5 h-3.5 text-orange-400" />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Kelly</span>
          </div>
          <p className="text-lg font-bold text-white">{sizingResult.data ? `${((sizingResult.data.kelly_fraction ?? 0) * 100).toFixed(1)}%` : '—'}</p>
          <p className="text-[10px] text-gray-600">eff: {sizingResult.data ? `${((sizingResult.data.effective_fraction ?? 0) * 100).toFixed(2)}%` : '—'}</p>
        </div>
        {/* Edge signals */}
        <div className="bg-slate-900 rounded-xl p-3 border border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            <Target className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Signals</span>
          </div>
          <p className="text-lg font-bold text-white">{edgeResult.data?.count ?? 0}</p>
          <p className="text-[10px] text-gray-600">edge signals</p>
        </div>
        {/* WS */}
        <div className="bg-slate-900 rounded-xl p-3 border border-slate-800">
          <div className="flex items-center gap-1.5 mb-1">
            {health?.ws.running ? <Wifi className="w-3.5 h-3.5 text-cyan-400" /> : <WifiOff className="w-3.5 h-3.5 text-red-400" />}
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">WS Feed</span>
          </div>
          <p className={`text-lg font-bold ${health?.ws.running ? 'text-cyan-400' : 'text-red-400'}`}>{health?.ws.events_forwarded ?? 0}</p>
          <p className="text-[10px] text-gray-600">{health?.ws.subscribed_tickers ?? 0} tickers</p>
        </div>
        {/* Kill Switch */}
        <div className={`rounded-xl p-3 border ${health?.risk.kill_switch ? 'bg-red-500/10 border-red-500/30' : 'bg-slate-900 border-slate-800'}`}>
          <div className="flex items-center gap-1.5 mb-1">
            <Shield className={`w-3.5 h-3.5 ${health?.risk.kill_switch ? 'text-red-400' : 'text-green-400'}`} />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Kill Switch</span>
          </div>
          <p className={`text-lg font-bold ${health?.risk.kill_switch ? 'text-red-400' : 'text-green-400'}`}>
            {health?.risk.kill_switch ? 'ACTIVE' : 'OFF'}
          </p>
          <p className="text-[10px] text-gray-600">{health?.rate_limits.orders_this_minute ?? 0}/{health?.rate_limits.max_per_minute ?? 30}/min</p>
        </div>
        {/* Consensus Signals */}
        <div className={`rounded-xl p-3 border ${consensusResult.data?.engine_running ? 'bg-slate-900 border-slate-800' : 'bg-slate-900/50 border-slate-800/50'}`}>
          <div className="flex items-center gap-1.5 mb-1">
            <Radio className={`w-3.5 h-3.5 ${consensusResult.data?.engine_running ? 'text-purple-400' : 'text-gray-600'}`} />
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Consensus</span>
          </div>
          <p className="text-lg font-bold text-white">{consensusResult.data?.count ?? 0}</p>
          <p className="text-[10px] text-gray-600">{consensusResult.data ? `${(consensusResult.data.consensus_rate * 100).toFixed(0)}% rate` : 'engine off'}</p>
        </div>
      </div>

      {/* News Signals Panel — only shown when monitor is running and has signals */}
      {newsResult.data && newsResult.data.count > 0 && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-3">
          <div className="flex items-center gap-2 mb-2">
            <Radio className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-xs font-semibold text-white uppercase tracking-wider">News Signals</span>
            <span className="text-[10px] text-gray-500">{newsResult.data.count} items</span>
            {newsResult.data.monitor_running && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse ml-auto" />}
          </div>
          <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto">
            {newsResult.data.signals.slice(0, 5).map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold ${s.importance >= 0.9 ? 'bg-red-500/20 text-red-400' : s.importance >= 0.7 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-slate-700 text-gray-400'}`}>
                  {s.importance >= 0.9 ? 'HIGH' : s.importance >= 0.7 ? 'MED' : 'LOW'}
                </span>
                <span className="text-gray-300 flex-1 leading-tight">{s.title}</span>
                {s.assets.length > 0 && (
                  <div className="flex gap-1 shrink-0">
                    {s.assets.slice(0, 3).map(a => (
                      <span key={a} className="px-1 py-0.5 rounded bg-orange-500/20 text-orange-300 text-[10px] font-mono">{a}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Continuous Trader diagnostics panel */}
      <CTStatusPanel />

      {/* Quick-Filter Tabs */}
      <div className="flex items-center gap-1 bg-slate-900 rounded-xl p-1 border border-slate-800 overflow-x-auto">
        {QUICK_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = quickTab === tab.id;
          return (
            <button
              type="button"
              key={tab.id}
              onClick={() => {
                setQuickTab(tab.id);
                if (!['all', 'my-positions', 'favorites'].includes(tab.id)) {
                  setFilterCategory('');
                  setFilterTimeframe('');
                }
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/40'
                  : 'text-gray-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {tab.label}
              {tab.id === 'live' && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />}
              {tab.id === 'my-positions' && positionTickers.size > 0 && (
                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-orange-500/30 text-orange-300 text-[10px]">
                  {positionTickers.size}
                </span>
              )}
              {tab.id === 'favorites' && favorites.size > 0 && (
                <span className="ml-1 px-1.5 py-0.5 rounded-full bg-yellow-500/30 text-yellow-300 text-[10px]">
                  {favorites.size}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Search */}
      <div className="flex items-center gap-2">
        <Search className="w-4 h-4 text-gray-400 shrink-0" />
        <input
          type="text"
          placeholder="Search by ticker, question, or asset..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 bg-slate-900 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 border border-slate-800 focus:border-orange-500 focus:outline-none"
          aria-label="Search markets"
        />
        {searchQuery && (
          <button type="button" onClick={() => setSearchQuery('')} className="text-gray-500 hover:text-white" title="Clear search" aria-label="Clear search">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Category chips */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-gray-500 shrink-0" />
          <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Category</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => { setFilterCategory(''); setQuickTab('all'); }}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
              !filterCategory && quickTab === 'all'
                ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500'
                : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
            }`}
          >
            All Categories
          </button>
          {Object.entries(catalog?.categories ?? {}).map(([cat, count]) => (
            <button
              type="button"
              key={cat}
              onClick={() => { setFilterCategory(filterCategory === cat ? '' : cat); setQuickTab('all'); }}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-all capitalize ${
                filterCategory === cat
                  ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500'
                  : (CATEGORY_COLORS[cat] ?? 'text-gray-400 bg-slate-800') + ' hover:ring-1 hover:ring-white/20'
              }`}
            >
              {cat} <span className="opacity-60">({count})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Asset + Timeframe + Sort chips */}
      <div className="flex flex-wrap gap-4">
        {/* Assets — AUDIT-05: always show canonical BTC/ETH/SOL/XRP/DOGE chips,
             merging counts from catalog when available. */}
        {(() => {
          const CANONICAL_ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
          const catalogAssets: Record<string, number> = catalog?.assets ?? {};
          // Build display list: canonical assets first, then any extra from catalog
          const extraAssets = Object.keys(catalogAssets).filter(
            a => !CANONICAL_ASSETS.includes(a)
          );
          const displayAssets = [...CANONICAL_ASSETS, ...extraAssets];
          return (
            <div className="space-y-2 flex-1 min-w-[200px]">
              <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Asset</span>
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => setFilterAsset('')}
                  className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all ${
                    !filterAsset
                      ? 'bg-blue-500/20 text-blue-300 ring-1 ring-blue-500'
                      : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
                  }`}
                >
                  All Assets
                </button>
                {displayAssets.map(asset => {
                  const count = catalogAssets[asset];
                  return (
                    <button
                      type="button"
                      key={asset}
                      onClick={() => setFilterAsset(filterAsset === asset ? '' : asset)}
                      className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all ${
                        filterAsset === asset
                          ? 'bg-blue-500/20 text-blue-300 ring-1 ring-blue-500'
                          : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
                      }`}
                    >
                      {asset}
                      {count !== undefined && (
                        <span className="opacity-60 ml-1">({count})</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })()}

        {/* Timeframes */}
        {Object.keys(catalog?.timeframes ?? {}).length > 0 && (
          <div className="space-y-2 flex-1 min-w-[200px]">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Timeframe</span>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => { setFilterTimeframe(''); setQuickTab('all'); }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all ${
                  !filterTimeframe
                    ? 'bg-purple-500/20 text-purple-300 ring-1 ring-purple-500'
                    : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
                }`}
              >
                All Timeframes
              </button>
              {Object.entries(catalog?.timeframes ?? {}).map(([tf, count]) => (
                <button
                  type="button"
                  key={tf}
                  onClick={() => { setFilterTimeframe(filterTimeframe === tf ? '' : tf); setQuickTab('all'); }}
                  className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all ${
                    filterTimeframe === tf
                      ? 'bg-purple-500/20 text-purple-300 ring-1 ring-purple-500'
                      : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
                  }`}
                >
                  {tf} <span className="opacity-60">({count})</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Sort + OB toggle */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Sort</span>
            <button
              type="button"
              onClick={() => setShowOrderbook(v => !v)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border transition-all ${
                showOrderbook ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300' : 'bg-slate-800 border-slate-700 text-gray-500 hover:text-white'
              }`}
              title="Toggle live orderbook in cards"
            >
              <Layers className="w-3 h-3" /> OB
            </button>
          </div>
          <div className="flex gap-1.5">
            {(['volume', 'expiry', 'spread'] as SortKey[]).map((key) => (
              <button
                type="button"
                key={key}
                onClick={() => setSortKey(key)}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all flex items-center gap-1 ${
                  sortKey === key
                    ? 'bg-yellow-500/20 text-yellow-300 ring-1 ring-yellow-500'
                    : 'text-gray-400 bg-slate-800 hover:text-white hover:bg-slate-700'
                }`}
              >
                {key === 'volume' && <TrendingUp className="w-3 h-3" />}
                {key === 'expiry' && <Clock className="w-3 h-3" />}
                {key === 'spread' && <ArrowUpDown className="w-3 h-3" />}
                {key.charAt(0).toUpperCase() + key.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Sizing Context Strip */}
      {sizingResult.data && (
        <div className="flex items-center gap-4 px-4 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs">
          <div className="flex items-center gap-1.5">
            <Gauge className="w-3.5 h-3.5 text-orange-400" />
            <span className="text-gray-500">Sizing:</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-gray-400">Kelly</span>
            <span className="font-mono text-white">{((sizingResult.data.kelly_fraction ?? 0) * 100).toFixed(1)}%</span>
            <span className="text-gray-600">({sizingResult.data.kelly_utilization_pct?.toFixed(0) ?? '—'}% util)</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1">
            <span className="text-gray-400">Vol Scale</span>
            <span className="font-mono text-white">{sizingResult.data.vol_scale?.toFixed(2) ?? '—'}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1">
            <span className="text-gray-400">Eff Risk</span>
            <span className="font-mono text-white">{((sizingResult.data.effective_fraction ?? 0) * 100).toFixed(2)}%</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1">
            <span className="text-gray-400">DD</span>
            <span className={`font-mono ${
              sizingResult.data.drawdown_tier === 'normal' ? 'text-green-400'
              : sizingResult.data.drawdown_tier === 'warning' ? 'text-yellow-400'
              : 'text-red-400'
            }`}>
              {sizingResult.data.drawdown_pct?.toFixed(1) ?? '0'}%
            </span>
            <span className={`text-[10px] font-medium px-1 py-0 rounded ${
              sizingResult.data.drawdown_tier === 'normal' ? 'bg-green-500/10 text-green-400'
              : sizingResult.data.drawdown_tier === 'warning' ? 'bg-yellow-500/10 text-yellow-400'
              : sizingResult.data.drawdown_tier === 'downsize' ? 'bg-orange-500/10 text-orange-400'
              : 'bg-red-500/10 text-red-400'
            }`}>
              {sizingResult.data.drawdown_tier?.toUpperCase()}
            </span>
          </div>
          {edgeResult.data && (
            <>
              <span className="text-slate-700">|</span>
              <span className="text-gray-500">{edgeResult.data.count} signals</span>
            </>
          )}
        </div>
      )}

      {/* Market Grid + Positions Sidebar */}
      <div className="flex gap-4 items-start">
      <div className="flex-1 min-w-0">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <div className="col-span-full text-center py-12 text-gray-500">Loading markets...</div>
        ) : markets.length === 0 ? (
          <div className="col-span-full text-center py-12 text-gray-500">
            No markets found. Try adjusting filters or refreshing the catalog.
          </div>
        ) : (
          markets.map((m) => (
            <div
              key={m.ticker}
              className={`relative bg-slate-900 rounded-xl p-4 border transition-all group ${
                quickTab === 'live'
                  ? 'border-red-500/30 hover:border-red-400/60'
                  : 'border-slate-800 hover:border-orange-500/50'
              }`}
            >
              {/* Clickable overlay for card — sits behind the star button */}
              <button
                type="button"
                className="absolute inset-0 w-full h-full rounded-xl cursor-pointer focus:outline-none focus:ring-2 focus:ring-orange-500/50"
                onClick={() => { setSelectedMarket(m); logUxEvent('ticket_open', m.ticker); }}
                aria-label={`Open market: ${m.question}`}
              />
              <div className="relative flex items-start justify-between mb-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    {quickTab === 'live' && (
                      <span className="inline-flex items-center gap-1 shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                      </span>
                    )}
                    <p className="text-sm font-medium text-white truncate group-hover:text-orange-300 transition-colors">
                      {m.question}
                    </p>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 font-mono">{m.ticker}</p>
                </div>
                <div className="relative z-10 flex items-center gap-1 shrink-0 ml-2">
                  {/* Favorite star — z-10 so it sits above the card overlay */}
                  <button
                    type="button"
                    onClick={(e) => toggleFavorite(m.ticker, e)}
                    className={`p-1 rounded hover:bg-slate-700 transition-colors ${
                      favorites.has(m.ticker) ? 'text-yellow-400' : 'text-gray-600 hover:text-yellow-400'
                    }`}
                    title={favorites.has(m.ticker) ? 'Remove from favorites' : 'Add to favorites'}
                    aria-label={favorites.has(m.ticker) ? 'Remove from favorites' : 'Add to favorites'}
                  >
                    <Star className={`w-3.5 h-3.5 ${favorites.has(m.ticker) ? 'fill-current' : ''}`} />
                  </button>
                  <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-orange-400" />
                </div>
              </div>

              <div className="flex items-center gap-2 mb-3 flex-wrap">
                {m.category && (
                  <span className={`px-2 py-0.5 rounded text-xs ${CATEGORY_COLORS[m.category] || 'text-gray-400 bg-slate-800'}`}>
                    {m.category}
                  </span>
                )}
                {m.asset && (
                  <span className="px-2 py-0.5 rounded text-xs text-blue-400 bg-blue-400/10">
                    {m.asset}
                  </span>
                )}
                {m.timeframe && (
                  <span className="px-2 py-0.5 rounded text-xs text-gray-400 bg-slate-800">
                    {m.timeframe}
                  </span>
                )}
                {/* Spread / liquidity badges */}
                {(() => {
                  const o = m.outcomes[0];
                  const sBadge = o ? spreadBadge(o.bid, o.ask) : null;
                  const vBadge = volumeBadge(m.volume);
                  return (
                    <>
                      {sBadge && (
                        <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${sBadge.color}`} title={sBadge.tooltip}>
                          {sBadge.label}
                        </span>
                      )}
                      {vBadge && (
                        <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${vBadge.color}`} title={vBadge.tooltip}>
                          {vBadge.label}
                        </span>
                      )}
                    </>
                  );
                })()}
                {/* Position badge */}
                {positionTickers.has(m.ticker) && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-medium text-orange-300 bg-orange-500/20">
                    <Briefcase className="w-2.5 h-2.5 inline mr-0.5" />POSITION
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between">
                <div className="flex gap-3">
                  {m.outcomes.map((o) => {
                    const sig = edgeResult.data?.signals?.[m.ticker];
                    const evCents = sig ? sig.ev_cents : Math.round((0.5 - o.price) * 100);
                    const confBucket = sig?.confidence_bucket ?? 'low';
                    const sizTier = sig ? SIZING_TIER_STYLE[sig.sizing_tier] : null;
                    return (
                      <div key={o.id} className="text-center">
                        <p className="text-xs text-gray-500">{o.name}</p>
                        <p className={`text-sm font-bold ${o.price >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                          {(o.price * 100).toFixed(0)}¢
                        </p>
                        <p className={`text-[10px] ${edgeColor(evCents, confBucket)}`}>
                          EV: {evCents > 0 ? '+' : ''}{evCents}¢
                          {sig && confBucket !== 'low' && (
                            <span className="ml-0.5 opacity-60">{confBucket === 'high' ? '●●●' : '●●○'}</span>
                          )}
                        </p>
                        {sizTier && sizTier.icon && (
                          <span className={`text-[9px] ${sizTier.color}`} title={`Sizing: ${sig?.sizing_tier}`}>
                            {sizTier.icon}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div className="text-right">
                  {m.minutes_to_expiry != null && (
                    <div className="flex items-center gap-1 text-xs text-gray-500">
                      <Clock className="w-3 h-3" />
                      {m.minutes_to_expiry < 60
                        ? `${m.minutes_to_expiry.toFixed(0)}m`
                        : m.minutes_to_expiry < 1440
                        ? `${(m.minutes_to_expiry / 60).toFixed(1)}h`
                        : `${(m.minutes_to_expiry / 1440).toFixed(0)}d`}
                    </div>
                  )}
                  <p className="text-xs text-gray-600">Vol: {m.volume.toLocaleString()}</p>
                </div>
              </div>
              {/* Live orderbook strip */}
              {showOrderbook && (
                <div className="mt-3 pt-3 border-t border-slate-800">
                  <OrderbookPanel ticker={m.ticker} />
                </div>
              )}
            </div>
          ))
        )}
      </div>
      </div>

      {/* Positions Sidebar */}
      {showPositionsSidebar && positionTickers.size > 0 && (
        <div className="w-56 shrink-0 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Briefcase className="w-3.5 h-3.5 text-orange-400" />
              <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Positions</span>
            </div>
            <span className="text-[10px] text-gray-500">{positionTickers.size} open</span>
          </div>
          {[...positionTickers].map(ticker => {
            const mkt = (allMktsResult.data?.markets ?? mktsResult.data?.markets ?? []).find(m => m.ticker === ticker);
            const sig = edgeResult.data?.signals?.[ticker];
            const exp = mkt?.minutes_to_expiry;
            return (
              <div key={ticker} className="bg-slate-900 rounded-xl p-3 border border-orange-500/20 hover:border-orange-500/40 transition-all">
                <button
                  type="button"
                  className="w-full text-left"
                  onClick={() => { if (mkt) { setSelectedMarket(mkt); setSizingHint(null); } }}
                >
                  <p className="text-xs font-medium text-white truncate mb-0.5">{mkt?.question ?? ticker}</p>
                  <p className="text-[10px] text-gray-600 font-mono mb-2">{ticker}</p>
                  {mkt && (
                    <div className="flex items-center justify-between">
                      <div className="flex gap-2">
                        {mkt.outcomes.map(o => (
                          <div key={o.id}>
                            <p className="text-[9px] text-gray-500">{o.name}</p>
                            <p className={`text-sm font-bold font-mono ${o.name.toLowerCase() === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
                              {(o.price * 100).toFixed(0)}¢
                            </p>
                          </div>
                        ))}
                      </div>
                      <div className="text-right">
                        {exp != null && (
                          <p className={`text-[10px] font-mono ${
                            exp < 60 ? 'text-red-400' : exp < 1440 ? 'text-yellow-400' : 'text-gray-500'
                          }`}>
                            {exp < 60 ? `${exp.toFixed(0)}m` : exp < 1440 ? `${(exp / 60).toFixed(1)}h` : `${(exp / 1440).toFixed(0)}d`}
                          </p>
                        )}
                        {sig && (
                          <p className={`text-[9px] font-medium ${
                            sig.ev_cents >= 1 ? 'text-emerald-400' : sig.ev_cents <= -1 ? 'text-red-400' : 'text-gray-500'
                          }`}>
                            EV {sig.ev_cents > 0 ? '+' : ''}{sig.ev_cents}¢
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      )}

      </div>

      {/* Market Detail Slide-over */}
      {selectedMarket && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            className="absolute inset-0 w-full h-full bg-black/50 cursor-default"
            onClick={() => setSelectedMarket(null)}
            aria-label="Close overlay"
          />
          <div className="relative w-full max-w-lg bg-slate-900 border-l border-slate-800 overflow-y-auto">
            <div className="sticky top-0 bg-slate-900 border-b border-slate-800 p-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Market Detail</h2>
              <button
                type="button"
                onClick={() => setSelectedMarket(null)}
                className="p-1 rounded hover:bg-slate-700 text-gray-400"
                aria-label="Close market detail"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <p className="text-white font-medium">{selectedMarket.question}</p>
                <p className="text-xs text-gray-500 font-mono mt-1">{selectedMarket.ticker}</p>
              </div>

              <div className="flex flex-wrap gap-2">
                {selectedMarket.category && (
                  <span className={`px-2 py-1 rounded text-xs ${CATEGORY_COLORS[selectedMarket.category] || 'text-gray-400 bg-slate-800'}`}>
                    {selectedMarket.category}
                  </span>
                )}
                {selectedMarket.asset && (
                  <span className="px-2 py-1 rounded text-xs text-blue-400 bg-blue-400/10">{selectedMarket.asset}</span>
                )}
                {selectedMarket.timeframe && (
                  <span className="px-2 py-1 rounded text-xs text-gray-400 bg-slate-800">{selectedMarket.timeframe}</span>
                )}
                <span className="px-2 py-1 rounded text-xs text-gray-400 bg-slate-800">{selectedMarket.market_type}</span>
              </div>

              <div className="bg-slate-800 rounded-lg p-4">
                <h3 className="text-sm font-medium text-gray-300 mb-3">Outcomes</h3>
                <div className="space-y-3">
                  {selectedMarket.outcomes.map((o) => (
                    <div key={o.id} className="flex items-center justify-between">
                      <span className="text-sm text-white">{o.name}</span>
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <p className={`text-lg font-bold ${o.price >= 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                            {(o.price * 100).toFixed(1)}¢
                          </p>
                        </div>
                        {o.bid != null && o.ask != null && (
                          <div className="text-xs text-gray-500">
                            <p>Bid: {(o.bid * 100).toFixed(0)}¢</p>
                            <p>Ask: {(o.ask * 100).toFixed(0)}¢</p>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Spread Depth Visualization */}
              {(() => {
                const o = selectedMarket.outcomes[0];
                if (!o || o.bid == null || o.ask == null) return null;
                const bid = o.bid * 100;
                const ask = o.ask * 100;
                const spread = ask - bid;
                const mid = (bid + ask) / 2;
                const sig = edgeResult.data?.signals?.[selectedMarket.ticker];
                return (
                  <div className="bg-slate-800 rounded-lg p-4">
                    <h3 className="text-sm font-medium text-gray-300 mb-3">Spread & Edge</h3>
                    {/* Spread bar */}
                    <div className="relative h-8 bg-slate-700 rounded overflow-hidden mb-2">
                      <div
                        className="absolute h-full bg-green-500/30 rounded-l"
                        style={{ left: 0, width: `${Math.min(100, bid)}%` }}
                      />
                      <div
                        className="absolute h-full bg-red-500/30 rounded-r"
                        style={{ left: `${Math.min(100, ask)}%`, width: `${Math.max(0, 100 - ask)}%` }}
                      />
                      <div
                        className="absolute h-full bg-yellow-500/20"
                        style={{ left: `${bid}%`, width: `${spread}%` }}
                      />
                      <div className="absolute inset-0 flex items-center justify-between px-2 text-[10px]">
                        <span className="text-green-400 font-mono">Bid {bid.toFixed(0)}¢</span>
                        <span className="text-yellow-400 font-mono">{spread.toFixed(1)}¢ spread</span>
                        <span className="text-red-400 font-mono">Ask {ask.toFixed(0)}¢</span>
                      </div>
                    </div>
                    {/* Edge signals from /edge endpoint */}
                    {sig && (
                      <div className="grid grid-cols-3 gap-2 mt-3">
                        <div className="text-center">
                          <p className="text-[10px] text-gray-500">Model Prob</p>
                          <p className="text-sm font-bold text-white font-mono">{((sig.model_prob ?? 0) * 100).toFixed(1)}¢</p>
                        </div>
                        <div className="text-center">
                          <p className="text-[10px] text-gray-500">EV/contract</p>
                          <p className={`text-sm font-bold font-mono ${sig.ev_cents >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {sig.ev_cents >= 0 ? '+' : ''}{sig.ev_cents}¢
                          </p>
                        </div>
                        <div className="text-center">
                          <p className="text-[10px] text-gray-500">Confidence</p>
                          <p className={`text-sm font-bold font-mono ${
                            sig.confidence_bucket === 'high' ? 'text-emerald-400'
                            : sig.confidence_bucket === 'medium' ? 'text-yellow-400'
                            : 'text-gray-500'
                          }`}>
                            {sig.confidence_bucket === 'high' ? '●●●' : sig.confidence_bucket === 'medium' ? '●●○' : '●○○'}
                            <span className="ml-1 text-[10px]">{((sig.confidence ?? 0) * 100).toFixed(0)}%</span>
                          </p>
                        </div>
                      </div>
                    )}
                    {/* Mid price marker */}
                    <p className="text-[10px] text-gray-500 mt-2 text-center">
                      Mid: {mid.toFixed(1)}¢ · Implied: {(o.price * 100).toFixed(1)}¢
                      {sig ? ` · Edge: ${sig.edge_pct >= 0 ? '+' : ''}${sig.edge_pct}%` : ''}
                    </p>
                  </div>
                );
              })()}

              <div className="grid grid-cols-2 gap-3">
                <div className="bg-slate-800 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Volume</p>
                  <p className="text-sm font-medium text-white">{selectedMarket.volume.toLocaleString()}</p>
                </div>
                <div className="bg-slate-800 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Time to Expiry</p>
                  <p className="text-sm font-medium text-white">
                    {selectedMarket.minutes_to_expiry != null
                      ? selectedMarket.minutes_to_expiry < 60
                        ? `${selectedMarket.minutes_to_expiry.toFixed(0)} min`
                        : selectedMarket.minutes_to_expiry < 1440
                        ? `${(selectedMarket.minutes_to_expiry / 60).toFixed(1)} hrs`
                        : `${(selectedMarket.minutes_to_expiry / 1440).toFixed(1)} days`
                      : '—'}
                  </p>
                </div>
                <div className="bg-slate-800 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Status</p>
                  <p className={`text-sm font-medium ${selectedMarket.active ? 'text-green-400' : 'text-gray-500'}`}>
                    {selectedMarket.active ? 'Active' : 'Inactive'}
                  </p>
                </div>
                <div className="bg-slate-800 rounded-lg p-3">
                  <p className="text-xs text-gray-500">Expires</p>
                  <p className="text-sm font-medium text-white">
                    {selectedMarket.expires_at
                      ? new Date(selectedMarket.expires_at).toLocaleDateString()
                      : '—'}
                  </p>
                </div>
              </div>

              {/* Sizing Hint */}
              {(() => {
                const sig = edgeResult.data?.signals?.[selectedMarket.ticker];
                const sizing = sizingResult.data;
                if (!sig || !sizing) return null;

                const effective = sizing.effective_fraction;
                const ddTier = sizing.drawdown_tier;
                const evCents = sig.ev_cents;
                const conf = sig.confidence;

                // Only show sizing hint when there's positive edge with decent confidence
                if (evCents <= 0 || conf < 0.3) return null;

                const bankroll = balResult.data?.available ?? 100;
                const kellyBet = effective * conf * bankroll;
                const priceCents = (selectedMarket.outcomes[0]?.price ?? 0.5) * 100;
                const suggestedContracts = Math.max(1, Math.floor(kellyBet / (priceCents / 100)));
                const suggestedSide: 'yes' | 'no' = sig.model_prob > sig.implied_prob ? 'yes' : 'no';

                // Build rationale
                const parts: string[] = [];
                parts.push(`${((effective ?? 0) * 100).toFixed(2)}% eff. Kelly`);
                if (ddTier !== 'normal') parts.push(`${ddTier} tier`);
                if (selectedMarket.asset) parts.push(`${selectedMarket.asset} limit`);
                parts.push(`${((conf ?? 0) * 100).toFixed(0)}% conf`);
                const rationale = parts.join(' · ');

                return (
                  <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Suggested Size</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        ddTier === 'normal' ? 'bg-emerald-500/10 text-emerald-400'
                        : ddTier === 'warning' ? 'bg-yellow-500/10 text-yellow-400'
                        : 'bg-red-500/10 text-red-400'
                      }`}>
                        {sig.sizing_tier}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        logUxEvent('sizing_hint', 'prefill_ticket', { ticker: selectedMarket.ticker, contracts: suggestedContracts, side: suggestedSide });
                        setSizingHint({ contracts: suggestedContracts, side: suggestedSide });
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors group"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold text-emerald-400 font-mono">{suggestedContracts}</span>
                        <span className="text-xs text-gray-400">{suggestedSide.toUpperCase()} contracts</span>
                      </div>
                      <span className="text-[10px] text-gray-500 group-hover:text-orange-400 transition-colors">
                        Click to pre-fill →
                      </span>
                    </button>
                    <p className="text-[10px] text-gray-600 mt-1.5">{rationale}</p>
                  </div>
                );
              })()}

              {/* Liquidity Health */}
              {liqHealthResult.data && (() => {
                const lh = liqHealthResult.data;
                const scoreColor = lh.health_score >= 0.7 ? 'text-green-400' : lh.health_score >= 0.4 ? 'text-yellow-400' : 'text-red-400';
                return (
                  <div className="bg-slate-800 rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Liquidity Health</h3>
                      <span className={`text-sm font-bold font-mono ${scoreColor}`}>{((lh.health_score ?? 0) * 100).toFixed(0)}%</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[10px]">
                      <div>
                        <span className="text-gray-500">Spread</span>
                        <p className="text-white font-mono">{lh.spread_cents != null ? `${lh.spread_cents}¢` : '—'}</p>
                      </div>
                      <div>
                        <span className="text-gray-500">Book Depth</span>
                        <p className="text-white font-mono">{lh.book_depth}</p>
                      </div>
                    </div>
                    {(lh.thin_book || lh.wide_spread) && (
                      <div className="flex gap-2">
                        {lh.thin_book && <span className="px-1.5 py-0.5 rounded text-[9px] bg-red-500/20 text-red-400">Thin Book</span>}
                        {lh.wide_spread && <span className="px-1.5 py-0.5 rounded text-[9px] bg-orange-500/20 text-orange-400">Wide Spread</span>}
                      </div>
                    )}
                    {lh.recommendation && (
                      <p className="text-[10px] text-gray-500 italic">{lh.recommendation}</p>
                    )}
                  </div>
                );
              })()}

              {/* Volume History */}
              {volHistoryResult.data?.history && volHistoryResult.data.history.length > 0 && (() => {
                const raw = volHistoryResult.data.history;
                const smoothed = volSmoothedResult.data?.smoothed ?? [];
                const maxVol = Math.max(...raw.map(p => p.volume), 1);
                return (
                  <div className="bg-slate-800 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Volume History</h3>
                      <span className="text-[10px] text-gray-600">{raw.length} intervals</span>
                    </div>
                    <div className="relative h-16">
                      <svg width="100%" height="100%" viewBox={`0 0 ${raw.length} 100`} preserveAspectRatio="none">
                        {/* Raw volume bars */}
                        {raw.map((p, i) => {
                          const h = (p.volume / maxVol) * 100;
                          return <rect key={i} x={i} y={100 - h} width={0.8} height={h} fill="#f59e0b" opacity="0.4" />;
                        })}
                        {/* Smoothed line */}
                        {smoothed.length > 1 && (
                          <polyline
                            fill="none"
                            stroke="#f59e0b"
                            strokeWidth="1.5"
                            points={smoothed.map((p, i) => {
                              const x = (i / (smoothed.length - 1)) * raw.length;
                              const y = 100 - (p.volume / maxVol) * 100;
                              return `${x},${y}`;
                            }).join(' ')}
                          />
                        )}
                      </svg>
                    </div>
                    <div className="flex justify-between text-[9px] text-gray-600 mt-1">
                      <span>{raw[0] ? new Date(raw[0].ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                      <span>Vol: {raw[raw.length - 1]?.volume.toLocaleString() ?? '—'} ct</span>
                      <span>{raw[raw.length - 1] ? new Date(raw[raw.length - 1].ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                    </div>
                  </div>
                );
              })()}

              {/* Market Extra Detail */}
              {marketDetailResult.data && (() => {
                const md = marketDetailResult.data;
                return (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-slate-800 rounded-lg p-3">
                      <p className="text-[10px] text-gray-500">Open Interest</p>
                      <p className="text-sm font-medium text-white">{md.open_interest.toLocaleString()}</p>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <p className="text-[10px] text-gray-500">Last Trade</p>
                      <p className="text-sm font-medium text-white">{md.last_trade_price != null ? `${(md.last_trade_price * 100).toFixed(0)}¢` : '—'}</p>
                      {md.last_trade_ts && <p className="text-[10px] text-gray-600">{new Date(md.last_trade_ts).toLocaleTimeString()}</p>}
                    </div>
                  </div>
                );
              })()}

              {/* Trade Ticket */}
              {selectedMarket.active && (
                <KalshiTradeTicket
                  ticker={selectedMarket.ticker}
                  question={selectedMarket.question}
                  outcomes={selectedMarket.outcomes}
                  onOrderPlaced={() => posResult.refetch()}
                  suggestedSize={sizingHint?.contracts}
                  suggestedSide={sizingHint?.side}
                  mode={venueMode}
                  kellyFraction={sizingResult.data?.kelly_fraction}
                />
              )}

              {/* Position badge */}
              {positionTickers.has(selectedMarket.ticker) && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-orange-500/10 border border-orange-500/30 text-orange-300 text-xs">
                  <Briefcase className="w-3.5 h-3.5" />
                  You have an open position in this market
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default KalshiDashboardView;
