/**
 * RiskControlView — Emergency risk controls and kill-switch management.
 *
 * Shows kill-switch status, risk state metrics, and emergency action buttons.
 */

import React, { useState } from 'react';
import {
  ShieldAlert, ShieldCheck, AlertTriangle, Zap, RefreshCw,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Interfaces ───────────────────────────────────────────────────────────────

interface KillSwitchStatus {
  active: boolean;
  can_trade: boolean;
  kill_reason: string | null;
}

interface RiskState {
  pnl: {
    daily_pnl: number;
    utilization_pct: number;
  };
  position: {
    utilization_pct: number;
  };
}

interface HaltStatus {
  halted: boolean;
  reason: string | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(val: number | null | undefined, decimals = 2, prefix = ''): string {
  if (val == null) return '—';
  return `${prefix}${val.toFixed(decimals)}`;
}

function pctBar(value: number, color: string) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden mt-1">
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

const RiskControlView: React.FC = () => {
  const opts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH };

  const killRes  = useApiData<KillSwitchStatus>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, opts);
  const riskRes  = useApiData<RiskState>(API_ENDPOINTS.OPERATOR_RISK_STATE, opts);
  const haltRes  = useApiData<HaltStatus>(API_ENDPOINTS.RISK_HALT_STATUS, opts);

  const [actionStatus, setActionStatus] = useState<{ msg: string; ok: boolean } | null>(null);
  const [actionLoading, setActionLoading] = useState<'stop' | 'reset' | null>(null);

  const kill  = killRes.data;
  const risk  = riskRes.data;
  const halt  = haltRes.data;

  const isKillActive = kill?.active ?? false;
  const canTrade     = kill?.can_trade ?? !isKillActive;
  const isHalted     = halt?.halted ?? false;

  async function postAction(endpoint: string, label: 'stop' | 'reset') {
    setActionLoading(label);
    setActionStatus(null);
    try {
      const token = localStorage.getItem('merid-access');
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (json as { detail?: string }).detail ?? `Action failed (${res.status})`;
        setActionStatus({ msg: detail, ok: false });
      } else {
        setActionStatus({ msg: (json as { message?: string }).message ?? 'Action completed', ok: true });
        killRes.refetch();
        riskRes.refetch();
        haltRes.refetch();
      }
    } catch {
      setActionStatus({ msg: 'Network error', ok: false });
    } finally {
      setActionLoading(null);
    }
  }

  const loading = killRes.loading && riskRes.loading;
  const error   = killRes.error ?? riskRes.error;

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-7 h-7 text-red-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Risk Control Panel</h1>
            <p className="text-sm text-gray-400">Kill-switch controls, risk state, and emergency actions</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => { killRes.refetch(); riskRes.refetch(); haltRes.refetch(); }}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* System alert banners */}
      {isKillActive && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 text-sm font-bold animate-pulse">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          KILL SWITCH ACTIVE — trading is disabled
        </div>
      )}
      {isHalted && !isKillActive && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-orange-500/20 border border-orange-500/40 text-orange-400 text-sm font-semibold">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          SYSTEM HALTED{halt?.reason ? ` — ${halt.reason}` : ''}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="inline w-4 h-4 mr-1.5" />
          {error.message}
        </div>
      )}

      {/* Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        {/* Kill Switch Status */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            {isKillActive
              ? <ShieldAlert className="w-4 h-4 text-red-400" />
              : <ShieldCheck className="w-4 h-4 text-green-400" />
            }
            <h3 className="text-sm font-medium text-gray-300">Kill Switch</h3>
            <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded ${
              isKillActive
                ? 'bg-red-500/20 text-red-400'
                : 'bg-green-500/20 text-green-400'
            }`}>
              {loading ? '…' : isKillActive ? 'ACTIVE' : 'CLEAR'}
            </span>
          </div>

          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Can Trade</span>
              <span className={canTrade ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold'}>
                {loading ? '—' : canTrade ? 'Yes' : 'No'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Reason</span>
              <span className="text-white text-right max-w-[160px] truncate" title={kill?.kill_reason ?? ''}>
                {loading ? '—' : kill?.kill_reason ?? 'None'}
              </span>
            </div>
          </div>
        </div>

        {/* Risk State */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-yellow-400" />
            <h3 className="text-sm font-medium text-gray-300">Risk State</h3>
          </div>

          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Daily P&amp;L</span>
              <span className={
                (risk?.pnl.daily_pnl ?? 0) >= 0 ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold'
              }>
                {fmt(risk?.pnl.daily_pnl, 2, '$')}
              </span>
            </div>
            <div>
              <div className="flex justify-between">
                <span className="text-gray-400">Loss Utilization</span>
                <span className="text-white">{fmt(risk?.pnl.utilization_pct, 2)}%</span>
              </div>
              {pctBar((risk?.pnl.utilization_pct ?? 0) / 100, 'bg-orange-500')}
            </div>
            <div>
              <div className="flex justify-between">
                <span className="text-gray-400">Position Utilization</span>
                <span className="text-white">{fmt(risk?.position.utilization_pct, 1)}%</span>
              </div>
              {pctBar((risk?.position.utilization_pct ?? 0) / 100, 'bg-blue-500')}
            </div>
          </div>
        </div>

        {/* Halt Status */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-medium text-gray-300">Halt Status</h3>
            <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded ${
              isHalted ? 'bg-orange-500/20 text-orange-400' : 'bg-green-500/20 text-green-400'
            }`}>
              {haltRes.loading ? '…' : isHalted ? 'HALTED' : 'NORMAL'}
            </span>
          </div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Halted</span>
              <span className={isHalted ? 'text-red-400 font-semibold' : 'text-green-400'}>
                {haltRes.loading ? '—' : isHalted ? 'Yes' : 'No'}
              </span>
            </div>
            {isHalted && halt?.reason && (
              <div className="flex justify-between">
                <span className="text-gray-400">Reason</span>
                <span className="text-orange-300 text-right max-w-[160px] truncate" title={halt.reason}>
                  {halt.reason}
                </span>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Emergency Controls */}
      <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="w-4 h-4 text-red-400" />
          <h3 className="text-sm font-semibold text-gray-200">Emergency Controls</h3>
        </div>

        <p className="text-xs text-gray-500">
          Use these controls only in emergency situations. Actions are logged and audited.
        </p>

        {actionStatus && (
          <div className={`px-3 py-2 rounded-lg text-sm ${
            actionStatus.ok
              ? 'bg-green-500/10 border border-green-500/30 text-green-400'
              : 'bg-red-500/10 border border-red-500/30 text-red-400'
          }`}>
            {actionStatus.msg}
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={actionLoading != null}
            onClick={() => postAction(API_ENDPOINTS.OPERATOR_EMERGENCY_STOP, 'stop')}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
          >
            <ShieldAlert className="w-4 h-4" />
            {actionLoading === 'stop' ? 'Stopping…' : 'Emergency Stop'}
          </button>

          <button
            type="button"
            disabled={actionLoading != null}
            onClick={() => postAction(API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH, 'reset')}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            {actionLoading === 'reset' ? 'Resetting…' : 'Reset Kill Switch'}
          </button>
        </div>
      </div>

    </div>
  );
};

export default RiskControlView;
