/**
 * SizeView — Unified Position Sizing & Bankroll (Stage 4)
 * 
 * Consolidates: size-bankroll + size-lanes + size-sizing
 * 
 * Tabs:
 *   - "Bankroll": Capital allocation, equity, drawdown tiers
 *   - "Lane Control": Asset×timeframe lane status, deployment phases
 *   - "Sizing Metrics": Kelly fraction, volatility scaling, performance ratios
 * 
 * Features:
 *   - Real-time bankroll status
 *   - Cross-timeframe signal alignment
 *   - Auto-promoter controls
 *   - Sizing parameter visualization
 */

import React, { useState, useCallback } from 'react';
import {
  Wallet, GitBranch, Sliders, Activity,
  Play, Square
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { DRAWDOWN_TIER_CONFIG, getDrawdownTierConfig } from '../shared/config/riskConfig';
import { authHeaders } from '../api/auth';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiBankrollPanel from '../components/KalshiBankrollPanel';

// ── Types ────────────────────────────────────────────────────────────────────

interface LaneSnapshot {
  timeframe: string;
  weight: number;
  avg_score: number;
  avg_confidence: number;
  signal_count: number;
  direction: "bullish" | "bearish" | "neutral";
  stale: boolean;
}

interface XtfSignal {
  asset: string;
  timestamp: string;
  composite_score: number;
  dominant_direction: "bullish" | "bearish" | "neutral";
  alignment_score: number;
  overall_confidence: number;
  active_timeframes: number;
  total_timeframes: number;
  sources: string[];
  is_aligned: boolean;
  has_trend_confirmation: boolean;
  conflict_flags: string[];
  lanes: LaneSnapshot[];
}

interface AgentDeployment {
  agent_name: string;
  mode: "PAPER" | "SHADOW" | "LIVE" | "HALTED";
  promoted_at: string | null;
  rollback_count: number;
  last_rollback_reason: string | null;
  live_trades: number;
  shadow_trades: number;
}

interface DeploymentStatus {
  agents: Record<string, AgentDeployment>;
  live: string[];
  shadow: string[];
  paper: string[];
  halted: string[];
  live_count: number;
  shadow_count: number;
  total_agents: number;
  max_live_agents: number;
  recent_transitions: Array<{
    ts: string;
    agent: string;
    from: string;
    to: string;
    reason: string;
  }>;
}

interface AutoPromoterStatus {
  running: boolean;
  eval_interval_seconds: number;
  eval_count: number;
  last_eval_at: string | null;
  promotions_24h: number;
  rollbacks_24h: number;
  next_eval_in_seconds: number;
}

interface SizingMetrics {
  drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  drawdown_pct: number;
  drawdown_thresholds: {
    warning: number;
    downsize: number;
    halt: number;
  };
  kelly_fraction: number;
  kelly_utilization_pct: number;
  vol_scale: number;
  effective_fraction: number;
  target_vol: number;
  realized_vol: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
}

type SizeTab = 'bankroll' | 'lanes' | 'sizing';




// ── Sub-Components ───────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  trend?: 'up' | 'down' | 'neutral';
  color?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, subtext, color = 'text-white' }) => (
  <div className="bg-slate-800 rounded-lg p-4">
    <div className="text-xs text-slate-500 mb-1">{label}</div>
    <div className={`text-2xl font-bold ${color}`}>{value}</div>
    {subtext && <div className="text-xs text-slate-400 mt-1">{subtext}</div>}
  </div>
);

// ── Main Component ───────────────────────────────────────────────────────────

