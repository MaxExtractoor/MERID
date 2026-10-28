/**
 * Risk View — canonical safety page.
 *
 * (a) Kill-switch + halt/release card: ConfirmModal + synchronous useRef
 *     in-flight guard + authoritative refreshAll() — preserved verbatim.
 * (b) Risk summary tiles from store.risk (/api/v1/kalshi/risk + kill-switch).
 * (c) Live panels via usePoll:
 *     - /api/v1/kalshi/risk/envelope        -> dd tracking + adaptive bands
 *     - /api/v1/kalshi/risk/dd-guard        -> per-lane drawdown brakes
 *     - /api/v1/kalshi/order-errors         -> rejection taxonomy table
 *     - /api/v1/loop/guard/verdicts         -> recent allow/block verdicts
 *     - /api/v1/kalshi/health/reconciliation-> fills-ledger recon status
 *
 * Every panel renders an honest empty/error state with a freshness chip;
 * missing fields are 'n/a', never fabricated zeros.
 */

import { memo, useRef, useState } from 'react';
import { useKalshiStore, selectRisk, selectSystem, selectConnected } from '../store';
import { usePoll } from '../hooks/usePoll';
import { Gauge, ShieldAlert, TrendingDown } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { ConfirmModal } from '../components/ConfirmModal';
import { AGENT_ENDPOINTS, haltEntries, postJson, releaseEntries } from '../agents/api';
import { cx, fmtAgeMs, numOr, parseTsMs } from '../agents/format';

// Kill-switch POST takes `activate` as a query param (verified in kalshi_api.py).
const setKalshiKillSwitch = (activate: boolean) =>
  postJson<Record<string, unknown>>(`${AGENT_ENDPOINTS.KILL_SWITCH}?activate=${activate}`);

type ActionKind = 'activate' | 'reset' | 'halt' | 'release';

/* ------------------------------------------------------------------ */
/* Server shapes (defensive)                                           */
/* ------------------------------------------------------------------ */

interface RiskEnvelope {
  profile?: string;
  envelope_enabled?: boolean;
  message?: string;
  drawdown?: {
    peak_equity_usd?: number;
    current_equity_usd?: number;
    current_drawdown_pct?: number;
    halt_pct?: number;
    unwind_pct?: number;
    distance_to_halt_pct?: number;
  };
  adaptive_risk?: {
    bands?: unknown;
    current_multiplier?: number;
    is_halted?: boolean;
  };
  kelly?: { kelly_fraction?: number };
  effective_risk?: {
    per_trade_risk_pct?: number;
    effective_per_trade_risk_usd?: number;
  };
}

interface DdLane {
  equity?: number;
  peak?: number;
  drawdown?: number;
  limit?: number;
  allowed?: boolean;
}

interface DdGuard {
  ok?: boolean;
  lanes?: Record<string, DdLane>;
  global_allowed?: boolean;
  timestamp?: string;
  error?: string;
}

interface OrderErrorRow {
  code?: string;
  count?: number;
  percentage?: number;
  severity?: string;
  category?: string;
  is_retryable?: boolean;
  description?: string;
}

interface OrderErrors {
  window_hours?: number;
  total_rejections?: number;
  breakdown?: OrderErrorRow[];
  by_severity?: Record<string, number>;
  last_updated?: string;
}

interface GuardVerdict {
  plan_id?: string;
  ts?: number | string;
  ticker?: string;
  action?: string;
  allowed?: boolean;
  reason?: string;
  source?: string;
  throttle_pct?: number;
  cqi_score?: number;
  domain?: string;
  checks_failed?: string[];
}

interface GuardVerdicts {
  verdicts?: GuardVerdict[];
  count?: number;
}

interface ReconHealth {
  status?: string;
  last_run?: string | number | null;
  divergence_count?: number;
  divergences?: unknown[];
  ghost_trade_candidates?: number;
  last_success_at?: number | string | null;
  message?: string;
  timestamp?: string;
}

const objMap = <T,>(raw: unknown): T =>
  (raw && typeof raw === 'object' ? (raw as T) : ({} as T));

/* ------------------------------------------------------------------ */
/* Shared bits                                                         */
/* ------------------------------------------------------------------ */

