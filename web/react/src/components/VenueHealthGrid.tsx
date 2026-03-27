import { useState } from 'react';
import { 
  Wifi, WifiOff, AlertTriangle, RefreshCw, Power, 
  Clock, Zap, ShieldCheck 
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS} from '../config/constants';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

interface VenueHealth {
  name: string;
  key: string;
  domain: 'prediction' | 'crypto' | 'equity';
  connected: boolean;
  enabled: boolean;
  mode: 'SIM' | 'PAPER' | 'LIVE';
  latencyMs: number;
  latencyP95Ms: number;
  errorRate: number;
  circuitBreaker: 'closed' | 'open' | 'half-open';
  lastHeartbeat: string;
  requestsPerMin: number;
}

const CB_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  closed: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'Healthy' },
  'half-open': { bg: 'bg-amber-500/20', text: 'text-amber-400', label: 'Recovering' },
  open: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'Tripped' },
};

const DOMAIN_COLORS: Record<string, string> = {
  prediction: 'border-l-orange-400',
  crypto: 'border-l-yellow-400',
  equity: 'border-l-blue-400',
};

export default function VenueHealthGrid() {
  const { data: rawData, loading, error, refetch } = useApiData<{ venues: VenueHealth[] }>(
    API_ENDPOINTS.PIPELINE_VENUES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const venues = rawData?.venues ?? [];
  const [toggleError, setToggleError] = useState<string | null>(null);

  const toggleVenue = async (key: string, enable: boolean) => {
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.PIPELINE_VENUE_TOGGLE(enable ? 'enable' : 'disable')}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ venue: key }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      refetch();
    } catch {
      setToggleError(`Failed to ${enable ? 'enable' : 'disable'} ${key}`);
    }
  };

  const getStaleness = (heartbeat: string): { text: string; color: string } => {
    if (!heartbeat) return { text: 'Never', color: 'text-red-400' };
    const ms = Date.now() - new Date(heartbeat).getTime();
    if (ms < 10000) return { text: `${Math.floor(ms / 1000)}s ago`, color: 'text-green-400' };
    if (ms < 30000) return { text: `${Math.floor(ms / 1000)}s ago`, color: 'text-amber-400' };
    return { text: `${Math.floor(ms / 1000)}s ago`, color: 'text-red-400' };
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading venue health...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wifi className="w-5 h-5 text-emerald-400" />
          <h3 className="text-lg font-bold text-white">Venue Health</h3>
          <span className="text-sm text-gray-400">
            {venues.filter(v => v.connected).length}/{venues.length} connected
          </span>
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh venue health"
         aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {toggleError && (
        <div className="px-3 py-2 rounded-lg bg-red-900/40 border border-red-700 text-red-300 text-xs flex items-center justify-between">
          <span>{toggleError}</span>
          <button type="button" onClick={() => setToggleError(null)} className="text-red-400 hover:text-red-200 ml-2">✕</button>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error?.message ?? 'Unknown error'}</span>
          <button type="button" onClick={() => refetch()} className="ml-auto text-xs underline hover:text-red-300">Retry</button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {venues.map((venue) => {
          const cb = CB_COLORS[venue.circuitBreaker];
          const staleness = getStaleness(venue.lastHeartbeat);

          return (
            <div
              key={venue.key}
              className={`bg-slate-800/50 rounded-lg border border-slate-700/50 border-l-4 ${DOMAIN_COLORS[venue.domain]} p-3`}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {venue.connected ? (
                    <Wifi className="w-4 h-4 text-green-400" />
                  ) : (
                    <WifiOff className="w-4 h-4 text-red-400" />
                  )}
                  <span className="font-semibold text-white">{venue.name}</span>
                  <span className="text-xs text-gray-500 uppercase">{venue.domain}</span>
                </div>
                <button type="button"
                  onClick={() => toggleVenue(venue.key, !venue.enabled)}
                  className={`p-1 rounded transition-colors ${
                    venue.enabled
                      ? 'text-green-400 hover:bg-green-500/20'
                      : 'text-gray-500 hover:bg-gray-500/20'
                  }`}
                  title={venue.enabled ? 'Disable venue' : 'Enable venue'}
                >
                  <Power className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Metrics Row */}
              <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                <div>
                  <span className="text-gray-500 flex items-center gap-1">
                    <Zap className="w-3 h-3" /> Latency
                  </span>
                  <span className={`font-medium ${venue.latencyMs > 200 ? 'text-red-400' : venue.latencyMs > 100 ? 'text-amber-400' : 'text-green-400'}`}>
                    {venue.latencyMs}ms
                  </span>
                  <span className="text-gray-500 ml-1">p95: {venue.latencyP95Ms}ms</span>
                </div>
                <div>
                  <span className="text-gray-500 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Errors
                  </span>
                  <span className={`font-medium ${(typeof venue.errorRate === 'number' ? venue.errorRate : 0) > 1 ? 'text-red-400' : (typeof venue.errorRate === 'number' ? venue.errorRate : 0) > 0 ? 'text-amber-400' : 'text-green-400'}`}>
                    {(typeof venue.errorRate === 'number' ? venue.errorRate : 0).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> Last
                  </span>
                  <span className={`font-medium ${staleness.color}`}>
                    {staleness.text}
                  </span>
                </div>
              </div>

              {/* Footer: Circuit Breaker + Mode */}
              <div className="flex items-center justify-between">
                <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs ${cb.bg} ${cb.text}`}>
                  <ShieldCheck className="w-3 h-3" />
                  {cb.label}
                </div>
                <span className="text-xs text-gray-400">
                  {venue.mode} · {venue.requestsPerMin} req/min
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
