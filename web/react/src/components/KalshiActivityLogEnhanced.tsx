/**
 * Enhanced Kalshi Activity Log with comprehensive robustness.
 * 
 * Features:
 * - Network status monitoring and awareness
 * - Error categorization and recovery
 * - Loading states with skeleton loaders
 * - Retry logic with exponential backoff
 * - Empty states with retry options
 * - Graceful degradation on failures
 */

import React, { useState, useCallback, useEffect } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { Bot, ArrowRight, RefreshCw, Wifi, WifiOff, AlertTriangle } from '../ui/icons';

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

interface EnhancedKalshiActivityLogProps {
  ticker: string | null;
  maxItems?: number;
}

type ErrorType = 'network' | 'api' | 'timeout' | 'unknown';
type LoadingState = 'idle' | 'loading' | 'refreshing' | 'error' | 'empty';

interface ErrorInfo {
  type: ErrorType;
  message: string;
  retryable: boolean;
  timestamp: number;
}

// Network status hook (mock implementation)
const useNetworkStatus = () => {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [networkSpeed, setNetworkSpeed] = useState<'fast' | 'slow' | 'unknown'>('unknown');

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Simple network speed detection
  useEffect(() => {
    if (!isOnline) {
      setNetworkSpeed('unknown');
      return;
    }

    // Detect connection speed (simplified)
    const connection = (navigator as any).connection;
    if (connection) {
      if (connection.effectiveType === 'slow-2g' || connection.effectiveType === '2g') {
        setNetworkSpeed('slow');
      } else if (connection.effectiveType === '4g') {
        setNetworkSpeed('fast');
      } else {
        setNetworkSpeed('unknown');
      }
    }
  }, [isOnline]);

  return { isOnline, networkSpeed };
};

// Error categorization utility
const categorizeError = (error: any): ErrorInfo => {
  const timestamp = Date.now();
  
  if (!error) {
    return {
      type: 'unknown' as ErrorType,
      message: 'Unknown error occurred',
      retryable: true,
      timestamp,
    };
  }

  // Network errors
  if (error.name === 'TypeError' && error.message.includes('fetch')) {
    return {
      type: 'network' as ErrorType,
      message: 'Network connection failed',
      retryable: true,
      timestamp,
    };
  }

  // Timeout errors
  if (error.name === 'AbortError' || error.message.includes('timeout')) {
    return {
      type: 'timeout' as ErrorType,
      message: 'Request timed out',
      retryable: true,
      timestamp,
    };
  }

  // API errors (HTTP status codes)
  if (error.status) {
    if (error.status >= 500) {
      return {
        type: 'api' as ErrorType,
        message: 'Server error occurred',
        retryable: true,
        timestamp,
      };
    } else if (error.status === 429) {
      return {
        type: 'api' as ErrorType,
        message: 'Rate limit exceeded',
        retryable: true,
        timestamp,
      };
    } else if (error.status >= 400) {
      return {
        type: 'api' as ErrorType,
        message: 'Invalid request',
        retryable: false,
        timestamp,
      };
    }
  }

  // Default unknown error
  return {
    type: 'unknown' as ErrorType,
    message: error.message || 'An unexpected error occurred',
    retryable: true,
    timestamp,
  };
};

// Retry logic hook
const useRetryLogic = (maxRetries: number = 3, baseDelay: number = 1000) => {
  const [retryCount, setRetryCount] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);

  const retry = useCallback(async (operation: () => Promise<any>) => {
    if (retryCount >= maxRetries) {
      return false; // Max retries reached
    }

    setIsRetrying(true);
    setRetryCount(prev => prev + 1);

    try {
      // Exponential backoff
      const delay = baseDelay * Math.pow(2, retryCount);
      await new Promise(resolve => setTimeout(resolve, delay));
      
      await operation();
      setIsRetrying(false);
      setRetryCount(0); // Reset on success
      return true;
    } catch (error) {
      setIsRetrying(false);
      throw error;
    }
  }, [retryCount, maxRetries, baseDelay]);

  const resetRetry = useCallback(() => {
    setRetryCount(0);
    setIsRetrying(false);
  }, []);

  return {
    retryCount,
    maxRetries,
    isRetrying,
    canRetry: retryCount < maxRetries,
    retry,
    resetRetry,
  };
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

