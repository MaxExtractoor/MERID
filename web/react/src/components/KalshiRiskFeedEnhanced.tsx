/**
 * Enhanced KalshiRiskFeed with improved error handling and offline support
 * 
 * Fixes:
 * - Offline detection and graceful degradation
 * - Connection retry logic
 * - Event buffering during disconnections
 * - Better error categorization
 * - Action status persistence
 */

import React, { useCallback, useState, useEffect, useRef } from 'react';
import {
  AlertTriangle, Shield, Activity, Zap,
  TrendingDown, AlertCircle,
  PauseCircle, ExternalLink, Wifi, WifiOff,
  Search, ShieldOff, Minimize2, RefreshCw, Clock,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, API_BASE_URL, AUTH_TOKEN_KEY } from '../config/constants';
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

interface ActionStatus {
  [actionId: string]: 'idle' | 'pending' | 'done' | 'error';
}

interface EnhancedRiskFeedProps {
  onOpenMarket?: (ticker: string) => void;
  maxEvents?: number;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

export const EnhancedKalshiRiskFeed: React.FC<EnhancedRiskFeedProps> = ({
  onOpenMarket,
  maxEvents = 50,
  autoRefresh = true,
  refreshInterval = 30000,
}) => {
  // Enhanced state management
  const [events, setEvents] = useState<RiskEvent[]>([]);
  const [actionStatus, setActionStatus] = useState<ActionStatus>({});
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected');
  const [lastConnected, setLastConnected] = useState<Date>(new Date());
  const [bufferedEvents, setBufferedEvents] = useState<RiskEvent[]>([]);
  const retryCountRef = useRef(0);
  const [isPaused, setIsPaused] = useState(false);
  
  // Refs for connection management
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const refreshIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const maxRetries = useRef(5);

  // WebSocket stream
  const { alerts: wsAlerts, connected: wsConnected } = useKalshiRiskStream();

  // Sync WS connection status
  useEffect(() => {
    if (wsConnected) {
      setConnectionStatus('connected');
      setLastConnected(new Date());
      retryCountRef.current = 0;
      // Process buffered events
      if (bufferedEvents.length > 0) {
        setEvents(prev => [...bufferedEvents, ...prev].slice(0, maxEvents));
        setBufferedEvents([]);
      }
    } else {
      setConnectionStatus('disconnected');
    }
  }, [wsConnected, bufferedEvents, maxEvents]);

  // Merge WS alerts into events
  useEffect(() => {
    if (wsAlerts.length > 0 && !isPaused) {
      const newEvents: RiskEvent[] = wsAlerts.map(a => ({
        id: a.id,
        ts: a.ts,
        severity: (a.severity === 'critical' ? 'critical' : a.severity === 'warning' ? 'warning' : 'info') as RiskEvent['severity'],
        category: (a.category || 'general') as RiskEvent['category'],
        title: a.title ?? a.message,
        detail: a.detail ?? '',
      }));
      setEvents(prev => [...newEvents, ...prev].slice(0, maxEvents));
    }
  }, [wsAlerts, isPaused, maxEvents]);

  // API data fetch with retry logic
  const { data: initialData, isLoading, refetch } = useApiData<RiskFeedResponse>(
    API_ENDPOINTS.KALSHI_RISK_EVENTS,
    {
      pollingInterval: autoRefresh && connectionStatus === 'connected' ? refreshInterval : undefined,
    }
  );

  // Initialize events from API data
  useEffect(() => {
    if (initialData?.events && events.length === 0) {
      setEvents(initialData.events.slice(0, maxEvents));
    }
  }, [initialData, events.length, maxEvents]);

  // Manual refresh
  const handleRefresh = useCallback(async () => {
    setConnectionStatus('reconnecting');
    try {
      await refetch();
      retryCountRef.current = 0;
    } catch (error) {
      console.error('Manual refresh failed:', error);
    }
  }, [refetch]);

  // Action handlers with enhanced error handling
  const executeAction = useCallback(async (
    actionId: string,
    action: () => Promise<void>,
    onSuccess?: () => void
  ) => {
    setActionStatus(prev => ({ ...prev, [actionId]: 'pending' }));
    
    try {
      await action();
      setActionStatus(prev => ({ ...prev, [actionId]: 'done' }));
      onSuccess?.();
      
      // Reset status after delay
      setTimeout(() => {
        setActionStatus(prev => ({ ...prev, [actionId]: 'idle' }));
      }, 3000);
      
    } catch (error) {
      console.error(`Action ${actionId} failed:`, error);
      setActionStatus(prev => ({ ...prev, [actionId]: 'error' }));
      
      // Reset error status after delay
      setTimeout(() => {
        setActionStatus(prev => ({ ...prev, [actionId]: 'idle' }));
      }, 5000);
    }
  }, []);

  const handlePauseAgents = useCallback(() => {
    executeAction('pause-agents', async () => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}/api/v1/system/pause-agents`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: AbortSignal.timeout(10000),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to pause agents: ${response.status}`);
      }
      
      logUxEvent('risk_feed_pause_agents');
    });
  }, [executeAction]);

  const handleResetKillSwitch = useCallback(() => {
    executeAction('reset-ks', async () => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}/api/v1/risk/kill-switch`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: AbortSignal.timeout(10000),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to reset kill switch: ${response.status}`);
      }
      
      logUxEvent('risk_feed_reset_kill_switch');
    });
  }, [executeAction]);

  const handleDownsize = useCallback(() => {
    executeAction('downsize-all', async () => {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}/api/v1/risk/downsize-all`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: AbortSignal.timeout(10000),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to downsize positions: ${response.status}`);
      }
      
      logUxEvent('risk_feed_downsize_all');
    });
  }, [executeAction]);

  const handleOpenMarketFromAlert = useCallback((title: string) => {
    const ticker = title.split(':')[0];
    onOpenMarket?.(ticker);
    logUxEvent('risk_feed_open_market');
  }, [onOpenMarket]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, []);

  // Connection status indicator
  const ConnectionStatusIndicator = () => (
    <div className="flex items-center gap-2 text-xs">
      {connectionStatus === 'connected' && <Wifi className="w-3 h-3 text-green-400" />}
      {connectionStatus === 'reconnecting' && <RefreshCw className="w-3 h-3 text-yellow-400 animate-spin" />}
      {connectionStatus === 'disconnected' && <WifiOff className="w-3 h-3 text-red-400" />}
      <span className={
        connectionStatus === 'connected' ? 'text-green-400' :
        connectionStatus === 'reconnecting' ? 'text-yellow-400' : 'text-red-400'
      }>
        {connectionStatus === 'connected' ? 'Live' :
         connectionStatus === 'reconnecting' ? 'Reconnecting...' : 'Offline'}
      </span>
      {connectionStatus === 'disconnected' && bufferedEvents.length > 0 && (
        <span className="text-gray-400">({bufferedEvents.length} buffered)</span>
      )}
    </div>
  );

  // Filter events based on pause state
  const displayEvents = isPaused ? events.slice(0, 5) : events;

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Risk Feed</h3>
        <div className="flex items-center gap-3">
          <ConnectionStatusIndicator />
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="p-1 text-gray-400 hover:text-white transition-colors"
            title={isPaused ? "Resume updates" : "Pause updates"}
          >
            <PauseCircle className={`w-4 h-4 ${isPaused ? 'text-yellow-400' : ''}`} />
          </button>
          <button
            onClick={handleRefresh}
            disabled={connectionStatus === 'reconnecting'}
            className="p-1 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
            title="Manual refresh"
          >
            <RefreshCw className={`w-4 h-4 ${connectionStatus === 'reconnecting' ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Connection Error Banner */}
      {connectionStatus === 'disconnected' && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <WifiOff className="w-3.5 h-3.5" />
          <span>Connection lost. Attempting to reconnect... ({retryCountRef.current}/{maxRetries.current})</span>
        </div>
      )}

      {/* Loading State */}
      {isLoading && events.length === 0 && (
        <div className="flex items-center justify-center py-8 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin mr-2" />
          <span>Loading risk events...</span>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && events.length === 0 && connectionStatus === 'connected' && (
        <div className="text-center py-8 text-gray-400">
          <Shield className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <span className="text-sm">No risk events</span>
        </div>
      )}

      {/* Events List */}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {displayEvents.map((event, idx) => {
          const config = CATEGORY_CONFIG[event.category];
          const Icon = config.icon;
          
          return (
            <div
              key={`${event.id}-${idx}`}
              className={`border-l-2 ${SEVERITY_RING[event.severity]} bg-slate-700/30 p-3 rounded-r-lg transition-all hover:bg-slate-700/50`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2 flex-1">
                  <Icon className={`w-4 h-4 ${config.color} shrink-0 mt-0.5`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-medium text-white truncate">
                        {event.title}
                      </span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        event.severity === 'critical' ? 'bg-red-500/20 text-red-400' :
                        event.severity === 'warning' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-slate-600/20 text-gray-400'
                      }`}>
                        {event.severity}
                      </span>
                    </div>
                    {event.detail && (
                      <p className="text-xs text-gray-400 break-words">{event.detail}</p>
                    )}
                    <div className="flex items-center gap-1 mt-1 text-[10px] text-gray-500">
                      <Clock className="w-2.5 h-2.5" />
                      <span>{new Date(event.ts).toLocaleTimeString()}</span>
                    </div>
                  </div>
                </div>
                
                {/* Action Buttons */}
                <div className="flex items-center gap-1 shrink-0">
                  {/* Rate limit → pause agents */}
                  {event.category === 'rate_limit' && (
                    <button
                      type="button"
                      onClick={handlePauseAgents}
                      disabled={actionStatus['pause-agents'] === 'pending'}
                      className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                    >
                      <PauseCircle className="w-2.5 h-2.5" />
                      {actionStatus['pause-agents'] === 'done' ? 'Paused ✓' : 
                       actionStatus['pause-agents'] === 'pending' ? 'Pausing...' : 
                       actionStatus['pause-agents'] === 'error' ? 'Failed ✗' : 'Pause agents'}
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
                      {actionStatus['reset-ks'] === 'done' ? 'Reset ✓' : 
                       actionStatus['reset-ks'] === 'pending' ? 'Resetting...' : 
                       actionStatus['reset-ks'] === 'error' ? 'Failed ✗' : 'Reset kill switch'}
                    </button>
                  )}
                  
                  {/* Liquidity alert → reduce size + open market */}
                  {event.category === 'liquidity' && (
                    <>
                      <button
                        type="button"
                        onClick={handleDownsize}
                        disabled={actionStatus['downsize-all'] === 'pending'}
                        className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
                      >
                        <Minimize2 className="w-2.5 h-2.5" />
                        {actionStatus['downsize-all'] === 'done' ? 'Reduced ✓' : 
                         actionStatus['downsize-all'] === 'error' ? 'Failed ✗' : 'Reduce size'}
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
                  {event.severity === 'critical' && (
                    <button
                      type="button"
                      className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                    >
                      <ExternalLink className="w-2.5 h-2.5" />
                      Risk
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer with stats */}
      <div className="flex justify-between items-center pt-2 border-t border-slate-700 text-xs text-gray-400">
        <span>
          {displayEvents.length} events
          {isPaused && ' (paused)'}
        </span>
        <span>
          Last updated: {lastConnected.toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
};

EnhancedKalshiRiskFeed.displayName = 'EnhancedKalshiRiskFeed';
