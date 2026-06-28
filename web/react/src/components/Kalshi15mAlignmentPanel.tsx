/**
 * Kalshi15mAlignmentPanel — 15m Kalshi invariant status panel.
 *
 * Displays the 7 backend invariants for the Kalshi 15m crypto stack:
 * 1. SPOT-PRICE-FRESHNESS: Spot price age < threshold
 * 2. SPREAD-PRESENCE: Orderbook spread exists and is reasonable
 * 3. DATA-QUALITY-SCORE: Data quality score >= threshold
 * 4. ASSET-CAP-ENFORCEMENT: Per-asset notional caps respected
 * 5. RISK-TARGET-ENFORCEMENT: Risk targets (Kelly, drawdown) respected
 * 6. CATALOG-HEALTH: Market catalog healthy and refreshed
 * 7. BANKROLL-VALIDATION: Bankroll configuration valid
 *
 * Shows for each invariant:
 * - Status: OK / Warning / Blocked
 * - Counters: number of blocks in the last N minutes
 * - Last error reason (e.g., SPOT-PRICE-MISSING, SPREAD-MISSING)
 */

import React from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { CheckCircle, AlertTriangle, XCircle, Clock } from '../ui/icons';

interface InvariantStatus {
  name: string;
  status: 'ok' | 'warning' | 'blocked';
  blocks_last_5m: number;
  blocks_last_15m: number;
  blocks_last_60m: number;
  last_error_reason: string | null;
  last_error_timestamp: string | null;
  last_check_timestamp: string;
}

interface AlignmentResponse {
  profile: string;
  overall_status: 'ok' | 'warning' | 'blocked';
  invariants: InvariantStatus[];
  summary: {
    total_invariants: number;
    ok_count: number;
    warning_count: number;
    blocked_count: number;
  };
}

const InvariantCard: React.FC<{ invariant: InvariantStatus }> = ({ invariant }) => {
  const statusColors = {
    ok: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    warning: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    blocked: 'bg-red-500/10 border-red-500/30 text-red-400',
  };

  const statusIcons = {
    ok: <CheckCircle className="w-4 h-4" />,
    warning: <AlertTriangle className="w-4 h-4" />,
    blocked: <XCircle className="w-4 h-4" />,
  };

  return (
    <div className={`p-3 rounded-lg border ${statusColors[invariant.status]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {statusIcons[invariant.status]}
          <span className="font-semibold text-sm uppercase">{invariant.name}</span>
        </div>
        <span className="text-xs font-mono uppercase">{invariant.status}</span>
      </div>
      
      <div className="grid grid-cols-3 gap-2 text-xs mb-2">
        <div>
          <span className="text-slate-500">5m:</span>
          <span className="ml-1 font-mono">{invariant.blocks_last_5m}</span>
        </div>
        <div>
          <span className="text-slate-500">15m:</span>
          <span className="ml-1 font-mono">{invariant.blocks_last_15m}</span>
        </div>
        <div>
          <span className="text-slate-500">60m:</span>
          <span className="ml-1 font-mono">{invariant.blocks_last_60m}</span>
        </div>
      </div>

      {invariant.last_error_reason && (
        <div className="text-xs">
          <span className="text-slate-500">Last error:</span>
          <span className="ml-1 font-mono">{invariant.last_error_reason}</span>
        </div>
      )}
    </div>
  );
};

const Kalshi15mAlignmentPanel: React.FC = () => {
  const { data, loading, error, refetch } = useApiData<AlignmentResponse>(
    '/api/v1/kalshi/15m/alignment',
    {
      pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST,
    }
  );

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <Clock className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading alignment status...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <XCircle className="w-4 h-4" />
          <span className="font-semibold">Alignment Status Unavailable</span>
        </div>
        <p className="text-sm text-slate-400 mb-3">{error}</p>
        <button
          type="button"
          onClick={refetch}
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <p className="text-slate-500 text-sm">No alignment data available.</p>
      </div>
    );
  }

  const overallColors = {
    ok: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    warning: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    blocked: 'bg-red-500/10 border-red-500/30 text-red-400',
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">15m Kalshi Alignment</h3>
          <p className="text-sm text-slate-400">Profile: {data.profile}</p>
        </div>
        <div className={`px-3 py-1 rounded-full border ${overallColors[data.overall_status]} text-sm font-semibold uppercase`}>
          {data.overall_status}
        </div>
      </div>

      <div className="flex gap-4 mb-4 text-sm">
        <div className="flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <span className="text-slate-400">OK:</span>
          <span className="font-mono text-white">{data.summary.ok_count}</span>
        </div>
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-slate-400">Warning:</span>
          <span className="font-mono text-white">{data.summary.warning_count}</span>
        </div>
        <div className="flex items-center gap-2">
          <XCircle className="w-4 h-4 text-red-400" />
          <span className="text-slate-400">Blocked:</span>
          <span className="font-mono text-white">{data.summary.blocked_count}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.invariants.map((inv) => (
          <InvariantCard key={inv.name} invariant={inv} />
        ))}
      </div>
    </div>
  );
};

Kalshi15mAlignmentPanel.displayName = 'Kalshi15mAlignmentPanel';
export default React.memo(Kalshi15mAlignmentPanel);
