/**
 * Enhanced Kalshi Mode Badge with comprehensive robustness.
 * 
 * Features:
 * - Network status monitoring integration
 * - Retry logic for mode fetch failures
 * - Fallback to cached mode data
 * - Enhanced error handling
 * - Graceful degradation on failures
 */

import React, { useState, useCallback, useEffect } from 'react';
import { useKalshiMode } from '../context/KalshiModeContext';
import { Shield, Zap, AlertTriangle, RefreshCw } from '../ui/icons';
import { useNetworkStatus } from '../hooks/useNetworkStatusProvider';
import { categorizeError, calculateRetryDelay } from '../utils/errorHandling';

interface EnhancedKalshiModeBadgeProps {
  className?: string;
  showTooltip?: boolean;
  fallbackMode?: string;
}

type LoadingState = 'idle' | 'loading' | 'error' | 'fallback';
type ErrorInfo = {
  type: 'network' | 'api' | 'timeout' | 'permission' | 'validation' | 'unknown';
  message: string;
  retryable: boolean;
  timestamp: number;
};

// Mode configuration with fallbacks
const MODE_CONFIG = {
  live: {
    label: 'LIVE',
    colorClass: 'bg-green-500/20 text-green-400 border-green-500/30',
    icon: Zap,
    tooltip: 'Live trading mode — real orders on Kalshi with real money',
  },
  shadow: {
    label: 'SHADOW',
    colorClass: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    icon: Shield,
    tooltip: 'Shadow mode — signals generated but not executed',
  },
  paper: {
    label: 'PAPER',
    colorClass: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    icon: Shield,
    tooltip: 'Paper trading mode — orders are simulated, no real money at risk',
  },
  mock: {
    label: 'MOCK',
    colorClass: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    icon: Shield,
    tooltip: 'Mock trading mode — simulated environment for testing',
  },
  sim: {
    label: 'SIM',
    colorClass: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    icon: Shield,
    tooltip: 'Simulation mode — backtesting and strategy testing',
  },
  unknown: {
    label: 'UNKNOWN',
    colorClass: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    icon: AlertTriangle,
    tooltip: 'Unknown trading mode — unable to determine current mode',
  },
};

// Loading skeleton for mode badge
function ModeBadgeSkeleton() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-700/50 text-slate-500 border-slate-600/30 animate-pulse">
      <div className="w-3 h-3 bg-slate-600 rounded" />
      <div className="w-8 h-3 bg-slate-600 rounded" />
    </span>
  );
}

// Error state display
function ModeBadgeError({ 
  error, 
  onRetry, 
  retryCount, 
  maxRetries 
}: { 
  error: ErrorInfo;
  onRetry: () => void;
  retryCount: number;
  maxRetries: number;
}) {
  const canRetry = retryCount < maxRetries && error.retryable;
  
  return (
    <div className="inline-flex items-center gap-2">
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-red-500/20 text-red-400 border-red-500/30">
        <AlertTriangle className="w-3 h-3" />
        ERROR
      </span>
      
      {canRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-blue-500/20 text-blue-400 border-blue-500/30 hover:bg-blue-500/30 transition-colors"
          title={`Retry mode fetch (attempt ${retryCount + 1}/${maxRetries})`}
        >
          <RefreshCw className="w-3 h-3" />
          RETRY
        </button>
      )}
      
      {retryCount >= maxRetries && (
        <span className="text-[8px] text-gray-500" title="Max retries reached">
          MAX
        </span>
      )}
    </div>
  );
}

