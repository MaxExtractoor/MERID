import { Shield, ShieldAlert, ShieldCheck, ShieldOff, Wifi, WifiOff, Zap, ZapOff, Clock, AlertTriangle } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { DEFAULTS } from '../config/constants';
import { useExecutionGate } from '../hooks/useExecutionGate';
import { HelpPopover } from './HelpPopover';

interface KillSwitch {
  active: boolean;
  reason: string | null;
  timestamp: number | null;
  daily_pnl: number;
  daily_loss_limit: number;
}

interface KillSwitchEvent {
  old_state: string;
  new_state: string;
  reason: string;
  details: string | null;
  timestamp: number;
}

interface Reconciliation {
  has_run: boolean;
  all_ok: boolean | null;
  blocked: boolean;
  check_count: number;
  pnl_delta: number | null;
}

interface FeedHealth {
  symbols_cached: number;
  symbols_total: number;
  healthy: boolean;
}

interface ModeSafetyData {
  trade_mode: string;
  is_live: boolean;
  allow_live_trades: boolean;
  fresh_start: boolean;
  kill_switch: KillSwitch;
  kill_switch_history: KillSwitchEvent[];
  reconciliation: Reconciliation;
  feed_health: FeedHealth;
  timestamp: number;
}

function formatTs(ts: number | null): string {
  if (!ts) return '--';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-green-400' : 'bg-red-400 animate-pulse'}`} />
  );
}

