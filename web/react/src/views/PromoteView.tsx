/**
 * PromoteView — Unified Deployment Pipeline (Stage 7)
 * 
 * Consolidates: promote-pipeline + promote-grid
 * 
 * Tabs:
 *   - "Pipeline": Deployment phases, promotion/rollback controls
 *   - "Agent Grid": 5×4 matrix of agents with live status
 * 
 * Features:
 *   - Paper → Shadow → Live promotion flow
 *   - Agent grid with real-time status
 *   - Auto-promoter integration
 *   - Deployment transition history
 */

import React, { useState, useCallback } from 'react';
import {
  Rocket, LayoutGrid, Play, Square, Pause, RotateCcw,
  ChevronRight, Zap, Activity, TrendingUp
} from '../ui/icons';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { getAuthHeaders } from '../services/auth';
import { fmtTimestamp } from '../utils/formatters';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';

// ── Types ────────────────────────────────────────────────────────────────────

type PromoteTab = 'pipeline' | 'grid';

interface AgentSummary {
  name: string;
  enabled: boolean;
  running: boolean;
  last_cycle_at: string | null;
  cycles_run: number;
  orders_placed: number;
  orders_this_window: number;
  active_tickers: string[];
  last_error: string | null;
  signal_count: number;
  order_count: number;
  fill_count: number;
  brier_score?: number;
  calibration_error?: number;
  last_heartbeat_ts: string | null;
  config: {
    assets: string[];
    timeframes: string[];
    risk_limits: {
      max_yes_position: number;
      max_no_position: number;
      max_orders_per_window: number;
      max_notional_usd: string;
      max_contracts_per_order: number;
    };
    entry_window: {
      minutes_before_expiry: number;
      cutoff_minutes_before_expiry: number;
    };
    risk_profile: string;
  };
  series_tickers?: string[];
}

interface GridStatus {
  running: boolean;
  agent_count: number;
  agents: AgentSummary[];
  venue_mode?: {
    mode: 'paper' | 'live' | 'mock';
    is_live: boolean;
    live_enabled: boolean;
  };
  venue_health: {
    connected: boolean;
    circuit: {
      state: string;
      failure_count: number;
      last_failure: string | null;
    };
    rate_limits: {
      read: number;
      write: number;
    };
    error_rate: number;
  };
  metrics: {
    active_markets: number;
    covered_markets: number;
    coverage_pct: number;
    total_orders: number;
    total_fills: number;
    pnl_by_category: Record<string, number>;
  };
}

interface DeploymentTransition {
  ts: string;
  agent: string;
  from: string;
  to: string;
  reason: string;
}

// ── Sub-Components ─────────────────────────────────────────────────────────

interface AgentCardProps {
  agent: AgentSummary;
}