// Fallback mode display
function ModeBadgeFallback({ mode, fallbackReason }: { mode: string; fallbackReason: string }) {
  const config = MODE_CONFIG[mode as keyof typeof MODE_CONFIG] || MODE_CONFIG.unknown;
  const Icon = config.icon;
  
  return (
    <div className="group relative inline-block">
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${config.colorClass}`}>
        <Icon className="w-3 h-3" />
        {config.label}
        <span className="ml-1 text-[8px] opacity-60">CACHED</span>
      </span>
      
      <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
        <div className="font-semibold">{config.tooltip}</div>
        <div className="text-gray-400 text-[10px] mt-1">{fallbackReason}</div>
        <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>
      </div>
    </div>
  );
}

function EnhancedKalshiModeBadge({ 
  className = '', 
  showTooltip = true,
  fallbackMode = 'paper'
}: EnhancedKalshiModeBadgeProps) {
  const { data, error, isLoading, refetch } = useKalshiMode();
  const { isOnline, networkSpeed } = useNetworkStatus();
  
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [errorInfo, setErrorInfo] = useState<ErrorInfo | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [cachedMode, setCachedMode] = useState<string | null>(null);
  const [fallbackReason, setFallbackReason] = useState<string>('');
  
  const maxRetries = 3;
  const retryDelay = calculateRetryDelay(retryCount + 1);

  // Cache successful mode data
  useEffect(() => {
    if (data?.mode && !error) {
      setCachedMode(data.mode);
      setErrorInfo(null);
      setRetryCount(0);
    }
  }, [data, error]);

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
    if (error && !isLoading) {
      const categorizedError = categorizeError(error, 'KalshiModeBadge');
      setErrorInfo(categorizedError);
      setLoadingState('error');
      
      // Auto-retry on network recovery
      if (isOnline && categorizedError.type === 'network' && retryCount < maxRetries) {
        const timer = setTimeout(() => {
          handleRetry();
        }, retryDelay);
        
        return () => clearTimeout(timer);
      }
    } else if (!error && loadingState === 'error') {
      setLoadingState('idle');
      setErrorInfo(null);
    }
  }, [error, isLoading, isOnline, retryCount, retryDelay]);

  // Fallback to cached mode on persistent errors
  useEffect(() => {
    if (loadingState === 'error' && retryCount >= maxRetries && cachedMode) {
      setLoadingState('fallback');
      setFallbackReason('Using cached mode due to persistent errors');
    }
  }, [loadingState, retryCount, cachedMode]);

  // Fallback to default mode on network issues
  useEffect(() => {
    if (!isOnline && cachedMode) {
      setLoadingState('fallback');
      setFallbackReason('Offline - using cached mode');
    } else if (isOnline && loadingState === 'fallback' && fallbackReason.includes('Offline')) {
      setLoadingState('idle');
      setFallbackReason('');
    }
  }, [isOnline, cachedMode, loadingState, fallbackReason]);

  // Manual retry handler
  const handleRetry = useCallback(async () => {
    if (retryCount >= maxRetries) return;
    
    setRetryCount(prev => prev + 1);
    
    try {
      await refetch();
    } catch (retryError) {
      // Error will be handled by the error effect above
      console.error('Mode fetch retry failed:', retryError);
    }
  }, [retryCount, maxRetries, refetch]);

  // Determine current mode
  const getCurrentMode = (): string => {
    if (data?.mode) return data.mode;
    if (cachedMode) return cachedMode;
    return fallbackMode;
  };

  const currentMode = getCurrentMode();
  const config = MODE_CONFIG[currentMode as keyof typeof MODE_CONFIG] || MODE_CONFIG.unknown;
  const Icon = config.icon;

  // Loading state
  if (loadingState === 'loading') {
    return <ModeBadgeSkeleton />;
  }

  // Error state
  if (loadingState === 'error' && errorInfo) {
    return (
      <ModeBadgeError
        error={errorInfo}
        onRetry={handleRetry}
        retryCount={retryCount}
        maxRetries={maxRetries}
      />
    );
  }

  // Fallback state
  if (loadingState === 'fallback') {
    return <ModeBadgeFallback mode={currentMode} fallbackReason={fallbackReason} />;
  }

  // Normal state
  if (!showTooltip) {
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${config.colorClass} ${className}`}>
        <Icon className="w-3 h-3" />
        {config.label}
        {cachedMode && !data && (
          <span className="ml-1 text-[8px] opacity-60">CACHED</span>
        )}
      </span>
    );
  }

  return (
    <div className={`group relative inline-block ${className}`}>
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${config.colorClass}`}>
        <Icon className="w-3 h-3" />
        {config.label}
        {cachedMode && !data && (
          <span className="ml-1 text-[8px] opacity-60">CACHED</span>
        )}
        {!isOnline && (
          <span className="ml-1 text-[8px] opacity-60">OFFLINE</span>
        )}
        {isOnline && networkSpeed === 'slow' && (
          <span className="ml-1 text-[8px] opacity-60">SLOW</span>
        )}
      </span>
      
      <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
        <div className="font-semibold">{config.tooltip}</div>
        
        {/* Additional context in tooltip */}
        <div className="text-gray-400 text-[10px] mt-1 space-y-1">
          {cachedMode && !data && (
            <div>Using cached mode data</div>
          )}
          
          {!isOnline && (
            <div>Currently offline - cached mode</div>
          )}
          
          {isOnline && networkSpeed === 'slow' && (
            <div>Slow connection detected</div>
          )}
          
          {retryCount > 0 && (
            <div>Retry attempts: {retryCount}/{maxRetries}</div>
          )}
        </div>
        
        <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-gray-900"></div>
      </div>
    </div>
  );
}

EnhancedKalshiModeBadge.displayName = 'EnhancedKalshiModeBadge';
export default React.memo(EnhancedKalshiModeBadge);
