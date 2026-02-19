import {
  Globe, WifiOff, RefreshCw, AlertTriangle,
  CheckCircle, Clock, Zap
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface ChainProvider {
  name: string;
  chain: string;
  status: 'healthy' | 'degraded' | 'down';
  latencyMs: number;
  priority: number;
  blockHeight: number;
  lastBlock: string;
}

interface CircuitBreakerState {
  chain: string;
  state: 'closed' | 'open' | 'half-open';
  trippedAt: string;
  reason: string;
}

interface OracleStatus {
  name: string;
  chain: string;
  status: 'live' | 'stale' | 'down';
  lastUpdate: string;
  priceFeeds: number;
  staleFeedCount: number;
}

const CHAIN_COLORS: Record<string, string> = {
  solana: 'border-l-purple-400',
  ethereum: 'border-l-blue-400',
  polygon: 'border-l-violet-400',
  arbitrum: 'border-l-sky-400',
};

const STATUS_ICONS: Record<string, { icon: typeof CheckCircle; color: string }> = {
  healthy: { icon: CheckCircle, color: 'text-green-400' },
  live: { icon: CheckCircle, color: 'text-green-400' },
  degraded: { icon: AlertTriangle, color: 'text-amber-400' },
  stale: { icon: AlertTriangle, color: 'text-amber-400' },
  down: { icon: WifiOff, color: 'text-red-400' },
};

const DEFAULT_STATUS_ICON = { icon: AlertTriangle, color: 'text-gray-400' };

export default function OnChainHealthPanel() {
  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ providers: ChainProvider[]; circuitBreakers: CircuitBreakerState[]; oracles: OracleStatus[] }>(
    API_ENDPOINTS.BLOCKCHAIN_HEALTH,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="On-chain health" error={fetchError} onRetry={refetch} />;
  }
  const providers = rawData?.providers ?? [];
  const circuitBreakers = rawData?.circuitBreakers ?? [];
  const oracles = rawData?.oracles ?? [];

  const healthyCount = providers.filter(p => p.status === 'healthy').length;
  const trippedCBs = circuitBreakers.filter(cb => cb.state !== 'closed');

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading on-chain health...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-purple-400" />
          <h3 className="text-lg font-bold text-white">On-Chain Health</h3>
          <span className="text-sm text-gray-400">
            {healthyCount}/{providers.length} providers
          </span>
          {trippedCBs.length > 0 && (
            <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400">
              {trippedCBs.length} CB tripped
            </span>
          )}
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh on-chain health"
         aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* RPC Providers */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {providers.map((p, i) => {
          const cfg = STATUS_ICONS[p.status] ?? DEFAULT_STATUS_ICON;
          const StatusIcon = cfg.icon;
          const chainColor = CHAIN_COLORS[p.chain] || 'border-l-gray-400';

          return (
            <div
              key={`${p.name}-${p.chain}-${i}`}
              className={`bg-slate-800/50 rounded-lg border border-slate-700/50 border-l-4 ${chainColor} p-3`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <StatusIcon className={`w-4 h-4 ${cfg.color}`} />
                  <span className="font-semibold text-white">{p.name}</span>
                  <span className="text-xs text-gray-500 uppercase">{p.chain}</span>
                </div>
                <span className="text-xs text-gray-500">P{p.priority}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-gray-500 flex items-center gap-1">
                    <Zap className="w-3 h-3" /> Latency
                  </span>
                  <span className={`font-medium ${p.latencyMs > 200 ? 'text-red-400' : p.latencyMs > 100 ? 'text-amber-400' : 'text-green-400'}`}>
                    {p.latencyMs}ms
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> Block
                  </span>
                  <span className="font-medium text-gray-300 font-mono">
                    {(p.blockHeight ?? 0).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Circuit Breakers + Oracles */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Circuit Breakers */}
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <h4 className="text-sm font-medium text-gray-400 mb-3">Chain Circuit Breakers</h4>
          <div className="space-y-2">
            {circuitBreakers.map((cb, idx) => {
              const isTripped = cb.state !== 'closed';
              return (
                <div
                  key={cb.chain || `cb-${idx}`}
                  className={`flex items-center justify-between px-3 py-2 rounded ${
                    isTripped ? 'bg-red-500/10' : 'bg-slate-900/50'
                  }`}
                >
                  <span className="text-sm text-white capitalize">{cb.chain}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    cb.state === 'closed' ? 'bg-green-500/20 text-green-400' :
                    cb.state === 'half-open' ? 'bg-amber-500/20 text-amber-400' :
                    'bg-red-500/20 text-red-400'
                  }`}>
                    {cb.state}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Oracles */}
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <h4 className="text-sm font-medium text-gray-400 mb-3">Price Oracles</h4>
          <div className="space-y-2">
            {oracles.map(oracle => {
              const cfg = STATUS_ICONS[oracle.status] ?? DEFAULT_STATUS_ICON;
              const OracleIcon = cfg.icon;
              return (
                <div
                  key={`${oracle.name}-${oracle.chain}`}
                  className="flex items-center justify-between px-3 py-2 bg-slate-900/50 rounded"
                >
                  <div className="flex items-center gap-2">
                    <OracleIcon className={`w-4 h-4 ${cfg.color}`} />
                    <span className="text-sm text-white">{oracle.name}</span>
                    <span className="text-xs text-gray-500 uppercase">{oracle.chain}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-gray-400">{oracle.priceFeeds ?? 0} feeds</span>
                    {(oracle.staleFeedCount ?? 0) > 0 && (
                      <span className="text-amber-400">{oracle.staleFeedCount} stale</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
