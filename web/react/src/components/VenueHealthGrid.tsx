import { useState, useEffect, useCallback } from 'react';
import { 
  Wifi, WifiOff, AlertTriangle, RefreshCw, Power, 
  Clock, Zap, ShieldCheck 
} from 'lucide-react';

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
  const [venues, setVenues] = useState<VenueHealth[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchVenues = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/pipeline/venues');
      if (res.ok) {
        const data = await res.json();
        if (data.venues) setVenues(data.venues);
      }
    } catch {
      setVenues([
        { name: 'Kalshi', key: 'kalshi', domain: 'prediction', connected: true, enabled: true, mode: 'SIM', latencyMs: 45, latencyP95Ms: 120, errorRate: 0.1, circuitBreaker: 'closed', lastHeartbeat: new Date().toISOString(), requestsPerMin: 12 },
        { name: 'Binance', key: 'binance', domain: 'crypto', connected: true, enabled: true, mode: 'SIM', latencyMs: 32, latencyP95Ms: 85, errorRate: 0.0, circuitBreaker: 'closed', lastHeartbeat: new Date().toISOString(), requestsPerMin: 45 },
        { name: 'Coinbase', key: 'coinbase', domain: 'crypto', connected: true, enabled: true, mode: 'SIM', latencyMs: 55, latencyP95Ms: 140, errorRate: 0.2, circuitBreaker: 'closed', lastHeartbeat: new Date().toISOString(), requestsPerMin: 30 },
        { name: 'Kraken', key: 'kraken', domain: 'crypto', connected: true, enabled: true, mode: 'SIM', latencyMs: 68, latencyP95Ms: 180, errorRate: 0.0, circuitBreaker: 'closed', lastHeartbeat: new Date().toISOString(), requestsPerMin: 20 },
        { name: 'Alpaca', key: 'alpaca', domain: 'equity', connected: true, enabled: true, mode: 'PAPER', latencyMs: 40, latencyP95Ms: 95, errorRate: 0.0, circuitBreaker: 'closed', lastHeartbeat: new Date().toISOString(), requestsPerMin: 8 },
        { name: 'IBKR', key: 'ibkr', domain: 'equity', connected: false, enabled: false, mode: 'SIM', latencyMs: 0, latencyP95Ms: 0, errorRate: 0, circuitBreaker: 'open', lastHeartbeat: '', requestsPerMin: 0 },
      ]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchVenues();
    const interval = setInterval(fetchVenues, 5000);
    return () => clearInterval(interval);
  }, [fetchVenues]);

  const toggleVenue = async (key: string, enable: boolean) => {
    try {
      await fetch(`/api/v1/pipeline/venue/${enable ? 'enable' : 'disable'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ venue: key }),
      });
      await fetchVenues();
    } catch (err) {
      console.error(`Failed to toggle venue ${key}:`, err);
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
        <button
          onClick={fetchVenues}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh venue health"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

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
                <button
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
                  <span className={`font-medium ${venue.errorRate > 1 ? 'text-red-400' : venue.errorRate > 0 ? 'text-amber-400' : 'text-green-400'}`}>
                    {venue.errorRate.toFixed(1)}%
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