export default function ModeSafetyPanel() {
  const { data, loading, error } = useApiData<ModeSafetyData>(
    '/api/v1/system/mode-safety',
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  const gate = useExecutionGate();

  if (loading && !data) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-5">
        <div className="flex items-center gap-2 text-slate-500">
          <Shield className="w-4 h-4 animate-pulse" />
          <span className="text-sm">Loading safety status...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800/50 p-5">
        <div className="flex items-center gap-2 text-red-400">
          <ShieldAlert className="w-4 h-4" />
          <span className="text-sm">Failed to load safety status</span>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const modeColor = data.is_live
    ? 'text-red-400 bg-red-500/10 border-red-500/30'
    : data.trade_mode === 'paper'
    ? 'text-blue-400 bg-blue-500/10 border-blue-500/30'
    : 'text-slate-400 bg-slate-700/50 border-slate-600/30';

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <ShieldCheck className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-slate-300">Mode & Safety</h3>
        <HelpPopover title="Mode & Safety">
          <p>This panel shows the current trading mode, safety flags, and execution gate status at a glance.</p>
          <p className="mt-1 font-medium text-slate-200">Key sections:</p>
          <ul className="list-disc list-inside mt-1 space-y-0.5 text-slate-400">
            <li><b>Trade Mode</b> — Current mode (paper/live/mock). Live requires explicit env flag.</li>
            <li><b>Kill Switch</b> — Emergency stop. Reset requires operator acknowledgment.</li>
            <li><b>Reconciliation</b> — Ledger consistency checks. Execution is gated until first run completes.</li>
            <li><b>Execution Gate</b> — Unified safety check. BLOCKED means no orders will fire.</li>
          </ul>
        </HelpPopover>
      </div>

      {/* Mode flags row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Trade Mode */}
        <div className={`rounded-lg border px-3 py-2 ${modeColor}`}>
          <div className="text-[10px] uppercase tracking-wide opacity-70">Trade Mode</div>
          <div className="text-sm font-bold uppercase">{data.trade_mode}</div>
        </div>

        {/* Live Trades Flag */}
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Live Trades</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {data.allow_live_trades ? (
              <><Zap className="w-3.5 h-3.5 text-red-400" /><span className="text-sm font-bold text-red-400">ENABLED</span></>
            ) : (
              <><ZapOff className="w-3.5 h-3.5 text-slate-500" /><span className="text-sm font-bold text-slate-400">Disabled</span></>
            )}
          </div>
        </div>

        {/* Fresh Start */}
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Session</div>
          <div className="text-sm font-bold mt-0.5">
            {data.fresh_start ? (
              <span className="text-orange-400">Fresh Start</span>
            ) : (
              <span className="text-slate-400">Resumed</span>
            )}
          </div>
        </div>

        {/* Feed Health */}
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Price Feeds</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {data.feed_health.healthy ? (
              <><Wifi className="w-3.5 h-3.5 text-green-400" /><span className="text-sm font-bold text-green-400">{data.feed_health.symbols_cached}/{data.feed_health.symbols_total}</span></>
            ) : (
              <><WifiOff className="w-3.5 h-3.5 text-red-400" /><span className="text-sm font-bold text-red-400">{data.feed_health.symbols_cached}/{data.feed_health.symbols_total}</span></>
            )}
          </div>
        </div>
      </div>

      {/* Kill Switch + Reconciliation row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {/* Kill Switch */}
        <div className={`rounded-lg border p-3 ${
          data.kill_switch.active
            ? 'border-red-500/40 bg-red-500/5'
            : 'border-slate-700/50 bg-slate-800/50'
        }`}>
          <div className="flex items-center gap-2 mb-2">
            <StatusDot ok={!data.kill_switch.active} />
            <span className="text-xs font-semibold text-slate-300">Kill Switch</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
              data.kill_switch.active ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'
            }`}>
              {data.kill_switch.active ? 'ACTIVE' : 'OFF'}
            </span>
          </div>
          {data.kill_switch.active && data.kill_switch.reason && (
            <p className="text-xs text-red-300/80 mb-1">{data.kill_switch.reason}</p>
          )}
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            <span>Daily PnL: <span className={(data.kill_switch.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>${(data.kill_switch.daily_pnl ?? 0).toFixed(2)}</span></span>
            <span>Limit: ${(data.kill_switch.daily_loss_limit ?? 0).toFixed(0)}</span>
          </div>
        </div>

        {/* Reconciliation */}
        <div className={`rounded-lg border p-3 ${
          data.reconciliation.blocked
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-slate-700/50 bg-slate-800/50'
        }`}>
          <div className="flex items-center gap-2 mb-2">
            <StatusDot ok={!data.reconciliation.blocked} />
            <span className="text-xs font-semibold text-slate-300">Reconciliation</span>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
              data.reconciliation.blocked
                ? 'bg-amber-500/20 text-amber-400'
                : data.reconciliation.all_ok
                ? 'bg-green-500/20 text-green-400'
                : 'bg-red-500/20 text-red-400'
            }`}>
              {data.reconciliation.blocked ? 'BLOCKED' : data.reconciliation.all_ok ? 'OK' : 'ISSUES'}
            </span>
          </div>
          <div className="text-[10px] text-slate-500">
            {data.reconciliation.has_run
              ? `${data.reconciliation.check_count} checks completed`
              : 'Not yet run — execution gated'}
          </div>
          {data.reconciliation.pnl_delta != null && (
            <div className={`text-[10px] mt-1 font-mono ${
              Math.abs(data.reconciliation.pnl_delta) > 5 ? 'text-amber-400' : 'text-slate-500'
            }`}>
              Cross-source PnL Δ: ${data.reconciliation.pnl_delta.toFixed(2)}
            </div>
          )}
        </div>
      </div>

      {/* Execution Gate */}
      <div className={`rounded-lg border p-3 ${
        gate.blocked
          ? 'border-red-500/40 bg-red-500/5'
          : gate.gateState === 'limited'
          ? 'border-amber-500/30 bg-amber-500/5'
          : 'border-green-500/30 bg-green-500/5'
      }`}>
        <div className="flex items-center gap-2 mb-1">
          {gate.blocked ? (
            <ShieldOff className="w-4 h-4 text-red-400" />
          ) : gate.gateState === 'limited' ? (
            <ShieldAlert className="w-4 h-4 text-amber-400" />
          ) : (
            <ShieldCheck className="w-4 h-4 text-green-400" />
          )}
          <span className="text-xs font-semibold text-slate-300">Execution Gate</span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
            gate.blocked
              ? 'bg-red-500/20 text-red-400'
              : gate.gateState === 'limited'
              ? 'bg-amber-500/20 text-amber-400'
              : 'bg-green-500/20 text-green-400'
          }`}>
            {gate.blocked ? 'BLOCKED' : gate.gateState === 'limited' ? 'LIMITED' : 'CLEAR'}
          </span>
          {gate.gateState === 'limited' && (
            <span className="text-[9px] text-amber-400/70 italic">reduce-only</span>
          )}
        </div>
        {gate.reasons.length > 0 && (
          <div className="space-y-1 mt-2">
            {gate.reasons.map((r, i) => (
              <div key={i} className="flex items-center gap-1.5 text-[10px]">
                <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  r.severity === 'critical' ? 'bg-red-400' : 'bg-amber-400'
                }`} />
                <span className={r.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>{r.message}</span>
                {r.details && <span className="text-slate-500">— {r.details}</span>}
              </div>
            ))}
          </div>
        )}
        {gate.gateState === 'clear' && (
          <p className="text-[10px] text-green-400/70">All safety checks passed — trading permitted</p>
        )}
      </div>

      {/* Kill Switch History */}
      {data.kill_switch_history.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Clock className="w-3 h-3 text-slate-500" />
            <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wide">Kill Switch History</span>
          </div>
          <div className="space-y-1 max-h-[160px] overflow-y-auto">
            {data.kill_switch_history.map((evt, i) => {
              const isActivation = evt.new_state === 'killed' || evt.new_state === 'active';
              return (
                <div key={i} className="flex items-start gap-2 text-[10px] bg-slate-800/50 rounded px-2 py-1.5">
                  <AlertTriangle className={`w-3 h-3 flex-shrink-0 mt-0.5 ${
                    isActivation ? 'text-red-400' : 'text-amber-400'
                  }`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400 font-mono">{formatTs(evt.timestamp)}</span>
                      <span className={`font-medium px-1 rounded ${
                        isActivation ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'
                      }`}>
                        {evt.old_state} → {evt.new_state}
                      </span>
                      <span className="text-slate-500">{evt.reason}</span>
                    </div>
                    {evt.details && (
                      <p className="text-slate-500 truncate mt-0.5">{evt.details}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
