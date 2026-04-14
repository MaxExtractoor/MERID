/**
 * EffectiveRiskConfigPanel — read-only mirror of the live risk configuration.
 *
 * Exposes drawdown thresholds, profit-lock params, kill-switch settings,
 * and CT time-boxing config from /api/v1/kalshi/risk/effective-config.
 * All values reflect the currently-running process; change via config
 * files / env vars, not through this panel.
 */

import { Settings, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { EffectiveRiskConfig } from '../types/kalshi';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">{title}</h4>
      <div className="bg-slate-800/50 rounded-lg p-3 space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ label, value, note }: { label: string; value: React.ReactNode; note?: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-slate-400 shrink-0">{label}</span>
      <span className="text-xs text-white text-right font-mono">{value}</span>
      {note && <span className="text-xs text-slate-600 italic">{note}</span>}
    </div>
  );
}

export function EffectiveRiskConfigPanel() {
  const { data, loading, error, refetch } = useApiData<EffectiveRiskConfig>(
    API_ENDPOINTS.KALSHI_RISK_EFFECTIVE_CONFIG,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Settings className="w-4 h-4 text-slate-400" />
          <h3 className="text-sm font-semibold text-white">Effective Risk Settings (live)</h3>
          <span className="text-xs text-slate-600 italic">read-only</span>
        </div>
        <button
          type="button"
          onClick={refetch}
          className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
          title="Refresh"
          aria-label="Refresh config"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error ? (
        <div className="px-5 py-4 text-sm text-slate-500">Config unavailable: {error.message}</div>
      ) : !data ? (
        <div className="p-5 animate-pulse space-y-3">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-16 bg-slate-800 rounded" />
          ))}
        </div>
      ) : (
        <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-5">

          {/* Drawdown */}
          <Section title="Drawdown">
            <Row label="GREEN threshold" value={`< ${data.drawdown.green_pct}%`} />
            <Row label="YELLOW threshold" value={`${data.drawdown.green_pct}–${data.drawdown.soft_pct}%`} />
            <Row label="ORANGE threshold" value={`${data.drawdown.soft_pct}–${data.drawdown.hard_pct}%`} />
            <Row label="RED / halt" value={`≥ ${data.drawdown.halt_pct}%`} />
            <div className="border-t border-slate-700/50 pt-1.5 mt-1.5">
              <Row label="GREEN multiplier"  value={`${data.drawdown.multipliers.green}×`} />
              <Row label="YELLOW multiplier" value={`${data.drawdown.multipliers.yellow}×`} />
              <Row label="ORANGE multiplier" value={`${data.drawdown.multipliers.orange}×`} />
              <Row label="RED multiplier"    value={`${data.drawdown.multipliers.red}× (halt)`} />
            </div>
          </Section>

          {/* Profit-lock */}
          <Section title="Profit-Lock">
            <Row label="Lock fraction"        value={`${(data.profit_lock.lock_fraction * 100).toFixed(0)}%`} note="of session peak" />
            <Row label="Max give-back"         value={`${(data.profit_lock.max_giveback_fraction * 100).toFixed(0)}%`} note="of locked profit" />
            <Row label="CAUTION threshold"     value={`< ${(data.profit_lock.caution_threshold * 100).toFixed(0)}% headroom`} />
            <div className="border-t border-slate-700/50 pt-1.5 mt-1.5">
              {Object.entries(data.profit_lock.states).map(([state, cfg]) => (
                <Row key={state} label={state.toUpperCase()} value={`${cfg.multiplier}×`} note={cfg.description} />
              ))}
            </div>
          </Section>

          {/* Kill-switch */}
          <Section title="Kill-Switch / Error Budget">
            <Row label="Error threshold"   value={`${data.kill_switch.error_budget_threshold} / hour`} />
            <Row label="Dedup window"       value={`${data.kill_switch.dedup_window_secs}s`} />
            <Row label="WARN at"            value={`${(data.kill_switch.warn_pct * 100).toFixed(0)}%`} />
            <Row label="LIMIT at"           value={`${(data.kill_switch.limit_pct * 100).toFixed(0)}%`} />
            {data.kill_switch.exempt_classes.length > 0 && (
              <Row
                label="Exempt classes"
                value={
                  <span className="text-slate-400 text-right">
                    {data.kill_switch.exempt_classes.join(', ')}
                  </span>
                }
              />
            )}
            <div className="mt-1.5 text-xs text-slate-500 italic">{data.kill_switch.note}</div>
          </Section>

          {/* CT time-boxing */}
          <Section title="CT Time-Boxing">
            <Row
              label="Taper start"
              value={`${data.ct_timebox.taper_start_minutes_before_expiry} min before expiry`}
            />
            <Row label="Expired skip" value={data.ct_timebox.expired_skip ? 'yes' : 'no'} />
            <div className="mt-1.5 text-xs text-slate-500">{data.ct_timebox.description}</div>
          </Section>

        </div>
      )}
    </div>
  );
}
