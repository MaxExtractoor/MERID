import React, { useState, useCallback, useEffect } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { Bot, ArrowRight, RefreshCw, Wifi, WifiOff, AlertTriangle } from '../ui/icons';
import { useNetworkStatus } from '../hooks/useNetworkStatusProvider';

interface ActivitySignalEntry {
  ts: string;
  market_id: string;
  question: string;
  side: string;
  confidence: number;
  ev_cents: number;
  agent: string;
}

interface ActivityOrderEntry {
  ts: string;
  market_id: string;
  side: string;
  size: number;
  price_cents: number;
  status: string;
  source: string;
  agent: string;
}

interface ActivityGridAgent {
  name: string;
  signals?: ActivitySignalEntry[];
  orders?: ActivityOrderEntry[];
}

interface KalshiActivityLogProps {
  ticker: string | null;
  maxItems?: number;
  enhanced?: boolean;
}

type ErrorType = 'network' | 'api' | 'timeout' | 'unknown';
type LoadingState = 'idle' | 'loading' | 'error' | 'empty';

interface ErrorInfo {
  type: ErrorType;
  message: string;
  retryable: boolean;
}

const categorizeError = (error: any): ErrorInfo => {
  if (!error) {
    return { type: 'unknown', message: 'Unknown error occurred', retryable: true };
  }
  if (error.name === 'TypeError' && error.message?.includes('fetch')) {
    return { type: 'network', message: 'Network connection failed', retryable: true };
  }
  if (error.name === 'AbortError' || error.message?.includes('timeout')) {
    return { type: 'timeout', message: 'Request timed out', retryable: true };
  }
  if (error.status >= 500) {
    return { type: 'api', message: 'Server error occurred', retryable: true };
  }
  return { type: 'unknown', message: error.message || 'An unexpected error occurred', retryable: true };
};

function LoadingSkeleton() {
  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="flex items-center gap-2 animate-pulse">
            <div className="w-3 h-3 bg-slate-600 rounded" />
            <div className="w-12 h-3 bg-slate-600 rounded" />
            <div className="w-16 h-3 bg-slate-600 rounded" />
            <div className="w-8 h-3 bg-slate-600 rounded" />
            <div className="flex-1 h-3 bg-slate-600 rounded" />
          </div>
        ))}
      </div>
    </div>
  );
}

function ErrorDisplay({ error, onRetry }: { error: ErrorInfo; onRetry: () => void }) {
  const getErrorIcon = () => {
    switch (error.type) {
      case 'network': return <WifiOff className="w-4 h-4 text-red-400" />;
      case 'timeout': return <AlertTriangle className="w-4 h-4 text-amber-400" />;
      default: return <AlertTriangle className="w-4 h-4 text-gray-400" />;
    }
  };

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
      <div className="flex items-center gap-2 mb-3">
        {getErrorIcon()}
        <span className="text-xs text-gray-400">{error.message}</span>
      </div>
      {error.retryable && (
        <button onClick={onRetry} className="flex items-center gap-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded">
          <RefreshCw className="w-3 h-3" /> Retry
        </button>
      )}
    </div>
  );
}

