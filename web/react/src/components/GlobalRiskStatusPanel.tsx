/**
 * GlobalRiskStatusPanel — top-level risk widget with:
 *   • Portfolio drawdown bar (green/yellow/orange/red zones)
 *   • Zone label + sizing multiplier
 *   • Profit-lock state (SAFE/CAUTION/FROZEN)
 *   • Kill-switch and halt indicators
 *
 * Fed by the /api/v1/kalshi/global-risk-status backend snapshot.
 */

import { RefreshCw, AlertTriangle, Shield, TrendingDown, Lock, Zap } from 'lucide-react';
import { useGlobalRiskStatus } from '../hooks/useGlobalRiskStatus';
import type { GlobalRiskStatus } from '../types/kalshi';

// ── Zone helpers ─────────────────────────────────────────────────────────────

const ZONE_META = {
  green:  { label: 'GREEN',  barColor: 'bg-emerald-500', textColor: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30' },
  yellow: { label: 'YELLOW', barColor: 'bg-yellow-400',  textColor: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/30' },
  orange: { label: 'ORANGE', barColor: 'bg-orange-500',  textColor: 'text-orange-400',  bg: 'bg-orange-500/10 border-orange-500/30' },
  red:    { label: 'RED',    barColor: 'bg-red-500',     textColor: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/30' },
} as const;

const PROFIT_LOCK_META = {
  safe:    { label: 'SAFE',    textColor: 'text-blue-400',   bg: 'bg-blue-500/10'   },
  caution: { label: 'CAUTION', textColor: 'text-amber-400',  bg: 'bg-amber-500/10'  },
  frozen:  { label: 'FROZEN',  textColor: 'text-slate-300',  bg: 'bg-slate-700/60'  },
} as const;

function fmt(v: number, decimals = 2): string {
  return v.toFixed(decimals);
}

function fmtUsd(v: number): string {
  return v >= 0 ? `+$${v.toFixed(0)}` : `-$${Math.abs(v).toFixed(0)}`;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function DrawdownBar({ pct, zone }: { pct: number; zone: GlobalRiskStatus['zone'] }) {
  const meta = ZONE_META[zone] ?? ZONE_META.green;
  const barWidth = Math.min(100, Math.max(0, pct));

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-slate-400">Portfolio Drawdown</span>
        <span className={`text-sm font-bold ${meta.textColor}`}>{fmt(pct, 1)}%</span>
      </div>
      <div className="h-3 bg-slate-700 rounded-full overflow-hidden relative">
        {/* Zone markers */}
        <div className="absolute inset-0 flex">
          <div className="h-full bg-emerald-500/20" style={{ width: '50%' }} />   {/* 0–10% */}
          <div className="h-full bg-yellow-500/20"  style={{ width: '25%' }} />   {/* 10–15% */}
          <div className="h-full bg-orange-500/20"  style={{ width: '25%' }} />   {/* 15–20% */}
        </div>
        {/* Threshold ticks */}
        <div className="absolute top-0 bottom-0 w-px bg-slate-500/60" style={{ left: '50%' }} />
        <div className="absolute top-0 bottom-0 w-px bg-slate-500/60" style={{ left: '75%' }} />
        {/* Actual bar */}
        <div
          className={`h-full rounded-full transition-all duration-500 ${meta.barColor}`}
          style={{ width: `${barWidth * 5}%` /* 0-20% maps to full bar */ }}
        />
      </div>
      <div className="flex justify-between mt-0.5 text-xs text-slate-600">
        <span>0%</span>
        <span>10%</span>
        <span>15%</span>
        <span>20%+</span>
      </div>
    </div>
  );
}

function ZoneBadge({ data }: { data: GlobalRiskStatus }) {
  const meta = ZONE_META[data.zone] ?? ZONE_META.green;
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${meta.bg}`}
      title={`Zone ${meta.label}: size multiplier ${data.zone_multiplier}×. GREEN<10%, YELLOW 10–15%, ORANGE 15–20%, RED ≥20% (halt).`}
    >
      <TrendingDown className={`w-4 h-4 ${meta.textColor}`} />
      <span className={`text-sm font-bold ${meta.textColor}`}>
        Zone: {meta.label} ({fmt(data.zone_multiplier, 3)}× sizing)
      </span>
    </div>
  );
}

function ProfitLockBadge({ data }: { data: GlobalRiskStatus }) {
  const state = data.profit_lock_state;
  const meta = PROFIT_LOCK_META[state] ?? PROFIT_LOCK_META.safe;
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg ${meta.bg}`}
      title={`Profit Lock: locked $${data.locked_profit_usd.toFixed(0)} (${(data.profit_lock_multiplier * 100).toFixed(0)}% sizing). Remaining give-back: $${data.giveback_remaining_usd.toFixed(0)}.`}
    >
      <Lock className={`w-4 h-4 ${meta.textColor}`} />
      <span className={`text-sm font-bold ${meta.textColor}`}>
        Profit lock: {meta.label}
        {data.session_high_usd > 0 && (
          <span className="font-normal ml-1 text-xs">
            (locked={fmtUsd(data.locked_profit_usd)}, give-back: {fmtUsd(data.giveback_remaining_usd)})
          </span>
        )}
      </span>
    </div>
  );
}

function EffectiveMultiplierBadge({ data }: { data: GlobalRiskStatus }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60"
      title={`Effective size = DD zone (${fmt(data.zone_multiplier, 3)}×) × Profit-lock (${fmt(data.profit_lock_multiplier, 3)}×) = ${fmt(data.effective_multiplier, 4)}×`}
    >
      <span className="text-xs text-slate-400">Effective size:</span>
      <span className="text-sm font-bold text-white">
        {fmt(data.effective_multiplier, 4)}×
      </span>
      <span className="text-xs text-slate-500">
        ({fmt(data.zone_multiplier, 3)} × {fmt(data.profit_lock_multiplier, 3)})
      </span>
    </div>
  );
}

