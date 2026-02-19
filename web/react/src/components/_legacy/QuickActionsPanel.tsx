import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Play, Pause, RefreshCw, AlertTriangle, Shield, Zap } from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { logUiError } from '../utils/logger';

interface QuickAction {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  action: () => void;
  disabled?: boolean;
}

interface QuickActionsPanelProps {
  className?: string;
}

function QuickActionsPanel({ className = '' }: QuickActionsPanelProps) {
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const statusTimeoutRef = useRef<number | null>(null);

  const showStatus = useCallback((type: 'success' | 'error', message: string) => {
    setActionStatus({ type, message });
    if (statusTimeoutRef.current) {
      window.clearTimeout(statusTimeoutRef.current);
    }
    statusTimeoutRef.current = window.setTimeout(() => {
      setActionStatus(null);
      statusTimeoutRef.current = null;
    }, DEFAULTS.TIMEOUTS.STATUS_RESET);
  }, []);

  useEffect(() => {
    return () => {
      if (statusTimeoutRef.current) {
        window.clearTimeout(statusTimeoutRef.current);
      }
    };
  }, []);

  const runAction = useCallback(async (actionId: string, fn: () => Promise<void>) => {
    if (pendingAction) return;
    setPendingAction(actionId);
    try {
      await fn();
    } catch (error) {
      logUiError('QuickActions', `${actionId} failed`, error);
    } finally {
      setPendingAction(null);
    }
  }, [pendingAction]);

  const handlePauseTrading = useCallback(() => {
    void runAction('pause-trading', async () => {
      if (!confirm('Are you sure you want to halt all trading?')) return;
      const token = localStorage.getItem('merid-access');
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_HALT}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ reason: 'operator_manual_halt' }),
      });
      if (response.ok) {
        showStatus('success', 'Trading halted successfully.');
      } else {
        showStatus('error', 'Failed to halt trading.');
      }
    });
  }, [runAction, showStatus]);

  const handleResumeTrading = useCallback(() => {
    void runAction('resume-trading', async () => {
      if (!confirm('Are you sure you want to resume trading?')) return;
      const token = localStorage.getItem('merid-access');
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_RESUME}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ operator: 'operator' }),
      });
      if (response.ok) {
        showStatus('success', 'Trading resumed successfully.');
      } else {
        showStatus('error', 'Failed to resume trading.');
      }
    });
  }, [runAction, showStatus]);

  const handleEmergencyStop = useCallback(() => {
    void runAction('emergency-stop', async () => {
      if (!confirm('Emergency stop will halt the system. Continue?')) return;
      const token = localStorage.getItem('merid-access');
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SYSTEM_STOP}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (response.ok) {
        showStatus('success', 'Emergency stop initiated.');
      } else {
        showStatus('error', 'Emergency stop failed.');
      }
    });
  }, [runAction, showStatus]);

  const handleRiskCheck = useCallback(() => {
    void runAction('risk-check', async () => {
      const token = localStorage.getItem('merid-access');
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_SUMMARY}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (response.ok) {
        showStatus('success', 'Risk summary fetched.');
      } else {
        showStatus('error', 'Risk summary fetch failed.');
      }
    });
  }, [runAction, showStatus]);

  const handleForceSync = useCallback(() => {
    void runAction('force-sync', async () => {
      const token = localStorage.getItem('merid-access');
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.LIVE_REFRESH}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (response.ok) {
        showStatus('success', 'Live data refresh triggered.');
      } else {
        showStatus('error', 'Live refresh failed.');
      }
    });
  }, [runAction, showStatus]);

  const actions: QuickAction[] = [
    {
      id: 'pause-trading',
      label: 'Pause Trading',
      icon: Pause,
      color: 'amber',
      action: handlePauseTrading,
      disabled: pendingAction === 'pause-trading',
    },
    {
      id: 'resume-trading',
      label: 'Resume Trading',
      icon: Play,
      color: 'emerald',
      action: handleResumeTrading,
      disabled: pendingAction === 'resume-trading',
    },
    {
      id: 'refresh-data',
      label: 'Refresh All Data',
      icon: RefreshCw,
      color: 'blue',
      action: () => window.location.reload(),
    },
    {
      id: 'emergency-stop',
      label: 'Emergency Stop',
      icon: AlertTriangle,
      color: 'rose',
      action: handleEmergencyStop,
      disabled: pendingAction === 'emergency-stop',
    },
    {
      id: 'risk-check',
      label: 'Run Risk Check',
      icon: Shield,
      color: 'purple',
      action: handleRiskCheck,
      disabled: pendingAction === 'risk-check',
    },
    {
      id: 'force-sync',
      label: 'Force Sync',
      icon: Zap,
      color: 'cyan',
      action: handleForceSync,
      disabled: pendingAction === 'force-sync',
    },
  ];

  const getColorClasses = (color: string) => {
    const colors: Record<string, string> = {
      amber: 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border-amber-500/30',
      emerald: 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border-emerald-500/30',
      blue: 'bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border-blue-500/30',
      rose: 'bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border-rose-500/30',
      purple: 'bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 border-purple-500/30',
      cyan: 'bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 border-cyan-500/30',
    };
    return colors[color] || colors.blue;
  };

  return (
    <div className={`bg-slate-900/70 rounded-xl p-6 border border-slate-800 ${className}`}>
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-200">Quick Actions</h2>
        <p className="text-sm text-slate-400">Common system controls</p>
      </div>

      {actionStatus && (
        <div className={`mb-4 rounded-lg px-3 py-2 text-xs border ${
          actionStatus.type === 'success'
            ? 'bg-emerald-900/20 border-emerald-500/30 text-emerald-300'
            : 'bg-rose-900/20 border-rose-500/30 text-rose-200'
        }`}>
          {actionStatus.message}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        {actions.map((action) => {
          const Icon = action.icon;
          return (
            <button type="button"
              key={action.id}
              onClick={action.action}
              disabled={action.disabled}
              className={`
                p-4 rounded-lg border transition-all
                disabled:opacity-50 disabled:cursor-not-allowed
                ${getColorClasses(action.color)}
              `}
            >
              <div className="flex flex-col items-center gap-2">
                <Icon className="w-5 h-5" />
                <span className="text-xs font-medium text-center">
                  {action.label}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-4 pt-4 border-t border-slate-800">
        <div className="text-xs text-slate-500 text-center">
          Keyboard shortcuts: Press <kbd className="px-1.5 py-0.5 bg-slate-800 rounded text-slate-400">?</kbd> for help
        </div>
      </div>
    </div>
  );
}

const MemoizedQuickActionsPanel = React.memo(QuickActionsPanel);
MemoizedQuickActionsPanel.displayName = 'QuickActionsPanel';
export default MemoizedQuickActionsPanel;
