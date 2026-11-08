import { useState } from 'react';
import { Wifi, WifiOff, AlertTriangle } from '../ui/icons';
import { useKalshiStore } from '../store';

type ConnectionState = 'connected' | 'degraded' | 'disconnected';

/**
 * Connectivity indicator driven by the shared store — refreshAll() already
 * polls /unified-health every 15s, so a second private poller here was pure
 * duplicate traffic (and could disagree with the rest of the UI).
 *
 *   connected    — store connected AND unified-health overall_status ok
 *   degraded     — store connected but health non-ok / missing
 *   disconnected — every core fetch failed this cycle
 */
export default function ConnectionStatusIndicator() {
  const connected = useKalshiStore(s => s.connected);
  const healthOk = useKalshiStore(s => s.system.health.ok);
  const refreshAll = useKalshiStore(s => s.refreshAll);
  const [showTooltip, setShowTooltip] = useState(false);

  const state: ConnectionState = !connected
    ? 'disconnected'
    : healthOk
      ? 'connected'
      : 'degraded';

  const config = {
    connected: { icon: Wifi, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', label: 'Connected' },
    degraded: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', label: 'Degraded' },
    disconnected: { icon: WifiOff, color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30', label: 'Offline' },
  }[state];

  const Icon = config.icon;

  return (
    <div
      className="relative"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      onFocus={() => setShowTooltip(true)}
      onBlur={() => setShowTooltip(false)}
    >
      <button type="button"
        onClick={() => void refreshAll()}
        className={`p-2 rounded-lg ${config.bg} border ${config.border} transition-all hover:scale-105`}
        title={`API: ${config.label}`}
        aria-label={`Connection status: ${config.label}. Activate to refresh.`}>
        <Icon className={`w-4 h-4 ${config.color}`} />
      </button>

      {showTooltip && (
        <div role="tooltip" className="absolute right-0 top-full mt-2 w-48 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 z-50">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-2 h-2 rounded-full ${
              state === 'connected' ? 'bg-emerald-400' : state === 'degraded' ? 'bg-yellow-400' : 'bg-red-400'
            }`} />
            <span className="text-xs font-medium text-white">{config.label}</span>
          </div>
          <p className="text-[10px] text-slate-400">
            {state === 'disconnected'
              ? 'All backend probes failed this cycle.'
              : state === 'degraded'
                ? 'Backend reachable but unified-health is not ok.'
                : 'Unified-health reports ok.'}
          </p>
          <p className="text-[10px] text-slate-500 mt-1">Click to refresh</p>
        </div>
      )}
    </div>
  );
}