function ErrorBudgetBadge({ data }: { data: GlobalRiskStatus }) {
  const pct = data.error_budget_pct;
  const isWarn = pct >= 70;
  const isLimit = pct >= 90;
  const colorClass = isLimit ? 'text-red-400' : isWarn ? 'text-amber-400' : 'text-slate-400';
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded-lg ${data.kill_switch_active ? 'bg-red-500/20 border border-red-500/40' : 'bg-slate-800/60'}`}
      title="Error budget: only non-exempt errors count (e.g. auth_error, generic). Drawdown halts do NOT consume budget."
    >
      <Zap className={`w-4 h-4 ${data.kill_switch_active ? 'text-red-400' : colorClass}`} />
      <span className={`text-xs ${data.kill_switch_active ? 'text-red-400 font-bold' : colorClass}`}>
        {data.kill_switch_active ? 'KILL SWITCH ACTIVE' : `Errors: ${data.error_budget_used}/${data.error_budget_threshold}`}
      </span>
      {data.kill_switch_reason && (
        <span className="text-xs text-red-400 ml-1">({data.kill_switch_reason})</span>
      )}
    </div>
  );
}

function HaltBadges({ data }: { data: GlobalRiskStatus }) {
  return (
    <div className="flex flex-wrap gap-2">
      {/* Drawdown halt */}
      <div
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-bold ${
          data.drawdown_halt_active
            ? 'bg-red-500/20 border border-red-500/40 text-red-400'
            : 'bg-slate-800/60 text-slate-500'
        }`}
        title={
          data.drawdown_halt_active
            ? 'Drawdown halt active (≥20%). No new risk-adding orders. Does NOT consume error budget.'
            : 'Drawdown halt inactive'
        }
      >
        <TrendingDown className="w-3 h-3" />
        DD halt: {data.drawdown_halt_active ? 'ACTIVE' : 'inactive'}
      </div>

      {/* Manual halt */}
      <div
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-bold ${
          data.manual_halt_active
            ? 'bg-orange-500/20 border border-orange-500/40 text-orange-400'
            : 'bg-slate-800/60 text-slate-500'
        }`}
        title="Manual operator halt status"
      >
        <Shield className="w-3 h-3" />
        Manual halt: {data.manual_halt_active ? 'ACTIVE' : 'inactive'}
      </div>

      {/* Drawdown-budget note */}
      <div
        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs text-slate-600 bg-slate-800/30 italic"
        title="Drawdown rejects are classified LOW and exempt from the error budget."
      >
        DD rejects ≠ budget
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface GlobalRiskStatusPanelProps {
  /** Show a condensed single-line card (for mobile / top bar use). */
  compact?: boolean;
}

export function GlobalRiskStatusPanel({ compact = false }: GlobalRiskStatusPanelProps) {
  const { data, loading, error, refetch } = useGlobalRiskStatus();

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-5 animate-pulse">
        <div className="h-5 bg-slate-700 rounded mb-3 w-48" />
        <div className="h-3 bg-slate-700 rounded mb-2" />
        <div className="h-16 bg-slate-800 rounded" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800/50 p-4">
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4" />
          Global risk status unavailable
        </div>
      </div>
    );
  }

  // ── Compact view for top-bar / mobile ───────────────────────────────
  if (compact) {
    const zone = data.zone;
    const meta = ZONE_META[zone] ?? ZONE_META.green;
    const isHalted = data.kill_switch_active || data.drawdown_halt_active || data.manual_halt_active;
    return (
      <div
        className={`flex items-center gap-3 px-3 py-1.5 rounded-lg border ${meta.bg} text-sm`}
        title="Click for full risk dashboard"
      >
        <TrendingDown className={`w-4 h-4 ${meta.textColor}`} />
        <span className={`font-bold ${meta.textColor}`}>{meta.label}</span>
        <span className="text-slate-400">{data.drawdown_pct.toFixed(1)}%</span>
        <span className="text-slate-500">|</span>
        <span className="text-slate-400">{(data.effective_multiplier * 100).toFixed(0)}% size</span>
        {isHalted && (
          <span className="text-red-400 font-bold text-xs bg-red-500/20 px-1.5 py-0.5 rounded">HALT</span>
        )}
      </div>
    );
  }

  // ── Full panel ───────────────────────────────────────────────────────
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400" />
          <h2 className="text-base font-semibold text-white">Core Risk Status</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">
            {new Date(data.ts).toLocaleTimeString()}
          </span>
          <button
            type="button"
            onClick={refetch}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
            title="Refresh"
            aria-label="Refresh risk status"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Drawdown bar */}
        <DrawdownBar pct={data.drawdown_pct} zone={data.zone} />

        {/* Zone + effective size row */}
        <div className="flex flex-wrap gap-2">
          <ZoneBadge data={data} />
          <EffectiveMultiplierBadge data={data} />
        </div>

        {/* Profit-lock state */}
        <ProfitLockBadge data={data} />

        {/* Kill-switch + error budget */}
        <ErrorBudgetBadge data={data} />

        {/* Halt indicators */}
        <HaltBadges data={data} />
      </div>
    </div>
  );
}