const FreshnessChip = memo(function FreshnessChip({
  error, lastOk,
}: { error?: string | null; lastOk?: number }) {
  if (error) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-red-400"
        title={error}
        role="alert"
      >
        source error{lastOk ? ' — showing last good' : ''}
      </span>
    );
  }
  if (lastOk != null) {
    return (
      <span className="text-[9px] text-slate-600 tabular-nums">
        updated {Math.max(0, Math.round((Date.now() - lastOk) / 1000))}s ago
      </span>
    );
  }
  return null;
});

const RiskRow = memo(function RiskRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-400">{label}</span>
      {children}
    </div>
  );
});

const usdOr = (v: unknown): string => {
  const n = numOr(v);
  return n == null ? 'n/a' : `$${n.toFixed(2)}`;
};

const pctOr = (v: unknown, digits = 2): string => {
  const n = numOr(v);
  return n == null ? 'n/a' : `${n.toFixed(digits)}%`;
};

const severityVariant = (s?: string): 'danger' | 'warning' | 'info' =>
  s === 'critical' ? 'danger' : s === 'warning' ? 'warning' : 'info';

const reconVariant = (s?: string): 'success' | 'warning' | 'danger' =>
  s === 'ok' ? 'success' : s === 'degraded' || s === 'unknown' ? 'warning' : 'danger';

/* ------------------------------------------------------------------ */
/* Live panels                                                         */
/* ------------------------------------------------------------------ */

