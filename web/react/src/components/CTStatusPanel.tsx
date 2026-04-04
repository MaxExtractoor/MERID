import { useMemo } from 'react';
import { Activity, AlertTriangle, BarChart3 } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { CTStatusResponse, CTTickerDiagnostic } from '../types/api';

function formatCycleAge(cycleTs?: number): string {
  if (!cycleTs) return '—';
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - cycleTs));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

function formatPercent(value?: number): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

function diagnosticTone(diagnostic: CTTickerDiagnostic): string {
  if (diagnostic.veto_reason) return 'text-amber-300';
  if (diagnostic.side === 'none') return 'text-slate-400';
  return diagnostic.side === 'YES' ? 'text-emerald-300' : 'text-rose-300';
}

export default function CTStatusPanel(): JSX.Element {
  const result = useApiData<CTStatusResponse>(API_ENDPOINTS.CT_STATUS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });

  const status = result.data?.data;
  const lastCycle = status?.last_cycle;
  const diagnostics = useMemo(
    () => (lastCycle?.ticker_diagnostics ?? []).slice(0, 5),
    [lastCycle]
  );
  const vetoEntries = useMemo(
    () => Object.entries(lastCycle?.vetoed_by_reason ?? {}).filter(([, count]) => typeof count === 'number' && count > 0),
    [lastCycle]
  );

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-cyan-400" />
          <div>
            <h2 className="text-sm font-semibold text-white">Continuous Trader Diagnostics</h2>
            <p className="text-xs text-slate-400">
              {status?.running ? 'Live CT diagnostics from the latest cycle.' : 'CT is idle or unavailable.'}
            </p>
          </div>
        </div>
        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${status?.running ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}>
          {status?.running ? 'RUNNING' : result.data?.status?.toUpperCase() ?? 'UNAVAILABLE'}
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Candidates" value={status?.candidate_count ?? 0} />
        <MetricCard label="Seen last cycle" value={lastCycle?.candidates_seen ?? 0} />
        <MetricCard label="Approved" value={lastCycle?.markets_after_risk_veto ?? 0} />
        <MetricCard label="Last cycle" value={formatCycleAge(lastCycle?.cycle_ts)} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
            <BarChart3 className="h-4 w-4 text-cyan-400" />
            Cycle snapshot
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs text-slate-300">
            <KeyValue label="Markets w/ edge" value={String(lastCycle?.markets_with_any_edge ?? 0)} />
            <KeyValue label="Vetoed total" value={String(lastCycle?.vetoed_total ?? 0)} />
            <KeyValue label="Kelly fraction" value={typeof status?.config?.kelly_fraction === 'number' ? status.config.kelly_fraction.toFixed(2) : '—'} />
            <KeyValue label="Bankroll fraction" value={typeof status?.config?.bankroll_fraction === 'number' ? formatPercent(status.config.bankroll_fraction) : '—'} />
          </div>

          <div className="mt-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Top veto reasons</div>
            {vetoEntries.length > 0 ? (
              <div className="space-y-2">
                {vetoEntries.slice(0, 5).map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between rounded-lg bg-slate-950/80 px-3 py-2 text-xs">
                    <span className="text-slate-300">{reason}</span>
                    <span className="font-semibold text-amber-300">{count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg bg-slate-950/80 px-3 py-2 text-xs text-slate-500">
                No vetoes recorded in the latest cycle.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            Ticker diagnostics
          </div>
          {diagnostics.length > 0 ? (
            <div className="space-y-2">
              {diagnostics.map((diagnostic) => (
                <div key={diagnostic.ticker} className="rounded-lg bg-slate-950/80 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-slate-200">{diagnostic.ticker}</span>
                    <span className={`text-[11px] font-semibold ${diagnosticTone(diagnostic)}`}>
                      {diagnostic.veto_reason ?? diagnostic.side}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400">
                    <span>Model {formatPercent(diagnostic.model_win_prob)}</span>
                    <span>Implied {formatPercent(diagnostic.implied_yes_prob)}</span>
                    <span>Kelly {diagnostic.kelly_frac.toFixed(3)}</span>
                    <span>Edge {diagnostic.edge_bps} bps</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg bg-slate-950/80 px-3 py-2 text-xs text-slate-500">
              No per-ticker diagnostics available yet.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }): JSX.Element {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-medium text-white">{value}</div>
    </div>
  );
}
