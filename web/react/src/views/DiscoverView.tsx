/**
 * DiscoverView — Kalshi-Style Prediction Market Discovery (Stage 1)
 * 
 * Core UX Principles:
 *   - Clear market questions and resolution criteria
 *   - Price shown as probability (%)
 *   - Trust signals: volume, liquidity, time to expiry
 *   - Fast, low-friction trade discovery
 *   - Mobile-first responsive design
 * 
 * Layout: Discovery → Market Card → Quick Trade Flow
 */

import React, { useState, useCallback, useMemo, useEffect } from 'react';
import {
  Search, TrendingUp, Clock, Droplets,
  ChevronLeft, ChevronRight, Star, Target,
  Activity, Filter,
  Zap
} from '../ui/icons';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { authHeaders } from '../api/auth';
import type { View } from '../types/views';

// Sub-components
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import KalshiTradeTicket from '../components/KalshiTradeTicket';
// import ConsensusPill from '../components/ConsensusPill'; // TODO: Create this component
import { KALSHI_CATEGORY_COLORS } from '../ui/constants';

// ── Types ───────────────────────────────────────────────────────────────────

interface Market {
  ticker: string;
  question: string;
  category: string;
  asset?: string;
  timeframe?: string;
  volume: number;
  open_interest: number;
  spread_cents: number;
  yes_price: number;
  no_price: number;
  expires_at: string;
  status: string;
  is_favorite?: boolean;
  resolution_source?: string;
  consensus?: {
    direction: 'bullish' | 'bearish' | 'neutral';
    confidence: number;
    agents: string[];
  };
}

interface PoolResponse {
  count: number;
  markets: Market[];
}

// ── Constants ────────────────────────────────────────────────────────────────

const DISCOVER_MODES = [
  { id: 'trending', label: 'Trending', icon: TrendingUp, desc: 'Most active markets' },
  { id: 'focus', label: 'Focus', icon: Target, desc: 'Featured opportunities' },
  { id: 'all', label: 'All', icon: Filter, desc: 'Complete market universe' },
] as const;

type DiscoverMode = typeof DISCOVER_MODES[number]['id'];

const QUICK_FILTERS = [
  { id: 'all', label: 'All Markets' },
  { id: 'favorites', label: '★ Favorites' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'economics', label: 'Macro' },
  { id: 'sports', label: 'Sports' },
  { id: 'politics', label: 'Politics' },
] as const;

const PAGE_SIZE = 20;

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format large numbers compactly */
function formatCompact(num: number): string {
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return num.toString();
}

