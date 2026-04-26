/**
 * KalshiModeBadge — Shows PAPER vs LIVE mode badge with tooltip.
 *
 * Fetches the current trade mode from the API and displays a clear
 * colored badge. Used across all Kalshi views so the operator always
 * knows which execution context is active.
 * 
 * Enhanced mode adds:
 * - Network status monitoring
 * - Retry logic for mode fetch failures
 * - Fallback to cached mode data
 * - Connection status indicators
 */

import React, { useState, useCallback, useEffect } from 'react';
import { useKalshiMode } from '../context/KalshiModeContext';
import { Shield, Zap, AlertTriangle, RefreshCw } from '../ui/icons';
import { MODE_COLORS, resolveModeKey } from '../config/modeColors';
import { useNetworkStatus } from '../hooks/useNetworkStatusProvider';

interface KalshiModeBadgeProps {
  enhanced?: boolean;
  className?: string;
  fallbackMode?: string;
}

const MODE_CONFIG = {
  live: { label: 'LIVE', tooltip: 'Live trading mode — real orders on Kalshi with real money' },
  paper: { label: 'PAPER', tooltip: 'Paper trading mode — orders are simulated, no real money at risk' },
  shadow: { label: 'SHADOW', tooltip: 'Shadow mode — signals generated but not executed' },
  unknown: { label: 'UNKNOWN', tooltip: 'Unknown trading mode' },
};

function KalshiModeBadge({ enhanced = false, className = '', fallbackMode = 'paper' }: KalshiModeBadgeProps) {
  const { data, error, isLoading, refetch } = useKalshiMode();
  const { isOnline } = useNetworkStatus();
  const [retryCount, setRetryCount] = useState(0);
  const [cachedMode, setCachedMode] = useState<string | null>(null);
  const maxRetries = 3;

  // Cache successful mode data
  useEffect(() => {
    if (data?.mode && !error) {
      setCachedMode(data.mode);
      setRetryCount(0);
    }
  }, [data, error]);

  // Get current mode
  const currentMode = data?.mode || cachedMode || fallbackMode;
  const modeKey = resolveModeKey(currentMode, data?.is_live ?? false);
  const colors = MODE_COLORS[modeKey];
  const config = MODE_CONFIG[modeKey as keyof typeof MODE_CONFIG] || MODE_CONFIG.unknown;
  const Icon = data?.is_live ? Zap : Shield;

  // Retry handler
  const handleRetry = useCallback(async () => {
    if (retryCount >= maxRetries) return;
    setRetryCount(prev => prev + 1);
    try {
      await refetch();
    } catch (retryError) {
      // Error handled by hook
    }
  }, [retryCount, maxRetries, refetch]);

  // Loading state
  if (isLoading && !data) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-700/50 text-slate-500 border-slate-600/30">
        <Shield className="w-3 h-3" />
        …
      </span>
    );
  }

  // Error state in enhanced mode
  if (enhanced && error && retryCount >= maxRetries) {
    return (
      <div className={`inline-flex items-center gap-2 ${className}`}>
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-red-500/20 text-red-400 border-red-500/30">
          <AlertTriangle className="w-3 h-3" />
          ERROR
        </span>
      </div>
    );
  }

  // Base badge
  const badge = (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${colors.badge} ${className}`}
      title={config.tooltip}
    >
      {data?.is_live && <span className={`w-1.5 h-1.5 rounded-full ${colors.dot} animate-pulse`} />}
      <Icon className="w-3 h-3" />
      {config.label}
      {enhanced && cachedMode && !data && (
        <span className="ml-1 text-[8px] opacity-60">CACHED</span>
      )}
      {enhanced && !isOnline && (
        <span className="ml-1 text-[8px] opacity-60">OFFLINE</span>
      )}
    </span>
  );

  // Enhanced mode with retry
  if (enhanced && error && retryCount < maxRetries) {
    return (
      <div className="inline-flex items-center gap-2">
        {badge}
        <button
          onClick={handleRetry}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-blue-500/20 text-blue-400 border-blue-500/30 hover:bg-blue-500/30"
        >
          <RefreshCw className="w-3 h-3" />
          RETRY
        </button>
      </div>
    );
  }

  return badge;
}

KalshiModeBadge.displayName = 'KalshiModeBadge';
export default React.memo(KalshiModeBadge);
