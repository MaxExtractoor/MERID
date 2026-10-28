/**
 * System — consolidated observability view (folds Calibration + Logs +
 * Settings).
 *
 * Tabs:
 *  - Calibration:  GET /api/v1/kalshi/calibration/stats       -> Brier buckets
 *                  GET /api/v1/kalshi/calibration/cell-metrics -> per-cell
 *                  order-flow (candidates/vetoes/fills/edge/pnl). The
 *                  CalibrationCurve only renders cells that carry a real
 *                  realized win-rate field — the current cell-metrics payload
 *                  has none, so the instrument honestly shows its empty state.
 *  - Tick Log:     GET /api/v1/loop/tick-log?limit=100 -> {ticks, count}
 *                  capped table with level colouring + level filter.
 *  - System State: read-only. live-runtime-state, unified-health services,
 *                  /api/health/kalshi-readiness, mode, connection state.
 *                  No save buttons, no dead config writes.
 */

import { memo, useMemo, useState } from 'react';
import {
  useKalshiStore, selectRisk, selectSystem, selectConnected,
} from '../store';
import { usePoll } from '../hooks/usePoll';
import { AGENT_ENDPOINTS } from '../agents/api';
import {
  Activity, CheckCircle, FileText, Filter, Settings as SettingsIcon,
  Shield, Target, XCircle,
} from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { CalibrationCurve } from '../components/instruments/CalibrationCurve';
import type { CalibrationCell } from '../components/instruments/CalibrationCurve';
import { cx, fmtAgeMs, numOr } from '../agents/format';

/* ------------------------------------------------------------------ */
/* Server shapes (defensive)                                           */
/* ------------------------------------------------------------------ */

interface BucketStat {
  bucket: string;
  ewma_brier: number;
  n_resolved: number;
  brier_sum?: number;
  brier_sum_sq?: number;
  weight: number;
}

interface CalibrationStatsResponse {
  forecasters?: number;
  bucket_filter?: string | null;
  stats?: Record<string, BucketStat[]>;
  error?: string;
}

interface CellMetrics {
  asset?: string;
  timeframe?: string;
  candidates?: number;
  vetoes?: number;
  orders_submitted?: number;
  fills?: number;
  avg_edge?: number;
  fill_rate?: number;
  cost_cents?: number;
  fill_cents?: number;
  pnl_cents?: number;
  veto_reasons?: Record<string, number>;
  last_order_ts?: number | null;
  last_fill_ts?: number | null;
  /** Realized win-rate fields — not emitted today; mapped defensively. */
  win_rate?: number;
  settle_rate?: number;
  realized_win_rate?: number;
  price_c?: number;
  avg_price_c?: number;
  mid_c?: number;
}

interface CellMetricsResponse {
  cells?: Record<string, CellMetrics>;
  count?: number;
  error?: string;
}

interface TickEntry {
  tick?: number;
  ts?: number;
  duration_ms?: number;
  actions?: string[];
  plans?: { generated?: number; executed?: number; blocked?: number };
  guard?: { kill_switch?: boolean };
  error?: string;
}

interface TickLogResponse {
  ticks?: TickEntry[];
  count?: number;
}

interface ReadinessResponse {
  status?: string;
  error?: string;
  reasons?: string[];
  config_valid?: boolean;
  config_error?: string | null;
  ws_connected?: boolean;
  ws_md_age_ms?: number;
  catalog?: { state?: string; age_s?: number; thread_alive?: boolean };
  spot?: Record<string, { state?: string; age_ms?: number }>;
  md?: Record<string, { state?: string; age_ms?: number }>;
}

/* ------------------------------------------------------------------ */
/* Mappers                                                             */
/* ------------------------------------------------------------------ */

const mapStats = (raw: unknown): CalibrationStatsResponse =>
  (raw && typeof raw === 'object' ? (raw as CalibrationStatsResponse) : {});

const mapCells = (raw: unknown): CellMetricsResponse =>
  (raw && typeof raw === 'object' ? (raw as CellMetricsResponse) : {});

const mapTickLog = (raw: unknown): TickLogResponse =>
  (raw && typeof raw === 'object' ? (raw as TickLogResponse) : {});

const mapReadiness = (raw: unknown): ReadinessResponse =>
  (raw && typeof raw === 'object' ? (raw as ReadinessResponse) : {});

