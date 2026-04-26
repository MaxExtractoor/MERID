import { useState, useCallback } from 'react';
import {
  Pause, Play, PowerOff, RefreshCw,
  ChevronDown, AlertOctagon, Settings, ShieldOff
} from '../ui/icons';
import { useExecutionGate } from '../hooks/useExecutionGate';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import type { OperatorSummary } from '../hooks/useOperatorSummary';

interface OperatorControlPlaneProps {
  summary: OperatorSummary | null;
  onPauseSwarm: () => Promise<boolean>;
  onResumeSwarm: () => Promise<boolean>;
  onSwitchMode: (mode: string, reason: string) => Promise<boolean>;
  onRefresh: () => Promise<void>;
}

const MODES = ['paper', 'live', 'hybrid', 'autonomous'] as const;

export function OperatorControlPlane({
  summary,
  onPauseSwarm,
  onResumeSwarm,
  onSwitchMode,
  onRefresh,
}: OperatorControlPlaneProps) {
  const [confirmAction, setConfirmAction] = useState<string | null>(null);
  const [modeDropdownOpen, setModeDropdownOpen] = useState(false);
  const [modeReason, setModeReason] = useState('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const isPaused = summary?.swarm?.paused ?? false;
  const { blocked: executionBlocked, blockSummary } = useExecutionGate();

  const handleAction = useCallback(async (action: string, fn: () => Promise<unknown>) => {
    setActionLoading(action);
    try {
      await fn();
    } finally {
      setActionLoading(null);
      setConfirmAction(null);
    }
  }, []);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const postOperatorAction = useCallback(async (endpoint: string) => {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      method: 'POST',
      headers: authHeaders(),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
  }, [authHeaders]);

  const handleShutdown = useCallback(async () => {
    try {
      await postOperatorAction(API_ENDPOINTS.DEV_SWARM_SHUTDOWN);
      setActionStatus({ type: 'success', message: 'Shutdown initiated successfully' });
      setTimeout(() => setActionStatus(null), DEFAULTS.POLLING_INTERVALS.STANDARD);
      await onRefresh();
    } catch {
      setActionStatus({ type: 'error', message: 'Shutdown failed. Please try again.' });
    }
  }, [onRefresh, postOperatorAction]);

  const handleSystemStop = useCallback(async () => {
    try {
      await postOperatorAction(API_ENDPOINTS.SYSTEM_STOP);
      setActionStatus({ type: 'success', message: 'System stop initiated successfully' });
      setTimeout(() => setActionStatus(null), DEFAULTS.POLLING_INTERVALS.STANDARD);
      await onRefresh();
    } catch {
      setActionStatus({ type: 'error', message: 'System stop failed. Please try again.' });
    }
  }, [onRefresh, postOperatorAction]);

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Control Plane</h3>

      {actionStatus && (
        <div className={`rounded-lg px-4 py-3 text-sm ${
          actionStatus.type === 'success'
            ? 'bg-emerald-900/20 border border-emerald-500/30 text-emerald-300'
            : 'bg-red-900/20 border border-red-500/30 text-red-300'
        }`}>
          {actionStatus.message}
        </div>
      )}

      {/* Execution blocked warning */}
      {executionBlocked && (
        <div className="flex items-center gap-2 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2 text-xs text-red-300">
          <ShieldOff className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
          <span>Execution blocked: {blockSummary}</span>
        </div>
      )}

      {/* Swarm Pause / Resume */}
      <div className="flex flex-wrap gap-2">
        {isPaused ? (
          <button type="button"
            onClick={() => handleAction('resume', onResumeSwarm)}
            disabled={actionLoading === 'resume' || executionBlocked}
            title={executionBlocked ? `Blocked: ${blockSummary}` : 'Resume swarm execution'}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
          >
            <Play className="w-4 h-4" />
            {actionLoading === 'resume' ? 'Resuming...' : 'Resume Swarm'}
          </button>
        ) : (
          <button type="button"
            onClick={() => handleAction('pause', onPauseSwarm)}
            disabled={actionLoading === 'pause'}
            className="flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
          >
            <Pause className="w-4 h-4" />
            {actionLoading === 'pause' ? 'Pausing...' : 'Pause Swarm'}
          </button>
        )}

        {/* Refresh */}
        <button type="button"
          onClick={() => handleAction('refresh', onRefresh)}
          disabled={actionLoading === 'refresh'}
          title="Refresh dashboard"
          className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 rounded-lg text-sm transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${actionLoading === 'refresh' ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Mode Switch */}
      <div className="relative">
        <button type="button"
          onClick={() => setModeDropdownOpen(!modeDropdownOpen)}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-medium transition-colors w-full justify-between"
        >
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-slate-400" />
            <span>Mode: {summary?.mode?.name || 'UNKNOWN'}</span>
          </div>
          <ChevronDown className={`w-4 h-4 transition-transform ${modeDropdownOpen ? 'rotate-180' : ''}`} />
        </button>

        {modeDropdownOpen && (
          <div className="absolute z-10 mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 space-y-2">
            <input aria-label="Mode Reason"
              id="mode-change-reason"
              name="modeReason"
              type="text"
              placeholder="Reason for mode change..."
              value={modeReason}
              onChange={(e) => setModeReason(e.target.value)}
              className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700 rounded text-sm text-slate-200 placeholder-slate-500"
            />
            <div className="grid grid-cols-2 gap-2">
              {MODES.map((m) => (
                <button type="button"
                  key={m}
                  onClick={async () => {
                    await handleAction(`mode-${m}`, () => onSwitchMode(m, modeReason || `Switched to ${m}`));
                    setModeDropdownOpen(false);
                    setModeReason('');
                  }}
                  disabled={summary?.mode?.name?.toLowerCase() === m || executionBlocked}
                  title={executionBlocked ? `Blocked: ${blockSummary}` : `Switch to ${m} mode`}
                  className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-30 disabled:cursor-not-allowed rounded text-sm capitalize transition-colors"
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Destructive Actions */}
      <div className="pt-2 border-t border-slate-800 space-y-2">
        {confirmAction === 'shutdown' ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-400">Confirm swarm shutdown?</span>
            <button type="button"
              onClick={() => handleAction('shutdown', handleShutdown)}
              className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-xs font-medium"
            >
              Yes, Shutdown
            </button>
            <button type="button"
              onClick={() => setConfirmAction(null)}
              className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs"
            >
              Cancel
            </button>
          </div>
        ) : confirmAction === 'system-stop' ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-400">Stop entire system?</span>
            <button type="button"
              onClick={() => handleAction('system-stop', handleSystemStop)}
              className="px-3 py-1 bg-red-600 hover:bg-red-700 rounded text-xs font-medium"
            >
              Yes, Stop
            </button>
            <button type="button"
              onClick={() => setConfirmAction(null)}
              className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button"
              onClick={() => setConfirmAction('shutdown')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-900/30 hover:bg-red-900/50 border border-red-800/50 rounded-lg text-xs text-red-400 transition-colors"
            >
              <PowerOff className="w-3.5 h-3.5" />
              Shutdown Swarm
            </button>
            <button type="button"
              onClick={() => setConfirmAction('system-stop')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-red-900/30 hover:bg-red-900/50 border border-red-800/50 rounded-lg text-xs text-red-400 transition-colors"
            >
              <AlertOctagon className="w-3.5 h-3.5" />
              Stop System
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
