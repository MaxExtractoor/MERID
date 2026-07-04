import { ShieldAlert, ShieldCheck, AlertTriangle, TrendingUp, Activity, Radio, RefreshCw } from '../ui/icons';
import { useState, useCallback } from 'react';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import { useKalshiMode } from '../context/KalshiModeContext';
import { MODE_COLORS, resolveModeKey } from '../config/modeColors';

interface GateBlockReason {
  source: string;
  severity: string;
  message: string;
  hint: string | null;
}

interface StripExecutionGateData {
  blocked: boolean;
  safe_to_trade: boolean;
  gate_state: string;
  reasons: GateBlockReason[];
}

interface RiskData {
  total_exposure: number;
  max_exposure: number;
  daily_pnl: number;
  max_daily_loss: number;
  position_count: number;
  max_positions: number;
}

/**
 * Always-visible execution gate + near-limit warnings strip.
 * Shows on all Live Trading views so operators always know:
 *   1. Whether execution is CLEAR / LIMITED / BLOCKED
 *   2. How close they are to risk limits
 *   3. What to do if gate is closed
 */
export default function ExecutionGateStrip() {
  const { data: gate } = useApiQuery<StripExecutionGateData>(
    API_ENDPOINTS.SYSTEM_EXECUTION_GATE,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  const { data: risk } = useApiQuery<RiskData>(
    API_ENDPOINTS.KALSHI_RISK,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const { data: modeData } = useKalshiMode();

  const [reloading, setReloading] = useState(false);
  const [reloadStatus, setReloadStatus] = useState<'idle' | 'ok' | 'err'>('idle');

  const handleConfigReload = useCallback(async () => {
    setReloading(true);
    setReloadStatus('idle');
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.CONFIG_RELOAD}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}) },
      });
      setReloadStatus(res.ok ? 'ok' : 'err');
    } catch {
      setReloadStatus('err');
    } finally {
      setReloading(false);
      setTimeout(() => setReloadStatus('idle'), DEFAULTS.TIMEOUTS.STATUS_RESET);
    }
  }, []);

  if (!gate) return null;

  const isLive = modeData?.is_live ?? false;
  const currentMode = modeData?.mode?.toUpperCase() ?? 'PAPER';
  const modeColors = MODE_COLORS[resolveModeKey(modeData?.mode, isLive)];

  const blocked = gate.blocked;
  const gateState = gate.gate_state ?? 'unknown';
  const criticals = gate.reasons?.filter((r: GateBlockReason) => r.severity === 'critical') ?? [];
  const warnings = gate.reasons?.filter((r: GateBlockReason) => r.severity === 'warning') ?? [];

  // Near-limit calculations
  const exposurePct = risk && risk.max_exposure > 0
    ? (risk.total_exposure / risk.max_exposure) * 100
    : 0;
  const dailyLossPct = risk && risk.max_daily_loss > 0
    ? (Math.abs(risk.daily_pnl) / risk.max_daily_loss) * 100
    : 0;
  const nearExposureLimit = exposurePct >= 75;
  const nearDailyLossLimit = dailyLossPct >= 75;

  // Gate color — 'unknown' is treated as a warning (we cannot confirm trading is safe)
  const gateColor = blocked
    ? 'bg-red-600/20 border-red-500/40 text-red-400'
    : gateState === 'limited' || gateState === 'unknown'
      ? 'bg-amber-600/20 border-amber-500/40 text-amber-400'
      : 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400';

  const GateIcon = blocked ? ShieldAlert : ShieldCheck;

  return (
    <div className={`flex flex-wrap items-center gap-3 px-4 py-2.5 rounded-xl border ${gateColor} text-sm`}>
      {/* Gate status */}
      <div className="flex items-center gap-2 font-semibold">
        <GateIcon className="w-4 h-4" />
        <span className="uppercase tracking-wider text-xs">
          {blocked ? 'BLOCKED' : gateState === 'limited' ? 'LIMITED' : gateState === 'unknown' ? 'UNKNOWN' : 'CLEAR'}
        </span>
      </div>

      {/* Mode badge */}
      <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold ${modeColors.badge}`}>
        <Radio className={`w-2.5 h-2.5 ${isLive ? 'animate-pulse' : ''}`} />
        {currentMode}
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-current opacity-20" />

      {/* Critical reasons (if blocked) */}
      {criticals.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs">
          <ShieldAlert className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <span>{criticals[0].message}</span>
          {criticals[0].hint && (
            <span className="text-slate-500 ml-1">— {criticals[0].hint}</span>
          )}
        </div>
      )}

      {/* Warnings (if limited) */}
      {!blocked && warnings.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>{warnings.length} warning{warnings.length > 1 ? 's' : ''}: {warnings[0].message}</span>
        </div>
      )}

      {/* Near-limit warnings (always visible when approaching) */}
      <div className="ml-auto flex items-center gap-3">
        {risk && (
          <>
            {/* Exposure utilization */}
            <div className={`flex items-center gap-1.5 text-xs ${
              nearExposureLimit ? 'text-amber-400' : 'text-slate-500'
            }`}>
              <TrendingUp className="w-3.5 h-3.5" />
              <span>Exp: {(exposurePct ?? 0).toFixed(0)}%</span>
              {nearExposureLimit && <AlertTriangle className="w-3 h-3" />}
            </div>

            {/* Daily loss utilization */}
            <div className={`flex items-center gap-1.5 text-xs ${
              nearDailyLossLimit ? 'text-red-400' : 'text-slate-500'
            }`}>
              <Activity className="w-3.5 h-3.5" />
              <span>Loss: {(dailyLossPct ?? 0).toFixed(0)}%</span>
              {nearDailyLossLimit && <AlertTriangle className="w-3 h-3" />}
            </div>
          </>
        )}

        {/* Config hot-reload button */}
        <div className="w-px h-4 bg-current opacity-20" />
        <button type="button"
          onClick={handleConfigReload}
          disabled={reloading}
          title="Hot-reload risk limits, reality assertions, and rebalancer targets"
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold border transition-colors ${
            reloadStatus === 'ok'
              ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300'
              : reloadStatus === 'err'
                ? 'bg-red-600/20 border-red-500/40 text-red-300'
                : 'bg-slate-700/60 border-slate-600 text-slate-400 hover:text-slate-200 hover:border-slate-500'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <RefreshCw className={`w-3 h-3 ${reloading ? 'animate-spin' : ''}`} />
          {reloadStatus === 'ok' ? 'RELOADED' : reloadStatus === 'err' ? 'FAILED' : 'RELOAD'}
        </button>
      </div>
    </div>
  );
}
