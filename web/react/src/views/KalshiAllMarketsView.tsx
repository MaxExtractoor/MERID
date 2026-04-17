/**
 * KalshiAllMarketsView — Paginated all-markets grid with universe controls.
 *
 * Features:
 *  - Coverage summary: total active, total liquid, per-category counts
 *  - Per-category mode badges (paper / live)
 *  - Category filter tabs + text search
 *  - Paginated market table (ticker, question, category, volume, spread, expiry)
 *  - Universal agent launcher (start/stop with dry-run toggle)
 *  - Category exposure caps panel
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Globe, RefreshCw, Play, Square, Shield,
  ChevronLeft, ChevronRight, Search, Filter, Zap,
} from '../ui/icons';
import { API_BASE_URL } from '../config/constants';
import ErrorBar from '../components/ErrorBar';
import { authHeaders } from '../api/auth';
import { KALSHI_CATEGORY_COLORS } from '../ui/constants';
import { RegimeBadge, type RegimeData } from '../components/RegimeBadge';
import './KalshiAllMarketsView.css';

// ── Types ──────────────────────────────────────────────────────────────────

interface CoverageMarket {
  ticker: string;
  question: string;
  category: string | null;
  asset: string | null;
  timeframe: string | null;
  volume: number | null;
  open_interest: number | null;
  expires_at: string | null;
  regime?: RegimeData;
}

interface CoverageSummary {
  total_active: number;
  total_liquid: number;
  by_category: Record<string, number>;
  category_modes: Record<string, string>;
  allowed_categories: string[];
  max_per_agent: number;
  error?: string;
}

interface PoolResponse {
  count: number;
  markets: CoverageMarket[];
  error?: string;
}

interface CategoryCaps {
  category_notional: Record<string, number>;
  category_caps: Record<string, number>;
  corr_notional: Record<string, number>;
  corr_cap: number;
  /** Per-underlying correlated-stack cap overrides (USD). CT skip caps are separate (cents). */
  asset_caps?: Record<string, number>;
  error?: string;
}

interface AgentState {
  running: boolean;
  enabled: boolean;
  cycles_run: number;
  markets_evaluated: number;
  orders_placed: number;
  orders_rejected: number;
  last_cycle_at: string | null;
  last_error: string | null;
  dry_run?: boolean;  // actual config on the running agent (may differ from checkbox until start)
}

// ── Helpers ────────────────────────────────────────────────────────────────

const ALL_CATEGORIES = [
  'cross_category', 'sports', 'crypto', 'economics', 'macro', 'financials', 'politics',
  'climate', 'tech', 'culture', 'science', 'equities', 'other',
];

