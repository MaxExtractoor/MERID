/**
 * Kalshi15mHealthPanel — 15m-specific health monitoring panel.
 *
 * Surfaces health status for the 15m Kalshi crypto stack using the real
 * backend endpoints (the legacy /api/v1/kalshi/15m/* routes do not exist):
 * - GET /api/v1/kalshi/internal/kalshi_health → per-market book health
 *   (ticker, underlying, initialized, last_update_age_ms, bid/ask/spread)
 *   plus trading_enabled and market_count vs expected.
 * - GET /api/v1/unified-health → service readiness incl. ws_bridge status.
 *
 * The "Venue Feed" tile reports the backend's Kalshi WS bridge status from
 * unified-health — this dashboard itself has no WebSocket connection.
 */

import React from 'react';
import { usePoll } from '../hooks/usePoll';
import { DEFAULTS } from '../config/constants';
import { CheckCircle, AlertTriangle, XCircle, Clock, Wifi, WifiOff } from '../ui/icons';

interface MarketHealth {
  ticker: string;
  underlying: string;
  timeframe: string;
  initialized: boolean;
  last_update_age_ms: number;
  best_bid_cents: number | null;
  best_ask_cents: number | null;
  mid_cents: number | null;
  spread_cents: number | null;
}

interface KalshiHealthResponse {
  trading_enabled: boolean;
  market_count: number;
  expected_market_count: number;
  markets: MarketHealth[];
  timestamp: string;
}

interface UnifiedService {
  status?: string;
  ready?: boolean;
  error?: string;
}

interface UnifiedHealthResponse {
  overall_status: string;
  startup_completed?: boolean;
  timestamp?: string;
  services?: Record<string, UnifiedService>;
}

const STALE_BOOK_MS = 30_000;

const formatAge = (ms: number) => {
  if (!Number.isFinite(ms)) return '∞';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

const MarketHealthCard: React.FC<{ market: MarketHealth }> = ({ market }) => {
  const fresh = market.initialized && market.last_update_age_ms < STALE_BOOK_MS;
  const bookStatus: 'ok' | 'stale' | 'missing' = !market.initialized
    ? 'missing'
    : fresh ? 'ok' : 'stale';
  const statusColors = {
    ok: 'text-emerald-400',
    stale: 'text-amber-400',
    missing: 'text-red-400',
  };

  return (
    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-white">{market.underlying}</span>
        <span className={`text-xs ${statusColors[bookStatus]}`}>
          Book: {bookStatus}
        </span>
      </div>
      <div className="text-[10px] text-slate-500 font-mono mb-2">{market.ticker}</div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-slate-500">Update age:</span>
          <span className="ml-1 font-mono text-white">{formatAge(market.last_update_age_ms)}</span>
        </div>
        <div>
          <span className="text-slate-500">Initialized:</span>
          <span className={`ml-1 font-mono ${market.initialized ? 'text-emerald-400' : 'text-red-400'}`}>
            {market.initialized ? 'yes' : 'no'}
          </span>
        </div>
        {market.spread_cents !== null && (
          <div>
            <span className="text-slate-500">Spread:</span>
            <span className="ml-1 font-mono text-white">{market.spread_cents}¢</span>
          </div>
        )}
        {market.mid_cents !== null && (
          <div>
            <span className="text-slate-500">Mid:</span>
            <span className="ml-1 font-mono text-white">{market.mid_cents}¢</span>
          </div>
        )}
      </div>
    </div>
  );
};

const Kalshi15mHealthPanel: React.FC = () => {
  const kalshiHealth = usePoll<KalshiHealthResponse>(
    '/api/v1/kalshi/internal/kalshi_health',
    { ms: DEFAULTS.POLLING_INTERVALS.FAST },
  );
  const unifiedHealth = usePoll<UnifiedHealthResponse>(
    '/api/v1/unified-health',
    { ms: DEFAULTS.POLLING_INTERVALS.FAST },
  );

  const isLoading = (kalshiHealth.loading || unifiedHealth.loading) && !kalshiHealth.data;
  const error = kalshiHealth.error ?? unifiedHealth.error;
  const data = kalshiHealth.data;
  const unified = unifiedHealth.data;

  if (isLoading) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <Clock className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading health status...</span>
        </div>
      </div>
    );
  }

  if (!data && error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <XCircle className="w-4 h-4" />
          <span className="font-semibold">Health Status Unavailable</span>
        </div>
        <p className="text-sm text-slate-400 mb-3">{String(error)}</p>
        <button
          type="button"
          onClick={() => { void kalshiHealth.refresh(); void unifiedHealth.refresh(); }}
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <p className="text-slate-500 text-sm">No health data available.</p>
      </div>
    );
  }

  const marketsOk = data.market_count >= data.expected_market_count;
  const staleCount = data.markets.filter((m: MarketHealth) => !m.initialized || m.last_update_age_ms >= STALE_BOOK_MS).length;
  const overall: 'healthy' | 'degraded' | 'unhealthy' =
    !data.trading_enabled ? 'unhealthy'
    : !marketsOk || staleCount > 0 ? 'degraded'
    : 'healthy';

  const overallColors = {
    healthy: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    degraded: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    unhealthy: 'bg-red-500/10 border-red-500/30 text-red-400',
  };

  const wsBridge = unified?.services?.['ws_bridge'];
  const wsStatus = wsBridge?.status ?? 'unknown';
  const wsOk = wsBridge?.ready === true;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white">15m Kalshi Health</h3>
        <div className={`px-3 py-1 rounded-full border ${overallColors[overall]} text-sm font-semibold uppercase`}>
          {overall}
        </div>
      </div>

      {/* Trading / feed / backend status */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Trading Enabled</div>
          <div className="flex items-center gap-2">
            {data.trading_enabled ? (
              <CheckCircle className="w-4 h-4 text-emerald-400" />
            ) : (
              <XCircle className="w-4 h-4 text-red-400" />
            )}
            <span className="font-mono text-white">{data.trading_enabled ? 'yes' : 'no'}</span>
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Markets Tracked</div>
          <div className={`font-mono ${marketsOk ? 'text-white' : 'text-amber-400'}`}>
            {data.market_count}/{data.expected_market_count}
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1" title="Backend Kalshi WS bridge status from unified-health — this dashboard has no WebSocket">
            Venue Feed (WS bridge)
          </div>
          <div className="flex items-center gap-2">
            {wsOk ? (
              <Wifi className="w-4 h-4 text-emerald-400" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-400" />
            )}
            <span className="font-mono text-white">{wsStatus}</span>
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Backend Overall</div>
          <div className="font-mono text-white">{unified?.overall_status ?? 'unknown'}</div>
        </div>
      </div>

      {/* Per-market book health */}
      {data.markets.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-300 mb-2">Market Book Health</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.markets.map((m: MarketHealth) => (
              <MarketHealthCard key={m.ticker} market={m} />
            ))}
          </div>
        </div>
      )}
      {staleCount > 0 && (
        <div className="mt-3 flex items-center gap-2 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5" />
          {staleCount} book(s) stale or uninitialized (&gt;{STALE_BOOK_MS / 1000}s)
        </div>
      )}
    </div>
  );
};

Kalshi15mHealthPanel.displayName = 'Kalshi15mHealthPanel';
export default React.memo(Kalshi15mHealthPanel);
