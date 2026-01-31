import { useState, useEffect } from 'react';
import { Activity, AlertCircle, CheckCircle, PauseCircle, TrendingUp, Shield, Server, Cpu } from 'lucide-react';

interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: number;
  environment: string;
  incident_flag: boolean;
  services: Record<string, { status: string; last_check: number }>;
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
        const response = await fetch('/api/system/health');
        if (response.ok) {
          const data = await response.json();
          setHealth(data);
        }
      } catch (e) {
        setError('Failed to fetch health');
      } finally {
        setLoading(false);
      }
    }

    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
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
        const response = await fetch('/api/risk/pnl-summary');
        if (response.ok) {
          const data = await response.json();
          setPnL(data);
        }
      } catch (e) {
        console.error('Failed to fetch P&L:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchPnL();
    const interval = setInterval(fetchPnL, 30000);
    return () => clearInterval(interval);
  }, []);

  return { pnl, loading };
}

export function useAgentsSummary() {
  const [agents, setAgents] = useState<AgentsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const response = await fetch('/api/agents/summary');
        if (response.ok) {
          const data = await response.json();
          setAgents(data);
        }
      } catch (e) {
        console.error('Failed to fetch agents:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchAgents();
    const interval = setInterval(fetchAgents, 15000);
    return () => clearInterval(interval);
  }, []);

  return { agents, loading };
}

export function useTradingSummary() {
  const [trading, setTrading] = useState<TradingSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchTrading() {
      try {
        const response = await fetch('/api/trading/summary');
        if (response.ok) {
          const data = await response.json();
          setTrading(data);
        }
      } catch (e) {
        console.error('Failed to fetch trading:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchTrading();
    const interval = setInterval(fetchTrading, 30000);
    return () => clearInterval(interval);
  }, []);

  return { trading, loading };
}

export function usePrimeStatus() {
  const [prime, setPrime] = useState<PrimeStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchPrime() {
      try {
        const response = await fetch('/api/prime/status');
        if (response.ok) {
          const data = await response.json();
          setPrime(data);
        }
      } catch (e) {
        console.error('Failed to fetch prime status:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchPrime();
    const interval = setInterval(fetchPrime, 10000);
    return () => clearInterval(interval);
  }, []);

  return { prime, loading };
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
        {agents?.agents?.slice(0, 3).map((agent) => (
          <div key={agent.id} className="flex items-center justify-between py-1.5 border-b border-slate-800/50 last:border-0">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${agent.status === 'healthy' ? 'bg-emerald-400' : agent.status === 'paused' ? 'bg-amber-400' : 'bg-rose-400'}`}></div>
              <span className="text-sm">{agent.name}</span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-slate-500">{agent.positions_count} pos</span>
              <span className={agent.today_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                {agent.today_pnl >= 0 ? '+' : ''}${agent.today_pnl.toFixed(0)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Risk Protection Card (Kill Switch)
export function RiskProtectionCard() {
  const [protections, setProtections] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchProtections() {
      try {
        const response = await fetch('/api/risk/protections');
        if (response.ok) {
          const data = await response.json();
          setProtections(data);
        }
      } catch (e) {
        console.error('Failed to fetch protections:', e);
      } finally {
        setLoading(false);
      }
    }

    fetchProtections();
    const interval = setInterval(fetchProtections, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  const isLocked = protections?.locked_down;
  const isTripped = protections?.breaker_tripped;

  return (
    <div className={`bg-slate-900/70 rounded-xl p-4 border ${isLocked ? 'border-rose-500' : isTripped ? 'border-amber-500' : 'border-slate-800'}`}>
      <div className="flex items-center gap-2 mb-3">
        <Shield className={`w-5 h-5 ${isLocked ? 'text-rose-400' : 'text-emerald-400'}`} />
        <h3 className="text-sm font-medium text-slate-400">Risk Protection</h3>
      </div>
      
      {isLocked ? (
        <div className="text-center py-2">
          <div className="text-rose-400 font-bold text-lg">🔒 LOCKED DOWN</div>
          <div className="text-xs text-rose-400/70 mt-1">{protections?.reason}</div>
        </div>
      ) : isTripped ? (
        <div className="text-center py-2">
          <div className="text-amber-400 font-bold text-lg">⚠️ BREAKER TRIPPED</div>
          <div className="text-xs text-amber-400/70 mt-1">Auto-trading paused</div>
        </div>
      ) : (
        <div className="text-center py-2">
          <div className="text-emerald-400 font-semibold">✓ All Protections Active</div>
        </div>
      )}
      
      <button 
        className={`w-full mt-3 py-2 rounded-lg font-semibold transition-all ${
          isLocked 
            ? 'bg-emerald-600 hover:bg-emerald-700 text-white' 
            : 'bg-rose-600 hover:bg-rose-700 text-white'
        }`}
        onClick={() => {/* TODO: Implement kill switch toggle */}}
      >
        {isLocked ? 'UNLOCK SYSTEM' : 'EMERGENCY LOCKDOWN'}
      </button>
    </div>
  );
}