const EnvelopePanel = memo(function EnvelopePanel() {
  const poll = usePoll<RiskEnvelope>('/api/v1/kalshi/risk/envelope', { ms: 30_000, map: objMap });
  const env = poll.data;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Risk Envelope</CardTitle>
          <FreshnessChip error={poll.error} lastOk={poll.lastOk} />
        </div>
      </CardHeader>
      <CardContent>
        {poll.loading && !env ? (
          <div className="text-center py-4 text-slate-500">Loading envelope…</div>
        ) : poll.error && !env ? (
          <div className="text-center py-4 text-red-400 text-xs" role="alert">
            Risk envelope unavailable: {poll.error}
          </div>
        ) : env?.envelope_enabled !== true ? (
          <div className="text-center py-4 text-slate-500">
            {env?.message ?? 'Risk envelope not reported by backend'}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
            <RiskRow label="Current Equity">
              <span className="text-white tabular-nums">{usdOr(env.drawdown?.current_equity_usd)}</span>
            </RiskRow>
            <RiskRow label="Peak Equity">
              <span className="text-white tabular-nums">{usdOr(env.drawdown?.peak_equity_usd)}</span>
            </RiskRow>
            <RiskRow label="Current Drawdown">
              <span className="text-white tabular-nums">{pctOr(env.drawdown?.current_drawdown_pct)}</span>
            </RiskRow>
            <RiskRow label="Halt / Unwind Thresholds">
              <span className="text-white tabular-nums">
                {pctOr(env.drawdown?.halt_pct, 1)} / {pctOr(env.drawdown?.unwind_pct, 1)}
              </span>
            </RiskRow>
            <RiskRow label="Distance to Halt">
              <span className="text-white tabular-nums">{pctOr(env.drawdown?.distance_to_halt_pct, 1)}</span>
            </RiskRow>
            <RiskRow label="Adaptive Multiplier">
              <span className="text-white tabular-nums">
                {numOr(env.adaptive_risk?.current_multiplier)?.toFixed(2) ?? 'n/a'}×
              </span>
            </RiskRow>
            <RiskRow label="Per-Trade Risk">
              <span className="text-white tabular-nums">
                {pctOr(env.effective_risk?.per_trade_risk_pct)} ({usdOr(env.effective_risk?.effective_per_trade_risk_usd)})
              </span>
            </RiskRow>
            <RiskRow label="Kelly Fraction">
              <span className="text-white tabular-nums">
                {numOr(env.kelly?.kelly_fraction)?.toFixed(3) ?? 'n/a'}
              </span>
            </RiskRow>
            <RiskRow label="Envelope Halted">
              <Badge variant={env.adaptive_risk?.is_halted ? 'danger' : 'success'}>
                {env.adaptive_risk?.is_halted ? 'HALTED' : 'active'}
              </Badge>
            </RiskRow>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

const DdGuardPanel = memo(function DdGuardPanel() {
  const poll = usePoll<DdGuard>('/api/v1/kalshi/risk/dd-guard', { ms: 30_000, map: objMap });
  const data = poll.data;
  const lanes = Object.entries(data?.lanes ?? {});

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            Drawdown Guard
            {data?.global_allowed != null && (
              <Badge variant={data.global_allowed ? 'success' : 'danger'} size="sm">
                global {data.global_allowed ? 'allowed' : 'blocked'}
              </Badge>
            )}
          </CardTitle>
          <FreshnessChip error={poll.error} lastOk={poll.lastOk} />
        </div>
      </CardHeader>
      <CardContent>
        {poll.loading && !data ? (
          <div className="text-center py-4 text-slate-500">Loading drawdown guard…</div>
        ) : poll.error && !data ? (
          <div className="text-center py-4 text-red-400 text-xs" role="alert">
            DD guard unavailable: {poll.error}
          </div>
        ) : data?.ok === false ? (
          <div className="text-xs text-red-400" role="alert">
            DD guard unavailable: {data.error ?? 'backend reported failure'}
          </div>
        ) : lanes.length === 0 ? (
          <div className="text-center py-4 text-slate-500">No drawdown lanes reported</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="drawdown guard lanes">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3" scope="col">Lane</th>
                  <th className="text-right p-3" scope="col">Equity</th>
                  <th className="text-right p-3" scope="col">Peak</th>
                  <th className="text-right p-3" scope="col">Drawdown</th>
                  <th className="text-right p-3" scope="col">Limit</th>
                  <th className="text-right p-3" scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {lanes.map(([key, lane]) => {
                  const dd = numOr(lane.drawdown);
                  const lim = numOr(lane.limit);
                  const ddPct = dd != null ? (dd <= 1 ? dd * 100 : dd) : null;
                  const limPct = lim != null ? (lim <= 1 ? lim * 100 : lim) : null;
                  return (
                    <tr key={key} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 font-medium text-white">{key}</td>
                      <td className="p-3 text-right tabular-nums text-white">{usdOr(lane.equity)}</td>
                      <td className="p-3 text-right tabular-nums text-white">{usdOr(lane.peak)}</td>
                      <td className="p-3 text-right tabular-nums">
                        <span className={cx(
                          ddPct != null && limPct != null && ddPct >= limPct * 0.8
                            ? 'text-amber-400'
                            : 'text-white',
                        )}>
                          {ddPct != null ? `${ddPct.toFixed(1)}%` : 'n/a'}
                        </span>
                      </td>
                      <td className="p-3 text-right tabular-nums text-white">
                        {limPct != null ? `${limPct.toFixed(1)}%` : 'n/a'}
                      </td>
                      <td className="p-3 text-right">
                        <Badge variant={lane.allowed !== false ? 'success' : 'danger'} size="sm">
                          {lane.allowed !== false ? 'allowed' : 'braked'}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

const OrderErrorsPanel = memo(function OrderErrorsPanel() {
  const poll = usePoll<OrderErrors>(AGENT_ENDPOINTS.ORDER_ERRORS, { ms: 30_000, map: objMap });
  const data = poll.data;
  const rows = data?.breakdown ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            Order Rejection Taxonomy
            {data?.total_rejections != null && (
              <span className="text-xs font-normal text-slate-500 tabular-nums">
                {data.total_rejections} in {data.window_hours ?? '?'}h
              </span>
            )}
          </CardTitle>
          <FreshnessChip error={poll.error} lastOk={poll.lastOk} />
        </div>
      </CardHeader>
      <CardContent>
        {poll.loading && !data ? (
          <div className="text-center py-4 text-slate-500">Loading order errors…</div>
        ) : rows.length === 0 ? (
          <div className="text-center py-4 text-slate-500">
            {poll.error ? `Order-error source unavailable: ${poll.error}` : 'No order rejections recorded in window'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="order rejection breakdown">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3" scope="col">Code</th>
                  <th className="text-left p-3" scope="col">Category</th>
                  <th className="text-right p-3" scope="col">Count</th>
                  <th className="text-right p-3" scope="col">Share</th>
                  <th className="text-left p-3" scope="col">Severity</th>
                  <th className="text-left p-3" scope="col">Retryable</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.code ?? i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-3">
                      <div className="font-medium text-white font-mono text-xs">{r.code ?? 'unknown'}</div>
                      {r.description && (
                        <div className="text-[10px] text-slate-500 mt-0.5">{r.description}</div>
                      )}
                    </td>
                    <td className="p-3 text-xs text-slate-400">{r.category ?? '—'}</td>
                    <td className="p-3 text-right tabular-nums text-white">{r.count ?? '—'}</td>
                    <td className="p-3 text-right tabular-nums text-white">
                      {numOr(r.percentage) != null ? `${numOr(r.percentage)?.toFixed(1)}%` : '—'}
                    </td>
                    <td className="p-3">
                      <Badge variant={severityVariant(r.severity)} size="sm">
                        {r.severity ?? 'unknown'}
                      </Badge>
                    </td>
                    <td className="p-3 text-xs text-slate-400">
                      {r.is_retryable == null ? '—' : r.is_retryable ? 'yes' : 'no'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

const GuardVerdictsPanel = memo(function GuardVerdictsPanel() {
  const poll = usePoll<GuardVerdicts>(
    `${AGENT_ENDPOINTS.GUARD_VERDICTS}?limit=25`, { ms: 15_000, map: objMap },
  );
  const verdicts = (poll.data?.verdicts ?? []).slice(-25).reverse();

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Recent Guard Verdicts</CardTitle>
          <FreshnessChip error={poll.error} lastOk={poll.lastOk} />
        </div>
      </CardHeader>
      <CardContent>
        {poll.loading && !poll.data ? (
          <div className="text-center py-4 text-slate-500">Loading guard verdicts…</div>
        ) : verdicts.length === 0 ? (
          <div className="text-center py-4 text-slate-500">
            {poll.error ? `Guard verdicts unavailable: ${poll.error}` : 'No recent verdicts'}
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {verdicts.map((v, i) => (
              <div key={`${v.plan_id ?? v.ts ?? i}`} className="p-3 rounded-lg border border-slate-700">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-white break-words flex-1">
                    {v.reason ?? v.action ?? 'no reason recorded'}
                  </span>
                  <Badge variant={v.allowed === false ? 'danger' : 'success'} size="sm">
                    {v.allowed === false ? 'BLOCKED' : 'ALLOWED'}
                  </Badge>
                </div>
                <div className="text-xs text-slate-400 mt-1 flex items-center gap-3 flex-wrap tabular-nums">
                  <span>{(() => {
                    const ms = parseTsMs(v.ts);
                    return ms != null ? new Date(ms).toLocaleString() : 'n/a';
                  })()}</span>
                  {v.ticker && <span className="font-mono">{v.ticker}</span>}
                  {v.domain && <span>domain {v.domain}</span>}
                  {numOr(v.throttle_pct) != null && (
                    <span>throttle {((numOr(v.throttle_pct) ?? 0) * 100).toFixed(0)}%</span>
                  )}
                  {numOr(v.cqi_score) != null && (
                    <span>CQI {numOr(v.cqi_score)?.toFixed(2)}</span>
                  )}
                </div>
                {v.checks_failed && v.checks_failed.length > 0 && (
                  <div className="text-[10px] text-red-400/80 mt-1">
                    failed: {v.checks_failed.slice(0, 6).join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
});

const ReconPanel = memo(function ReconPanel() {
  const poll = usePoll<ReconHealth>(
    '/api/v1/kalshi/health/reconciliation', { ms: 30_000, map: objMap },
  );
  const data = poll.data;
  const divergenceCount = numOr(data?.divergence_count) ?? (data?.divergences?.length ?? 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            Reconciliation Health
            {data?.status && (
              <Badge variant={reconVariant(data.status)} size="sm">
                {data.status}
              </Badge>
            )}
          </CardTitle>
          <FreshnessChip error={poll.error} lastOk={poll.lastOk} />
        </div>
      </CardHeader>
      <CardContent>
        {poll.loading && !data ? (
          <div className="text-center py-4 text-slate-500">Loading reconciliation status…</div>
        ) : poll.error && !data ? (
          <div className="text-center py-4 text-red-400 text-xs" role="alert">
            Reconciliation status unavailable: {poll.error}
          </div>
        ) : !data || (!data.status && !data.message) ? (
          <div className="text-center py-4 text-slate-500">Reconciliation status unavailable</div>
        ) : (
          <div className="space-y-3">
            {data.message && <div className="text-sm text-slate-300">{data.message}</div>}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              <RiskRow label="Divergences">
                <span className={cx('tabular-nums', divergenceCount > 0 ? 'text-red-400' : 'text-white')}>
                  {divergenceCount}
                </span>
              </RiskRow>
              <RiskRow label="Ghost Trade Candidates">
                <span className={cx(
                  'tabular-nums',
                  (numOr(data.ghost_trade_candidates) ?? 0) > 0 ? 'text-amber-400' : 'text-white',
                )}>
                  {numOr(data.ghost_trade_candidates) ?? 'n/a'}
                </span>
              </RiskRow>
              <RiskRow label="Last Run">
                <span className="text-white tabular-nums">
                  {parseTsMs(data.last_run) != null
                    ? `${fmtAgeMs(Date.now() - (parseTsMs(data.last_run) ?? 0))} ago`
                    : 'n/a'}
                </span>
              </RiskRow>
              <RiskRow label="Last Fill Poll OK">
                <span className="text-white tabular-nums">
                  {parseTsMs(data.last_success_at) != null
                    ? `${fmtAgeMs(Date.now() - (parseTsMs(data.last_success_at) ?? 0))} ago`
                    : 'n/a'}
                </span>
              </RiskRow>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

/* ------------------------------------------------------------------ */
/* View                                                                */
/* ------------------------------------------------------------------ */

const Risk = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const risk = useKalshiStore(selectRisk);
  const system = useKalshiStore(selectSystem);
  const connected = useKalshiStore(selectConnected);
  const inFlightRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<ActionKind | null>(null);

  const entryHalted = system.live?.entry_halted === true;

  const runAction = async (kind: ActionKind) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      if (kind === 'activate') await setKalshiKillSwitch(true);
      else if (kind === 'reset') await setKalshiKillSwitch(false);
      else if (kind === 'halt') await haltEntries('operator_halt');
      else await releaseEntries();
      await refreshAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlightRef.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Gauge className="w-8 h-8 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Risk</h1>
            <p className="text-sm text-slate-400">Safety controls, limits and guard telemetry</p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      {/* (a) Kill switch + halt/release — preserved mutation pattern */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-red-400" />
            Kill Switch &amp; Live Entries
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
                    Kill switch {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
                  </Badge>
                  {risk.kill_switch_reason && (
                    <span className="text-sm text-slate-400">{risk.kill_switch_reason}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={risk.kill_switch_active ? 'outline' : 'danger'}
                    disabled={busy || risk.kill_switch_active}
                    onClick={() => setConfirmAction('activate')}
                  >
                    Activate
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !risk.kill_switch_active}
                    onClick={() => setConfirmAction('reset')}
                  >
                    Reset
                  </Button>
                </div>
              </div>
              <div className="flex items-center justify-between border-t border-slate-700/60 pt-4">
                <div className="flex items-center gap-3">
                  <Badge variant={entryHalted ? 'warning' : 'success'}>
                    {system.live?.state ?? 'UNKNOWN'}
                  </Badge>
                  {system.live?.reason && (
                    <span className="text-sm text-slate-400">{system.live.reason}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy || entryHalted}
                    onClick={() => setConfirmAction('halt')}
                  >
                    Halt Entries
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !entryHalted}
                    onClick={() => setConfirmAction('release')}
                  >
                    Release Entries
                  </Button>
                </div>
              </div>
              {actionError && (
                <div className="text-xs text-red-400 break-words">Error: {actionError}</div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* (b) Risk summary tiles */}
      <Card>
        <CardHeader>
          <CardTitle>Risk Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              <RiskRow label="Daily PnL">
                <span className={risk.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  ${risk.daily_pnl.toFixed(2)}
                </span>
              </RiskRow>
              <RiskRow label="Realized / Unrealized">
                <span className="text-white">
                  ${risk.realized_pnl.toFixed(2)} / ${risk.unrealized_pnl.toFixed(2)}
                </span>
              </RiskRow>
              <RiskRow label="Drawdown">
                <span className="text-white">{risk.drawdown_pct.toFixed(2)}%</span>
              </RiskRow>
              <RiskRow label="Total Notional">
                <span className="text-white">${risk.total_notional.toFixed(2)}</span>
              </RiskRow>
              <RiskRow label="Open Markets / Daily Trades">
                <span className="text-white">{risk.open_market_count} / {risk.daily_trades}</span>
              </RiskRow>
              <RiskRow label="Win Rate">
                <span className="text-white">{risk.win_rate_pct.toFixed(1)}%</span>
              </RiskRow>
              <RiskRow label="Sharpe / Profit Factor">
                <span className="text-white">
                  {risk.sharpe_ratio.toFixed(2)} / {risk.profit_factor.toFixed(2)}
                </span>
              </RiskRow>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configured Limits</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : Object.keys(risk.limits).length === 0 ? (
            <div className="text-center py-4 text-slate-500">No limits reported by backend</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              {risk.limits.max_notional_usd != null && (
                <RiskRow label="Max Notional">
                  <span className="text-white">${risk.limits.max_notional_usd.toFixed(2)}</span>
                </RiskRow>
              )}
              {risk.limits.max_open_markets != null && (
                <RiskRow label="Max Open Markets">
                  <span className="text-white">{risk.limits.max_open_markets}</span>
                </RiskRow>
              )}
              {risk.limits.daily_loss_limit != null && (
                <RiskRow label="Daily Loss Limit">
                  <span className="text-white">${risk.limits.daily_loss_limit.toFixed(2)}</span>
                </RiskRow>
              )}
              {risk.limits.max_drawdown_pct != null && (
                <RiskRow label="Max Drawdown">
                  <span className="text-white">{risk.limits.max_drawdown_pct.toFixed(1)}%</span>
                </RiskRow>
              )}
              {risk.limits.max_orders_per_minute != null && (
                <RiskRow label="Max Orders / Min">
                  <span className="text-white">{risk.limits.max_orders_per_minute}</span>
                </RiskRow>
              )}
              {risk.limits.max_orders_per_hour != null && (
                <RiskRow label="Max Orders / Hour">
                  <span className="text-white">{risk.limits.max_orders_per_hour}</span>
                </RiskRow>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* (c) Live guard telemetry */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <EnvelopePanel />
        <DdGuardPanel />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <OrderErrorsPanel />
        <ReconPanel />
      </div>
      <GuardVerdictsPanel />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingDown className="w-5 h-5 text-yellow-400" />
            Recent Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : risk.alerts.length === 0 ? (
            <div className="text-center py-4 text-slate-500">No recent alerts</div>
          ) : (
            <div className="space-y-2">
              {risk.alerts.map((alert) => (
                <div key={alert.id} className="p-3 rounded-lg border border-slate-700">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white">{alert.message}</span>
                    <Badge variant={alert.severity === 'critical' ? 'danger' : 'warning'}>
                      {alert.severity}
                    </Badge>
                  </div>
                  <div className="text-xs text-slate-400 mt-1">
                    {new Date(alert.timestamp).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmModal
        isOpen={confirmAction !== null}
        title={
          confirmAction === 'activate' ? 'Activate Kill Switch'
            : confirmAction === 'reset' ? 'Reset Kill Switch'
            : confirmAction === 'halt' ? 'Halt Live Entries'
            : 'Release Live Entries'
        }
        message={
          confirmAction === 'activate'
            ? 'Activate the Kalshi kill switch? This halts all trading immediately.'
            : confirmAction === 'reset'
              ? 'Reset the kill switch? Trading remains subject to runtime halt gates.'
              : confirmAction === 'halt'
                ? 'Halt new live entries? Exits and cancellations remain active.'
                : 'Release live entries? Entries resume only if all safety gates pass.'
        }
        confirmText="Confirm"
        confirmVariant={confirmAction === 'activate' || confirmAction === 'halt' ? 'danger' : 'primary'}
        onConfirm={() => {
          const kind = confirmAction;
          setConfirmAction(null);
          if (kind) void runAction(kind);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
};

export default Risk;
