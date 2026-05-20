/**
 * KalshiRiskFeed — Live risk event stream panel.
 *
 * Renders a scrollable feed of critical risk events:
 *   - Circuit breaker trips
 *   - Daily loss cap hits
 *   - Drawdown tier changes
 *   - API errors / repeated 429s
 *   - Liquidity alerts (wide spreads, thin books)
 */

import React, { useMemo, useCallback, useState, useEffect } from 'react';
import {
  AlertTriangle, Shield, Activity, Zap,
  TrendingDown, Radio, AlertCircle,
  ArrowDownCircle, PauseCircle, ExternalLink, Wifi, WifiOff,
  Search, ShieldOff, Minimize2, RefreshCw,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, API_BASE_URL, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUxEvent } from '../utils/uxTelemetry';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';

interface RiskEvent {
  id: string;
  ts: string;
  severity: 'info' | 'warning' | 'critical';
  category: 'circuit_breaker' | 'loss_cap' | 'drawdown' | 'api_error' | 'liquidity' | 'rate_limit' | 'general';
  title: string;
  detail?: string;
}

interface RiskFeedResponse {
  events: RiskEvent[];
}

const CATEGORY_CONFIG: Record<string, { icon: React.ElementType; color: string }> = {
  circuit_breaker: { icon: Shield, color: 'text-red-400' },
  loss_cap: { icon: TrendingDown, color: 'text-red-400' },
  drawdown: { icon: TrendingDown, color: 'text-orange-400' },
  api_error: { icon: AlertCircle, color: 'text-yellow-400' },
  liquidity: { icon: Activity, color: 'text-blue-400' },
  rate_limit: { icon: Zap, color: 'text-yellow-400' },
  general: { icon: AlertTriangle, color: 'text-gray-400' },
};

const SEVERITY_RING: Record<string, string> = {
  critical: 'border-l-red-500',
  warning: 'border-l-yellow-500',
  info: 'border-l-slate-600',
};

interface RiskFeedProps {
  maxItems?: number;
  onNavigate?: (view: string) => void;
  onOpenMarket?: (ticker: string) => void;
  enhanced?: boolean;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

const KalshiRiskFeed: React.FC<RiskFeedProps> = ({ 
  maxItems = 50, 
  onNavigate, 
  onOpenMarket,
  enhanced = false,
  autoRefresh = true,
  refreshInterval = 30000
}) => {
  const [actionStatus, setActionStatus] = useState<Record<string, 'pending' | 'done' | 'error'>>({});
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected');
  const { alerts: wsAlerts, summary: wsSummary, connected: wsConnected } = useKalshiRiskStream();
  
  // Enhanced: Track connection status
  useEffect(() => {
    setConnectionStatus(wsConnected ? 'connected' : 'disconnected');
  }, [wsConnected]);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const handleDownsize = useCallback(async (asset?: string) => {
    if (!window.confirm(`Downsize ${asset ?? 'all'} positions by 50%? This will reduce live position sizes.`)) return;
    const key = `downsize-${asset ?? 'all'}`;
    setActionStatus(prev => ({ ...prev, [key]: 'pending' }));
    logUxEvent('risk_action', 'downsize', { asset });
    try {
      const params = new URLSearchParams();
      if (asset) params.set('asset', asset);
      params.set('factor', '0.5');
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_RISK_DOWNSIZE}?${params}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      setActionStatus(prev => ({ ...prev, [key]: 'done' }));
      setTimeout(() => setActionStatus(prev => { const n = { ...prev }; delete n[key]; return n; }), DEFAULTS.TIMEOUTS.TOAST);
    } catch {
      setActionStatus(prev => ({ ...prev, [key]: 'error' }));
    }
  }, [authHeaders]);

  const handleNavigateRisk = useCallback(() => {
    logUxEvent('risk_action', 'open_risk_tab');
    onNavigate?.('kalshi-portfolio');
  }, [onNavigate]);

