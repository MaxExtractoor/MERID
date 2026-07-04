/**
 * Kalshi15mPreflightCheck — End-to-end 15m-only pre-flight validation.
 *
 * Validates the entire stack is aligned with the 15m Kalshi crypto profile:
 * 1. Profile check: MERID_PROFILE = kalshi_crypto_15m_v2
 * 2. Timeframe check: No non-15m timeframes (1h, daily, weekly) in active use
 * 3. API endpoint check: Legacy endpoints removed/unused
 * 4. Component check: Legacy UI components not imported/used
 * 5. Invariant check: All 7 backend invariants passing
 * 6. Health check: 15m health status healthy
 * 7. Shadow mode check: Shadow mode logging functional
 *
 * This component can be run on startup or on-demand to verify 15m alignment.
 */

import React, { useState, useEffect } from 'react';
import { CheckCircle, XCircle, AlertTriangle, RefreshCw, Shield, Clock, Activity } from '../ui/icons';
import { useApiQuery } from '../hooks/useTanStackQuery';

interface PreflightCheck {
  name: string;
  status: 'pass' | 'fail' | 'warning' | 'pending';
  message: string;
  details?: string;
}

interface PreflightResponse {
  overall_status: 'pass' | 'fail' | 'warning';
  checks: PreflightCheck[];
  profile: string;
  timestamp: string;
}

const CheckRow: React.FC<{ check: PreflightCheck }> = ({ check }) => {
  const statusIcons = {
    pass: <CheckCircle className="w-5 h-5 text-emerald-400" />,
    fail: <XCircle className="w-5 h-5 text-red-400" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-400" />,
    pending: <Clock className="w-5 h-5 text-slate-400 animate-spin" />,
  };

  const statusColors = {
    pass: 'border-emerald-500/30 bg-emerald-500/5',
    fail: 'border-red-500/30 bg-red-500/5',
    warning: 'border-amber-500/30 bg-amber-500/5',
    pending: 'border-slate-500/30 bg-slate-500/5',
  };

  return (
    <div className={`p-4 rounded-lg border ${statusColors[check.status]}`}>
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">{statusIcons[check.status]}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-white">{check.name}</span>
            <span className="text-xs font-mono uppercase text-slate-400">{check.status}</span>
          </div>
          <p className="text-sm text-slate-300">{check.message}</p>
          {check.details && (
            <p className="text-xs text-slate-500 mt-1 font-mono">{check.details}</p>
          )}
        </div>
      </div>
    </div>
  );
};

const Kalshi15mPreflightCheck: React.FC = () => {
  const [isRunning, setIsRunning] = useState(false);
  const { data, isLoading, error, refetch } = useApiQuery<PreflightResponse>(
    '/api/v1/kalshi/15m/preflight',
    {
      staleTime: 30_000,
    }
  );

  const handleRunCheck = async () => {
    setIsRunning(true);
    await refetch();
    setIsRunning(false);
  };

  useEffect(() => {
    // Auto-run on mount
    handleRunCheck();
  }, []);

  if (isLoading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span className="text-sm">Running pre-flight checks...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <XCircle className="w-5 h-5" />
          <span className="font-semibold">Preflight Check Failed</span>
        </div>
        <p className="text-sm text-slate-400 mb-3">{String(error)}</p>
        <button
          type="button"
          onClick={handleRunCheck}
          disabled={isRunning}
          className="text-sm text-blue-400 hover:text-blue-300 disabled:text-slate-500"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <p className="text-slate-500 text-sm">No pre-flight data available.</p>
      </div>
    );
  }

  const overallColors = {
    pass: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    fail: 'bg-red-500/10 border-red-500/30 text-red-400',
    warning: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
  };

  const passCount = data.checks.filter((c: PreflightCheck) => c.status === 'pass').length;
  const failCount = data.checks.filter((c: PreflightCheck) => c.status === 'fail').length;
  const warningCount = data.checks.filter((c: PreflightCheck) => c.status === 'warning').length;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-blue-400" />
          <div>
            <h3 className="text-lg font-semibold text-white">15m Pre-Flight Check</h3>
            <p className="text-sm text-slate-400">Profile: {data.profile}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className={`px-3 py-1.5 rounded-lg text-sm font-bold ${overallColors[data.overall_status as keyof typeof overallColors]}`}>
            {data.overall_status.toUpperCase()}
          </div>
          <button
            type="button"
            onClick={handleRunCheck}
            disabled={isRunning}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors disabled:opacity-50"
            title="Re-run checks"
          >
            <RefreshCw className={`w-4 h-4 ${isRunning ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Pass</div>
          <div className="text-xl font-bold text-emerald-400">{passCount}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Warning</div>
          <div className="text-xl font-bold text-amber-400">{warningCount}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">Fail</div>
          <div className="text-xl font-bold text-red-400">{failCount}</div>
        </div>
      </div>

      {/* Checks */}
      <div className="space-y-2">
        {data.checks.map((check: PreflightCheck, idx: number) => (
          <CheckRow key={idx} check={check} />
        ))}
      </div>

      {/* Timestamp */}
      <div className="mt-4 pt-4 border-t border-slate-800 flex items-center gap-2 text-xs text-slate-500">
        <Activity className="w-3 h-3" />
        <span>Last run: {new Date(data.timestamp).toLocaleString()}</span>
      </div>
    </div>
  );
};

Kalshi15mPreflightCheck.displayName = 'Kalshi15mPreflightCheck';
export default React.memo(Kalshi15mPreflightCheck);
