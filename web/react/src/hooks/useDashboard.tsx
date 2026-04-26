/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect } from 'react';
import { Activity, AlertCircle, CheckCircle, TrendingUp, Server, Cpu } from '../ui/icons';
import { api } from '../services/api';
import type { SystemHealth } from '../services/api';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { useApiData } from './useApiData';
import { logUiError } from '../utils/logger';

const RETRY_DELAY_MS = 500;
const LOG_THROTTLE_MS = 10000;
const logDedup = new Map<string, number>();

async function retryOnce<T>(request: () => Promise<T>): Promise<T> {
  try {
    return await request();
  } catch {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, RETRY_DELAY_MS);
    });
    return request();
  }
}

function logUiErrorThrottled(scope: string, message: string, error: unknown): void {
  const key = `${scope}:${message}`;
  const now = Date.now();
  const lastLogged = logDedup.get(key) ?? 0;

  if (now - lastLogged < LOG_THROTTLE_MS) {
    return;
  }

  logDedup.set(key, now);
  logUiError(scope, message, error);
}

interface PnLSummary {
  today_pnl: number;
  today_pnl_pct: number;
  mtm_pnl: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  limit_daily_loss: number;
  limit_utilization_pct: number;
}

interface Agent {
  id: string;
  name: string;
  status: string;
  heartbeat_age_ms: number;
  strategy: string;
  state: string;
  positions_count: number;
  today_pnl: number;
  tasks_completed?: number;
  uptime?: number;
}

interface AgentsSummary {
  agents: Agent[];
  summary: {
    total: number;
    healthy: number;
    paused: number;
    unhealthy: number;
  };
}

interface TradingSummary {
  active_strategies: number;
  paused_strategies: number;
  venues_connected: number;
  venues: string[];
  notional_deployed: number;
  notional_capacity: number;
  utilization_pct: number;
}

interface PrimeStatus {
  mode: string;
  market_data_connected: boolean;
  narrative_available: boolean;
  last_narrative_timestamp: number;
  data_feeds: Record<string, { connected: boolean; latency_ms: number }>;
}

export function useSystemHealth() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchHealth() {
      try {
        const data = await retryOnce(() => api.getSystemHealth());
        setHealth(data);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to fetch health');
        logUiErrorThrottled('useDashboard', 'System health fetch error', e);
      } finally {
        setLoading(false);
      }
    }

    fetchHealth();
    const interval = setInterval(fetchHealth, DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    return () => clearInterval(interval);
  }, []);

  return { health, loading, error };
}

export function usePnLSummary() {
  const [pnl, setPnL] = useState<PnLSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchPnL() {
      try {
        const data = await api.getPnLSummary();
        setPnL(data);
      } catch (e) {
        logUiErrorThrottled('useDashboard', 'Failed to fetch P&L', e);
      } finally {
        setLoading(false);
      }
    }

    const t = setTimeout(() => { fetchPnL(); }, 2000);
    const interval = setInterval(fetchPnL, DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    return () => { clearTimeout(t); clearInterval(interval); };
  }, []);

  return { pnl, loading };
}

export function useAgentsSummary() {
  const [agents, setAgents] = useState<AgentsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const data = await api.getAgentSummary();
        setAgents(data);
      } catch (e) {
        logUiErrorThrottled('useDashboard', 'Failed to fetch agents', e);
      } finally {
        setLoading(false);
      }
    }

    const t = setTimeout(() => { fetchAgents(); }, 4000);
    const interval = setInterval(fetchAgents, DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    return () => { clearTimeout(t); clearInterval(interval); };
  }, []);

  return { agents, loading };
}

export function useTradingSummary() {
  const [trading, setTrading] = useState<TradingSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchTrading() {
      try {
        const data = await retryOnce(() => api.getTradingSummary());
        setTrading(data);
      } catch (e) {
        logUiErrorThrottled('useDashboard', 'Failed to fetch trading', e);
      } finally {
        setLoading(false);
      }
    }

    const t = setTimeout(() => { fetchTrading(); }, 6000);
    const interval = setInterval(fetchTrading, DEFAULTS.POLLING_INTERVALS.FAST_REFRESH);
    return () => { clearTimeout(t); clearInterval(interval); };
  }, []);

  return { trading, loading };
}

interface HealthStatus {
  status?: string;
  venue?: {
    connected?: boolean;
    circuit?: { state?: string };
    rate_limits?: { read?: number; write?: number };
  };
  venue_health?: {
    connected?: boolean;
    circuit?: { state?: string };
  };
  metrics?: {
    active_markets?: number;
    covered_markets?: number;
    coverage_pct?: number;
  };
}

