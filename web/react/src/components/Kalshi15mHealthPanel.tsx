/**
 * Kalshi15mHealthPanel — 15m-specific health monitoring panel.
 *
 * Surfaces health status for the 15m Kalshi crypto stack:
 * - Series health (healthy, stuck, no_active_tickers)
 * - Spot price age per asset (with thresholds/colour)
 * - Orderbook health (spread present/missing)
 * - API latency and error rates
 * - WebSocket connection status
 */

import React from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { CheckCircle, AlertTriangle, XCircle, Clock, Wifi, WifiOff } from '../ui/icons';

interface AssetHealth {
  asset: string;
  spot_price_age_ms: number;
  spot_price_threshold_ms: number;
  spot_price_status: 'ok' | 'stale' | 'missing';
  orderbook_status: 'ok' | 'missing' | 'stale';
  spread_cents: number | null;
  last_update_timestamp: string;
}

interface SeriesHealth {
  series_name: string;
  status: 'healthy' | 'stuck' | 'no_active_tickers';
  active_tickers: number;
  last_tick_timestamp: string | null;
  stuck_reason: string | null;
}

interface HealthResponse {
  overall_status: 'healthy' | 'degraded' | 'unhealthy';
  series_health: SeriesHealth[];
  asset_health: AssetHealth[];
  api_latency_ms: number;
  api_error_rate_5m: number;
  websocket_connected: boolean;
  websocket_last_message_timestamp: string | null;
  summary: {
    total_assets: number;
    healthy_assets: number;
    stale_assets: number;
    missing_assets: number;
  };
}

const AssetHealthCard: React.FC<{ asset: AssetHealth }> = ({ asset }) => {
  const spotStatusColors = {
    ok: 'text-emerald-400',
    stale: 'text-amber-400',
    missing: 'text-red-400',
  };

  const orderbookStatusColors = {
    ok: 'text-emerald-400',
    missing: 'text-red-400',
    stale: 'text-amber-400',
  };

  const formatAge = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  return (
    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-white">{asset.asset}</span>
        <div className="flex items-center gap-2 text-xs">
          <span className={spotStatusColors[asset.spot_price_status]}>
            Spot: {asset.spot_price_status}
          </span>
          <span className={orderbookStatusColors[asset.orderbook_status]}>
            OB: {asset.orderbook_status}
          </span>
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-slate-500">Spot age:</span>
          <span className="ml-1 font-mono text-white">{formatAge(asset.spot_price_age_ms)}</span>
        </div>
        <div>
          <span className="text-slate-500">Threshold:</span>
          <span className="ml-1 font-mono text-white">{formatAge(asset.spot_price_threshold_ms)}</span>
        </div>
        {asset.spread_cents !== null && (
          <div>
            <span className="text-slate-500">Spread:</span>
            <span className="ml-1 font-mono text-white">{asset.spread_cents}¢</span>
          </div>
        )}
      </div>
    </div>
  );
};

const SeriesHealthCard: React.FC<{ series: SeriesHealth }> = ({ series }) => {
  const statusColors = {
    healthy: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    stuck: 'bg-red-500/10 border-red-500/30 text-red-400',
    no_active_tickers: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
  };

  const statusIcons = {
    healthy: <CheckCircle className="w-4 h-4" />,
    stuck: <XCircle className="w-4 h-4" />,
    no_active_tickers: <AlertTriangle className="w-4 h-4" />,
  };

  return (
    <div className={`p-3 rounded-lg border ${statusColors[series.status]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {statusIcons[series.status]}
          <span className="font-semibold text-sm">{series.series_name}</span>
        </div>
        <span className="text-xs font-mono uppercase">{series.status}</span>
      </div>
      
      <div className="text-xs">
        <span className="text-slate-500">Active tickers:</span>
        <span className="ml-1 font-mono">{series.active_tickers}</span>
      </div>

      {series.stuck_reason && (
        <div className="text-xs mt-1">
          <span className="text-slate-500">Reason:</span>
          <span className="ml-1">{series.stuck_reason}</span>
        </div>
      )}
    </div>
  );
};

const Kalshi15mHealthPanel: React.FC = () => {
  const { data, loading, error, refetch } = useApiData<HealthResponse>(
    '/api/v1/kalshi/15m/health',
    {
      pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST,
    }
  );

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <Clock className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading health status...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <XCircle className="w-4 h-4" />
          <span className="font-semibold">Health Status Unavailable</span>
        </div>
        <p className="text-sm text-slate-400 mb-3">{error}</p>
        <button
          type="button"
          onClick={refetch}
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

  const overallColors = {
    healthy: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    degraded: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    unhealthy: 'bg-red-500/10 border-red-500/30 text-red-400',
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white">15m Kalshi Health</h3>
        <div className={`px-3 py-1 rounded-full border ${overallColors[data.overall_status]} text-sm font-semibold uppercase`}>
          {data.overall_status}
        </div>
      </div>

      {/* API & WebSocket Status */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">API Latency</div>
          <div className="font-mono text-white">{data.api_latency_ms.toFixed(0)}ms</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Error Rate (5m)</div>
          <div className="font-mono text-white">{(data.api_error_rate_5m * 100).toFixed(2)}%</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">WebSocket</div>
          <div className="flex items-center gap-2">
            {data.websocket_connected ? (
              <Wifi className="w-4 h-4 text-emerald-400" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-400" />
            )}
            <span className="font-mono text-white">{data.websocket_connected ? 'Connected' : 'Disconnected'}</span>
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Asset Health</div>
          <div className="flex gap-2 text-xs">
            <span className="text-emerald-400">{data.summary.healthy_assets} OK</span>
            <span className="text-amber-400">{data.summary.stale_assets} Stale</span>
            <span className="text-red-400">{data.summary.missing_assets} Missing</span>
          </div>
        </div>
      </div>

      {/* Series Health */}
      {data.series_health.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-semibold text-slate-300 mb-2">Series Health</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.series_health.map((series) => (
              <SeriesHealthCard key={series.series_name} series={series} />
            ))}
          </div>
        </div>
      )}

      {/* Asset Health */}
      {data.asset_health.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-300 mb-2">Asset Health</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.asset_health.map((asset) => (
              <AssetHealthCard key={asset.asset} asset={asset} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

Kalshi15mHealthPanel.displayName = 'Kalshi15mHealthPanel';
export default React.memo(Kalshi15mHealthPanel);
