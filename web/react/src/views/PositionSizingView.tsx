/**
 * PositionSizingView — Kelly-based position sizing and vol-targeting metrics.
 *
 * Shows Kelly fraction, vol scaling, performance ratios, and drawdown tier.
 */

import React from 'react';
import {
  Target, TrendingUp, BarChart3, Gauge, Activity, RefreshCw, AlertTriangle,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { SizingMetrics } from '../types/kalshi';

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmt(val: number | null | undefined, decimals = 3): string {
  if (val == null) return '—';
  return val.toFixed(decimals);
}

function pct(val: number | null | undefined, decimals = 1): string {
  if (val == null) return '—';
  return `${(val * 100).toFixed(decimals)}%`;
}

const TIER_STYLES: Record<string, { text: string; bg: string; border: string; label: string }> = {
  normal:   { text: 'text-green-400',  bg: 'bg-green-500/20',  border: 'border-green-500/40',  label: 'NORMAL' },
  warning:  { text: 'text-yellow-400', bg: 'bg-yellow-500/20', border: 'border-yellow-500/40', label: 'WARNING' },
  downsize: { text: 'text-orange-400', bg: 'bg-orange-500/20', border: 'border-orange-500/40', label: 'DOWNSIZE' },
  halt:     { text: 'text-red-400',    bg: 'bg-red-500/20',    border: 'border-red-500/40',    label: 'HALT' },
};

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}

function StatCard({ icon, label, value, sub }: StatCardProps) {
  return (
    <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-gray-400">
        {icon}
        <span className="text-xs font-medium">{label}</span>
      </div>
      <span className="text-2xl font-bold text-white">{value}</span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

const PositionSizingView: React.FC = () => {
  const sizingRes = useApiData<SizingMetrics>(
    API_ENDPOINTS.KALSHI_SIZING_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const s = sizingRes.data;
  const tier = s?.drawdown_tier ?? 'normal';
  const tierStyle = TIER_STYLES[tier] ?? TIER_STYLES.normal;

  const kellyFraction    = s?.kelly_fraction ?? null;
  const effectiveFraction = s?.effective_fraction ?? null;
  const kellyUtilization = kellyFraction != null && effectiveFraction != null && kellyFraction > 0
    ? Math.min(1, effectiveFraction / kellyFraction)
    : null;

  const barColor = tier === 'normal' ? 'bg-green-500'
    : tier === 'warning' ? 'bg-yellow-500'
    : tier === 'downsize' ? 'bg-orange-500'
    : 'bg-red-500';

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Target className="w-7 h-7 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Position Sizing Dashboard</h1>
            <p className="text-sm text-gray-400">Kelly fractions, volatility targeting, and performance ratios</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Drawdown tier badge */}
          {s && (
            <span className={`px-3 py-1 rounded-full text-xs font-bold border ${tierStyle.text} ${tierStyle.bg} ${tierStyle.border}`}>
              {tierStyle.label}
            </span>
          )}
          <button
            type="button"
            onClick={() => sizingRes.refetch()}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Error state */}
      {sizingRes.error && (
        <div className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="inline w-4 h-4 mr-1.5" />
          {sizingRes.error.message}
        </div>
      )}

      {/* Kelly / Vol cards — top row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard
          icon={<Target className="w-4 h-4" />}
          label="Kelly Fraction"
          value={sizingRes.loading ? '…' : fmt(kellyFraction)}
          sub="raw Kelly"
        />
        <StatCard
          icon={<Gauge className="w-4 h-4" />}
          label="Effective Fraction"
          value={sizingRes.loading ? '…' : fmt(effectiveFraction)}
          sub={`${tier} tier`}
        />
        <StatCard
          icon={<Activity className="w-4 h-4" />}
          label="Vol Scale"
          value={sizingRes.loading ? '…' : fmt(s?.vol_scale)}
          sub="sizing multiplier"
        />
        <StatCard
          icon={<TrendingUp className="w-4 h-4" />}
          label="Target Vol"
          value={sizingRes.loading ? '…' : pct(s?.target_vol)}
          sub="annualized"
        />
        <StatCard
          icon={<BarChart3 className="w-4 h-4" />}
          label="Realized Vol"
          value={sizingRes.loading ? '…' : pct(s?.realized_vol)}
          sub="annualized"
        />
      </div>

      {/* Kelly utilization */}
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4 text-blue-400" />
            <span className="text-sm font-medium text-gray-300">Kelly Utilization</span>
          </div>
          <span className="text-sm font-bold text-white">
            {kellyUtilization != null ? `${(kellyUtilization * 100).toFixed(1)}%` : '—'}
          </span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${((kellyUtilization ?? 0) * 100).toFixed(1)}%` }}
          />
        </div>
        <p className="text-xs text-gray-500">
          Ratio of effective fraction to raw Kelly fraction. Lower = more conservative sizing.
        </p>
      </div>

      {/* Performance ratios */}
      <div className="bg-slate-900 rounded-xl p-5 border border-slate-800 space-y-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold text-gray-200">Performance Ratios</h3>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {(
            [
              { label: 'Win Rate', value: s?.win_rate_pct != null ? `${s.win_rate_pct.toFixed(1)}%` : '—', sub: 'of trades' },
              { label: 'Profit Factor', value: fmt(s?.profit_factor, 2), sub: 'gross P/L ratio' },
              { label: 'Sharpe', value: fmt(s?.sharpe_ratio, 2), sub: 'annualized' },
              { label: 'Sortino', value: fmt(s?.sortino_ratio, 2), sub: 'annualized' },
              { label: 'Calmar', value: fmt(s?.calmar_ratio, 2), sub: 'return/drawdown' },
            ] as { label: string; value: string; sub: string }[]
          ).map(({ label, value, sub }) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-xs text-gray-400">{label}</span>
              <span className="text-lg font-bold text-white">
                {sizingRes.loading ? '…' : value}
              </span>
              <span className="text-xs text-gray-600">{sub}</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
};

export default PositionSizingView;