export function useKalshiHealth() {
  const { data, loading, error } = useApiData<HealthStatus>(
    API_ENDPOINTS.KALSHI_GRID_STATUS, // Use status for full data including health
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  return { health: data, loading, error };
}

export function usePrimeStatus() {
  const { data, loading, error } = useApiData<PrimeStatus>(
    API_ENDPOINTS.PRIME_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  return { prime: data, loading, error };
}

// System Health Card Component
export function SystemHealthCard() {
  const { health, loading } = useSystemHealth();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const isHealthy = health?.status === 'healthy';
  const isDegraded = health?.status === 'degraded';

  return (
    <div className={`bg-slate-900/70 rounded-xl p-4 border ${isHealthy ? 'border-emerald-500/30' : isDegraded ? 'border-amber-500/30' : 'border-rose-500/30'}`}>
      <div className="flex items-center gap-2 mb-3">
        {isHealthy ? (
          <CheckCircle className="w-5 h-5 text-emerald-400" />
        ) : isDegraded ? (
          <AlertCircle className="w-5 h-5 text-amber-400" />
        ) : (
          <AlertCircle className="w-5 h-5 text-rose-400" />
        )}
        <h3 className="text-sm font-medium text-slate-400">System Health</h3>
      </div>
      
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-2xl font-semibold ${isHealthy ? 'text-emerald-400' : isDegraded ? 'text-amber-400' : 'text-rose-400'}`}>
          {health?.status === 'healthy' ? 'Operational' : health?.status === 'degraded' ? 'Degraded' : 'Critical'}
        </span>
      </div>
      
      <div className="text-xs text-slate-400">
        {health?.incident_flag ? (
          <span className="text-rose-400">⚠️ Active Incident</span>
        ) : (
          <span>All systems operational</span>
        )}
      </div>
      
      {health?.services && (
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          {Object.entries(health.services).slice(0, 4).map(([name, service]) => (
            <div key={name} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-full ${service.status === 'healthy' ? 'bg-emerald-400' : 'bg-rose-400'}`}></div>
              <span className="text-slate-500 capitalize">{name.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// P&L Card Component with Sparkline
export function PnLCard() {
  const { pnl, loading } = usePnLSummary();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const isPositive = (pnl?.today_pnl || 0) >= 0;
  const utilizationColor = (pnl?.limit_utilization_pct || 0) > 75 ? 'text-rose-400' : (pnl?.limit_utilization_pct || 0) > 50 ? 'text-amber-400' : 'text-emerald-400';

  return (
    <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="w-5 h-5 text-blue-400" />
        <h3 className="text-sm font-medium text-slate-400">P&L Analytics</h3>
      </div>
      
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-2xl font-semibold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isPositive ? '+' : ''}${pnl?.today_pnl?.toFixed(2) || '0.00'}
        </span>
        <span className={`text-sm ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
          ({isPositive ? '+' : ''}{pnl?.today_pnl_pct?.toFixed(2) || '0.00'}%)
        </span>
      </div>
      
      <div className="text-xs text-slate-400 mb-3">
        MTM: ${pnl?.mtm_pnl?.toLocaleString() || '0.00'}
      </div>
      
      {/* Limit utilization bar */}
      <div className="mt-3">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-slate-500">Daily Limit</span>
          <span className={utilizationColor}>{pnl?.limit_utilization_pct?.toFixed(1) || '0'}%</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div 
            className={`h-full rounded-full transition-all ${(pnl?.limit_utilization_pct || 0) > 75 ? 'bg-rose-500' : (pnl?.limit_utilization_pct || 0) > 50 ? 'bg-amber-500' : 'bg-emerald-500'}`}
            style={{ width: `${Math.min(pnl?.limit_utilization_pct || 0, 100)}%` }}
          ></div>
        </div>
        <div className="text-xs text-slate-500 mt-1">
          Drawdown: {pnl?.max_drawdown_pct?.toFixed(1) || '0'}% of limit
        </div>
      </div>
    </div>
  );
}

// Trading Operations Card
export function TradingOperationsCard() {
  const { trading, loading } = useTradingSummary();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-5 h-5 text-purple-400" />
        <h3 className="text-sm font-medium text-slate-400">Trading Operations</h3>
      </div>
      
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <div className="text-2xl font-semibold text-emerald-400">{trading?.active_strategies || 0}</div>
          <div className="text-xs text-slate-500">Active</div>
        </div>
        <div>
          <div className="text-2xl font-semibold text-amber-400">{trading?.paused_strategies || 0}</div>
          <div className="text-xs text-slate-500">Paused</div>
        </div>
      </div>
      
      <div className="border-t border-slate-800 pt-3">
        <div className="flex justify-between items-center mb-2">
          <span className="text-xs text-slate-500">Venues</span>
          <span className="text-sm font-medium">{trading?.venues_connected || 0}</span>
        </div>
        <div className="flex flex-wrap gap-1">
          {trading?.venues?.map((venue) => (
            <span key={venue} className="text-xs px-2 py-0.5 bg-slate-800 rounded text-slate-400">{venue}</span>
          ))}
        </div>
      </div>
      
      <div className="border-t border-slate-800 pt-3 mt-3">
        <div className="flex justify-between text-xs mb-1">
          <span className="text-slate-500">Deployed</span>
          <span className="text-slate-300">${((trading?.notional_deployed || 0) / 1000).toFixed(1)}k / ${((trading?.notional_capacity || 0) / 1000).toFixed(0)}k</span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div 
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${trading?.utilization_pct || 0}%` }}
          ></div>
        </div>
      </div>
    </div>
  );
}

// Prime Status Card
export function PrimeStatusCard() {
  const { prime, loading } = usePrimeStatus();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const mode = prime?.mode || 'paper';
  const isLive = mode === 'live';

  return (
    <div className={`bg-slate-900/70 rounded-xl p-4 border ${isLive ? 'border-rose-500/30' : 'border-slate-800'}`}>
      <div className="flex items-center gap-2 mb-3">
        <Server className={`w-5 h-5 ${isLive ? 'text-rose-400' : 'text-blue-400'}`} />
        <h3 className="text-sm font-medium text-slate-400">Prime Screen</h3>
        {isLive && <span className="text-xs px-2 py-0.5 bg-rose-500/20 text-rose-400 rounded">LIVE</span>}
      </div>
      
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-3 h-3 rounded-full ${prime?.market_data_connected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`}></div>
        <span className="text-sm">{prime?.market_data_connected ? 'Data Connected' : 'Disconnected'}</span>
      </div>
      
      {prime?.data_feeds && (
        <div className="grid grid-cols-3 gap-2 text-xs">
          {Object.entries(prime.data_feeds).map(([name, feed]) => (
            <div key={name} className="flex items-center gap-1">
              <div className={`w-1.5 h-1.5 rounded-full ${feed.connected ? 'bg-emerald-400' : 'bg-rose-400'}`}></div>
              <span className="text-slate-500 capitalize">{name}</span>
              {feed.connected && <span className="text-slate-600">{feed.latency_ms}ms</span>}
            </div>
          ))}
        </div>
      )}
      
      <div className="mt-3 text-xs text-slate-500">
        Narrative: {prime?.narrative_available ? 'Available' : 'Unavailable'}
      </div>
    </div>
  );
}

// Kalshi Health Card
export function KalshiHealthCard() {
  const { health, loading } = useKalshiHealth();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const isConnected = health?.venue_health?.connected ?? health?.venue?.connected ?? false;
  const circuitState = health?.venue_health?.circuit?.state ?? health?.venue?.circuit?.state ?? 'unknown';
  const coveragePct = health?.metrics?.coverage_pct;

  return (
    <div className={`bg-slate-900/70 rounded-xl p-4 border ${isConnected ? 'border-orange-500/30' : 'border-rose-500/30'}`}>
      <div className="flex items-center gap-2 mb-3">
        <Activity className={`w-5 h-5 ${isConnected ? 'text-orange-400' : 'text-rose-400'}`} />
        <h3 className="text-sm font-medium text-slate-400">Kalshi Health</h3>
      </div>
      
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-2xl font-semibold ${isConnected ? 'text-orange-400' : 'text-rose-400'}`}>
          {isConnected ? 'Connected' : 'Offline'}
        </span>
      </div>
      
      <div className="text-xs text-slate-400 space-y-1">
        <div className="flex justify-between">
          <span>Breaker:</span>
          <span className={circuitState === 'closed' ? 'text-emerald-400' : 'text-amber-400'}>
            {circuitState.toUpperCase()}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Coverage:</span>
          <span className="text-blue-400">
            {typeof coveragePct === 'number' ? coveragePct.toFixed(1) : '0.0'}%
          </span>
        </div>
      </div>
    </div>
  );
}

// Agent Status Card
export function AgentStatusCard() {
  const { agents, loading } = useAgentsSummary();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  if (!agents || !agents.agents || agents.agents.length === 0) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
        <div className="flex items-center gap-2 mb-3">
          <Cpu className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-medium text-slate-400">Agent Status</h3>
        </div>
        <div className="text-sm text-slate-500">No agents available</div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800">
      <div className="flex items-center gap-2 mb-3">
        <Cpu className="w-5 h-5 text-cyan-400" />
        <h3 className="text-sm font-medium text-slate-400">Agent Status</h3>
      </div>
      
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="text-center">
          <div className="text-xl font-semibold text-emerald-400">{agents?.summary?.healthy || 0}</div>
          <div className="text-xs text-slate-500">Healthy</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-semibold text-amber-400">{agents?.summary?.paused || 0}</div>
          <div className="text-xs text-slate-500">Paused</div>
        </div>
        <div className="text-center">
          <div className="text-xl font-semibold text-rose-400">{agents?.summary?.unhealthy || 0}</div>
          <div className="text-xs text-slate-500">Unhealthy</div>
        </div>
      </div>
      
      <div className="space-y-2">
        {agents.agents.slice(0, 3).map((agent) => (
          <div key={agent.id} className="flex items-center justify-between py-1.5 border-b border-slate-800/50 last:border-0">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${agent.status === 'active' ? 'bg-emerald-400' : agent.status === 'paused' ? 'bg-amber-400' : 'bg-rose-400'}`}></div>
              <span className="text-sm">{agent.name}</span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-slate-500">{agent.tasks_completed ?? 0} tasks</span>
              <span className="text-emerald-400">
                {typeof agent.uptime === 'number' ? `${agent.uptime.toFixed(1)}%` : 'N/A'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Risk Protection Card - uses real risk protections API
export { RiskProtectionsCard as RiskProtectionCard } from '../components/RiskProtectionsPanel';