function KalshiActivityLog({ ticker, maxItems = 12, enhanced = false }: KalshiActivityLogProps) {
  const { isOnline } = useNetworkStatus();
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [cachedData, setCachedData] = useState<ActivityGridAgent[] | null>(null);

  const { data: gridData, isLoading, refetch } = useApiData<{ agents: ActivityGridAgent[] }>(
    API_ENDPOINTS.KALSHI_GRID_AGENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD, enabled: isOnline || !enhanced }
  );

  useEffect(() => {
    if (gridData?.agents) setCachedData(gridData.agents);
  }, [gridData]);

  useEffect(() => {
    if (isLoading) setLoadingState('loading');
    else if (gridData === null && !isLoading && enhanced) {
      setError(categorizeError(new Error('Failed to fetch')));
      setLoadingState('error');
    } else {
      setLoadingState('idle');
      setError(null);
    }
  }, [isLoading, gridData, enhanced]);

  const handleRetry = useCallback(async () => {
    try {
      await refetch();
      setError(null);
    } catch (err) {
      setError(categorizeError(err));
    }
  }, [refetch]);

  const processData = (agents: ActivityGridAgent[]) => {
    type LogItem = { ts: string; type: 'signal' | 'order'; agent: string; side: string; detail: string };
    const items: LogItem[] = [];
    for (const agent of agents ?? []) {
      for (const s of agent.signals ?? []) {
        if (!ticker || s.market_id === ticker) {
          items.push({
            ts: s.ts, type: 'signal', agent: agent.name, side: s.side,
            detail: `EV ${s.ev_cents > 0 ? '+' : ''}${s.ev_cents}¢ · ${((s.confidence ?? 0) * 100).toFixed(0)}% conf`,
          });
        }
      }
      for (const o of agent.orders ?? []) {
        if (!ticker || o.market_id === ticker) {
          items.push({ ts: o.ts, type: 'order', agent: agent.name, side: o.side, detail: `${o.size}×${o.price_cents}¢ ${o.status}` });
        }
      }
    }
    items.sort((a, b) => b.ts.localeCompare(a.ts));
    return items.slice(0, maxItems);
  };

  // Base mode - simple
  if (!enhanced) {
    if (!gridData) return null;
    const items = processData(gridData.agents || []);
    if (items.length === 0) {
      return (
        <div className="bg-slate-800 rounded-xl p-3">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
          <p className="text-[10px] text-gray-600 text-center py-3">No agent activity for this market</p>
        </div>
      );
    }
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {items.map((item, i) => (
            <div key={`${item.ts}-${item.agent}-${i}`} className="flex items-center gap-2 text-[10px] py-1 px-1 rounded hover:bg-slate-700/50">
              {item.type === 'signal' ? <Bot className="w-3 h-3 text-cyan-400 shrink-0" /> : <ArrowRight className="w-3 h-3 text-orange-400 shrink-0" />}
              <span className="text-gray-500 font-mono shrink-0">{new Date(item.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              <span className="text-gray-400 truncate">{item.agent}</span>
              <span className={`font-medium ${item.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>{item.side.toUpperCase()}</span>
              <span className="text-gray-500 truncate">{item.detail}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Enhanced mode
  if (!isOnline) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <div className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/30 rounded-lg mb-2">
          <WifiOff className="w-4 h-4 text-red-400" />
          <span className="text-xs text-red-400">Offline - Activity unavailable</span>
        </div>
      </div>
    );
  }

  if (loadingState === 'loading') return <LoadingSkeleton />;

  if (error && loadingState === 'error') {
    return <ErrorDisplay error={error} onRetry={handleRetry} />;
  }

  const currentData = gridData?.agents || cachedData;
  if (!currentData || currentData.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <div className="flex items-center gap-2 px-3 py-2 bg-green-500/20 border border-green-500/30 rounded-lg mb-2">
          <Wifi className="w-4 h-4 text-green-400" />
          <span className="text-xs text-green-400">Connected</span>
        </div>
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
        <div className="text-center py-6">
          <Bot className="w-8 h-8 text-gray-600 mx-auto mb-2" />
          <p className="text-[10px] text-gray-600 mb-3">No agent activity available</p>
          <button onClick={handleRetry} className="flex items-center gap-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded mx-auto">
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
        </div>
      </div>
    );
  }

  const items = processData(currentData);
  if (items.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <div className="flex items-center gap-2 px-3 py-2 bg-green-500/20 border border-green-500/30 rounded-lg mb-2">
          <Wifi className="w-4 h-4 text-green-400" />
          <span className="text-xs text-green-400">Connected</span>
        </div>
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
        <p className="text-[10px] text-gray-600 text-center py-3">No agent activity for this market</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <div className="flex items-center gap-2 px-3 py-2 bg-green-500/20 border border-green-500/30 rounded-lg mb-2">
        <Wifi className="w-4 h-4 text-green-400" />
        <span className="text-xs text-green-400">Connected</span>
        {cachedData && !gridData && <span className="text-[10px] text-amber-400">Using cached data</span>}
      </div>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Agent Activity</h4>
        <button onClick={handleRetry} className="p-1 hover:bg-slate-700 rounded transition-colors" title="Refresh activity">
          <RefreshCw className="w-3 h-3 text-gray-400" />
        </button>
      </div>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {items.map((item, i) => (
          <div key={`${item.ts}-${item.agent}-${i}`} className="flex items-center gap-2 text-[10px] py-1 px-1 rounded hover:bg-slate-700/50 transition-colors">
            {item.type === 'signal' ? <Bot className="w-3 h-3 text-cyan-400 shrink-0" /> : <ArrowRight className="w-3 h-3 text-orange-400 shrink-0" />}
            <span className="text-gray-500 font-mono shrink-0">{new Date(item.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            <span className="text-gray-400 truncate">{item.agent}</span>
            <span className={`font-medium ${item.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>{(item.side ?? '').toUpperCase()}</span>
            <span className="text-gray-500 truncate">{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

KalshiActivityLog.displayName = 'KalshiActivityLog';
export default React.memo(KalshiActivityLog);
