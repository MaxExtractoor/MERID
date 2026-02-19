import { useState, useEffect, useCallback } from 'react';
import { Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS} from '../config/constants';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

type ConnectionState = 'connected' | 'degraded' | 'disconnected';

export default function ConnectionStatusIndicator() {
  const [state, setState] = useState<ConnectionState>('connected');
  const [latency, setLatency] = useState<number | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);

  const checkConnection = useCallback(async () => {
    const start = performance.now();
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SYSTEM_HEALTH}`, {
        signal: AbortSignal.timeout(5000),
        headers: authHeaders(),
      });
      const elapsed = Math.round(performance.now() - start);
      setLatency(elapsed);
      if (res.ok) {
        setState(elapsed > 2000 ? 'degraded' : 'connected');
      } else {
        setState('degraded');
      }
    } catch {
      setState('disconnected');
      setLatency(null);
    }
  }, []);

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(interval);
  }, [checkConnection]);

  const config = {
    connected: { icon: Wifi, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', label: 'Connected' },
    degraded: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', label: 'Slow' },
    disconnected: { icon: WifiOff, color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30', label: 'Offline' },
  }[state];

  const Icon = config.icon;

  return (
    <div
      className="relative"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button type="button"
        onClick={checkConnection}
        className={`p-2 rounded-lg ${config.bg} border ${config.border} transition-all hover:scale-105`}
        title={`API: ${config.label}`}
       aria-label="Icon">
        <Icon className={`w-4 h-4 ${config.color}`} />
      </button>

      {showTooltip && (
        <div className="absolute right-0 top-full mt-2 w-48 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 z-50">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-2 h-2 rounded-full ${
              state === 'connected' ? 'bg-emerald-400' : state === 'degraded' ? 'bg-yellow-400' : 'bg-red-400'
            }`} />
            <span className="text-xs font-medium text-white">{config.label}</span>
          </div>
          {latency !== null && (
            <p className="text-[10px] text-slate-400">
              Latency: <span className={`font-mono ${latency > 1000 ? 'text-yellow-400' : 'text-slate-300'}`}>{latency}ms</span>
            </p>
          )}
          <p className="text-[10px] text-slate-500 mt-1">Click to refresh</p>
        </div>
      )}
    </div>
  );
}