/** Extract a realized win-rate cell only when the backend reports one. */
const toCalibrationCells = (cells: Record<string, CellMetrics>): CalibrationCell[] => {
  const out: CalibrationCell[] = [];
  for (const c of Object.values(cells)) {
    if (!c || typeof c !== 'object') continue;
    const win = numOr(c.win_rate) ?? numOr(c.settle_rate) ?? numOr(c.realized_win_rate);
    const price = numOr(c.price_c) ?? numOr(c.avg_price_c) ?? numOr(c.mid_c);
    if (win == null || price == null) continue; // honest: no win-rate data -> no point
    out.push({
      price_c: price,
      win_rate: win,
      n: numOr(c.fills) ?? numOr(c.orders_submitted) ?? 0,
    });
  }
  return out;
};

type TickLevel = 'info' | 'warning' | 'error';
interface TickRow { id: string; tsMs: number | null; level: TickLevel; message: string }

const toTickRow = (t: TickEntry, idx: number): TickRow => {
  const kill = t.guard?.kill_switch === true;
  const blocked = numOr(t.plans?.blocked) ?? 0;
  const level: TickLevel = t.error ? 'error' : (kill || blocked > 0 ? 'warning' : 'info');
  const parts = [`tick ${t.tick ?? idx}`];
  if (t.actions && t.actions.length > 0) parts.push(t.actions.join(', '));
  if (t.plans) {
    parts.push(
      `plans gen=${numOr(t.plans.generated) ?? 0} exec=${numOr(t.plans.executed) ?? 0} blocked=${blocked}`,
    );
  }
  if (t.duration_ms != null) parts.push(`${t.duration_ms}ms`);
  if (kill) parts.push('KILL SWITCH ACTIVE');
  if (t.error) parts.push(`error: ${t.error}`);
  const tsMs = typeof t.ts === 'number' && Number.isFinite(t.ts)
    ? (t.ts > 1e12 ? t.ts : t.ts * 1000)
    : null;
  return { id: `tick-${t.tick ?? idx}-${t.ts ?? 0}`, tsMs, level, message: parts.join(' · ') };
};

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

const StateRow = memo(function StateRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-800/50 last:border-0">
      <span className="text-slate-400 text-sm">{label}</span>
      {children}
    </div>
  );
});

const readinessVariant = (status?: string): 'success' | 'warning' | 'danger' => {
  const s = (status ?? '').toLowerCase();
  if (s === 'healthy' || s === 'ready' || s === 'ok') return 'success';
  if (s === 'degraded' || s === 'partial') return 'warning';
  return 'danger';
};

const centsToUsd = (c: number | undefined): string =>
  c == null ? 'n/a' : `$${(c / 100).toFixed(2)}`;

/* ------------------------------------------------------------------ */
/* Tabs                                                                */
/* ------------------------------------------------------------------ */

type TabId = 'calibration' | 'ticklog' | 'state';

const TABS: Array<{ id: TabId; label: string; icon: React.ReactNode }> = [
  { id: 'calibration', label: 'Calibration', icon: <Target className="w-4 h-4" /> },
  { id: 'ticklog', label: 'Tick Log', icon: <FileText className="w-4 h-4" /> },
  { id: 'state', label: 'System State', icon: <Activity className="w-4 h-4" /> },
];