function NetworkStatusIndicator({ isOnline, networkSpeed }: { isOnline: boolean; networkSpeed: string }) {
  if (!isOnline) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/30 rounded-lg mb-2">
        <WifiOff className="w-4 h-4 text-red-400" />
        <span className="text-xs text-red-400">Offline - Activity unavailable</span>
      </div>
    );
  }

  if (networkSpeed === 'slow') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-amber-500/20 border border-amber-500/30 rounded-lg mb-2">
        <Wifi className="w-4 h-4 text-amber-400" />
        <span className="text-xs text-amber-400">Slow connection - Activity may be delayed</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-green-500/20 border border-green-500/30 rounded-lg mb-2">
      <Wifi className="w-4 h-4 text-green-400" />
      <span className="text-xs text-green-400">Connected</span>
    </div>
  );
}

function ErrorDisplay({ error, onRetry, retryCount, maxRetries, isRetrying }: {
  error: ErrorInfo;
  onRetry: () => void;
  retryCount: number;
  maxRetries: number;
  isRetrying: boolean;
}) {
  const getErrorIcon = () => {
    switch (error.type) {
      case 'network':
        return <WifiOff className="w-4 h-4 text-red-400" />;
      case 'timeout':
        return <AlertTriangle className="w-4 h-4 text-amber-400" />;
      case 'api':
        return <AlertTriangle className="w-4 h-4 text-orange-400" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-gray-400" />;
    }
  };

  const getErrorColor = () => {
    switch (error.type) {
      case 'network':
        return 'text-red-400';
      case 'timeout':
        return 'text-amber-400';
      case 'api':
        return 'text-orange-400';
      default:
        return 'text-gray-400';
    }
  };

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
      <div className="flex items-center gap-2 mb-3">
        {getErrorIcon()}
        <span className={`text-xs ${getErrorColor()}`}>{error.message}</span>
      </div>
      
      {error.retryable && retryCount < maxRetries && (
        <button
          onClick={onRetry}
          disabled={isRetrying}
          className="flex items-center gap-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:opacity-50 text-white text-xs rounded transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${isRetrying ? 'animate-spin' : ''}`} />
          {isRetrying ? 'Retrying...' : `Retry (${retryCount}/${maxRetries})`}
        </button>
      )}
      
      {retryCount >= maxRetries && (
        <div className="text-xs text-gray-500">
          Max retries reached. Please check your connection and try again later.
        </div>
      )}
    </div>
  );
}

function EmptyState({ onRetry, retryCount, maxRetries, isRetrying }: {
  onRetry: () => void;
  retryCount: number;
  maxRetries: number;
  isRetrying: boolean;
}) {
  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
      <div className="text-center py-6">
        <Bot className="w-8 h-8 text-gray-600 mx-auto mb-2" />
        <p className="text-[10px] text-gray-600 mb-3">No agent activity available</p>
        <button
          onClick={onRetry}
          disabled={isRetrying}
          className="flex items-center gap-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 disabled:opacity-50 text-white text-xs rounded transition-colors mx-auto"
        >
          <RefreshCw className={`w-3 h-3 ${isRetrying ? 'animate-spin' : ''}`} />
          {isRetrying ? 'Refreshing...' : 'Refresh'}
        </button>
        {retryCount > 0 && (
          <p className="text-[10px] text-gray-500 mt-2">
            Retry attempts: {retryCount}/{maxRetries}
          </p>
        )}
      </div>
    </div>
  );
}

