/**
 * KalshiBankrollPanel — Live view of the BankrollManager state from
 * the continuous multi-asset trader.
 *
 * Shows: bankroll, drawdown, PnL, win rate, fee drag, vol band,
 * effective limits, and [TIGHT] status. Polls every 10s.
 */

import { useState, useCallback } from 'react';
import {
  DollarSign, TrendingUp, TrendingDown, Activity,
  AlertTriangle, Shield, Gauge, BarChart3,
  ChevronDown, ChevronUp, StopCircle,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';

/* ═══════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════ */

interface TraderStatus {
  available: boolean;
  running: boolean;
  cycle: number;
  dry_run: boolean;
  interval_seconds: number;
  balance_cents: number;
  portfolio_cents: number;
  total_value_cents: number;
  peak_balance_cents: number;
  drawdown_pct: number;
  halted: boolean;
  halt_reason: string;
  total_trades: number;
  total_wins: number;
  total_losses: number;
  win_rate_pct: number;
  total_pnl_cents: number;
  total_fees_cents: number;
  fee_drag_pct: number;
  fee_drag_tightening: boolean;
  fee_drag_window: number;
  vol_band: string;
  annualized_vol_pct: number;
  eff_max_orders_per_cycle: number;
  eff_max_exposure_pct: number;
  orders_placed: number;
  orders_filled: number;
  orders_cancelled: number;
  resting_orders: number;
  /** Omitted or partial when CT snapshot is degraded — always optional-chain in UI. */
  config?: {
    initial_bankroll_cents: number;
    kelly_fraction: number;
    max_risk_per_trade_pct: number;
    max_contract_price_cents: number;
    min_edge: string;
    drawdown_halt_pct: number;
    drawdown_reduce_pct: number;
    churn_cooldown_cycles: number;
    churn_edge_improvement: number;
    max_fee_drag_pct: number;
    vol_low_threshold: number;
    vol_high_threshold: number;
    fee_window_low_vol: number;
    fee_window_mid_vol: number;
    fee_window_high_vol: number;
  };
  cycle_history: Array<{
    cycle: number;
    drawdown_pct: number;
    fee_drag_pct: number;
    pnl_cents: number;
    balance_cents: number;
    vol_pct: number;
  }>;
  reason?: string;
  /** Set when status_snapshot throws but trader exists (see kalshi_continuous_trader_api). */
  error?: string;
  /** From CT snapshot — unified execution gate */
  execution_gate_state?: string | null;
  execution_gate_blocked?: boolean;
  execution_gate_safe_to_trade?: boolean;
  execution_gate_reasons?: Array<{ source?: string; message?: string; severity?: string }>;
  kalshi_ct_profile?: string;
  /** agent_grid when PM path uses AgentGrid with CT loop idle */
  pm_signal_source?: string;
  pm_ct_loop_idle?: boolean;
  pm_note?: string;
  agent_grid_cycles_total?: number;
  agent_grid_agent_count?: number;
}

/* ═══════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════ */

function num(v: unknown, fallback = 0): number {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

/** USD string from integer cents; never NaN. */
function centsSafe(centsVal: unknown): string {
  return `$${(num(centsVal, 0) / 100).toFixed(2)}`;
}

function hasBankrollSnapshot(d: TraderStatus): boolean {
  const b = num(d.balance_cents as unknown, NaN);
  return Number.isFinite(b);
}

function pctColor(pct: number, thresholds: { warn: number; danger: number }): string {
  if (pct >= thresholds.danger) return 'text-red-400';
  if (pct >= thresholds.warn) return 'text-amber-400';
  return 'text-emerald-400';
}

function volBandColor(band: string): string {
  if (band === 'high') return 'text-red-400 bg-red-500/10 border-red-500/30';
  if (band === 'low') return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30';
  return 'text-blue-400 bg-blue-500/10 border-blue-500/30';
}

/* ═══════════════════════════════════════════════════════════════════
   Sparkline — tiny inline SVG chart
   ═══════════════════════════════════════════════════════════════════ */

function Sparkline({ data, color, warnThreshold, dangerThreshold, width = 64, height = 20 }: {
  data: number[];
  color: string;
  warnThreshold?: number;
  dangerThreshold?: number;
  width?: number;
  height?: number;
}) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 1;
  const xStep = (width - pad * 2) / (data.length - 1);
  const points = data.map((v, i) => {
    const x = pad + i * xStep;
    const y = height - pad - ((v - min) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const polyline = points.join(' ');

  // Threshold lines
  const thresholdLines: Array<{ y: number; stroke: string }> = [];
  if (warnThreshold !== undefined && warnThreshold >= min && warnThreshold <= max) {
    const y = height - pad - ((warnThreshold - min) / range) * (height - pad * 2);
    thresholdLines.push({ y, stroke: '#eab308' });
  }
  if (dangerThreshold !== undefined && dangerThreshold >= min && dangerThreshold <= max) {
    const y = height - pad - ((dangerThreshold - min) / range) * (height - pad * 2);
    thresholdLines.push({ y, stroke: '#ef4444' });
  }

  // Trend indicator
  const last = data[data.length - 1];
  const prev = data[data.length - 2];
  const trend = last > prev ? '▲' : last < prev ? '▼' : '─';
  const trendColor = last > prev ? 'text-red-400' : last < prev ? 'text-emerald-400' : 'text-slate-500';

  return (
    <span className="inline-flex items-center gap-1">
      <svg width={width} height={height} className="shrink-0" aria-hidden>
        {thresholdLines.map((tl, i) => (
          <line
            key={i}
            x1={0} y1={tl.y} x2={width} y2={tl.y}
            stroke={tl.stroke} strokeWidth={0.5} strokeDasharray="2,2" opacity={0.5}
          />
        ))}
        <polyline
          points={polyline}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className={`text-[9px] font-bold ${trendColor}`}>{trend}</span>
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Stat card sub-component
   ═══════════════════════════════════════════════════════════════════ */

function Stat({ label, value, sub, color, icon: Icon, sparkline }: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  icon?: React.ComponentType<{ className?: string }>;
  sparkline?: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2 p-2 rounded-lg bg-slate-800/50 border border-slate-700/50">
      {Icon && <Icon className={`w-4 h-4 mt-0.5 ${color ?? 'text-slate-400'}`} />}
      <div className="min-w-0 flex-1">
        <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
        <div className="flex items-center gap-2">
          <span className={`text-sm font-mono font-semibold ${color ?? 'text-slate-200'}`}>{value}</span>
          {sparkline}
        </div>
        {sub && <div className="text-[10px] text-slate-500">{sub}</div>}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Main component
   ═══════════════════════════════════════════════════════════════════ */

export default function KalshiBankrollPanel() {
  const [expanded, setExpanded] = useState(true);
  const [stopping, setStopping] = useState(false);

  const { data, loading } = useApiData<TraderStatus>(
    API_ENDPOINTS.KALSHI_CONTINUOUS_TRADER_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const handleStop = useCallback(async () => {
    if (!confirm('Stop the continuous trader? It will finish its current cycle.')) return;
    setStopping(true);
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CONTINUOUS_TRADER_STOP}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch { /* ignore */ }
    setStopping(false);
  }, []);

  /* ── Loading / unavailable ────────────────────────────────────── */

  if (loading && !data) {
    return (
      <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Activity className="w-4 h-4 animate-pulse" />
          Loading continuous trader…
        </div>
      </div>
    );
  }

  if (!data || !data.available) {
    return (
      <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Shield className="w-4 h-4" />
          Continuous trader not available
          {data?.reason && <span className="text-slate-600">— {data.reason}</span>}
        </div>
      </div>
    );
  }

  const d = data;
  /** API can return { available, running, error } only when status_snapshot throws. */
  const snapshotFailed = Boolean(d.error) || !hasBankrollSnapshot(d);
  const money = (c: unknown) => (snapshotFailed ? '—' : centsSafe(c));
  const ddColor = pctColor(num(d.drawdown_pct, 0), { warn: 10, danger: 20 });
  const fdColor = pctColor(num(d.fee_drag_pct, 0), { warn: 20, danger: 30 });
  const pnlColor = num(d.total_pnl_cents, 0) >= 0 ? 'text-emerald-400' : 'text-red-400';
  const volBandKey = String(d.vol_band ?? 'normal');

  /* ── Render ───────────────────────────────────────────────────── */

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-white">Multi-Asset Continuous Trader · Live Signal</span>
          {d.pm_signal_source === 'agent_grid' && (
            <span
              className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/35"
              title={d.pm_note ?? 'PM sizing via AgentGrid + shared risk layer'}
            >
              AGENT GRID PM
            </span>
          )}
          {/* Status pill */}
          {d.halted ? (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red-500/20 text-red-400 border border-red-500/30">
              HALTED
            </span>
          ) : d.running ? (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse mr-1" />
              RUNNING
            </span>
          ) : (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-slate-600/30 text-slate-500 border border-slate-600/30">
              STOPPED
            </span>
          )}
          {d.dry_run === true && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
              DRY RUN
            </span>
          )}
          {d.fee_drag_tightening === true && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/30">
              TIGHT
            </span>
          )}
          {d.kalshi_ct_profile && d.kalshi_ct_profile !== 'production' && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-violet-500/20 text-violet-300 border border-violet-500/35 font-mono">
              CT {(d.kalshi_ct_profile ?? '').toUpperCase()}
            </span>
          )}
          {d.execution_gate_state && (
            <span
              className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${
                d.execution_gate_blocked
                  ? 'bg-red-500/25 text-red-300 border-red-500/40'
                  : d.execution_gate_state === 'limited'
                    ? 'bg-amber-500/20 text-amber-300 border-amber-500/35'
                    : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
              }`}
              title={
                d.execution_gate_reasons?.length
                  ? d.execution_gate_reasons.map((r) => r.message).join(' · ')
                  : undefined
              }
            >
              GATE {(d.execution_gate_state ?? '').toUpperCase()}
            </span>
          )}
          {/* Vol band pill */}
          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${volBandColor(volBandKey)}`}>
            VOL {volBandKey.toUpperCase()}{' '}
            {snapshotFailed ? '—' : `${num(d.annualized_vol_pct, 0)}%`}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">
            Cycle {typeof d.cycle === 'number' && Number.isFinite(d.cycle) ? d.cycle : '—'}
            {typeof d.agent_grid_cycles_total === 'number' && d.agent_grid_cycles_total > 0 && (
              <span className="text-slate-600"> Σ{d.agent_grid_cycles_total}</span>
            )}
          </span>
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {snapshotFailed && (
            <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs text-amber-100">
              <strong className="text-amber-200">Snapshot incomplete:</strong>{' '}
              {d.error ?? 'Bankroll fields missing — the server could not build status_snapshot(). Check API logs.'}
            </div>
          )}
          {/* Row 1: Bankroll */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat
              label="Balance"
              value={money(d.balance_cents)}
              icon={DollarSign}
              color="text-slate-200"
            />
            <Stat
              label="Total Value"
              value={money(d.total_value_cents)}
              sub={snapshotFailed ? undefined : `Peak: ${centsSafe(d.peak_balance_cents)}`}
              icon={TrendingUp}
              color="text-slate-200"
            />
            <Stat
              label="Drawdown"
              value={snapshotFailed ? '—' : `${num(d.drawdown_pct, 0).toFixed(1)}%`}
              sub={`Halt: ${((d.config?.drawdown_halt_pct ?? 0) * 100).toFixed(0)}% | Reduce: ${((d.config?.drawdown_reduce_pct ?? 0) * 100).toFixed(0)}%`}
              icon={TrendingDown}
              color={ddColor}
              sparkline={
                !snapshotFailed && d.cycle_history && d.cycle_history.length >= 2
                  ? <Sparkline
                      data={d.cycle_history.map(h => num(h.drawdown_pct, 0))}
                      color="#f87171"
                      warnThreshold={(d.config?.drawdown_reduce_pct ?? 0) * 100}
                      dangerThreshold={(d.config?.drawdown_halt_pct ?? 0) * 100}
                    />
                  : undefined
              }
            />
            <Stat
              label="PnL"
              value={
                snapshotFailed
                  ? '—'
                  : `${num(d.total_pnl_cents, 0) >= 0 ? '+' : ''}${centsSafe(d.total_pnl_cents)}`
              }
              sub={snapshotFailed ? undefined : `Fees: ${centsSafe(d.total_fees_cents)}`}
              icon={BarChart3}
              color={pnlColor}
            />
          </div>

          {/* Row 2: Performance + Fee Drag */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat
              label="Trades"
              value={snapshotFailed ? '—' : `${num(d.total_trades, 0)}`}
              sub={
                snapshotFailed
                  ? undefined
                  : `W:${num(d.total_wins, 0)} L:${num(d.total_losses, 0)} (${num(d.win_rate_pct, 0).toFixed(1)}%)`
              }
              icon={Activity}
              color="text-slate-200"
            />
            <Stat
              label="Fee Drag"
              value={snapshotFailed ? '—' : `${num(d.fee_drag_pct, 0).toFixed(1)}%`}
              sub={
                snapshotFailed
                  ? undefined
                  : `Window: ${num(d.fee_drag_window, 0)} trades${d.fee_drag_tightening ? ' [TIGHT]' : ''}`
              }
              icon={AlertTriangle}
              color={fdColor}
              sparkline={
                !snapshotFailed && d.cycle_history && d.cycle_history.length >= 2
                  ? <Sparkline
                      data={d.cycle_history.map(h => num(h.fee_drag_pct, 0))}
                      color="#fb923c"
                      dangerThreshold={(d.config?.max_fee_drag_pct ?? 0) * 100}
                    />
                  : undefined
              }
            />
            <Stat
              label="Vol Band"
              value={
                snapshotFailed
                  ? '—'
                  : `${volBandKey.toUpperCase()} ${num(d.annualized_vol_pct, 0).toFixed(1)}%`
              }
              sub={`Thresholds: <${((d.config?.vol_low_threshold ?? 0) * 100).toFixed(0)}% / >${((d.config?.vol_high_threshold ?? 0) * 100).toFixed(0)}%`}
              icon={Gauge}
              color={d.vol_band === 'high' ? 'text-red-400' : d.vol_band === 'low' ? 'text-emerald-400' : 'text-blue-400'}
            />
            <Stat
              label="Eff. Limits"
              value={
                snapshotFailed
                  ? '—'
                  : `${num(d.eff_max_orders_per_cycle, 0)} ord / ${num(d.eff_max_exposure_pct, 0).toFixed(1)}% exp`
              }
              sub={`Kelly: ${((d.config?.kelly_fraction ?? 0) * 100).toFixed(0)}% | Risk: ${((d.config?.max_risk_per_trade_pct ?? 0) * 100).toFixed(0)}%/trade`}
              icon={Shield}
              color="text-slate-200"
            />
          </div>

          {/* Row 3: Orders + Config + Stop */}
          <div className="flex items-center justify-between pt-1 border-t border-slate-700/50">
            <div className="flex items-center gap-4 text-xs text-slate-500">
              <span>
                Orders: {snapshotFailed ? '—' : `${num(d.orders_placed, 0)} placed / ${num(d.orders_filled, 0)} filled / ${num(d.orders_cancelled, 0)} cancelled`}
              </span>
              <span>Resting: {snapshotFailed ? '—' : num(d.resting_orders, 0)}</span>
              <span>Edge ≥ {d.config?.min_edge ?? '—'}</span>
              <span>Max price: {d.config?.max_contract_price_cents != null ? `${d.config?.max_contract_price_cents}¢` : '—'}</span>
              <span>Churn: {d.config?.churn_cooldown_cycles ?? '—'} cyc / {((d.config?.churn_edge_improvement ?? 0) * 100).toFixed(0)}%</span>
            </div>
            {d.running && (
              <button
                onClick={handleStop}
                disabled={stopping}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-colors disabled:opacity-50"
              >
                <StopCircle className="w-3 h-3" />
                {stopping ? 'Stopping…' : 'Stop Trader'}
              </button>
            )}
          </div>

          {/* Halt reason */}
          {d.halted && d.halt_reason && (
            <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-400">
              <strong>HALTED:</strong> {d.halt_reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
