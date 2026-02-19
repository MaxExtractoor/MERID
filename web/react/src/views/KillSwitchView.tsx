import { useState, useMemo, useCallback } from 'react';
import { ShieldAlert, ShieldCheck, AlertTriangle, Zap, Eye, Ban } from 'lucide-react';
import ModeSafetyPanel from '../components/ModeSafetyPanel';
import PnLConsistencyWidget from '../components/PnLConsistencyWidget';
import SessionLogPanel from '../components/SessionLogPanel';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { formatCurrency } from '../utils/formatters';
import KalshiModeBadge from '../components/KalshiModeBadge';

interface BlockReason {
  source: string;
  severity: string;
  message: string;
  details: string | null;
  hint: string | null;
}

interface KillSwitchState {
  global_kill: boolean;
  state: string;
  can_trade: boolean;
  kill_reason: string | null;
  kill_timestamp: string | null;
  daily_pnl: number;
  daily_loss_limit: number;
  total_position_value: number;
  max_position_value: number;
  error_count: number;
  error_threshold: number;
}

interface RiskState {
  kill_switch: {
    active: boolean;
    reason: string | null;
    can_trade: boolean;
  };
  pnl: {
    daily_pnl: number;
    daily_loss_limit: number;
    limit_remaining: number;
    utilization_pct: number;
  };
  position: {
    total_value: number;
    max_allowed: number;
    utilization_pct: number;
  };
  errors: {
    count_1h: number;
    threshold: number;
    near_limit: boolean;
  };
}

interface CategoryConfig {
  categories: Record<string, string>;
  known: string[];
}

type CatMode = 'live' | 'read-only' | 'blocked';

const MODE_STYLE: Record<CatMode, { label: string; color: string; icon: typeof Zap }> = {
  'live':      { label: 'Live',      color: 'bg-emerald-600 text-white',              icon: Zap },
  'read-only': { label: 'Read-only', color: 'bg-slate-600 text-slate-200',            icon: Eye },
  'blocked':   { label: 'Blocked',   color: 'bg-red-700 text-white',                  icon: Ban },
};

const CYCLE: CatMode[] = ['live', 'read-only', 'blocked'];