function EnhancedKalshiActivityLog({ ticker, maxItems = 12 }: EnhancedKalshiActivityLogProps) {
  const { isOnline, networkSpeed } = useNetworkStatus();
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [cachedData, setCachedData] = useState<ActivityGridAgent[] | null>(null);
  
  const { data: gridData, isLoading, refetch } = useApiData<{ agents: ActivityGridAgent[] }>(
    API_ENDPOINTS.KALSHI_GRID_AGENTS,
    { 
      pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
      enabled: isOnline, // Only fetch when online
    }
  );

  const { retryCount, maxRetries, isRetrying, canRetry, retry, resetRetry } = useRetryLogic(3, 1000);

  // Handle loading states
  useEffect(() => {
    if (isLoading && loadingState === 'idle') {
      setLoadingState('loading');
    } else if (!isLoading && loadingState === 'loading') {
      setLoadingState('idle');
    }
  }, [isLoading, loadingState]);

  // Handle errors
  useEffect(() => {
    if (gridData === null && !isLoading && isOnline) {
      // Likely an error occurred
      setError(categorizeError(new Error('Failed to fetch activity data')));
      setLoadingState('error');
    } else if (gridData && error) {
      // Recovery from error
      setError(null);
      setLoadingState('idle');
      resetRetry();
    }
  }, [gridData, isLoading, isOnline, error, resetRetry]);

  // Cache data for graceful degradation
  useEffect(() => {
    if (gridData?.agents) {
      setCachedData(gridData.agents);
    }
  }, [gridData]);

  // Manual retry function
  const handleRetry = useCallback(async () => {
    if (!canRetry || !isOnline) return;
    
    try {
      await retry(() => refetch());
    } catch (retryError) {
      setError(categorizeError(retryError));
    }
  }, [canRetry, isOnline, retry, refetch]);

  // Process activity data
  const processActivityData = useCallback((agents: ActivityGridAgent[]) => {
    type LogItem = { ts: string; type: 'signal' | 'order'; agent: string; side: string; detail: string };
    const items: LogItem[] = [];

    for (const agent of agents ?? []) {
      for (const s of agent.signals ?? []) {
        if (!ticker || s.market_id === ticker) {
          items.push({
            ts: s.ts,
            type: 'signal',
            agent: agent.name,
            side: s.side,
            detail: `EV ${s.ev_cents > 0 ? '+' : ''}${s.ev_cents}¢ · ${((s.confidence ?? 0) * 100).toFixed(0)}% conf`,
          });
        }
      }
      for (const o of agent.orders ?? []) {
        if (!ticker || o.market_id === ticker) {
          items.push({
            ts: o.ts,
            type: 'order',
            agent: agent.name,
            side: o.side,
            detail: `${o.size}×${o.price_cents}¢ ${o.status}`,
          });
        }
      }
    }

    items.sort((a, b) => b.ts.localeCompare(a.ts));
    return items.slice(0, maxItems);
  }, [ticker, maxItems]);

  // Render based on state
  if (!isOnline) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <NetworkStatusIndicator isOnline={false} networkSpeed={networkSpeed} />
        <div className="text-center py-6">
          <WifiOff className="w-8 h-8 text-gray-600 mx-auto mb-2" />
          <p className="text-[10px] text-gray-600">Activity unavailable offline</p>
        </div>
      </div>
    );
  }

  if (loadingState === 'loading') {
    return <LoadingSkeleton />;
  }

  if (error && loadingState === 'error') {
    return (
      <ErrorDisplay
        error={error}
        onRetry={handleRetry}
        retryCount={retryCount}
        maxRetries={maxRetries}
        isRetrying={isRetrying}
      />
    );
  }

  // Use current data or cached data for graceful degradation
  const currentData = gridData?.agents || cachedData;
  
  if (!currentData || currentData.length === 0) {
    return (
      <EmptyState
        onRetry={handleRetry}
        retryCount={retryCount}
        maxRetries={maxRetries}
        isRetrying={isRetrying}
      />
    );
  }

  const items = processActivityData(currentData);

  if (items.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <NetworkStatusIndicator isOnline={isOnline} networkSpeed={networkSpeed} />
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
        <p className="text-[10px] text-gray-600 text-center py-3">No agent activity for this market</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <NetworkStatusIndicator isOnline={isOnline} networkSpeed={networkSpeed} />
      
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Agent Activity</h4>
        <div className="flex items-center gap-2">
          {cachedData && !gridData && (
            <span className="text-[10px] text-amber-400">Using cached data</span>
          )}
          <button
            onClick={handleRetry}
            disabled={isRetrying}
            className="p-1 hover:bg-slate-700 rounded transition-colors"
            title="Refresh activity"
          >
            <RefreshCw className={`w-3 h-3 text-gray-400 ${isRetrying ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {items.map((item, i) => (
          <div 
            key={`${item.ts}-${item.agent}-${item.type}-${i}`} 
            className="flex items-center gap-2 text-[10px] py-1 px-1 rounded hover:bg-slate-700/50 transition-colors"
          >
            {item.type === 'signal' ? (
              <Bot className="w-3 h-3 text-cyan-400 shrink-0" />
            ) : (
              <ArrowRight className="w-3 h-3 text-orange-400 shrink-0" />
            )}
            <span className="text-gray-500 font-mono shrink-0">
              {new Date(item.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            <span className="text-gray-400 truncate">{item.agent}</span>
            <span className={`font-medium ${item.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
              {(item.side ?? '').toUpperCase()}
            </span>
            <span className="text-gray-500 truncate">{item.detail}</span>
          </div>
        ))}
      </div>
      
      {items.length >= maxItems && (
        <div className="text-[10px] text-gray-600 text-center mt-2">
          Showing {maxItems} of {items.length + maxItems - items.length} activities
        </div>
      )}
    </div>
  );
}

EnhancedKalshiActivityLog.displayName = 'EnhancedKalshiActivityLog';
export default React.memo(EnhancedKalshiActivityLog);
