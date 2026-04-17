/**
 * KalshiReconciliationBadge - Shows reconciliation status between
 * local state and server truth for Kalshi positions/orders
 */

import { useState, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import ErrorBar, { ClassifiedError } from '../components/ErrorBar';
import { classifyError } from '../utils/errorClassification';

interface ReconciliationStatus {
  status: 'ok' | 'drift' | 'unknown';
  detail: string;
  last_checked: string;
  position_count?: number;
  order_count?: number;
  drift_details?: {
    missing_positions: number;
    extra_positions: number;
    missing_orders: number;
    extra_orders: number;
  };
}

export default function KalshiReconciliationBadge({ 
  compact = false,
  onClick 
}: { 
  compact?: boolean;
  onClick?: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<ClassifiedError | null>(null);

  const { data: reconciliation, refetch } = useApiData<ReconciliationStatus>(
    API_ENDPOINTS.RECONCILIATION_STATUS,
    { pollingInterval: 60000 } // Check every minute
  );

  const refreshStatus = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      await refetch();
    } catch (err) {
      setError(classifyError(err as Error));
    } finally {
      setRefreshing(false);
    }
  }, [refetch]);

  if (!reconciliation) {
    return (
      <div className="flex items-center gap-2 px-2 py-1 rounded-lg bg-gray-500/20 text-gray-400 text-xs">
        <Icon name="refresh" size={12} className="w-3 h-3 animate-spin" />
        Checking...
      </div>
    );
  }

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'ok':
        return {
          icon: 'check' as const,
          color: 'text-green-400',
          bg: 'bg-green-500/20',
          border: 'border-green-500/30',
          label: 'Reconciled'
        };
      case 'drift':
        return {
          icon: 'alert' as const,
          color: 'text-amber-400',
          bg: 'bg-amber-500/20',
          border: 'border-amber-500/30',
          label: 'Drift'
        };
      default:
        return {
          icon: 'search' as const,
          color: 'text-gray-400',
          bg: 'bg-gray-500/20',
          border: 'border-gray-500/30',
          label: 'Unknown'
        };
    }
  };

  const statusValue = (reconciliation.status ?? 'unknown') as string;
  const detailValue = reconciliation.detail ?? 'No reconciliation detail available';
  const lastChecked = reconciliation.last_checked ? new Date(reconciliation.last_checked) : null;
  const config = getStatusConfig(statusValue);

  if (compact) {
    return (
      <button
        type="button"
        onClick={() => {
          setShowDetails(!showDetails);
          onClick?.();
        }}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-medium transition-colors ${config.bg} ${config.color} ${config.border} hover:opacity-80`}
        title={`Reconciliation: ${statusValue.toUpperCase()} - ${detailValue}`}
      >
        <Icon name={config.icon} size={12} className="w-3 h-3" />
        {config.label}
        {reconciliation.status === 'drift' && (
          <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
        )}
      </button>
    );
  }

  return (
    <div className="space-y-2">
      {/* Main Badge */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setShowDetails(!showDetails)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${config.bg} ${config.color} ${config.border} hover:opacity-80`}
        >
          <Icon name={config.icon} size={14} className="w-3.5 h-3.5" />
          Reconciliation: {config.label}
          {reconciliation.status === 'drift' && (
            <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
          )}
        </button>

        <button
          type="button"
          onClick={refreshStatus}
          disabled={refreshing}
          className="p-1 rounded hover:bg-slate-700 transition-colors text-gray-400"
          title="Refresh reconciliation status"
        >
          <Icon name="refresh" size={12} className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <ErrorBar
          label="Reconciliation Check"
          error={error}
          onRetry={error.retryable ? refreshStatus : undefined}
        />
      )}

      {/* Details Panel */}
      {showDetails && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-white">Reconciliation Details</h4>
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
              <span className="text-gray-400">Status:</span>
              <span className={`font-medium ${config.color}`}>{statusValue.toUpperCase()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Last Checked:</span>
              <span className="text-white">
                {lastChecked ? lastChecked.toLocaleString() : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Detail:</span>
              <span className="text-white">{detailValue}</span>
            </div>

            {reconciliation.position_count !== undefined && (
              <div className="flex justify-between">
                <span className="text-gray-400">Positions:</span>
                <span className="text-white">{reconciliation.position_count}</span>
              </div>
            )}

            {reconciliation.order_count !== undefined && (
              <div className="flex justify-between">
                <span className="text-gray-400">Orders:</span>
                <span className="text-white">{reconciliation.order_count}</span>
              </div>
            )}

            {/* Drift Details */}
            {reconciliation.status === 'drift' && reconciliation.drift_details && (
              <div className="mt-3 pt-3 border-t border-slate-700 space-y-2">
                <h5 className="text-xs font-semibold text-amber-400">Drift Analysis</h5>
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Missing Positions:</span>
                    <span className="text-red-400">{reconciliation.drift_details.missing_positions}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Extra Positions:</span>
                    <span className="text-amber-400">{reconciliation.drift_details.extra_positions}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Missing Orders:</span>
                    <span className="text-red-400">{reconciliation.drift_details.missing_orders}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Extra Orders:</span>
                    <span className="text-amber-400">{reconciliation.drift_details.extra_orders}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          {reconciliation.status === 'drift' && (
            <div className="pt-3 border-t border-slate-700 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  // Navigate to logs for detailed investigation
                  window.location.hash = '#/kalshi-logs';
                }}
                className="flex items-center gap-1 px-3 py-1 bg-blue-500/20 text-blue-400 rounded text-xs hover:bg-blue-500/30 transition-colors"
              >
                <Icon name="search" size={12} className="w-3 h-3" />
                View Logs
              </button>
              <button
                type="button"
                onClick={refreshStatus}
                disabled={refreshing}
                className="flex items-center gap-1 px-3 py-1 bg-green-500/20 text-green-400 rounded text-xs hover:bg-green-500/30 transition-colors disabled:opacity-50"
              >
                <Icon name="refresh" size={12} className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
                Re-check
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
