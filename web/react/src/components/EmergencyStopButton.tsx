/**
 * EmergencyStopButton — Single canonical emergency stop control.
 *
 * Replaces all scattered window.confirm() / window.alert() kill-switch
 * call sites in KillSwitchView, KalshiGridView, and OperatorDashboard.
 *
 * Always posts to OPERATOR_EMERGENCY_STOP (the canonical endpoint).
 * Uses ConfirmModal for a styled, testable, non-blocking confirmation.
 */

import { useState, useCallback, forwardRef } from 'react';
import { ShieldAlert, Loader2 } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY } from '../config/constants';

interface EmergencyStopButtonProps {
  /** Called after a successful stop POST so callers can refetch state. */
  onSuccess?: () => void;
  /** Optional additional CSS classes (sizing, positioning). */
  className?: string;
  /** Render a compact icon-only variant for tight control bars. */
  compact?: boolean;
  /** Disable the button (e.g. kill switch already active). */
  disabled?: boolean;
}

const EmergencyStopButton = forwardRef<HTMLButtonElement, EmergencyStopButtonProps>(function EmergencyStopButton({
  onSuccess,
  className = '',
  compact = false,
  disabled = false,
}, ref) {
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = useCallback(async () => {
    setModalOpen(false);
    setSaving(true);
    setError(null);
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_EMERGENCY_STOP}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
        body: JSON.stringify({ reason: 'Manual operator emergency stop' }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null) as { message?: string } | null;
        throw new Error(body?.message ?? `HTTP ${res.status}: ${res.statusText}`);
      }
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Emergency stop failed');
    } finally {
      setSaving(false);
    }
  }, [onSuccess]);

  const baseClass = compact
    ? 'flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 disabled:bg-red-900 disabled:opacity-50 text-white text-xs font-bold transition-colors'
    : 'flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 disabled:bg-red-900 disabled:opacity-50 text-white font-semibold transition-colors';

  return (
    <>
      <button
        ref={ref}
        type="button"
        onClick={() => setModalOpen(true)}
        disabled={disabled || saving}
        className={`${baseClass} ${className}`}
        title="Emergency Stop — immediately halts all trading (Ctrl+Shift+K)"
        aria-label="Emergency Stop"
      >
        {saving
          ? <Loader2 className="w-4 h-4 animate-spin" />
          : <ShieldAlert className="w-4 h-4" />
        }
        {compact ? 'KILL' : 'Emergency Stop'}
        {!compact && (
          <kbd className="ml-1 px-1 py-0.5 text-[10px] font-medium bg-red-800 border border-red-600 rounded opacity-70">
            Ctrl+Shift+K
          </kbd>
        )}
      </button>

      {error && (
        <div className="mt-1 px-3 py-1.5 rounded bg-red-900/50 border border-red-700 text-red-300 text-xs flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} className="text-red-400 hover:text-red-200 shrink-0">✕</button>
        </div>
      )}

      <ConfirmModal
        isOpen={modalOpen}
        title="⚠ Emergency Stop"
        message="This will immediately halt ALL trading activity and cancel pending orders. Use only in an emergency."
        confirmText="Stop All Trading"
        cancelText="Cancel"
        confirmVariant="danger"
        onConfirm={handleConfirm}
        onCancel={() => setModalOpen(false)}
      />
    </>
  );
});

EmergencyStopButton.displayName = 'EmergencyStopButton';
export default EmergencyStopButton;