function categoryBadge(cat: string | null) {
  const c = (cat || 'other').toLowerCase();
  const cls = (KALSHI_CATEGORY_COLORS as Record<string, string>)[c] || (KALSHI_CATEGORY_COLORS as Record<string, string>).other;
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${cls}`}>
      {c}
    </span>
  );
}

function modeBadge(mode: string) {
  return mode === 'live'
    ? <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-green-500/20 text-green-300 border border-green-500/30">LIVE</span>
    : <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-yellow-500/20 text-yellow-300 border border-yellow-500/30">PAPER</span>;
}

function minutesToExpiry(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  try {
    const ms = new Date(expiresAt).getTime() - Date.now();
    if (ms <= 0) return 'expired';
    const mins = Math.floor(ms / 60000);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    return `${Math.floor(hrs / 24)}d`;
  } catch {
    return null;
  }
}


const PAGE_SIZE = 25;

// ── Component ──────────────────────────────────────────────────────────────

export default function KalshiAllMarketsView() {
  const [coverage, setCoverage] = useState<CoverageSummary | null>(null);
  const [pool, setPool] = useState<CoverageMarket[]>([]);
  const [caps, setCaps] = useState<CategoryCaps | null>(null);
  const [agentState, setAgentState] = useState<AgentState | null>(null);

  const [activeCategory, setActiveCategory] = useState<string>('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [poolLoading, setPoolLoading] = useState(false);
  const [agentDryRun, setAgentDryRun] = useState(true);
  const [agentMaxMarkets, setAgentMaxMarkets] = useState(50);
  const [error, setError] = useState<Error | null>(null);

  // ── Fetch coverage summary ─────────────────────────────────────────────
  const fetchCoverage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/kalshi/universe/coverage`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: CoverageSummary = await res.json();
      setCoverage(data);
      if (data.error) setError(new Error(data.error));
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Fetch pool for active category ────────────────────────────────────
  const fetchPool = useCallback(async (cat: string) => {
    setPoolLoading(true);
    try {
      const params = new URLSearchParams({ limit: '500' });
      if (cat) params.set('category', cat);
      const res = await fetch(
        `${API_BASE_URL}/api/v1/kalshi/universe/pool?${params}`,
        { headers: authHeaders() },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PoolResponse = await res.json();
      setPool(data.markets || []);
      setPage(1);
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setPoolLoading(false);
    }
  }, []);

  // ── Fetch category caps ────────────────────────────────────────────────
  const fetchCaps = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/kalshi/universe/category-caps`, {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      setCaps(await res.json());
    } catch { /* non-critical */ }
  }, []);

  // ── Fetch agent state ──────────────────────────────────────────────────
  const fetchAgentState = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/kalshi/universe/agents`, {
        headers: authHeaders(),
      });
      if (!res.ok) return;
      const data = await res.json();
      const agent: AgentState | undefined = data.agents?.['sweep-all'];
      if (agent) {
        setAgentState(agent);
        // Sync the checkbox to what the agent is actually configured with.
        // This ensures the UI reflects the real running state rather than stale local state.
        if (agent.dry_run !== undefined) setAgentDryRun(agent.dry_run);
      }
    } catch { /* non-critical */ }
  }, []);

  useEffect(() => {
    fetchCoverage();
    fetchPool('');
    fetchCaps();
    fetchAgentState();

    // BUG-004 fix: auto-refresh market data so prices/expiry/OI don't go stale
    const coverageTimer = setInterval(fetchCoverage, 60_000);
    const poolTimer = setInterval(() => fetchPool(activeCategory), 60_000);
    const capsTimer = setInterval(fetchCaps, 120_000);
    const agentTimer = setInterval(fetchAgentState, 30_000);
    return () => {
      clearInterval(coverageTimer);
      clearInterval(poolTimer);
      clearInterval(capsTimer);
      clearInterval(agentTimer);
    };
  }, [fetchCoverage, fetchPool, fetchCaps, fetchAgentState, activeCategory]);

  useEffect(() => {
    setPage(1); // BUG-003 fix: reset synchronously before the async fetch resolves
    fetchPool(activeCategory);
  }, [activeCategory, fetchPool]);

  // ── Agent controls ─────────────────────────────────────────────────────
  const startAgent = async () => {
    setError(null);
    try {
      const params = new URLSearchParams({
        dry_run: String(agentDryRun),
        max_markets: String(agentMaxMarkets),
      });
      if (activeCategory) params.set('categories', activeCategory);
      const res = await fetch(
        `${API_BASE_URL}/api/v1/kalshi/universe/agents/sweep-all/start?${params}`,
        { method: 'POST', headers: authHeaders() },
      );
      const data = await res.json();
      if (data.agent) {
        setAgentState(data.agent);
        // Reflect what the agent actually started with (server is source of truth).
        if (data.agent.dry_run !== undefined) setAgentDryRun(data.agent.dry_run);
      }
      if (data.error) setError(new Error(data.error));
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  const stopAgent = async () => {
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/v1/kalshi/universe/agents/sweep-all/stop`,
        { method: 'POST', headers: authHeaders() },
      );
      const data = await res.json();
      if (data.agent) setAgentState(data.agent);
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  };

  // ── Filtered / paginated markets ───────────────────────────────────────
  const filtered = pool.filter(m => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      m.ticker.toLowerCase().includes(q) ||
      (m.question || '').toLowerCase().includes(q) ||
      (m.asset || '').toLowerCase().includes(q)
    );
  });
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageMarkets = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Globe className="w-7 h-7 text-sky-400" />
          <div>
            <h1 className="text-xl font-bold text-white">All Markets</h1>
            <p className="text-xs text-slate-400">
              Full Kalshi universe — all categories, all markets
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => { fetchCoverage(); fetchPool(activeCategory); fetchCaps(); fetchAgentState(); }}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <ErrorBar label="All Markets" error={error} onRetry={() => { fetchCoverage(); fetchPool(activeCategory); }} />

      {/* Coverage cards */}
      {coverage && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
            <div className="text-xs text-slate-400 mb-1">Total Active</div>
            <div className="text-2xl font-bold text-white">{coverage.total_active}</div>
          </div>
          <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
            <div className="text-xs text-slate-400 mb-1">Liquid (pass filter)</div>
            <div className="text-2xl font-bold text-sky-300">{coverage.total_liquid}</div>
          </div>
          <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
            <div className="text-xs text-slate-400 mb-1">Categories</div>
            <div className="text-2xl font-bold text-white">
              {Object.keys(coverage.by_category ?? {}).length}
            </div>
          </div>
          <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
            <div className="text-xs text-slate-400 mb-1">Max/Agent</div>
            <div className="text-2xl font-bold text-white">{coverage.max_per_agent}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Left: Market table */}
        <div className="xl:col-span-2 space-y-3">

          {/* Category filter tabs */}
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setActiveCategory('')}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                activeCategory === ''
                  ? 'bg-sky-600 text-white border-sky-500'
                  : 'bg-slate-800 text-slate-300 border-slate-600 hover:border-sky-500'
              }`}
            >
              All ({coverage?.total_liquid ?? '…'})
            </button>
            {ALL_CATEGORIES.map(cat => {
              const count = coverage?.by_category?.[cat] ?? 0;
              if (!count) return null;
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setActiveCategory(cat)}
                  className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors capitalize ${
                    activeCategory === cat
                      ? 'bg-sky-600 text-white border-sky-500'
                      : 'bg-slate-800 text-slate-300 border-slate-600 hover:border-sky-500'
                  }`}
                >
                  {cat} ({count})
                </button>
              );
            })}
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search ticker or question…"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              className="w-full pl-9 pr-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Table */}
          <div className="rounded-xl border border-slate-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-800/80 text-slate-400 text-xs uppercase tracking-wide">
                  <th className="text-left px-3 py-2.5">Ticker</th>
                  <th className="text-left px-3 py-2.5 hidden md:table-cell">Question</th>
                  <th className="text-left px-3 py-2.5">Category</th>
                  <th className="text-left px-3 py-2.5 hidden lg:table-cell">Regime</th>
                  <th className="text-right px-3 py-2.5 hidden sm:table-cell">Volume</th>
                  <th className="text-right px-3 py-2.5 hidden lg:table-cell">OI</th>
                  <th className="text-right px-3 py-2.5">Expiry</th>
                </tr>
              </thead>
              <tbody>
                {poolLoading ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-slate-500">
                      <RefreshCw className="w-5 h-5 animate-spin inline mr-2" />Loading markets…
                    </td>
                  </tr>
                ) : pageMarkets.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center py-8 text-slate-500">
                      No markets found
                      {search && ` for "${search}"`}
                    </td>
                  </tr>
                ) : pageMarkets.map((m, i) => (
                  <tr
                    key={m.ticker}
                    className={`border-t border-slate-700/50 hover:bg-slate-800/40 transition-colors ${
                      i % 2 === 0 ? 'bg-slate-900/20' : ''
                    }`}
                  >
                    <td className="px-3 py-2.5 font-mono text-sky-300 text-xs">{m.ticker}</td>
                    <td className="px-3 py-2.5 text-slate-300 hidden md:table-cell max-w-[260px] truncate" title={m.question || ''}>
                      {m.question || '—'}
                    </td>
                    <td className="px-3 py-2.5">{categoryBadge(m.category)}</td>
                    <td className="px-3 py-2.5 hidden lg:table-cell">
                      {m.regime ? <RegimeBadge regime={m.regime} size="sm" showConfidence={false} /> : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-300 hidden sm:table-cell">
                      {m.volume != null ? m.volume.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-300 hidden lg:table-cell">
                      {m.open_interest != null ? m.open_interest.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-400 text-xs">
                      {minutesToExpiry(m.expires_at) ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-slate-400">
              <span>{filtered.length} markets</span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="p-1.5 rounded-lg hover:bg-slate-700 disabled:opacity-30"
                  aria-label="Previous page"
                  title="Previous page"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span>{page} / {totalPages}</span>
                <button
                  type="button"
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-1.5 rounded-lg hover:bg-slate-700 disabled:opacity-30"
                  aria-label="Next page"
                  title="Next page"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right: Controls + caps */}
        <div className="space-y-4">

          {/* Category modes panel */}
          {coverage?.category_modes && (
            <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Filter className="w-4 h-4 text-sky-400" />
                <span className="text-sm font-semibold text-white">Category Modes</span>
              </div>
              <div className="space-y-1.5">
                {ALL_CATEGORIES.map(cat => {
                  const count = coverage.by_category?.[cat] ?? 0;
                  const mode = coverage.category_modes?.[cat] ?? 'paper';
                  return (
                    <div key={cat} className="flex items-center justify-between text-xs">
                      <span className="capitalize text-slate-300">{cat}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-slate-500">{count} mkts</span>
                        {modeBadge(mode)}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-slate-500 mt-3">
                Set via <code className="text-slate-400">MERID_UNIVERSE_MODE_&lt;CAT&gt;</code> env var.
              </p>
            </div>
          )}

          {/* Universal agent control */}
          <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 text-yellow-400" />
              <span className="text-sm font-semibold text-white">Universal Agent</span>
              {agentState?.running && (
                <span className="ml-auto flex items-center gap-1.5 text-xs">
                  <span className="flex items-center gap-1 text-green-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                    running
                  </span>
                  {agentState.dry_run
                    ? <span className="px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-300 border border-yellow-500/30">dry-run</span>
                    : <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30">LIVE</span>
                  }
                </span>
              )}
            </div>

            {agentState && (
              <div className="grid grid-cols-2 gap-2 text-xs mb-3">
                <div className="rounded-lg bg-slate-900/50 p-2">
                  <div className="text-slate-400">Cycles</div>
                  <div className="text-white font-semibold">{agentState.cycles_run}</div>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-2">
                  <div className="text-slate-400">Evaluated</div>
                  <div className="text-white font-semibold">{agentState.markets_evaluated}</div>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-2">
                  <div className="text-slate-400">Orders</div>
                  <div className="text-emerald-300 font-semibold">{agentState.orders_placed}</div>
                </div>
                <div className="rounded-lg bg-slate-900/50 p-2">
                  <div className="text-slate-400">Rejected</div>
                  <div className="text-red-300 font-semibold">{agentState.orders_rejected}</div>
                </div>
              </div>
            )}

            {agentState?.last_error && (
              <p className="text-xs text-red-400 mb-2 truncate" title={agentState.last_error}>
                {agentState.last_error}
              </p>
            )}

            <div className="space-y-2 mb-3">
              <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agentDryRun}
                  onChange={e => setAgentDryRun(e.target.checked)}
                  className="rounded"
                />
                Dry-run (no real orders)
              </label>
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <span>Max markets:</span>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={agentMaxMarkets}
                  onChange={e => setAgentMaxMarkets(parseInt(e.target.value) || 50)}
                  className="w-16 px-2 py-1 rounded bg-slate-900 border border-slate-600 text-white text-xs"
                />
              </div>
            </div>

            <div className="flex gap-2">
              {!agentState?.running ? (
                <button
                  type="button"
                  onClick={startAgent}
                  className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-colors"
                  aria-label="Start market sweep agent"
                >
                  <Play className="w-3.5 h-3.5" />
                  Start Sweep
                </button>
              ) : (
                <button
                  type="button"
                  onClick={stopAgent}
                  className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold transition-colors"
                  aria-label="Stop market sweep agent"
                >
                  <Square className="w-3.5 h-3.5" />
                  Stop
                </button>
              )}
              <button
                type="button"
                onClick={fetchAgentState}
                className="px-3 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Category caps */}
          {caps && (
            <div className="rounded-xl bg-slate-800/70 border border-slate-700 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="w-4 h-4 text-violet-400" />
                <span className="text-sm font-semibold text-white">Exposure Caps</span>
              </div>
              <div className="space-y-1.5">
                {Object.entries(caps.category_caps ?? {}).map(([cat, cap]) => {
                  const used = caps.category_notional?.[cat] ?? 0;
                  const pct = cap > 0 ? Math.min(100, (used / cap) * 100) : 0;
                  const barColor = pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-yellow-500' : 'bg-emerald-500';
                  return (
                    <div key={cat}>
                      <div className="flex justify-between text-xs text-slate-400 mb-0.5">
                        <span className="capitalize">{cat}</span>
                        <span>${used.toFixed(0)} / ${cap.toFixed(0)}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-slate-700 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${barColor} exposure-bar-fill`}
                          style={{ '--exposure-width': `${pct}%` } as React.CSSProperties}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              {caps.asset_caps && Object.keys(caps.asset_caps).length > 0 && (
                <div className="mt-4 pt-3 border-t border-slate-700/80">
                  <div className="text-xs font-medium text-slate-300 mb-2">
                    Per-asset corr cap (USD, router / tracker)
                  </div>
                  <div className="space-y-1 text-xs text-slate-400">
                    {Object.entries(caps.asset_caps).map(([sym, capUsd]) => {
                      const used = caps.corr_notional?.[sym] ?? 0;
                      return (
                        <div key={sym} className="flex justify-between gap-2">
                          <span className="font-mono text-slate-300">{sym}</span>
                          <span>
                            ${used.toFixed(0)} / ${Number(capUsd).toFixed(0)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