function CalibrationTab() {
  const statsPoll = usePoll<CalibrationStatsResponse>(
    AGENT_ENDPOINTS.CALIBRATION_STATS, { ms: 60_000, map: mapStats },
  );
  const cellsPoll = usePoll<CellMetricsResponse>(
    AGENT_ENDPOINTS.CALIBRATION_CELLS, { ms: 30_000, map: mapCells },
  );

  const stats = statsPoll.data?.stats ?? {};
  const statRows = Object.entries(stats).flatMap(([forecaster, buckets]) =>
    (buckets ?? []).map((b) => ({ forecaster, ...b })),
  );
  const cellsRecord = cellsPoll.data?.cells;
  const cellRows = Object.entries(cellsRecord ?? {});
  const curveCells = useMemo(
    () => toCalibrationCells(cellsRecord ?? {}),
    [cellsRecord],
  );

  return (
    <div className="space-y-4">
      {/* Win-rate calibration curve (cells with real win-rate data only) */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Realized Win-Rate vs Implied Price</CardTitle>
            <FreshnessChip error={cellsPoll.error} lastOk={cellsPoll.lastOk} />
          </div>
        </CardHeader>
        <CardContent>
          <CalibrationCurve cells={curveCells} height={220} />
          {curveCells.length === 0 && !cellsPoll.error && (
            <p className="mt-2 text-[10px] text-slate-600">
              Cell metrics do not report per-price realized win rates — curve
              renders only when win-rate data is present.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Brier stats */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Forecaster Calibration (Brier)</CardTitle>
            <FreshnessChip error={statsPoll.error} lastOk={statsPoll.lastOk} />
          </div>
        </CardHeader>
        <CardContent>
          {statRows.length === 0 ? (
            <div className="text-center py-8 text-slate-500">
              {statsPoll.error ? `Calibration stats unavailable: ${statsPoll.error}` : 'No calibration data available'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="forecaster brier stats">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3" scope="col">Forecaster</th>
                    <th className="text-left p-3" scope="col">Bucket</th>
                    <th className="text-right p-3" scope="col">Resolved</th>
                    <th className="text-right p-3" scope="col">EWMA Brier</th>
                    <th className="text-right p-3" scope="col">Consensus Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {statRows.map((row) => (
                    <tr key={`${row.forecaster}:${row.bucket}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 font-medium text-white">{row.forecaster}</td>
                      <td className="p-3"><Badge variant="info">{row.bucket}</Badge></td>
                      <td className="p-3 text-right font-mono tabular-nums text-white">{row.n_resolved}</td>
                      <td className="p-3 text-right font-mono tabular-nums text-white">
                        {numOr(row.ewma_brier)?.toFixed(4) ?? 'n/a'}
                      </td>
                      <td className="p-3 text-right font-mono tabular-nums text-white">
                        {numOr(row.weight) != null ? `${(row.weight * 100).toFixed(1)}%` : 'n/a'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Cell metrics */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Per-Cell Order-Flow (asset × timeframe)</CardTitle>
            <span className="text-[10px] text-slate-600 tabular-nums">
              {cellsPoll.data?.count ?? cellRows.length} cell(s)
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {cellRows.length === 0 ? (
            <div className="text-center py-8 text-slate-500">
              {cellsPoll.error ? `Cell metrics unavailable: ${cellsPoll.error}` : 'No cell metrics available'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="cell order-flow metrics">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3" scope="col">Cell</th>
                    <th className="text-right p-3" scope="col">Candidates</th>
                    <th className="text-right p-3" scope="col">Vetoes</th>
                    <th className="text-right p-3" scope="col">Orders</th>
                    <th className="text-right p-3" scope="col">Fills (n)</th>
                    <th className="text-right p-3" scope="col">Win Rate</th>
                    <th className="text-right p-3" scope="col">Fill Rate</th>
                    <th className="text-right p-3" scope="col">Avg Edge</th>
                    <th className="text-right p-3" scope="col">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {cellRows.map(([key, cell]) => {
                    const win = numOr(cell.win_rate) ?? numOr(cell.settle_rate) ?? numOr(cell.realized_win_rate);
                    const pnl = numOr(cell.pnl_cents);
                    return (
                      <tr key={key} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                        <td className="p-3">
                          <div className="font-medium text-white">
                            {cell.asset ?? key.split('/')[0]}/{cell.timeframe ?? key.split('/')[1] ?? 'n/a'}
                          </div>
                          {cell.veto_reasons && Object.keys(cell.veto_reasons).length > 0 && (
                            <div className="text-[10px] text-slate-500 mt-0.5">
                              vetoes: {Object.entries(cell.veto_reasons).map(([r, n]) => `${r}:${n}`).join(', ')}
                            </div>
                          )}
                        </td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">{cell.candidates ?? '—'}</td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">{cell.vetoes ?? '—'}</td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">{cell.orders_submitted ?? '—'}</td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">{cell.fills ?? '—'}</td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">
                          {win != null ? `${(win > 1 ? win : win * 100).toFixed(1)}%` : 'n/a'}
                        </td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">
                          {numOr(cell.fill_rate) != null ? `${((numOr(cell.fill_rate) ?? 0) * 100).toFixed(0)}%` : 'n/a'}
                        </td>
                        <td className="p-3 text-right font-mono tabular-nums text-white">
                          {numOr(cell.avg_edge)?.toFixed(4) ?? 'n/a'}
                        </td>
                        <td
                          className={cx(
                            'p-3 text-right font-mono tabular-nums',
                            pnl == null ? 'text-slate-500' : pnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                          )}
                        >
                          {centsToUsd(pnl)}
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
    </div>
  );
}

function TickLogTab() {
  const [levelFilter, setLevelFilter] = useState<'all' | TickLevel>('all');
  const tickPoll = usePoll<TickLogResponse>(
    `${AGENT_ENDPOINTS.TICK_LOG}?limit=100`, { ms: 10_000, map: mapTickLog },
  );

  const rows = useMemo(
    () => (tickPoll.data?.ticks ?? []).slice(0, 100).map(toTickRow),
    [tickPoll.data],
  );
  const filtered = levelFilter === 'all' ? rows : rows.filter((r) => r.level === levelFilter);

  const levelVariant = (l: TickLevel): 'danger' | 'warning' | 'success' =>
    l === 'error' ? 'danger' : l === 'warning' ? 'warning' : 'success';

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Loop Tick Log</CardTitle>
          <div className="flex items-center gap-3">
            <FreshnessChip error={tickPoll.error} lastOk={tickPoll.lastOk} />
            <span className="text-[10px] text-slate-600 tabular-nums">
              {tickPoll.data?.count ?? rows.length} tick(s)
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2 mb-4">
          <Filter className="w-4 h-4 text-slate-500" />
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as typeof levelFilter)}
            className="bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600"
            aria-label="Filter by log level"
          >
            <option value="all">All Levels</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </div>

        {tickPoll.loading && !tickPoll.data ? (
          <div className="text-center py-8 text-slate-500">Loading tick log…</div>
        ) : rows.length === 0 ? (
          <div className="text-center py-8 text-slate-500">
            {tickPoll.error ? `Tick log unavailable: ${tickPoll.error}` : 'No tick log entries'}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-slate-500">No entries match the current filter</div>
        ) : (
          <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
            <table className="w-full text-sm" aria-label="loop tick log">
              <thead className="sticky top-0 bg-slate-800 z-10">
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3" scope="col">Timestamp</th>
                  <th className="text-left p-3" scope="col">Level</th>
                  <th className="text-left p-3" scope="col">Component</th>
                  <th className="text-left p-3" scope="col">Message</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr key={row.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-3 text-xs text-slate-400 font-mono tabular-nums whitespace-nowrap">
                      {row.tsMs != null ? new Date(row.tsMs).toLocaleString() : 'n/a'}
                    </td>
                    <td className="p-3">
                      <Badge variant={levelVariant(row.level)}>{row.level.toUpperCase()}</Badge>
                    </td>
                    <td className="p-3 text-xs text-slate-400">merid-loop</td>
                    <td className="p-3 text-white">{row.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SystemStateTab() {
  const system = useKalshiStore(selectSystem);
  const risk = useKalshiStore(selectRisk);
  const connected = useKalshiStore(selectConnected);
  const readinessPoll = usePoll<ReadinessResponse>(
    '/api/health/kalshi-readiness', { ms: 30_000, map: mapReadiness },
  );

  const readiness = readinessPoll.data;
  const services = Object.entries(system.health.services);

  return (
    <div className="space-y-4">
      {/* Runtime state — read only */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-400" />
            Runtime State
          </CardTitle>
        </CardHeader>
        <CardContent>
          <StateRow label="Order mode">
            <Badge variant={system.mode === 'live' ? 'success' : 'info'}>
              {system.mode.toUpperCase()}
            </Badge>
          </StateRow>
          <StateRow label="Live runtime state">
            <Badge variant={system.live?.entry_halted ? 'warning' : 'success'}>
              {system.live?.state ?? 'UNKNOWN'}
            </Badge>
          </StateRow>
          {system.live?.reason && (
            <div className="text-xs text-slate-500 py-1">Reason: {system.live.reason}</div>
          )}
          <StateRow label="Kill switch">
            <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
              {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
            </Badge>
          </StateRow>
          {risk.kill_switch_reason !== '' && (
            <div className="text-xs text-slate-500 py-1">{risk.kill_switch_reason}</div>
          )}
          <StateRow label="Backend startup">
            <span className="text-white text-sm tabular-nums">
              {system.startup_completed ? 'completed' : 'in progress / unknown'}
            </span>
          </StateRow>
          <StateRow label="Connection">
            <Badge variant={connected ? 'success' : 'danger'}>
              {connected ? 'Connected' : 'Disconnected'}
            </Badge>
          </StateRow>
          {system.error && (
            <div className="text-xs text-red-400 py-1" role="alert">
              System slice error: {system.error}
            </div>
          )}
          <p className="text-[10px] text-slate-600 mt-2">
            Read-only — runtime changes go through the trading process and the
            Risk view controls, not this panel.
          </p>
        </CardContent>
      </Card>

      {/* Unified health services */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-emerald-400" />
              Unified Health
            </CardTitle>
            <Badge variant={system.health.ok ? 'success' : 'warning'}>
              {system.health.ok ? 'ok' : 'degraded / unknown'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {services.length === 0 ? (
            <div className="text-center py-6 text-slate-500 text-sm">
              No service health reported
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {services.map(([name, svc]) => (
                <div
                  key={name}
                  className="flex items-center justify-between p-2 rounded border border-slate-700/60"
                >
                  <span className="text-sm text-slate-300 flex items-center gap-2">
                    {svc.ok
                      ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                      : <XCircle className="w-3.5 h-3.5 text-red-400" />}
                    {name}
                  </span>
                  <div className="flex items-center gap-2">
                    {svc.error && (
                      <span className="text-[10px] text-slate-500 max-w-[180px] truncate" title={svc.error}>
                        {svc.error}
                      </span>
                    )}
                    <Badge variant={svc.ok ? 'success' : 'danger'} size="sm">
                      {svc.ok ? 'ok' : 'degraded'}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Kalshi readiness */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Shield className="w-5 h-5 text-cyan-400" />
              Kalshi Venue Readiness
            </CardTitle>
            <FreshnessChip error={readinessPoll.error} lastOk={readinessPoll.lastOk} />
          </div>
        </CardHeader>
        <CardContent>
          {readinessPoll.loading && !readiness ? (
            <div className="text-center py-6 text-slate-500 text-sm">Checking venue readiness…</div>
          ) : readinessPoll.error && !readiness ? (
            <div className="text-xs text-red-400" role="alert">
              Readiness check failed: {readinessPoll.error}
            </div>
          ) : (
            <div className="space-y-3">
              <StateRow label="Overall status">
                <Badge variant={readinessVariant(readiness?.status)}>
                  {(readiness?.status ?? 'unavailable').toUpperCase()}
                </Badge>
              </StateRow>
              {readiness?.config_valid != null && (
                <StateRow label="Config valid">
                  <Badge variant={readiness.config_valid ? 'success' : 'danger'}>
                    {readiness.config_valid ? 'yes' : 'no'}
                  </Badge>
                </StateRow>
              )}
              {readiness?.ws_connected != null && (
                <StateRow label="Venue WS connected">
                  <Badge variant={readiness.ws_connected ? 'success' : 'danger'}>
                    {readiness.ws_connected ? 'yes' : 'no'}
                  </Badge>
                </StateRow>
              )}
              {readiness?.ws_md_age_ms != null && (
                <StateRow label="WS market-data age">
                  <span className="text-white text-sm tabular-nums">
                    {fmtAgeMs(readiness.ws_md_age_ms)}
                  </span>
                </StateRow>
              )}
              {readiness?.catalog && (
                <StateRow label="Market catalog">
                  <span className="text-sm">
                    <Badge variant={readiness.catalog.state === 'live' || readiness.catalog.state === 'ready' ? 'success' : 'warning'}>
                      {readiness.catalog.state ?? 'unknown'}
                    </Badge>
                    {readiness.catalog.age_s != null && (
                      <span className="ml-2 text-slate-400 tabular-nums">
                        age {fmtAgeMs(readiness.catalog.age_s * 1000)}
                      </span>
                    )}
                  </span>
                </StateRow>
              )}
              {readiness?.error && (
                <div className="text-xs text-red-400">{readiness.error}</div>
              )}
              {readiness?.config_error && (
                <div className="text-xs text-red-400">config: {readiness.config_error}</div>
              )}
              {(readiness?.reasons?.length ?? 0) > 0 && (
                <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
                  {(readiness?.reasons ?? []).slice(0, 8).map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* View                                                                */
/* ------------------------------------------------------------------ */

const System = () => {
  const connected = useKalshiStore(selectConnected);
  const [tab, setTab] = useState<TabId>('calibration');

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <SettingsIcon className="w-8 h-8 text-slate-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">System</h1>
            <p className="text-sm text-slate-400">
              Calibration, tick log and live system state (read-only)
            </p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit" role="tablist" aria-label="System view tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`${t.id}-panel`}
            onClick={() => setTab(t.id)}
            className={cx(
              'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium',
              tab === t.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white',
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`${tab}-panel`}>
        {tab === 'calibration' && <CalibrationTab />}
        {tab === 'ticklog' && <TickLogTab />}
        {tab === 'state' && <SystemStateTab />}
      </div>
    </div>
  );
};

export default System;