  const handlePauseAgents = useCallback(async () => {
    if (!window.confirm('Pause all agents? This will stop new order placement.')) return;
    setActionStatus(prev => ({ ...prev, 'pause-agents': 'pending' }));
    logUxEvent('risk_action', 'pause_agents');
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_PAUSE}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      setActionStatus(prev => ({ ...prev, 'pause-agents': 'done' }));
      setTimeout(() => setActionStatus(prev => { const n = { ...prev }; delete n['pause-agents']; return n; }), DEFAULTS.TIMEOUTS.TOAST);
    } catch {
      setActionStatus(prev => ({ ...prev, 'pause-agents': 'error' }));
    }
  }, [authHeaders]);

  const handleResetKillSwitch = useCallback(async () => {
    if (!window.confirm('Reset kill switch and re-enable trading? Ensure all issues are resolved first.')) return;
    setActionStatus(prev => ({ ...prev, 'reset-ks': 'pending' }));
    logUxEvent('risk_action', 'reset_kill_switch');
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ confirm: true }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      setActionStatus(prev => ({ ...prev, 'reset-ks': 'done' }));
      setTimeout(() => setActionStatus(prev => { const n = { ...prev }; delete n['reset-ks']; return n; }), DEFAULTS.TIMEOUTS.TOAST);
    } catch {
      setActionStatus(prev => ({ ...prev, 'reset-ks': 'error' }));
    }
  }, [authHeaders]);

  const handleOpenMarketFromAlert = useCallback((title: string) => {
    const ticker = title.match(/^([A-Z0-9-]+):/)?.[1];
    if (ticker && onOpenMarket) {
      logUxEvent('risk_action', 'open_market_from_alert', { ticker });
      onOpenMarket(ticker);
    }
  }, [onOpenMarket]);
  const { data, loading, refetch } = useApiData<RiskFeedResponse>(
    API_ENDPOINTS.KALSHI_RISK_EVENTS,
    { pollingInterval: enhanced && autoRefresh && connectionStatus === 'connected' ? refreshInterval : DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  
  // Enhanced: Manual refresh
  const handleRefresh = useCallback(async () => {
    if (!enhanced) return;
    setConnectionStatus('reconnecting');
    try {
      await refetch();
      setConnectionStatus('connected');
    } catch {
      setConnectionStatus('disconnected');
    }
  }, [enhanced, refetch]);

  // Also pull from liquidity alerts
  const liqResult = useApiData<{ alerts: Array<{ ticker: string; message: string; severity: string; ts: string }> }>(
    API_ENDPOINTS.KALSHI_LIQUIDITY_ALERTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const events = useMemo(() => {
    const riskEvents: RiskEvent[] = (data?.events ?? []).slice(0, maxItems);

    // Merge liquidity alerts as risk events
    const liqAlerts: RiskEvent[] = (liqResult.data?.alerts ?? []).map((a, i) => ({
      id: `liq-${i}`,
      ts: a.ts,
      severity: (a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : 'info') as RiskEvent['severity'],
      category: 'liquidity' as const,
      title: `${a.ticker}: ${a.message}`,
    }));

    // Merge WS-pushed alerts (deduplicate by id)
    const polledIds = new Set(riskEvents.map(e => e.id));
    const wsEvents: RiskEvent[] = wsAlerts
      .filter(a => !polledIds.has(a.id))
      .map(a => ({
        id: a.id,
        ts: a.ts,
        severity: (a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : 'info') as RiskEvent['severity'],
        category: (a.category || 'general') as RiskEvent['category'],
        title: a.title ?? a.message,
        detail: a.detail ?? '',
      }));

    const merged = [...riskEvents, ...liqAlerts, ...wsEvents]
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime())
      .slice(0, maxItems);

    return merged;
  }, [data, liqResult.data, wsAlerts, maxItems]);

  const criticalCount = events.filter(e => e.severity === 'critical').length;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Radio className={`w-4 h-4 ${criticalCount > 0 ? 'text-red-400 animate-pulse' : 'text-emerald-400'}`} />
          <h3 className="text-sm font-medium text-gray-300">Live Risk Feed</h3>
        </div>
        <div className="flex items-center gap-2">
          {criticalCount > 0 && (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/20 text-red-400 border border-red-500/30">
              {criticalCount} CRITICAL
            </span>
          )}
          <span className="text-[10px] text-gray-500">{events.length} events</span>
          {enhanced ? (
            <>
              <span className={
                connectionStatus === 'connected' ? 'text-emerald-400' : 
                connectionStatus === 'reconnecting' ? 'text-yellow-400' : 'text-red-400'
              }>
                {connectionStatus === 'connected' ? 'Live' : 
                 connectionStatus === 'reconnecting' ? 'Reconnecting...' : 'Offline'}
              </span>
              <button
                onClick={handleRefresh}
                disabled={connectionStatus === 'reconnecting'}
                className="p-1 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
                title="Manual refresh"
              >
                <RefreshCw className={`w-3 h-3 ${connectionStatus === 'reconnecting' ? 'animate-spin' : ''}`} />
              </button>
            </>
          ) : (
            <span title={wsConnected ? 'WS risk stream connected' : 'WS risk stream disconnected — using polling'}>
              {wsConnected
                ? <Wifi className="w-3 h-3 text-emerald-400" />
                : <WifiOff className="w-3 h-3 text-gray-600" />
              }
            </span>
          )}
        </div>
      </div>

      {/* Enhanced: WebSocket disconnect warning */}
      {enhanced && connectionStatus === 'disconnected' && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-red-500/30 bg-red-500/10 text-red-400 text-xs">
          <WifiOff className="w-3.5 h-3.5" />
          <span>Connection lost. Using polling fallback...</span>
        </div>
      )}

      {/* Live risk summary from WS */}
      {wsSummary && (
        <div className="flex items-center gap-3 px-4 py-1.5 border-b border-slate-800/50 text-[10px]">
          <div>
            <span className="text-gray-500">Equity</span>{' '}
            <span className="text-white font-mono">${(wsSummary.total_equity ?? 0).toFixed(2)}</span>
          </div>
          <div>
            <span className="text-gray-500">PnL</span>{' '}
            <span className={`font-mono ${(wsSummary.total_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {(wsSummary.total_pnl ?? 0) >= 0 ? '+' : ''}${(wsSummary.total_pnl ?? 0).toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-gray-500">Positions</span>{' '}
            <span className="text-white font-mono">{wsSummary.position_count ?? 0}</span>
          </div>
          <div>
            <span className="text-gray-500">Exposure</span>{' '}
            <span className="text-white font-mono">${(wsSummary.exposure ?? 0).toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Event list */}
      <div className="max-h-[320px] overflow-y-auto divide-y divide-slate-800/50">
        {loading && events.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-500 text-xs">Loading risk events...</div>
        ) : events.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-500 text-xs">
            No risk events. All systems nominal.
          </div>
        ) : (
          events.map(event => {
            const cfg = CATEGORY_CONFIG[event.category] ?? CATEGORY_CONFIG.general;
            const Icon = cfg.icon;
            const ring = SEVERITY_RING[event.severity] ?? SEVERITY_RING.info;

            return (
              <div
                key={event.id}
                className={`px-4 py-2.5 border-l-2 ${ring} hover:bg-slate-800/30 transition-colors`}
              >
                <div className="flex items-start gap-2">
                  <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${cfg.color}`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-white leading-tight">{event.title}</p>
                    {event.detail && (
                      <p className="text-[10px] text-gray-500 mt-0.5">{event.detail}</p>
                    )}
                    {/* Quick actions based on event category */}
                    <div className="flex items-center gap-1.5 mt-1">
                      {/* Drawdown / loss cap → downsize + pause venue */}
                      {(event.category === 'drawdown' || event.category === 'loss_cap') && (
                        <>
                          <button
                            type="button"
                            onClick={() => {
                              const asset = event.title.match(/\b(BTC|ETH|SOL)\b/)?.[1];
                              handleDownsize(asset);
                            }}
                            disabled={actionStatus[`downsize-${event.title.match(/\b(BTC|ETH|SOL)\b/)?.[1] ?? 'all'}`] === 'pending'}
                            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
                          >
                            <ArrowDownCircle className="w-2.5 h-2.5" />
                            {actionStatus[`downsize-${event.title.match(/\b(BTC|ETH|SOL)\b/)?.[1] ?? 'all'}`] === 'done'
                              ? 'Done ✓'
                              : actionStatus[`downsize-${event.title.match(/\b(BTC|ETH|SOL)\b/)?.[1] ?? 'all'}`] === 'pending'
                              ? 'Sizing...'
                              : actionStatus[`downsize-${event.title.match(/\b(BTC|ETH|SOL)\b/)?.[1] ?? 'all'}`] === 'error'
                              ? 'Failed ✗'
                              : 'Downsize 50%'}
                          </button>
                          {event.severity === 'critical' && (
                            <button
                              type="button"
                              onClick={handlePauseAgents}
                              disabled={actionStatus['pause-agents'] === 'pending'}
                              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                            >
                              <PauseCircle className="w-2.5 h-2.5" />
                              {actionStatus['pause-agents'] === 'done' ? 'Paused ✓' : actionStatus['pause-agents'] === 'pending' ? 'Pausing...' : actionStatus['pause-agents'] === 'error' ? 'Failed ✗' : 'Pause venue'}
                            </button>
                          )}
                        </>
                      )}
                      {/* Rate limit → pause agents */}
                      {event.category === 'rate_limit' && (
                        <button
                          type="button"
                          onClick={handlePauseAgents}
                          disabled={actionStatus['pause-agents'] === 'pending'}
                          className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                        >
                          <PauseCircle className="w-2.5 h-2.5" />
                          {actionStatus['pause-agents'] === 'done' ? 'Paused ✓' : actionStatus['pause-agents'] === 'pending' ? 'Pausing...' : actionStatus['pause-agents'] === 'error' ? 'Failed ✗' : 'Pause agents'}
                        </button>
                      )}
                      {/* Circuit breaker → reset kill switch */}
                      {event.category === 'circuit_breaker' && (
                        <button
                          type="button"
                          onClick={handleResetKillSwitch}
                          disabled={actionStatus['reset-ks'] === 'pending'}
                          className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                        >
                          <ShieldOff className="w-2.5 h-2.5" />
                          {actionStatus['reset-ks'] === 'done' ? 'Reset ✓' : actionStatus['reset-ks'] === 'pending' ? 'Resetting...' : actionStatus['reset-ks'] === 'error' ? 'Failed ✗' : 'Reset kill switch'}
                        </button>
                      )}
                      {/* Liquidity alert → reduce size + open market */}
                      {event.category === 'liquidity' && (
                        <>
                          <button
                            type="button"
                            onClick={() => handleDownsize()}
                            disabled={actionStatus['downsize-all'] === 'pending'}
                            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
                          >
                            <Minimize2 className="w-2.5 h-2.5" />
                            {actionStatus['downsize-all'] === 'done' ? 'Reduced ✓' : actionStatus['downsize-all'] === 'error' ? 'Failed ✗' : 'Reduce size'}
                          </button>
                          {onOpenMarket && event.title.match(/^[A-Z0-9-]+:/) && (
                            <button
                              type="button"
                              onClick={() => handleOpenMarketFromAlert(event.title)}
                              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700/50 text-gray-400 hover:bg-slate-700 hover:text-white transition-colors"
                            >
                              <Search className="w-2.5 h-2.5" />
                              Market detail
                            </button>
                          )}
                        </>
                      )}
                      {/* Critical events → risk tab */}
                      {event.severity === 'critical' && onNavigate && (
                        <button
                          type="button"
                          onClick={handleNavigateRisk}
                          className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-700/50 text-gray-400 hover:bg-slate-700 hover:text-white transition-colors"
                        >
                          <ExternalLink className="w-2.5 h-2.5" />
                          Risk tab
                        </button>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] text-gray-600 whitespace-nowrap shrink-0">
                    {new Date(event.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default KalshiRiskFeed;
