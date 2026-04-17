/**
 * KalshiErrorPill - Shows the most recent Kalshi error classification
 * in the OperatorDashboard with contextual actions
 */

import { useState, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { classifyError } from '../utils/errorClassification';

interface KalshiErrorLog {
  timestamp: string;
  error: string;
  class: string;
  endpoint?: string;
}

export default function KalshiErrorPill() {
  const [showDetails, setShowDetails] = useState(false);

  // Mock recent Kalshi errors - in production this would come from an endpoint
  const { data: errorLogs } = useApiData<KalshiErrorLog[]>(
    '/api/v1/kalshi/errors/recent',
    { pollingInterval: 30000 } // Check every 30 seconds
  );

  const latestError = errorLogs?.[0];

  if (!latestError) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-xs">
        <Icon name="check" size={12} className="w-3 h-3" />
        <span>Kalshi Healthy</span>
      </div>
    );
  }

  const classifiedError = classifyError(new Error(latestError.error));
  const isErrorRecent = (Date.now() - new Date(latestError.timestamp).getTime()) < 60000; // Within last minute

  const getErrorConfig = (errorClass: string) => {
    switch (errorClass) {
      case 'auth':
        return {
          icon: 'shield' as const,
          color: 'text-red-400',
          bg: 'bg-red-500/20',
          border: 'border-red-500/30',
          action: 'Check credentials',
          href: '#/settings?tab=kalshi'
        };
      case 'rate_limit':
        return {
          icon: 'alert' as const,
          color: 'text-amber-400',
          bg: 'bg-amber-500/20',
          border: 'border-amber-500/30',
          action: 'Reduce polling',
          hint: 'Try wider intervals or fewer agents'
        };
      case 'network':
        return {
          icon: 'wifi' as const,
          color: 'text-orange-400',
          bg: 'bg-orange-500/20',
          border: 'border-orange-500/30',
          action: 'Check connection',
          hint: 'Verify network and API endpoints'
        };
      case 'system':
        return {
          icon: 'alert' as const,
          color: 'text-purple-400',
          bg: 'bg-purple-500/20',
          border: 'border-purple-500/30',
          action: 'System issue',
          hint: 'Contact support if persistent'
        };
      // P0-002: Asset-ticker mismatch (cross-asset mispairing)
      case 'asset_mismatch':
        return {
          icon: 'target' as const,
          color: 'text-red-500',
          bg: 'bg-red-500/30',
          border: 'border-red-500/50',
          action: 'Fix spot-market wiring',
          hint: 'Asset implied by ticker does not match expected asset. Check kalshi_strike_selector configuration.',
          metric: 'merid_pm_strike_asset_mismatch_total'
        };
      // P0-001: Spot staleness violation
      case 'staleness':
        return {
          icon: 'clock' as const,
          color: 'text-orange-400',
          bg: 'bg-orange-500/20',
          border: 'border-orange-500/40',
          action: 'Check price feed',
          hint: 'Spot price is stale (age > max_spot_age_seconds). Check LivePriceFeed or increase MERID_PM_MAX_SPOT_AGE_SECONDS.',
          metric: 'merid_pm_spot_staleness_violations_total'
        };
      default:
        return {
          icon: 'search' as const,
          color: 'text-gray-400',
          bg: 'bg-gray-500/20',
          border: 'border-gray-500/30',
          action: 'Unknown error',
          hint: 'Check logs for details'
        };
    }
  };

  const config = getErrorConfig(classifiedError.class);

  const handleAction = useCallback(() => {
    if (config.href) {
      window.location.hash = config.href;
    }
  }, [config.href]);

  return (
    <div className="space-y-2">
      {/* Compact Error Pill */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowDetails(!showDetails)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${config.bg} ${config.color} ${config.border} hover:opacity-80 ${isErrorRecent ? 'animate-pulse' : ''}`}
        >
          <Icon name={config.icon} size={12} className="w-3 h-3" />
          <span>Kalshi: {classifiedError.class}</span>
          {isErrorRecent && <span className="w-2 h-2 bg-current rounded-full" />}
        </button>

        {config.href && (
          <button
            type="button"
            onClick={handleAction}
            className="text-xs text-blue-400 hover:text-blue-300 underline"
            title={config.action}
          >
            {config.action}
          </button>
        )}
      </div>

      {/* Details Panel */}
      {showDetails && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-white">Kalshi Error Details</h4>
            <button
              type="button"
              onClick={() => setShowDetails(false)}
              className="text-gray-400 hover:text-white"
            >
              <Icon name="close" size={14} className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-400">Type:</span>
              <span className={`font-medium ${config.color}`}>{classifiedError.class.toUpperCase()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Time:</span>
              <span className="text-white">
                {new Date(latestError.timestamp).toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Endpoint:</span>
              <span className="text-white font-mono">{latestError.endpoint || 'Unknown'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Message:</span>
              <span className="text-white max-w-xs truncate">{latestError.error}</span>
            </div>
          </div>

          {/* Action Hints */}
          <div className="pt-3 border-t border-slate-700">
            <div className="flex items-center gap-2 text-xs">
              <Icon name="info" size={12} className="w-3 h-3 text-blue-400" />
              <span className="text-blue-400">{config.hint}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            {config.href && (
              <button
                type="button"
                onClick={handleAction}
                className="flex items-center gap-1 px-3 py-1 bg-blue-500/20 text-blue-400 rounded text-xs hover:bg-blue-500/30 transition-colors"
              >
                <Icon name="settings" size={12} className="w-3 h-3" />
                {config.action}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                window.location.hash = '#/kalshi-logs';
              }}
              className="flex items-center gap-1 px-3 py-1 bg-slate-700 text-gray-300 rounded text-xs hover:bg-slate-600 transition-colors"
            >
              <Icon name="search" size={12} className="w-3 h-3" />
              View Logs
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
