/**
 * PromotionStatusView — Agent promotion pipeline status.
 *
 * Shows auto-promoter running state, recent evaluations, and deployment transitions.
 */

import React from 'react';
import {
  Award, ArrowRight, CheckCircle, XCircle, Clock, RefreshCw, AlertTriangle,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Interfaces ───────────────────────────────────────────────────────────────

interface AutoPromoterStatus {
  running: boolean;
  total_promotions: number;
  eval_count: number;
}

interface Promotion {
  id?: string;
  ticker: string;
  direction: string;  // e.g. "PAPER→SHADOW" | "SHADOW→LIVE"
  verdict: string;    // e.g. "promote" | "hold" | "demote"
  timestamp: string;
}

interface AutoPromoterPromotions {
  promotions: Promotion[];
}

interface Transition {
  id?: string;
  ticker: string;
  from_stage: string;
  to_stage: string;
  reason: string;
  timestamp: string;
}

interface DeploymentTransitions {
  transitions: Transition[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function relTime(ts: string | undefined): string {
  if (!ts) return '—';
  try {
    const diff = Date.now() - new Date(ts).getTime();
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    return `${h}h ago`;
  } catch {
    return ts;
  }
}

function verdictStyle(verdict: string): string {
  switch (verdict?.toLowerCase()) {
    case 'promote': return 'text-green-400';
    case 'hold':    return 'text-yellow-400';
    case 'demote':  return 'text-red-400';
    default:        return 'text-gray-400';
  }
}

function VerdictIcon({ verdict }: { verdict: string }) {
  switch (verdict?.toLowerCase()) {
    case 'promote': return <CheckCircle className="w-4 h-4 text-green-400" />;
    case 'demote':  return <XCircle className="w-4 h-4 text-red-400" />;
    default:        return <Clock className="w-4 h-4 text-yellow-400" />;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

const PromotionStatusView: React.FC = () => {
  const opts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };

  const statusRes      = useApiData<AutoPromoterStatus>(API_ENDPOINTS.AUTO_PROMOTER_STATUS, opts);
  const promotionsRes  = useApiData<AutoPromoterPromotions>(API_ENDPOINTS.AUTO_PROMOTER_PROMOTIONS, opts);
  const transitionsRes = useApiData<DeploymentTransitions>(API_ENDPOINTS.KALSHI_DEPLOYMENT_TRANSITIONS, opts);

  const status      = statusRes.data;
  const promotions  = promotionsRes.data?.promotions ?? [];
  const transitions = transitionsRes.data?.transitions ?? [];

  const anyError = statusRes.error ?? promotionsRes.error ?? transitionsRes.error;

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Award className="w-7 h-7 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Promotion Status</h1>
            <p className="text-sm text-gray-400">Auto-promoter health, evaluations, and stage transitions</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => { statusRes.refetch(); promotionsRes.refetch(); transitionsRes.refetch(); }}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {/* Error banner */}
      {anyError && (
        <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="inline w-4 h-4 mr-1.5" />
          {anyError.message}
        </div>
      )}

      {/* ═══ TOP ROW: Auto-promoter status ═══ */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <Award className="w-4 h-4 text-purple-400" />
            <h3 className="text-sm font-medium text-gray-300">Auto-Promoter</h3>
            <span className={`ml-auto text-xs font-bold px-2 py-0.5 rounded ${
              status?.running
                ? 'bg-green-500/20 text-green-400'
                : 'bg-red-500/20 text-red-400'
            }`}>
              {statusRes.loading ? '…' : status?.running ? 'RUNNING' : 'STOPPED'}
            </span>
          </div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Total Promotions</span>
              <span className="text-white font-semibold">
                {statusRes.loading ? '—' : status?.total_promotions ?? '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Eval Count</span>
              <span className="text-white font-semibold">
                {statusRes.loading ? '—' : status?.eval_count ?? '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Summary stats from promotions */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-400" />
            <h3 className="text-sm font-medium text-gray-300">Recent Outcomes</h3>
          </div>
          <div className="space-y-1.5 text-sm">
            {(['promote', 'hold', 'demote'] as const).map(v => {
              const count = promotions.filter(p => p.verdict?.toLowerCase() === v).length;
              return (
                <div key={v} className="flex justify-between">
                  <span className="text-gray-400 capitalize">{v}</span>
                  <span className={`font-semibold ${verdictStyle(v)}`}>{count}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Transition summary */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <ArrowRight className="w-4 h-4 text-blue-400" />
            <h3 className="text-sm font-medium text-gray-300">Stage Transitions</h3>
          </div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Total Logged</span>
              <span className="text-white font-semibold">
                {transitionsRes.loading ? '—' : transitions.length}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Latest</span>
              <span className="text-gray-300">
                {transitionsRes.loading
                  ? '—'
                  : transitions.length > 0
                    ? relTime(transitions[0]?.timestamp)
                    : 'none'}
              </span>
            </div>
          </div>
        </div>

      </div>

      {/* ═══ RECENT EVALUATIONS TABLE ═══ */}
      <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-200">Recent Evaluations</h3>
        </div>

        {promotionsRes.loading ? (
          <p className="text-sm text-gray-500 py-4 text-center">Loading…</p>
        ) : promotions.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">No evaluations recorded</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-slate-800">
                  <th className="text-left py-2 pr-4 font-medium">Ticker</th>
                  <th className="text-left py-2 pr-4 font-medium">Direction</th>
                  <th className="text-left py-2 pr-4 font-medium">Verdict</th>
                  <th className="text-right py-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {promotions.slice(0, 20).map((p, i) => (
                  <tr key={p.id ?? i} className="hover:bg-slate-800/50 transition-colors">
                    <td className="py-2 pr-4 text-white font-mono text-xs">{p.ticker ?? '—'}</td>
                    <td className="py-2 pr-4">
                      <span className="flex items-center gap-1 text-gray-300">
                        {p.direction?.replace('→', '') !== p.direction
                          ? <>
                              <span className="text-gray-400">{p.direction?.split('→')[0]}</span>
                              <ArrowRight className="w-3 h-3 text-gray-500" />
                              <span className="text-blue-300">{p.direction?.split('→')[1]}</span>
                            </>
                          : p.direction ?? '—'
                        }
                      </span>
                    </td>
                    <td className="py-2 pr-4">
                      <span className={`flex items-center gap-1 font-semibold ${verdictStyle(p.verdict)}`}>
                        <VerdictIcon verdict={p.verdict} />
                        {p.verdict ?? '—'}
                      </span>
                    </td>
                    <td className="py-2 text-right text-gray-500 text-xs">{relTime(p.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ═══ DEPLOYMENT TRANSITIONS LIST ═══ */}
      <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <ArrowRight className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-gray-200">Deployment Transitions</h3>
        </div>

        {transitionsRes.loading ? (
          <p className="text-sm text-gray-500 py-4 text-center">Loading…</p>
        ) : transitions.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">No transitions recorded</p>
        ) : (
          <div className="space-y-2">
            {transitions.slice(0, 15).map((t, i) => (
              <div
                key={t.id ?? i}
                className="flex items-start gap-3 px-3 py-2.5 rounded-lg bg-slate-800/60 border border-slate-700/50 hover:bg-slate-800 transition-colors"
              >
                <ArrowRight className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono text-white">{t.ticker ?? '—'}</span>
                    <span className="text-xs text-gray-500">{t.from_stage ?? '?'}</span>
                    <ArrowRight className="w-3 h-3 text-gray-600" />
                    <span className="text-xs text-blue-300">{t.to_stage ?? '?'}</span>
                  </div>
                  {t.reason && (
                    <p className="text-xs text-gray-500 mt-0.5 truncate" title={t.reason}>{t.reason}</p>
                  )}
                </div>
                <span className="text-xs text-gray-600 shrink-0">{relTime(t.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
};

export default PromotionStatusView;
