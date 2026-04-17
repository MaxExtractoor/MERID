/**
 * KalshiCancelAllButton - Emergency cancel-all orders functionality
 * with confirmation modal and error classification
 */

import { useState, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY } from '../config/constants';
import { ConfirmModal } from './ConfirmModal';
import ErrorBar, { ClassifiedError } from './ErrorBar';
import { classifyError } from '../utils/errorClassification';

interface KalshiCancelAllButtonProps {
  compact?: boolean;
  onSuccess?: () => void;
  className?: string;
}

export default function KalshiCancelAllButton({ 
  compact = false,
  onSuccess,
  className = ''
}: KalshiCancelAllButtonProps) {
  const [cancelling, setCancelling] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<ClassifiedError | null>(null);
  const [success, setSuccess] = useState(false);

  const cancelAllOrders = useCallback(async () => {
    setCancelling(true);
    setError(null);
    setSuccess(false);

    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS_BATCH_CANCEL}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const error = new Error(errorData.message || `HTTP ${response.status}`);
        (error as any).status = response.status;
        (error as any).code = errorData.code;
        throw error;
      }

      await response.json(); // consume response body
      setSuccess(true);
      onSuccess?.();

      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(false), 3000);

    } catch (err) {
      const classified = classifyError(err as Error);
      setError(classified);
    } finally {
      setCancelling(false);
      setShowConfirm(false);
    }
  }, [onSuccess]);

  if (compact) {
    return (
      <>
        <button
          type="button"
          onClick={() => setShowConfirm(true)}
          disabled={cancelling}
          className={`flex items-center gap-2 px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/30 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${className}`}
          title="Cancel all Kalshi orders"
        >
          {cancelling ? (
            <>
              <Icon name="refresh" size={12} className="w-3 h-3 animate-spin" />
              Cancelling...
            </>
          ) : (
            <>
              <Icon name="close" size={12} className="w-3 h-3" />
              Cancel All
            </>
          )}
        </button>

        <ConfirmModal
          isOpen={showConfirm}
          title="Cancel All Kalshi Orders"
          message="⚠️ This will immediately cancel ALL open Kalshi orders across all markets. This action cannot be undone."
          confirmText="Cancel All Orders"
          cancelText="Never Mind"
          confirmVariant="danger"
          onConfirm={cancelAllOrders}
          onCancel={() => setShowConfirm(false)}
        />

        {error && (
          <ErrorBar
            label="Cancel All Orders"
            error={error}
            onRetry={error.retryable ? cancelAllOrders : undefined}
          />
        )}

        {success && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm">
            <Icon name="check" size={16} className="w-4 h-4" />
            <span>All orders cancelled successfully</span>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => setShowConfirm(true)}
        disabled={cancelling}
        className={`flex items-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 disabled:bg-slate-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors ${className}`}
      >
        {cancelling ? (
          <>
            <Icon name="refresh" size={14} className="w-3.5 h-3.5 animate-spin" />
            Cancelling All Orders...
          </>
        ) : (
          <>
            <Icon name="close" size={14} className="w-3.5 h-3.5" />
            Cancel All Orders
          </>
        )}
      </button>

      <ConfirmModal
        isOpen={showConfirm}
        title="Cancel All Kalshi Orders"
        message="⚠️ This will immediately cancel ALL open Kalshi orders across all markets. This action cannot be undone."
        confirmText="Cancel All Orders"
        cancelText="Never Mind"
        confirmVariant="danger"
        onConfirm={cancelAllOrders}
        onCancel={() => setShowConfirm(false)}
      />

      {error && (
        <ErrorBar
          label="Cancel All Orders"
          error={error}
          onRetry={error.retryable ? cancelAllOrders : undefined}
        />
      )}

      {success && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-sm">
          <Icon name="check" size={16} className="w-4 h-4" />
          <span>All orders cancelled successfully</span>
        </div>
      )}

      <div className="text-xs text-gray-500">
        <p>• Cancels all open orders across all Kalshi markets</p>
        <p>• Works in both paper and live environments</p>
        <p>• Cannot be undone - use with caution</p>
      </div>
    </div>
  );
}
