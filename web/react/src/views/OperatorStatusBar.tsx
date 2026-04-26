import { Wifi, WifiOff, AlertTriangle, Clock, Shield } from '../ui/icons';
import { useMeridSocket } from '../hooks/useMeridSocket';
import { useRiskProtections, getOverallRiskStatus } from '../hooks/useRiskProtections';
import { formatTime } from '../utils/formatters';
import type { OperatorSummary } from '../hooks/useOperatorSummary';

interface OperatorStatusBarProps {
  summary: OperatorSummary | null;
  lastUpdated: Date | null;
  alertCount?: number;
}

const MODE_COLORS: Record<string, string> = {
  PAPER: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
  LIVE: 'bg-red-500/20 text-red-400 border-red-500/40',
  SIMULATION: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
  SIM: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
  HYBRID: 'bg-purple-500/20 text-purple-400 border-purple-500/40',
  AUTONOMOUS: 'bg-rose-500/20 text-rose-400 border-rose-500/40',
  OFFLINE: 'bg-slate-500/20 text-slate-400 border-slate-500/40',
  UNKNOWN: 'bg-slate-500/20 text-slate-400 border-slate-500/40',
};

export function OperatorStatusBar({ summary, lastUpdated, alertCount = 0 }: OperatorStatusBarProps) {
  const { connected } = useMeridSocket();
  const { data: protections } = useRiskProtections();

  const modeName = summary?.mode?.name?.toUpperCase() || 'UNKNOWN';
  const modeColor = MODE_COLORS[modeName] || MODE_COLORS.UNKNOWN;

  const circuitStatus = protections ? getOverallRiskStatus(protections) : null;
  const circuitOk = !circuitStatus || circuitStatus.status === 'good';

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-2 bg-slate-900/80 border border-slate-800 rounded-xl">
      {/* Trading Mode Badge */}
      <div className={`px-3 py-1 rounded-full text-xs font-bold border ${modeColor} uppercase tracking-wider`}>
        {modeName}
      </div>

      {/* WebSocket Connection */}
      <div className="flex items-center gap-1.5 text-xs text-slate-400">
        {connected ? (
          <Wifi className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <WifiOff className="w-3.5 h-3.5 text-red-400" />
        )}
        <span>{connected ? 'Live' : 'Disconnected'}</span>
      </div>

      {/* Circuit Breaker */}
      <div className="flex items-center gap-1.5 text-xs">
        <Shield className={`w-3.5 h-3.5 ${circuitOk ? 'text-emerald-400' : 'text-red-400'}`} />
        <span className={circuitOk ? 'text-emerald-400' : 'text-red-400'}>
          {circuitOk ? 'CB OK' : 'CB TRIPPED'}
        </span>
      </div>

      {/* Swarm Paused Indicator */}
      {summary?.swarm?.paused && (
        <div className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-xs font-semibold border border-amber-500/40">
          SWARM PAUSED
        </div>
      )}

      {/* Alert Count */}
      {alertCount > 0 && (
        <div className="flex items-center gap-1 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5" />
          <span>{alertCount} alert{alertCount !== 1 ? 's' : ''}</span>
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* System Metrics */}
      {summary?.system && (
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>CPU {(summary.system.cpu_percent ?? 0).toFixed(0)}%</span>
          <span>MEM {(summary.system.memory_percent ?? 0).toFixed(0)}%</span>
        </div>
      )}

      {/* Last Updated */}
      {lastUpdated && (
        <div className="flex items-center gap-1 text-xs text-slate-500">
          <Clock className="w-3 h-3" />
          <span>{formatTime(lastUpdated.toISOString())}</span>
        </div>
      )}
    </div>
  );
}
