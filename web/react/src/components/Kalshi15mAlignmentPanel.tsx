/**
 * Kalshi15mAlignmentPanel — 15m pipeline alignment panel.
 *
 * Renders the six end-to-end data-flow validation stages reported by
 * GET /api/v1/data-flow-validation (the legacy /api/v1/kalshi/15m/alignment
 * route does not exist):
 *   1. ws_to_market_state      — WS bridge → market state store
 *   2. market_state_to_agents  — market state → agent wiring
 *   3. agents_to_orders        — agent grid initialized
 *   4. orders_to_fills         — fills ledger accessible
 *   5. fills_to_ledger         — ledger persistence
 *   6. ledger_to_position_cache — position cache tracking
 *
 * Stage statuses (ok / degraded / failed / error) map to the panel's
 * ok / warning / blocked display. Honest unavailable/error states preserved.
 */

import React from 'react';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { apiUrl } from '../config/apiBase';
import { DEFAULTS } from '../config/constants';
import { CheckCircle, AlertTriangle, XCircle, Clock } from '../ui/icons';

type StageStatus = 'ok' | 'degraded' | 'failed' | 'error';

interface StageResult {
  status: StageStatus;
  reason?: string;
  error?: string;
  [key: string]: unknown;
}

interface DataFlowResponse {
  overall_health: 'ok' | 'degraded';
  timestamp?: string;
  validation_stages?: Record<string, StageResult>;
}

const STAGE_LABELS: Record<string, string> = {
  ws_to_market_state: 'WS → Market State',
  market_state_to_agents: 'Market State → Agents',
  agents_to_orders: 'Agents → Orders',
  orders_to_fills: 'Orders → Fills',
  fills_to_ledger: 'Fills → Ledger',
  ledger_to_position_cache: 'Ledger → Position Cache',
};

const STAGE_ORDER = [
  'ws_to_market_state',
  'market_state_to_agents',
  'agents_to_orders',
  'orders_to_fills',
  'fills_to_ledger',
  'ledger_to_position_cache',
];

const toDisplayStatus = (s: StageStatus): 'ok' | 'warning' | 'blocked' =>
  s === 'ok' ? 'ok' : s === 'degraded' ? 'warning' : 'blocked';

/** Render the small detail fields a stage reports (skip status/reason/error). */
const stageDetails = (stage: StageResult): Array<[string, string]> =>
  Object.entries(stage)
    .filter(([k]) => !['status', 'reason', 'error'].includes(k))
    .slice(0, 4)
    .map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]);

const StageCard: React.FC<{ name: string; stage: StageResult }> = ({ name, stage }) => {
  const display = toDisplayStatus(stage.status);
  const colors = {
    ok: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    warning: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    blocked: 'bg-red-500/10 border-red-500/30 text-red-400',
  };
  const icons = {
    ok: <CheckCircle className="w-4 h-4" />,
    warning: <AlertTriangle className="w-4 h-4" />,
    blocked: <XCircle className="w-4 h-4" />,
  };

  return (
    <div className={`p-3 rounded-lg border ${colors[display]}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {icons[display]}
          <span className="font-semibold text-sm">{STAGE_LABELS[name] ?? name}</span>
        </div>
        <span className="text-xs font-mono uppercase">{stage.status}</span>
      </div>

      {stageDetails(stage).length > 0 && (
        <div className="grid grid-cols-2 gap-1 text-xs mb-1">
          {stageDetails(stage).map(([k, v]) => (
            <div key={k}>
              <span className="text-slate-500">{k}:</span>
              <span className="ml-1 font-mono">{v}</span>
            </div>
          ))}
        </div>
      )}

      {(stage.reason ?? stage.error) && (
        <div className="text-xs">
          <span className="text-slate-500">{stage.error ? 'Error:' : 'Reason:'}</span>
          <span className="ml-1 font-mono break-words">{stage.error ?? stage.reason}</span>
        </div>
      )}
    </div>
  );
};

const Kalshi15mAlignmentPanel: React.FC = () => {
  const { data, isLoading, error, refetch } = useApiQuery<DataFlowResponse>(
    apiUrl('/api/v1/data-flow-validation'),
    {
      refetchInterval: DEFAULTS.POLLING_INTERVALS.FAST,
      staleTime: 10_000,
    }
  );

  if (isLoading && !data) {
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
        <p className="text-sm text-slate-400 mb-3">{String(error)}</p>
        <button
          type="button"
          onClick={() => refetch()}
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

  const stages = data.validation_stages ?? {};
  const orderedNames = [
    ...STAGE_ORDER.filter(n => n in stages),
    ...Object.keys(stages).filter(n => !STAGE_ORDER.includes(n)),
  ];
  const counts = { ok: 0, warning: 0, blocked: 0 };
  orderedNames.forEach(n => { counts[toDisplayStatus(stages[n].status)] += 1; });

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">15m Kalshi Alignment</h3>
          <p className="text-sm text-slate-400">End-to-end data-flow validation</p>
        </div>
        <div className={`px-3 py-1 rounded-full border text-sm font-semibold uppercase ${
          data.overall_health === 'ok'
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
            : 'bg-amber-500/10 border-amber-500/30 text-amber-400'
        }`}>
          {data.overall_health}
        </div>
      </div>

      <div className="flex gap-4 mb-4 text-sm">
        <div className="flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-emerald-400" />
          <span className="text-slate-400">OK:</span>
          <span className="font-mono text-white">{counts.ok}</span>
        </div>
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-slate-400">Warning:</span>
          <span className="font-mono text-white">{counts.warning}</span>
        </div>
        <div className="flex items-center gap-2">
          <XCircle className="w-4 h-4 text-red-400" />
          <span className="text-slate-400">Blocked:</span>
          <span className="font-mono text-white">{counts.blocked}</span>
        </div>
      </div>

      {orderedNames.length === 0 ? (
        <p className="text-slate-500 text-sm">No validation stages reported.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {orderedNames.map(name => (
            <StageCard key={name} name={name} stage={stages[name]} />
          ))}
        </div>
      )}
    </div>
  );
};

Kalshi15mAlignmentPanel.displayName = 'Kalshi15mAlignmentPanel';
export default React.memo(Kalshi15mAlignmentPanel);