/** Time remaining with color coding */
function TimeToExpiry({ expiresAt }: { expiresAt: string }) {
  const expiryTs = new Date(expiresAt).getTime();
  if (!isFinite(expiryTs)) return <span className="text-slate-500">—</span>;
  const ms = expiryTs - Date.now();
  if (ms <= 0) return <span className="text-slate-500">Expired</span>;
  
  const mins = Math.floor(ms / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  
  let text = '';
  let colorClass = 'text-slate-400';
  
  if (mins < 60) {
    text = `${mins}m`;
    colorClass = 'text-orange-400 font-medium';
  } else if (hrs < 24) {
    text = `${hrs}h`;
    colorClass = hrs < 6 ? 'text-yellow-400' : 'text-slate-400';
  } else {
    text = `${days}d`;
  }
  
  return (
    <span className={`flex items-center gap-1 ${colorClass}`}>
      <Clock className="w-3 h-3" />
      {text}
    </span>
  );
}

/** Trust signal: liquidity indicator */
function LiquidityBadge({ spread, volume }: { spread: number; volume: number }) {
  const isLiquid = spread <= 3 && volume > 10000;
  const isMedium = spread <= 8 && volume > 1000;
  
  if (isLiquid) {
    return (
      <span className="flex items-center gap-1 text-xs text-green-400">
        <Droplets className="w-3 h-3" />
        Liquid
      </span>
    );
  }
  if (isMedium) {
    return (
      <span className="flex items-center gap-1 text-xs text-yellow-400">
        <Droplets className="w-3 h-3" />
        Moderate
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-slate-500">
      <Droplets className="w-3 h-3" />
      Thin
    </span>
  );
}

/** Category badge with consistent styling */
function CategoryBadge({ category }: { category: string }) {
  const c = category.toLowerCase();
  const cls = (KALSHI_CATEGORY_COLORS as Record<string, string>)[c] || 'bg-slate-700 text-slate-300 border-slate-600';
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider border ${cls}`}>
      {c}
    </span>
  );
}

// ── Sub-Components ───────────────────────────────────────────────────────────

/** Probability display with visual bar */
function ProbabilityBar({ yesPrice, noPrice }: { yesPrice: number; noPrice: number }) {
  const yesPct = yesPrice;
  const noPct = noPrice;
  
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-green-400 font-medium">YES {yesPct}%</span>
        <span className="text-red-400 font-medium">NO {noPct}%</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden flex">
        <div 
          className="h-full bg-green-500 transition-all duration-300" 
          style={{ width: `${yesPct}%` }}
        />
        <div 
          className="h-full bg-red-500 transition-all duration-300" 
          style={{ width: `${noPct}%` }}
        />
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

interface DiscoverViewProps {
  onNavigate?: (view: View) => void;
  initialMode?: DiscoverMode;
}

const DiscoverView: React.FC<DiscoverViewProps> = ({ 
  initialMode = 'trending' 
}) => {
  // Mode & filter state
  const [mode, setMode] = useState<DiscoverMode>(initialMode);
  const [quickFilter, setQuickFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  
  // Market selection
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  
  // Data fetching
  const marketsRes = useApiQuery<PoolResponse>(
    `${API_ENDPOINTS.KALSHI_CATALOG}/pool?limit=500${quickFilter !== 'all' && quickFilter !== 'favorites' ? `&category=${quickFilter}` : ''}`,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const favoritesRes = useApiQuery<{ favorites: string[] }>(
    API_ENDPOINTS.KALSHI_FAVORITES,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  // Update favorites when loaded
  useEffect(() => {
    if (favoritesRes.data?.favorites) {
      setFavorites(new Set(favoritesRes.data.favorites));
    }
  }, [favoritesRes.data]);

  // Toggle favorite
  const toggleFavorite = useCallback(async (ticker: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_FAVORITES_TOGGLE}`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker }),
      });
      if (!res.ok) throw new Error('Failed to toggle favorite');
      
      setFavorites(prev => {
        const next = new Set(prev);
        if (next.has(ticker)) next.delete(ticker);
        else next.add(ticker);
        return next;
      });
    } catch (err) {
      console.error('Failed to toggle favorite:', err);
    }
  }, []);

  // Filter and sort markets
  const filteredMarkets = useMemo(() => {
    let markets = marketsRes.data?.markets || [];
    
    // Apply quick filters
    if (quickFilter === 'favorites') {
      markets = markets.filter((m: Market) => favorites.has(m.ticker));
    } else if (quickFilter !== 'all') {
      markets = markets.filter((m: Market) => m.category?.toLowerCase() === quickFilter.toLowerCase());
    }
    
    // Apply search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      markets = markets.filter((m: Market) => 
        m.ticker.toLowerCase().includes(q) ||
        m.question.toLowerCase().includes(q)
      );
    }
    
    // Sort based on mode
    if (mode === 'trending') {
      markets = [...markets].sort((a, b) => (b.volume || 0) - (a.volume || 0));
    } else if (mode === 'focus') {
      // Focus: prioritize liquid markets with consensus
      markets = [...markets].sort((a, b) => {
        const aScore = (a.consensus ? 1 : 0) + (a.spread_cents <= 3 ? 2 : 0);
        const bScore = (b.consensus ? 1 : 0) + (b.spread_cents <= 3 ? 2 : 0);
        return bScore - aScore;
      });
    }
    
    return markets;
  }, [marketsRes.data, quickFilter, searchQuery, mode, favorites]);

  // Pagination
  const totalPages = Math.ceil(filteredMarkets.length / PAGE_SIZE);
  const paginatedMarkets = filteredMarkets.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [quickFilter, searchQuery, mode]);

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header: Clean, focused */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
            <Zap className="w-5 h-5 sm:w-6 sm:h-6 text-blue-400" />
            Markets <KalshiModeBadge />
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Trade on what you believe
          </p>
        </div>
        
        {/* Mode tabs */}
        <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 overflow-x-auto">
          {DISCOVER_MODES.map(m => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              title={m.desc}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
                mode === m.id
                  ? 'bg-blue-500 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700'
              }`}
            >
              <m.icon className="w-4 h-4" />
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Filters: Compact, mobile-friendly */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 overflow-x-auto">
          {QUICK_FILTERS.map(f => (
            <button
              key={f.id}
              onClick={() => setQuickFilter(f.id)}
              className={`px-2.5 py-1.5 rounded-md text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                quickFilter === f.id
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        
        <div className="flex-1 min-w-[200px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by ticker or question..."
              className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      {/* Market Grid: Responsive */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Market List */}
        <div className="xl:col-span-2 bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          {/* Mobile-first card view, table on larger screens */}
          <div className="sm:hidden">
            {marketsRes.isLoading && paginatedMarkets.length === 0 ? (
              <div className="p-8 text-center text-slate-500">
                <div className="w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin mx-auto mb-2" />
                Loading markets...
              </div>
            ) : paginatedMarkets.length === 0 ? (
              <div className="p-8 text-center text-slate-500">No markets found</div>
            ) : (
              <div className="divide-y divide-slate-800">
                {paginatedMarkets.map((market: Market) => (
                  <div
                    key={market.ticker}
                    onClick={() => setSelectedMarket(market)}
                    className={`p-4 cursor-pointer transition-colors ${
                      selectedMarket?.ticker === market.ticker ? 'bg-blue-500/10' : ''
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <CategoryBadge category={market.category} />
                          <span className="text-xs text-slate-500">{market.ticker}</span>
                        </div>
                        <p className="text-sm text-white line-clamp-2">{market.question}</p>
                        <div className="flex items-center gap-3 mt-2 text-xs">
                          <LiquidityBadge spread={market.spread_cents} volume={market.volume} />
                          <TimeToExpiry expiresAt={market.expires_at} />
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-semibold text-white">{market.yes_price}¢</div>
                        <div className="text-xs text-slate-500">{formatCompact(market.volume)} vol</div>
                        <button
                          onClick={(e) => toggleFavorite(market.ticker, e)}
                          className={`mt-1 ${favorites.has(market.ticker) ? 'text-yellow-400' : 'text-slate-600'}`}
                        >
                          <Star className={`w-4 h-4 ${favorites.has(market.ticker) ? 'fill-current' : ''}`} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          
          {/* Desktop table view */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3 pl-4">Market</th>
                  <th className="text-right p-3">Prob.</th>
                  <th className="text-right p-3">Spread</th>
                  <th className="text-right p-3">Volume</th>
                  <th className="text-right p-3">Expires</th>
                  <th className="text-center p-3 pr-4 w-10">★</th>
                </tr>
              </thead>
              <tbody>
                {marketsRes.isLoading && paginatedMarkets.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-500">
                      <div className="flex items-center justify-center gap-2">
                        <div className="w-4 h-4 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
                        Loading markets...
                      </div>
                    </td>
                  </tr>
                ) : paginatedMarkets.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-slate-500">
                      No markets found
                    </td>
                  </tr>
                ) : (
                  paginatedMarkets.map((market: Market) => (
                    <tr
                      key={market.ticker}
                      onClick={() => setSelectedMarket(market)}
                      className={`border-b border-slate-800/50 cursor-pointer transition-colors ${
                        selectedMarket?.ticker === market.ticker
                          ? 'bg-blue-500/10'
                          : 'hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="p-3 pl-4">
                        <div className="flex items-start gap-2">
                          <CategoryBadge category={market.category} />
                          <div className="min-w-0">
                            <div className="font-medium text-white truncate">{market.ticker}</div>
                            <div className="text-xs text-slate-400 line-clamp-1">{market.question}</div>
                          </div>
                        </div>
                      </td>
                      <td className="p-3 text-right">
                        <div className="font-mono font-medium text-white">{market.yes_price}%</div>
                        <div className="text-xs text-slate-500">YES</div>
                      </td>
                      <td className="p-3 text-right">
                        <LiquidityBadge spread={market.spread_cents} volume={market.volume} />
                      </td>
                      <td className="p-3 text-right">
                        <span className="text-slate-300">{formatCompact(market.volume || 0)}</span>
                      </td>
                      <td className="p-3 text-right">
                        <TimeToExpiry expiresAt={market.expires_at} />
                      </td>
                      <td className="p-3 pr-4 text-center">
                        <button
                          onClick={(e) => toggleFavorite(market.ticker, e)}
                          className={`transition-colors ${
                            favorites.has(market.ticker)
                              ? 'text-yellow-400'
                              : 'text-slate-600 hover:text-yellow-400'
                          }`}
                        >
                          <Star className={`w-4 h-4 ${favorites.has(market.ticker) ? 'fill-current' : ''}`} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between p-3 border-t border-slate-800">
              <span className="text-xs text-slate-500">
                {filteredMarkets.length} markets · Page {page} of {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="text-sm text-slate-400 px-2">{page}</span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Side Panel: Market Detail & Trade */}
        <div className="space-y-4">
          {selectedMarket ? (
            <div className="space-y-4">
              {/* Market Header Card */}
              <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
                <div className="p-4 border-b border-slate-800">
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <CategoryBadge category={selectedMarket.category} />
                        <span className="text-xs font-mono text-slate-500">{selectedMarket.ticker}</span>
                      </div>
                      <h2 className="text-base font-medium text-white leading-snug">
                        {selectedMarket.question}
                      </h2>
                    </div>
                    <button
                      onClick={(e) => toggleFavorite(selectedMarket.ticker, e)}
                      className={`shrink-0 ${favorites.has(selectedMarket.ticker) ? 'text-yellow-400' : 'text-slate-600 hover:text-yellow-400'}`}
                    >
                      <Star className={`w-5 h-5 ${favorites.has(selectedMarket.ticker) ? 'fill-current' : ''}`} />
                    </button>
                  </div>
                  
                  {/* Probability Bar */}
                  <ProbabilityBar yesPrice={selectedMarket.yes_price} noPrice={selectedMarket.no_price} />
                </div>
                
                {/* Trust Signals Grid */}
                <div className="grid grid-cols-3 gap-px bg-slate-800">
                  <div className="bg-slate-900 p-3 text-center">
                    <div className="text-[10px] uppercase text-slate-500 mb-1">Volume</div>
                    <div className="text-sm font-semibold text-white">{formatCompact(selectedMarket.volume)}</div>
                  </div>
                  <div className="bg-slate-900 p-3 text-center">
                    <div className="text-[10px] uppercase text-slate-500 mb-1">Spread</div>
                    <div className={`text-sm font-semibold ${selectedMarket.spread_cents <= 3 ? 'text-green-400' : 'text-yellow-400'}`}>
                      {selectedMarket.spread_cents}¢
                    </div>
                  </div>
                  <div className="bg-slate-900 p-3 text-center">
                    <div className="text-[10px] uppercase text-slate-500 mb-1">Expires</div>
                    <div className="text-sm font-semibold text-white">
                      <TimeToExpiry expiresAt={selectedMarket.expires_at} />
                    </div>
                  </div>
                </div>
              </div>
              
              {/* Trade Ticket */}
              {selectedMarket.status === 'active' && (
                <KalshiTradeTicket
                  ticker={selectedMarket.ticker}
                  question={selectedMarket.question}
                  outcomes={[
                    { id: 'yes', name: 'YES', price: selectedMarket.yes_price / 100, bid: null, ask: null },
                    { id: 'no', name: 'NO', price: selectedMarket.no_price / 100, bid: null, ask: null }
                  ]}
                  onOrderPlaced={() => { /* refresh */ }}
                />
              )}
              
              {/* Consensus Signal */}
              {selectedMarket.consensus && (
                <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
                  <h3 className="text-sm font-medium text-slate-300 mb-2 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-cyan-400" />
                    Agent Consensus
                  </h3>
                  {/* <ConsensusPill
                    direction={selectedMarket.consensus.direction}
                    confidence={selectedMarket.consensus.confidence}
                    agents={selectedMarket.consensus.agents}
                  /> */}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-slate-900 rounded-xl p-8 border border-slate-800 text-center">
              <div className="w-12 h-12 bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-3">
                <Target className="w-6 h-6 text-slate-500" />
              </div>
              <p className="text-slate-400 font-medium mb-1">Select a market</p>
              <p className="text-sm text-slate-500">Click on any market to view details and trade</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default DiscoverView;