export default function KillSwitchView() {
  // Real kill switch state from backend
  const { data: killSwitch, refetch: refetchKillSwitch } = useApiData<KillSwitchState>(
    API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  
  // Risk state for detailed metrics
  const { data: riskState } = useApiData<RiskState>(
    API_ENDPOINTS.OPERATOR_RISK_STATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  
  const { data: catData, refetch: refetchCats } = useApiData<CategoryConfig>(
    API_ENDPOINTS.KALSHI_CATEGORIES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );
  const [saving, setSaving] = useState(false);

  const blocked = killSwitch?.global_kill ?? false;
  const gateState = blocked ? 'blocked' : (riskState?.errors.near_limit ? 'limited' : 'clear');
  
  // Build reasons from kill switch state
  const reasons: BlockReason[] = [];
  if (killSwitch?.kill_reason) {
    reasons.push({
      source: 'kill_switch',
      severity: 'critical',
      message: killSwitch.kill_reason,
      details: killSwitch.kill_timestamp ? `Triggered at ${new Date(killSwitch.kill_timestamp).toLocaleString()}` : null,
      hint: 'Use Reset button below to re-enable trading after resolving issues',
    });
  }
  if (riskState?.pnl.daily_pnl && Math.abs(riskState.pnl.daily_pnl) >= riskState.pnl.daily_loss_limit * 0.8) {
    reasons.push({
      source: 'daily_loss_limit',
      severity: riskState.pnl.daily_pnl <= -riskState.pnl.daily_loss_limit ? 'critical' : 'warning',
      message: 'Daily loss limit approaching',
      details: `Current P&L: ${formatCurrency(riskState.pnl.daily_pnl)} / Limit: ${formatCurrency(-riskState.pnl.daily_loss_limit)}`,
      hint: 'Trading will halt if limit is breached',
    });
  }
  if (riskState?.errors.near_limit) {
    reasons.push({
      source: 'error_rate',
      severity: 'warning',
      message: 'Error rate elevated',
      details: `${riskState.errors.count_1h} errors in last hour (threshold: ${riskState.errors.threshold})`,
      hint: 'Circuit breaker may trip if errors continue',
    });
  }
  
  const criticalReasons = reasons.filter(r => r.severity === 'critical');
  const warningReasons = reasons.filter(r => r.severity === 'warning');

  const categories = useMemo(() => catData?.categories ?? {}, [catData]);
  const knownCats = useMemo(() => catData?.known ?? Object.keys(categories), [catData, categories]);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const handleEmergencyStop = useCallback(async () => {
    if (!confirm('⚠️ EMERGENCY STOP - This will immediately halt ALL trading. Continue?')) {
      return;
    }
    const reason = prompt('Reason for emergency stop:', 'Manual operator intervention') || 'Manual stop';
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_EMERGENCY_STOP}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      refetchKillSwitch();
    } catch (err) {
      alert(`Failed to trigger emergency stop: ${err}`);
    }
    setSaving(false);
  }, [authHeaders, refetchKillSwitch]);

  const handleResetKillSwitch = useCallback(async () => {
    if (!confirm('Reset kill switch and re-enable trading? Ensure all issues are resolved first.')) {
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ confirm: true }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      refetchKillSwitch();
    } catch (err) {
      alert(`Failed to reset kill switch: ${err}`);
    }
    setSaving(false);
  }, [authHeaders, refetchKillSwitch]);

  const cycleMode = useCallback(async (cat: string) => {
    const current = (categories[cat] ?? 'read-only') as CatMode;
    const idx = CYCLE.indexOf(current);
    const next = CYCLE[(idx + 1) % CYCLE.length];
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CATEGORIES}`, {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify({ [cat]: next }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      refetchCats();
    } catch { /* best effort */ }
    setSaving(false);
  }, [authHeaders, categories, refetchCats]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <ShieldAlert className="w-6 h-6 text-red-400" />
        <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">Kill Switch & Safety <KalshiModeBadge /></h1>
      </div>

      {/* Gate Status Hero */}
      <div className={`rounded-2xl border p-6 ${
        gateState === 'clear'
          ? 'bg-emerald-950/30 border-emerald-500/30'
          : gateState === 'limited'
          ? 'bg-amber-950/30 border-amber-500/30'
          : 'bg-red-950/30 border-red-500/30'
      }`}>
        <div className="flex items-center gap-4 mb-4">
          {blocked
            ? <ShieldAlert className="w-10 h-10 text-red-400 animate-pulse" />
            : <ShieldCheck className="w-10 h-10 text-emerald-400" />
          }
          <div>
            <h2 className="text-2xl font-bold text-white">
              {gateState === 'clear' ? 'Execution Enabled' : gateState === 'limited' ? 'Limited Mode' : 'Execution Blocked'}
            </h2>
            <p className="text-sm text-slate-400">
              {blocked ? 'Trading is halted due to critical safety checks' : 'All safety checks passing — trading permitted'}
            </p>
          </div>
        </div>

        {criticalReasons.length > 0 && (
          <div className="space-y-2 mb-3">
            <h3 className="text-xs font-semibold text-red-400 uppercase">Critical</h3>
            {criticalReasons.map((r, i) => (
              <div key={i} className="bg-red-900/40 border border-red-700/40 rounded-lg p-3">
                <div className="flex items-center gap-2 text-sm text-red-200 font-medium">
                  <AlertTriangle className="w-4 h-4 text-red-400" />
                  {r.message}
                </div>
                {r.details && <p className="text-xs text-red-300/70 mt-1 ml-6">{r.details}</p>}
                {r.hint && <p className="text-xs text-red-300/50 mt-1 ml-6 italic">{r.hint}</p>}
              </div>
            ))}
          </div>
        )}
        {warningReasons.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-xs font-semibold text-amber-400 uppercase">Warnings</h3>
            {warningReasons.map((r, i) => (
              <div key={i} className="bg-amber-900/20 border border-amber-700/30 rounded-lg p-3">
                <div className="flex items-center gap-2 text-sm text-amber-200 font-medium">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  {r.message}
                </div>
                {r.details && <p className="text-xs text-amber-300/70 mt-1 ml-6">{r.details}</p>}
                {r.hint && <p className="text-xs text-amber-300/50 mt-1 ml-6 italic">{r.hint}</p>}
              </div>
            ))}
          </div>
        )}
        {reasons.length === 0 && (
          <p className="text-sm text-emerald-300">No issues detected. All safety checks passing.</p>
        )}
        
        {/* Risk Metrics */}
        {riskState && (
          <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-slate-700/50">
            <div>
              <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Daily P&L</p>
              <p className={`text-lg font-bold ${riskState.pnl.daily_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatCurrency(riskState.pnl.daily_pnl)}
              </p>
              <p className="text-xs text-slate-500">
                Limit: {formatCurrency(-riskState.pnl.daily_loss_limit)} ({riskState.pnl.utilization_pct.toFixed(1)}% used)
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Position Size</p>
              <p className="text-lg font-bold text-blue-400">
                {formatCurrency(riskState.position.total_value)}
              </p>
              <p className="text-xs text-slate-500">
                Max: {formatCurrency(riskState.position.max_allowed)} ({riskState.position.utilization_pct.toFixed(1)}%)
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Errors (1h)</p>
              <p className={`text-lg font-bold ${riskState.errors.near_limit ? 'text-amber-400' : 'text-slate-400'}`}>
                {riskState.errors.count_1h} / {riskState.errors.threshold}
              </p>
              <p className="text-xs text-slate-500">
                {riskState.errors.near_limit ? 'Near threshold' : 'Within limits'}
              </p>
            </div>
          </div>
        )}
        
        {/* Control Buttons */}
        <div className="flex gap-3 mt-4 pt-4 border-t border-slate-700/50">
          {!blocked ? (
            <button
              type="button"
              onClick={handleEmergencyStop}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-red-800 disabled:opacity-50 text-white font-medium rounded-lg transition-colors"
            >
              <ShieldAlert className="w-4 h-4" />
              Emergency Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={handleResetKillSwitch}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-800 disabled:opacity-50 text-white font-medium rounded-lg transition-colors"
            >
              <ShieldCheck className="w-4 h-4" />
              Reset Kill Switch
            </button>
          )}
          <span className="text-xs text-slate-500 flex items-center">
            {killSwitch ? `Last updated: ${new Date(killSwitch.kill_timestamp || Date.now()).toLocaleTimeString()}` : 'Loading...'}
          </span>
        </div>
      </div>

      {/* Category Trading Permissions */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-1">Category Trading Permissions</h3>
        <p className="text-xs text-slate-500 mb-4">Click a category to cycle: Live → Read-only → Blocked. Controls which market categories agents can trade.</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {knownCats.map(cat => {
            const mode = (categories[cat] ?? 'read-only') as CatMode;
            const style = MODE_STYLE[mode];
            const Icon = style.icon;
            return (
              <button
                key={cat}
                type="button"
                onClick={() => cycleMode(cat)}
                disabled={saving}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all border border-slate-700/50 hover:border-slate-600 ${saving ? 'opacity-50' : ''}`}
              >
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold ${style.color}`}>
                  <Icon className="w-3 h-3" />
                  {style.label}
                </span>
                <span className="text-slate-300 capitalize">{cat}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Mode & Safety Controls */}
      <ModeSafetyPanel />

      {/* PnL Consistency */}
      <PnLConsistencyWidget />

      {/* Session Log */}
      <SessionLogPanel />
    </div>
  );
}
