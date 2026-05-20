/**
 * KalshiActionArea — Minimal Action Area (Phase 6)
 *
 * Primary controls only for Kalshi operations.
 * 
 * Controls:
 * - Grid start/stop
 * - Kill switch toggle
 * - Mode toggle (paper/live)
 */

import { useState } from 'react';
import {
  Play,
  Square,
  Shield,
  ShieldAlert,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { getAuthHeaders } from '../services/auth';
import KalshiModeBadge from './KalshiModeBadge';
import { ConfirmModal } from './ConfirmModal';

// ── Main Component ───────────────────────────────────────────────────────────────

export default function KalshiActionArea() {
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    variant?: 'primary' | 'danger' | 'warning';
  }>({ isOpen: false, title: '', message: '', onConfirm: () => undefined });

  // Fetch grid status
  const { data: gridStatus, refetch: refetchGrid } = useApiData<{
    running: boolean;
    agent_count: number;
  }>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  // Fetch mode
  const { data: modeData, refetch: refetchMode } = useApiData<{
    mode: 'paper' | 'live';
    is_live_enabled: boolean;
  }>(
    API_ENDPOINTS.KALSHI_GRID_MODE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  // Fetch kill switch status
  const { data: killSwitchData, refetch: refetchKillSwitch } = useApiData<{
    active: boolean;
    can_trade: boolean;
    kill_reason: string | null;
  }>(
    API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const gridRunning = gridStatus?.running ?? false;
  const currentMode = modeData?.mode ?? 'paper';
  const killSwitchActive = killSwitchData?.active ?? false;
  const canTrade = killSwitchData?.can_trade ?? !killSwitchActive;

  // Grid controls
  const handleStartGrid = async () => {
    setBusyAction('start-grid');
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_START}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (response.ok) {
        refetchGrid();
      }
    } catch (error) {
      console.error('Failed to start grid:', error);
    } finally {
      setBusyAction(null);
    }
  };

  const handleStopGrid = () => {
    setConfirmModal({
      isOpen: true,
      title: 'Stop Grid',
      message: 'Are you sure you want to stop the agent grid? This will halt all trading activity.',
      onConfirm: async () => {
        setBusyAction('stop-grid');
        try {
          const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_STOP}`, {
            method: 'POST',
            headers: getAuthHeaders(),
          });
          if (response.ok) {
            refetchGrid();
          }
        } catch (error) {
          console.error('Failed to stop grid:', error);
        } finally {
          setBusyAction(null);
        }
        setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: () => undefined });
      },
      variant: 'warning',
    });
  };

  // Kill switch controls
  const handleToggleKillSwitch = () => {
    const action = killSwitchActive ? 'disable' : 'enable';
    setConfirmModal({
      isOpen: true,
      title: `${action === 'enable' ? 'Activate' : 'Deactivate'} Kill Switch`,
      message: killSwitchActive
        ? 'Are you sure you want to deactivate the kill switch? Trading will resume.'
        : 'Are you sure you want to activate the kill switch? This will halt all trading.',
      onConfirm: async () => {
        setBusyAction('kill-switch');
        try {
          const endpoint = killSwitchActive
            ? API_ENDPOINTS.RISK_KILL_SWITCH('disable')
            : API_ENDPOINTS.RISK_KILL_SWITCH('enable');
          const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: getAuthHeaders(),
          });
          if (response.ok) {
            refetchKillSwitch();
            refetchGrid();
          }
        } catch (error) {
          console.error('Failed to toggle kill switch:', error);
        } finally {
          setBusyAction(null);
        }
        setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: () => undefined });
      },
      variant: killSwitchActive ? 'primary' : 'danger',
    });
  };

  // Mode toggle
  const handleToggleMode = () => {
    const newMode = currentMode === 'paper' ? 'live' : 'paper';
    setConfirmModal({
      isOpen: true,
      title: `Switch to ${newMode.toUpperCase()} Mode`,
      message: currentMode === 'paper'
        ? 'Are you sure you want to switch to LIVE mode? Real money will be at risk.'
        : 'Are you sure you want to switch to PAPER mode? Trading will use simulated funds.',
      onConfirm: async () => {
        setBusyAction('mode-toggle');
        try {
          const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_MODE}`, {
            method: 'POST',
            headers: {
              ...getAuthHeaders(),
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ mode: newMode }),
          });
          if (response.ok) {
            refetchMode();
          }
        } catch (error) {
          console.error('Failed to toggle mode:', error);
        } finally {
          setBusyAction(null);
        }
        setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: () => undefined });
      },
      variant: currentMode === 'paper' ? 'danger' : 'primary',
    });
  };

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Play className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-slate-200">Controls</span>
        </div>
        <KalshiModeBadge />
      </div>

      {/* Grid Control */}
      <div className="flex items-center gap-3">
        {gridRunning ? (
          <button
            onClick={handleStopGrid}
            disabled={busyAction !== null}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors"
          >
            {busyAction === 'stop-grid' ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Square className="w-4 h-4" />
            )}
            <span className="text-sm font-medium">Stop Grid</span>
          </button>
        ) : (
          <button
            onClick={handleStartGrid}
            disabled={busyAction !== null || !canTrade}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors"
          >
            {busyAction === 'start-grid' ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            <span className="text-sm font-medium">Start Grid</span>
          </button>
        )}
      </div>

      {/* Kill Switch */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleToggleKillSwitch}
          disabled={busyAction !== null}
          className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            killSwitchActive
              ? 'bg-red-600 hover:bg-red-700 text-white'
              : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
          } disabled:bg-slate-700 disabled:text-slate-500`}
        >
          {busyAction === 'kill-switch' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : killSwitchActive ? (
            <ShieldAlert className="w-4 h-4" />
          ) : (
            <Shield className="w-4 h-4" />
          )}
          <span className="text-sm font-medium">
            {killSwitchActive ? 'Deactivate Kill Switch' : 'Activate Kill Switch'}
          </span>
        </button>
      </div>

      {/* Mode Toggle */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleToggleMode}
          disabled={busyAction !== null || !modeData?.is_live_enabled}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-500 text-slate-300 rounded-lg transition-colors"
        >
          {busyAction === 'mode-toggle' ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : currentMode === 'paper' ? (
            <ToggleRight className="w-4 h-4" />
          ) : (
            <ToggleLeft className="w-4 h-4" />
          )}
          <span className="text-sm font-medium">
            Switch to {currentMode === 'paper' ? 'LIVE' : 'PAPER'}
          </span>
        </button>
      </div>

      {/* Status Message */}
      {killSwitchActive && killSwitchData?.kill_reason && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-3">
          <div className="flex items-start gap-2">
            <ShieldAlert className="w-4 h-4 text-red-400 mt-0.5" />
            <div>
              <p className="text-xs font-medium text-red-400">Kill Switch Active</p>
              <p className="text-xs text-red-300 mt-1">{killSwitchData.kill_reason}</p>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Modal */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal({ isOpen: false, title: '', message: '', onConfirm: () => undefined })}
        confirmVariant={confirmModal.variant}
      />
    </div>
  );
}