const SizeView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SizeTab>('bankroll');
  const [promoterLoading, setPromoterLoading] = useState(false);
  
  // Data fetching
  const lanesRes = useApiData<{ signals: XtfSignal[] }>(
    API_ENDPOINTS.XTF_SIGNALS_ALL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const deploymentRes = useApiData<DeploymentStatus>(
    API_ENDPOINTS.KALSHI_DEPLOYMENT_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const promoterRes = useApiData<AutoPromoterStatus>(
    API_ENDPOINTS.AUTO_PROMOTER_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  
  const sizingRes = useApiData<SizingMetrics>(
    API_ENDPOINTS.KALSHI_SIZING_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const sizing = sizingRes.data;
  const deployment = deploymentRes.data;
  const promoter = promoterRes.data;
  const lanes = lanesRes.data?.signals || [];

  const tier = sizing ? DRAWDOWN_TIER_CONFIG[sizing.drawdown_tier] : DRAWDOWN_TIER_CONFIG.normal;

  // Auto-promoter toggle
  const togglePromoter = useCallback(async () => {
    setPromoterLoading(true);
    try {
      // Auto-promoter toggle via generic operator endpoint
      const res = await fetch(`${API_BASE_URL}/api/v1/operator/auto-promoter/${promoter?.running ? 'stop' : 'start'}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error('Failed to toggle promoter');
      promoterRes.refetch();
    } catch (err) {
      console.error('Failed to toggle promoter:', err);
    } finally {
      setPromoterLoading(false);
    }
  }, [promoter?.running, promoterRes]);

  const tabs = [
    { id: 'bankroll' as const, label: 'Bankroll', icon: Wallet },
    { id: 'lanes' as const, label: 'Lane Control', icon: GitBranch },
    { id: 'sizing' as const, label: 'Sizing Metrics', icon: Sliders },
  ];

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Sliders className="w-6 h-6 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Size</h1>
            <p className="text-sm text-slate-400">Position sizing and bankroll management</p>
          </div>
        </div>
        
        {sizing && (
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${tier.bg} border border-opacity-30 ${tier.color.replace('text-', 'border-').replace('400', '500')}`}>
            {tier.icon}
            <span className={`text-sm font-medium ${tier.color}`}>{tier.label}</span>
            <span className="text-xs text-slate-400">({sizing.drawdown_pct.toFixed(1)}% DD)</span>
          </div>
        )}
      </div>

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
        {/* Bankroll Tab */}
        {activeTab === 'bankroll' && (
          <div className="space-y-4">
            <KalshiBankrollPanel />
            
            {sizing && (
              <Card>
                <CardHeader>
                  <CardTitle>Drawdown Status</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className={`p-3 rounded-lg ${tier.bg}`}>
                      <div className="text-xs text-slate-400 mb-1">Current Tier</div>
                      <div className={`font-bold ${tier.color}`}>{tier.label}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-400 mb-1">Drawdown</div>
                      <div className="font-bold text-white">{sizing.drawdown_pct.toFixed(1)}%</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-400 mb-1">Warning Threshold</div>
                      <div className="font-bold text-yellow-400">{sizing.drawdown_thresholds.warning}%</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-400 mb-1">Halt Threshold</div>
                      <div className="font-bold text-red-400">{sizing.drawdown_thresholds.halt}%</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Lane Control Tab */}
        {activeTab === 'lanes' && (
          <div className="space-y-4">
            {/* Deployment Summary */}
            {deployment && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard 
                  label="Live Agents" 
                  value={deployment.live_count} 
                  subtext={`max ${deployment.max_live_agents}`}
                  color="text-green-400"
                />
                <MetricCard 
                  label="Shadow Agents" 
                  value={deployment.shadow_count} 
                  color="text-purple-400"
                />
                <MetricCard 
                  label="Paper Agents" 
                  value={deployment.paper?.length || 0} 
                  color="text-blue-400"
                />
                <MetricCard 
                  label="Halted" 
                  value={deployment.halted?.length || 0} 
                  color="text-red-400"
                />
              </div>
            )}

            {/* Auto-Promoter Control */}
            {promoter && (
              <Card>
                <CardHeader>
                  <CardTitle>Auto-Promoter</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-3 h-3 rounded-full ${promoter.running ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
                      <span className={promoter.running ? 'text-green-400' : 'text-red-400'}>
                        {promoter.running ? 'RUNNING' : 'STOPPED'}
                      </span>
                    </div>
                    <Button
                      variant={promoter.running ? 'danger' : 'primary'}
                      loading={promoterLoading}
                      onClick={togglePromoter}
                      icon={promoter.running ? <Square className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                    >
                      {promoter.running ? 'Stop' : 'Start'}
                    </Button>
                  </div>
                  
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Evaluations</div>
                      <div className="font-bold text-white">{promoter.eval_count}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Promotions (24h)</div>
                      <div className="font-bold text-green-400">{promoter.promotions_24h}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Rollbacks (24h)</div>
                      <div className="font-bold text-red-400">{promoter.rollbacks_24h}</div>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-3">
                      <div className="text-xs text-slate-500">Next Eval</div>
                      <div className="font-bold text-white">{promoter.next_eval_in_seconds}s</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* XTF Signals */}
            <Card>
              <CardHeader>
                <CardTitle>Cross-Timeframe Signals</CardTitle>
              </CardHeader>
              <CardContent>
                {lanes.length === 0 ? (
                  <div className="text-center py-8 text-slate-500">
                    <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>No active XTF signals</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {lanes.map(signal => (
                      <div key={signal.asset} className="bg-slate-800 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-3">
                          <div className="flex items-center gap-3">
                            <span className="font-bold text-white text-lg">{signal.asset}</span>
                            <Badge variant={signal.dominant_direction === 'bullish' ? 'success' : signal.dominant_direction === 'bearish' ? 'danger' : 'default'}>
                              {signal.dominant_direction.toUpperCase()}
                            </Badge>
                            {signal.is_aligned && (
                              <Badge variant="success">Aligned</Badge>
                            )}
                          </div>
                          <div className="text-right">
                            <div className="text-sm font-bold text-white">{(signal.composite_score * 100).toFixed(0)}%</div>
                            <div className="text-xs text-slate-500">confidence</div>
                          </div>
                        </div>
                        
                        {/* Lanes */}
                        <div className="grid grid-cols-4 gap-2">
                          {signal.lanes.map(lane => (
                            <div 
                              key={lane.timeframe} 
                              className={`p-2 rounded border ${lane.stale ? 'border-slate-700 bg-slate-800/50' : 'border-slate-700 bg-slate-800'}`}
                            >
                              <div className="text-xs text-slate-500 uppercase">{lane.timeframe}</div>
                              <div className={`text-sm font-medium ${
                                lane.direction === 'bullish' ? 'text-green-400' : 
                                lane.direction === 'bearish' ? 'text-red-400' : 'text-slate-400'
                              }`}>
                                {lane.direction}
                              </div>
                              <div className="text-xs text-slate-500">
                                {(lane.avg_confidence * 100).toFixed(0)}% · {lane.signal_count} sigs
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {/* Sizing Metrics Tab */}
        {activeTab === 'sizing' && sizing && (
          <div className="space-y-4">
            {/* Kelly & Vol Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard 
                label="Kelly Fraction" 
                value={sizing.kelly_fraction.toFixed(3)} 
                subtext={`${sizing.kelly_utilization_pct.toFixed(0)}% utilized`}
              />
              <MetricCard 
                label="Vol Scale" 
                value={`${sizing.vol_scale.toFixed(2)}x`} 
              />
              <MetricCard 
                label="Effective Fraction" 
                value={`${(sizing.effective_fraction * 100).toFixed(2)}%`} 
              />
              <MetricCard 
                label="Target Vol" 
                value={`${(sizing.target_vol * 100).toFixed(1)}%`} 
                subtext={`realized ${(sizing.realized_vol * 100).toFixed(1)}%`}
              />
            </div>

            {/* Performance Ratios */}
            <Card>
              <CardHeader>
                <CardTitle>Performance Ratios</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="bg-slate-800 rounded-lg p-4 text-center">
                    <div className="text-2xl font-bold text-blue-400">{sizing.sharpe_ratio.toFixed(2)}</div>
                    <div className="text-xs text-slate-500 mt-1">Sharpe</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-4 text-center">
                    <div className="text-2xl font-bold text-purple-400">{sizing.sortino_ratio.toFixed(2)}</div>
                    <div className="text-xs text-slate-500 mt-1">Sortino</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-4 text-center">
                    <div className="text-2xl font-bold text-teal-400">{sizing.calmar_ratio.toFixed(2)}</div>
                    <div className="text-xs text-slate-500 mt-1">Calmar</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-4 text-center">
                    <div className="text-2xl font-bold text-white">{sizing.win_rate_pct.toFixed(0)}%</div>
                    <div className="text-xs text-slate-500 mt-1">Win Rate</div>
                  </div>
                  <div className="bg-slate-800 rounded-lg p-4 text-center">
                    <div className="text-2xl font-bold text-white">{sizing.profit_factor.toFixed(2)}</div>
                    <div className="text-xs text-slate-500 mt-1">Profit Factor</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default SizeView;