const AgentCard: React.FC<AgentCardProps> = ({ agent }) => {
  const isHealthy = agent.running && !agent.last_error;
  
  return (
    <div 
      className={`p-3 rounded-lg border transition-colors ${
        isHealthy 
          ? 'bg-slate-800 border-slate-700' 
          : 'bg-red-500/10 border-red-500/30'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-white text-sm">{agent.name}</span>
        <div className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-green-400' : 'bg-red-400'}`} />
      </div>
      
      <div className="text-xs text-slate-500">
        {agent.series_tickers?.join(', ') || 'No tickers'}
      </div>
      
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="text-slate-400">
          Cycles: <span className="text-white">{agent.cycles_run}</span>
        </div>
        <div className="text-slate-400">
          Orders: <span className="text-white">{agent.order_count}</span>
        </div>
      </div>
      
      {agent.series_tickers && agent.series_tickers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {agent.series_tickers.slice(0, 3).map(ticker => (
            <span key={ticker} className="text-[10px] px-1.5 py-0.5 bg-slate-700 rounded text-slate-300">
              {ticker}
            </span>
          ))}
          {agent.series_tickers.length > 3 && (
            <span className="text-[10px] px-1.5 py-0.5 bg-slate-700 rounded text-slate-300">
              +{agent.series_tickers.length - 3}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────

const PromoteView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PromoteTab>('pipeline');
  const [gridLoading, setGridLoading] = useState(false);
  
  // Data fetching
  const gridRes = useApiQuery<GridStatus>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const transitionsRes = useApiQuery<{ transitions: DeploymentTransition[] }>(
    API_ENDPOINTS.KALSHI_DEPLOYMENT_TRANSITIONS,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const grid = gridRes.data;
  const agents = grid?.agents || [];
  const transitions = transitionsRes.data?.transitions || [];

  // Grid controls
  const toggleGrid = useCallback(async (action: 'start' | 'stop' | 'pause') => {
    setGridLoading(true);
    try {
      const endpoint = action === 'start' 
        ? API_ENDPOINTS.KALSHI_GRID_START 
        : action === 'stop' 
          ? API_ENDPOINTS.KALSHI_GRID_STOP 
          : API_ENDPOINTS.KALSHI_GRID_PAUSE;
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error(`Failed to ${action} grid`);
      gridRes.refetch();
    } catch (err) {
      console.error(`Failed to ${action} grid:`, err);
    } finally {
      setGridLoading(false);
    }
  }, [gridRes]);

  const tabs = [
    { id: 'pipeline' as const, label: 'Pipeline', icon: Rocket },
    { id: 'grid' as const, label: 'Agent Grid', icon: LayoutGrid },
  ];

  // Group agents by asset/timeframe for matrix view
  // 15m stack focus: only 15m timeframe (1h, daily, weekly removed as legacy)
  const agentMatrix = React.useMemo(() => {
    const assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
    const timeframes = ['15m'];
    
    return assets.map(asset => ({
      asset,
      lanes: timeframes.map(tf => {
        const agent = agents.find((a: AgentSummary) => 
          a.config.assets?.includes(asset) && 
          a.config.timeframes?.some((t: string) => t.toLowerCase().includes(tf))
        );
        return { timeframe: tf, agent };
      }),
    }));
  }, [agents]);

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Rocket className="w-6 h-6 text-violet-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Promote <KalshiModeBadge />
            </h1>
            <p className="text-sm text-slate-400">Deployment pipeline and agent management</p>
          </div>
        </div>
        
        {/* Grid Status */}
        {grid && (
          <div className="flex items-center gap-4">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${
              grid.running 
                ? 'bg-green-500/10 border border-green-500/30' 
                : 'bg-red-500/10 border border-red-500/30'
            }`}>
              <div className={`w-2 h-2 rounded-full ${grid.running ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
              <span className={`text-sm font-medium ${grid.running ? 'text-green-400' : 'text-red-400'}`}>
                {grid.running ? 'Grid Running' : 'Grid Stopped'}
              </span>
            </div>
            
            <div className="flex items-center gap-1">
              {!grid.running ? (
                <Button
                  variant="primary"
                  size="sm"
                  loading={gridLoading}
                  onClick={() => toggleGrid('start')}
                  icon={<Play className="w-4 h-4" />}
                >
                  Start
                </Button>
              ) : (
                <>
                  <Button
                    variant="warning"
                    size="sm"
                    loading={gridLoading}
                    onClick={() => toggleGrid('pause')}
                    icon={<Pause className="w-4 h-4" />}
                  >
                    Pause
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    loading={gridLoading}
                    onClick={() => toggleGrid('stop')}
                    icon={<Square className="w-4 h-4" />}
                  >
                    Stop
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Grid Metrics */}
      {grid?.metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Active Markets</div>
            <div className="text-2xl font-bold text-white">{grid.metrics.active_markets}</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Coverage</div>
            <div className="text-2xl font-bold text-white">{grid.metrics.coverage_pct.toFixed(1)}%</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Total Orders</div>
            <div className="text-2xl font-bold text-white">{grid.metrics.total_orders}</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4">
            <div className="text-xs text-slate-500 mb-1">Total Fills</div>
            <div className="text-2xl font-bold text-green-400">{grid.metrics.total_fills}</div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[500px]">
        {/* Pipeline Tab */}
        {activeTab === 'pipeline' && (
          <div className="space-y-4">
            {/* Deployment Phases */}
            <Card>
              <CardHeader>
                <CardTitle>Deployment Phases</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center justify-between mb-6">
                  {['Paper', 'Shadow', 'Live'].map((phase, i) => (
                    <React.Fragment key={phase}>
                      <div className="flex flex-col items-center">
                        <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-2 ${
                          phase === 'Paper' ? 'bg-blue-500/20 text-blue-400' :
                          phase === 'Shadow' ? 'bg-purple-500/20 text-purple-400' :
                          'bg-green-500/20 text-green-400'
                        }`}>
                          {phase === 'Paper' ? <Zap className="w-6 h-6" /> :
                           phase === 'Shadow' ? <Activity className="w-6 h-6" /> :
                           <TrendingUp className="w-6 h-6" />}
                        </div>
                        <span className="font-medium text-white">{phase}</span>
                        <span className="text-xs text-slate-500">
                          {phase === 'Paper' ? 'Strategy testing' :
                           phase === 'Shadow' ? 'Signal validation' :
                           'Real capital'}
                        </span>
                      </div>
                      {i < 2 && (
                        <ChevronRight className="w-6 h-6 text-slate-600" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Recent Transitions */}
            <Card>
              <CardHeader>
                <CardTitle>Recent Transitions</CardTitle>
              </CardHeader>
              <CardContent>
                {transitions.length === 0 ? (
                  <div className="text-center py-8 text-slate-500">
                    <RotateCcw className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>No recent transitions</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {transitions.slice(0, 10).map((t: DeploymentTransition) => (
                      <div key={`${t.agent}:${t.ts}`} className="flex items-center gap-4 p-3 bg-slate-800 rounded-lg">
                        <div className="text-xs text-slate-500 w-24">
                          {fmtTimestamp(t.ts, { timeOnly: true })}
                        </div>
                        <div className="font-medium text-white w-32">{t.agent}</div>
                        <div className="flex items-center gap-2">
                          <Badge variant="default">{t.from}</Badge>
                          <ChevronRight className="w-4 h-4 text-slate-500" />
                          <Badge variant="success">{t.to}</Badge>
                        </div>
                        <div className="text-xs text-slate-400 flex-1">{t.reason}</div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {/* Agent Grid Tab */}
        {activeTab === 'grid' && (
          <div className="space-y-4">
            {/* Agent Matrix */}
            <Card>
              <CardHeader>
                <CardTitle>Agent Matrix (Asset × Timeframe)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="text-left p-3 text-slate-500 text-sm">Asset</th>
                        <th className="text-center p-3 text-slate-500 text-sm">15m</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agentMatrix.map(row => (
                        <tr key={row.asset} className="border-b border-slate-800/50">
                          <td className="p-3 font-medium text-white">{row.asset}</td>
                          {row.lanes.map(({ timeframe, agent }) => (
                            <td key={timeframe} className="p-2">
                              {agent ? (
                                <button
                                  className={`w-full p-2 rounded text-xs text-left transition-colors ${
                                    agent.running 
                                      ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' 
                                      : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                                  }`}
                                >
                                  <div className="font-medium truncate">{agent.name}</div>
                                  <div className="opacity-75">{agent.cycles_run} cycles</div>
                                </button>
                              ) : (
                                <div className="w-full p-2 rounded text-xs bg-slate-800 text-slate-500 text-center">
                                  No agent
                                </div>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            {/* All Agents List */}
            <Card>
              <CardHeader>
                <CardTitle>All Agents ({agents.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {agents.map((agent: AgentSummary) => (
                    <AgentCard 
                      key={agent.name} 
                      agent={agent} 
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default PromoteView;
