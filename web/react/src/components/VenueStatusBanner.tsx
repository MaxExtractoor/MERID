/**
 * VenueStatusBanner Component
 * 
 * Displays venue health and crypto availability status.
 * Connects to crypto venue status API for real-time monitoring.
 */

import React from 'react';
import { AlertCircle, CheckCircle, XCircle, RefreshCw, Wifi, WifiOff } from '../ui/icons';
import { useCryptoVenueStatus } from '../hooks/useCryptoVenueStatus';

interface VenueStatusBannerProps {
  className?: string;
  showRefresh?: boolean;
  compact?: boolean;
}

const VenueStatusBanner: React.FC<VenueStatusBannerProps> = ({
  className = '',
  showRefresh = true,
  compact = false
}) => {
  const { status, loading, error, refresh, isHealthy, hasCryptoMarkets } = useCryptoVenueStatus();

  const getStatusIcon = () => {
    if (loading) {
      return <RefreshCw className="w-4 h-4 animate-spin" />;
    }

    switch (status.status) {
      case 'ok':
        return <CheckCircle className="w-4 h-4 text-green-400" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-400" />;
      case 'no_markets_visible':
        return <AlertCircle className="w-4 h-4 text-yellow-400" />;
      case 'degraded':
        return <AlertCircle className="w-4 h-4 text-orange-400" />;
      default:
        return <WifiOff className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = () => {
    if (loading) return 'bg-gray-800 border-gray-700';
    
    switch (status.status) {
      case 'ok':
        return isHealthy ? 'bg-green-900/30 border-green-700/50' : 'bg-yellow-900/30 border-yellow-700/50';
      case 'error':
        return 'bg-red-900/30 border-red-700/50';
      case 'no_markets_visible':
        return 'bg-yellow-900/30 border-yellow-700/50';
      case 'degraded':
        return 'bg-orange-900/30 border-orange-700/50';
      default:
        return 'bg-gray-800 border-gray-700';
    }
  };

  const getStatusText = () => {
    if (loading) return 'Checking venue status...';
    if (error) return 'Venue status unavailable';
    
    switch (status.status) {
      case 'ok':
        if (isHealthy) {
          return `Kalshi venue healthy • ${status.crypto_markets} crypto markets`;
        } else {
          return 'Kalshi venue connected • No crypto markets available';
        }
      case 'error':
        return status.error_message || 'Kalshi venue connection error';
      case 'no_markets_visible':
        return 'Kalshi venue connected • No markets visible';
      case 'degraded':
        return 'Kalshi venue degraded • Limited functionality';
      default:
        return 'Kalshi venue status unknown';
    }
  };

  const getConnectivityIcon = (endpoint: any) => {
    return endpoint.status === 'ok' ? (
      <Wifi className="w-3 h-3 text-green-400" />
    ) : (
      <WifiOff className="w-3 h-3 text-red-400" />
    );
  };

  if (compact) {
    return (
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${getStatusColor()} ${className}`}>
        {getStatusIcon()}
        <span className="text-xs text-white truncate">
          {getStatusText()}
        </span>
        {showRefresh && (
          <button
            onClick={refresh}
            disabled={loading}
            className="p-0.5 rounded hover:bg-white/10 transition-colors"
            title="Refresh venue status"
          >
            <RefreshCw className={`w-3 h-3 text-white/70 ${loading ? 'animate-spin' : ''}`} />
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`rounded-lg border ${getStatusColor()} ${className}`}>
      <div className="flex items-center justify-between p-3">
        <div className="flex items-center gap-3">
          {getStatusIcon()}
          <div>
            <p className="text-sm font-medium text-white">
              Kalshi Venue Status
            </p>
            <p className="text-xs text-gray-300">
              {getStatusText()}
            </p>
          </div>
        </div>
        
        {showRefresh && (
          <button
            onClick={refresh}
            disabled={loading}
            className="p-2 rounded-lg hover:bg-white/10 transition-colors"
            title="Refresh venue status"
          >
            <RefreshCw className={`w-4 h-4 text-white/70 ${loading ? 'animate-spin' : ''}`} />
          </button>
        )}
      </div>

      {/* Detailed connectivity info */}
      {!compact && (
        <div className="border-t border-gray-700/50 p-3 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Connectivity</span>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1">
                {getConnectivityIcon(status.connectivity.primary_endpoint)}
                <span className="text-gray-300">Primary</span>
              </div>
              <div className="flex items-center gap-1">
                {getConnectivityIcon(status.connectivity.fallback_endpoint)}
                <span className="text-gray-300">Fallback</span>
              </div>
            </div>
          </div>

          {/* Market counts */}
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Markets</span>
            <div className="flex items-center gap-4">
              <span className="text-gray-300">
                Total: {status.total_markets}
              </span>
              <span className={`font-medium ${hasCryptoMarkets ? 'text-green-400' : 'text-gray-400'}`}>
                Crypto: {status.crypto_markets}
              </span>
            </div>
          </div>

          {/* Capabilities */}
          {status.capabilities && status.capabilities.length > 0 && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-400">Capabilities</span>
              <div className="flex gap-1">
                {status.capabilities.map((cap, index) => (
                  <span
                    key={index}
                    className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Last checked */}
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">Last checked</span>
            <span className="text-gray-300">
              {status.last_checked ? new Date(status.last_checked).toLocaleString() : 'Never'}
            </span>
          </div>

          {/* Error details */}
          {error && (
            <div className="flex items-start gap-2 text-xs">
              <XCircle className="w-3 h-3 text-red-400 mt-0.5" />
              <div>
                <span className="text-red-400">Error:</span>
                <span className="text-red-300 ml-1">{error}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default VenueStatusBanner;
