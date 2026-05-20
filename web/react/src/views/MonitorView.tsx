/**
 * MonitorView — Unified Portfolio Monitoring (Stage 6)
 * 
 * Consolidates: monitor-portfolio + monitor-pnl + monitor-health
 * 
 * Tabs:
 *   - "Portfolio": Positions, fills, equity curve
 *   - "PnL": Profit/loss history, performance metrics
 *   - "Health": System health, diagnostics, circuit breakers
 * 
 * Features:
 *   - Real-time portfolio tracking
 *   - PnL visualization with charts
 *   - System health dashboard
 */

import { useState, useEffect, useMemo } from 'react';
import { subscribeToPortfolio, PortfolioSnapshot, PositionSnapshot } from '../lib/portfolioClient';
import {
  Briefcase,
  Activity,
  Zap,
  AlertTriangle,
  DollarSign,
  TrendingUp,
  Heart,
  CheckCircle,
  XCircle
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiPnlChart from '../components/KalshiPnlChart';
import KalshiRiskFeed from '../components/KalshiRiskFeed';
import { fmtTimestamp } from '../utils/formatters';
import type { KalshiOrder, KalshiRiskSummary } from '../types/kalshi';

// ── Types ────────────────────────────────────────────────────────────────────

type MonitorTab = 'portfolio' | 'pnl' | 'health';

interface HealthStatus {
  ok: boolean;
  services: Record<string, { ok: boolean; latency_ms: number; error?: string }>;
  overall_latency_ms: number;
  timestamp: string;
  next_retry: string | null;
}

interface Fill {
  fill_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  fee_cents: number;
  pnl_cents: number;
  filled_at: string;
  market_question?: string;
}

interface PnlHistory {
  equity_curve: Array<{ ts: string; equity_usd: number }>;
  daily_pnl: Array<{ date: string; pnl_usd: number }>;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
}


// ── Sub-Components ─────────────────────────────────────────────────────────

interface MetricCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  color?: string;
  icon?: React.ReactNode;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, subtext, color = 'text-white', icon }) => (
  <div className="bg-slate-800 rounded-lg p-4">
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs text-slate-500">{label}</span>
      {icon}
    </div>
    <div className={`text-2xl font-bold ${color}`}>{value}</div>
    {subtext && <div className="text-xs text-slate-400 mt-1">{subtext}</div>}
  </div>
);

// ── Main Component ─────────────────────────────────────────────────────────

const MonitorView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<MonitorTab>('portfolio');
  
  // Data fetching - using portfolio service (event-driven)
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null);
  
  // Subscribe to portfolio updates on mount
  useEffect(() => {
    const unsubscribe = subscribeToPortfolio((update) => {
      try {
        setPortfolio(update as PortfolioSnapshot);
      } catch (error) {
        console.error('[MonitorView] Portfolio update error:', error);
        // Don't crash on malformed updates
      }
    });
    
    return unsubscribe;
  }, []);
  
  // Legacy positions fetch for backward compatibility (will be removed)
  // const posRes = useApiData<{ positions: KalshiPosition[] }>(
  //   `${API_ENDPOINTS.KALSHI_POSITIONS}?fresh=true`,
  //   { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  // );
  
  const ordRes = useApiData<{ orders: KalshiOrder[] }>(
    API_ENDPOINTS.KALSHI_ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const riskRes = useApiData<KalshiRiskSummary>(
    API_ENDPOINTS.KALSHI_RISK,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const healthRes = useApiData<HealthStatus>(
    API_ENDPOINTS.SYSTEM_HEALTH,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const fillsRes = useApiData<{ fills: Fill[] }>(
    API_ENDPOINTS.KALSHI_GRID_FILLS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  const pnlRes = useApiData<PnlHistory>(
    API_ENDPOINTS.KALSHI_PNL_HISTORY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const positions = portfolio?.positions.map((p: PositionSnapshot) => ({
    ...p,
    // Add legacy compatibility fields
    size: Math.abs(p.quantity),
    avg_price: p.avg_entry_price_cents / 100,
    unrealized_pnl: p.unrealized_pnl_usd,
    outcome: p.side,
  })) || [];
  const orders = ordRes.data?.orders || [];
  const fills = fillsRes.data?.fills || [];
  
  // Derived metrics
  const totalExposure = useMemo(() => 
    positions.reduce((acc: number, p: PositionSnapshot) => acc + Math.abs(p.quantity || 0), 0),
    [positions]
  );
  
  const totalUnrealizedPnl = useMemo(() => 
    positions.reduce((acc: number, p: PositionSnapshot) => acc + (p.unrealized_pnl_cents || 0), 0),
    [positions]
  );
  
  const totalRealizedPnl = useMemo(() => 
    fills.reduce((acc: number, f: any) => acc + (f.pnl_cents || 0) / 100, 0),
    [fills]
  );

  const tabs = [
    { id: 'portfolio' as const, label: 'Portfolio', icon: Briefcase },
    { id: 'pnl' as const, label: 'PnL History', icon: DollarSign },
    { id: 'health' as const, label: 'System Health', icon: Heart },
  ];

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Briefcase className="w-6 h-6 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Monitor</h1>
            <p className="text-sm text-slate-400">Portfolio tracking and system health</p>
          </div>
        </div>
        
        {/* Quick Stats */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-slate-500">Positions</div>
            <div className="text-lg font-bold text-white">{positions.length}</div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Unrealized PnL</div>
            <div className={`text-lg font-bold ${totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${totalUnrealizedPnl.toFixed(2)}
            </div>
          </div>
        </div>
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
        {/* Portfolio Tab */}
        {activeTab === 'portfolio' && (
          <div className="space-y-4">
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard 
                label="Total Exposure" 
                value={`${totalExposure} ct`}
                icon={<Activity className="w-4 h-4 text-slate-500" />}
              />
              <MetricCard 
                label="Unrealized PnL" 
                value={`$${totalUnrealizedPnl.toFixed(2)}`}
                color={totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}
                icon={<TrendingUp className="w-4 h-4 text-slate-500" />}
              />
              <MetricCard 
                label="Realized PnL" 
                value={`$${totalRealizedPnl.toFixed(2)}`}
                color={totalRealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}
                icon={<DollarSign className="w-4 h-4 text-slate-500" />}
              />
              <MetricCard 
                label="Open Orders" 
                value={orders.filter(o => o.status === 'resting').length}
                subtext={`${orders.length} total`}
                icon={<Zap className="w-4 h-4 text-slate-500" />}
              />
            </div>

            {/* Positions Table */}
            <Card>
              <CardHeader>
                <CardTitle>Positions</CardTitle>
              </CardHeader>
              <CardContent>
                {positions.length === 0 ? (
                  <div className="text-center py-8 text-slate-500">
                    <Briefcase className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>No open positions</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                          <th className="text-left p-3">Market</th>
                          <th className="text-left p-3">Side</th>
                          <th className="text-right p-3">Contracts</th>
                          <th className="text-right p-3">Avg Price</th>
                          <th className="text-right p-3">Mark</th>
                          <th className="text-right p-3">Unrealized</th>
                        </tr>
                      </thead>
                      <tbody>
                        {positions.map((pos, idx: number) => (
                          <tr key={pos.ticker || idx} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td className="p-3">
                              <div className="font-medium text-white">{pos.ticker}</div>
                              <div className="text-xs text-slate-500">{pos.outcome}</div>
                            </td>
                            <td className="p-3">
                              <span className={`font-medium ${
                                pos.outcome === 'yes' ? 'text-green-400' : 'text-red-400'
                              }`}>
                                {pos.outcome.toUpperCase()}
                              </span>
                            </td>
                            <td className="p-3 text-right">{pos.size}</td>
                            <td className="p-3 text-right font-mono">¢{Math.round(pos.avg_price * 100)}</td>
                            <td className="p-3 text-right font-mono">—</td>
                            <td className={`p-3 text-right font-mono ${
                              (pos.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'
                            }`}>
                              ${(pos.unrealized_pnl || 0).toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Recent Fills */}
            <Card>
              <CardHeader>
                <CardTitle>Recent Fills</CardTitle>
              </CardHeader>
              <CardContent>
                {fills.length === 0 ? (
                  <div className="text-center py-8 text-slate-500">
                    <p>No recent fills</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                          <th className="text-left p-3">Time</th>
                          <th className="text-left p-3">Market</th>
                          <th className="text-left p-3">Side</th>
                          <th className="text-right p-3">Contracts</th>
                          <th className="text-right p-3">Price</th>
                          <th className="text-right p-3">PnL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fills.slice(0, 10).map(fill => (
                          <tr key={fill.fill_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                            <td className="p-3 text-xs text-slate-400">
                              {fmtTimestamp(fill.filled_at, { timeOnly: true })}
                            </td>
                            <td className="p-3">
                              <div className="font-medium text-white">{fill.ticker}</div>
                            </td>
                            <td className="p-3">
                              <span className={`font-medium ${
                                fill.side === 'yes' ? 'text-green-400' : 'text-red-400'
                              }`}>
                                {fill.side.toUpperCase()}
                              </span>
                            </td>
                            <td className="p-3 text-right">{fill.contracts}</td>
                            <td className="p-3 text-right font-mono">¢{fill.price_cents}</td>
                            <td className={`p-3 text-right font-mono ${
                              (fill.pnl_cents || 0) >= 0 ? 'text-green-400' : 'text-red-400'
                            }`}>
                              ${((fill.pnl_cents || 0) / 100).toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {/* PnL Tab */}
        {activeTab === 'pnl' && (
          <div className="space-y-4">
            {pnlRes.data && (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard 
                    label="Total Return" 
                    value={`${(pnlRes.data.total_return_pct || 0).toFixed(2)}%`}
                    color={(pnlRes.data.total_return_pct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}
                  />
                  <MetricCard 
                    label="Sharpe Ratio" 
                    value={(pnlRes.data.sharpe_ratio || 0).toFixed(2)}
                  />
                  <MetricCard 
                    label="Max Drawdown" 
                    value={`${(pnlRes.data.max_drawdown_pct || 0).toFixed(2)}%`}
                    color="text-red-400"
                  />
                  <MetricCard 
                    label="Daily PnL" 
                    value={`$${(riskRes.data?.daily_pnl_usd || 0).toFixed(2)}`}
                    color={(riskRes.data?.daily_pnl_usd || 0) >= 0 ? 'text-green-400' : 'text-red-400'}
                  />
                </div>

                {/* PnL Chart */}
                <Card>
                  <CardHeader>
                    <CardTitle>Equity Curve</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <KalshiPnlChart />
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        )}

        {/* Health Tab */}
        {activeTab === 'health' && (
          <div className="space-y-4">
            {/* Overall Health */}
            <Card>
              <CardHeader>
                <CardTitle>System Health</CardTitle>
              </CardHeader>
              <CardContent>
                {healthRes.data ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      {healthRes.data.ok ? (
                        <>
                          <CheckCircle className="w-8 h-8 text-green-400" />
                          <div>
                            <div className="font-bold text-green-400">All Systems Operational</div>
                            <div className="text-sm text-slate-400">
                              Latency: {healthRes.data.overall_latency_ms}ms
                            </div>
                          </div>
                        </>
                      ) : (
                        <>
                          <XCircle className="w-8 h-8 text-red-400" />
                          <div>
                            <div className="font-bold text-red-400">System Degraded</div>
                            <div className="text-sm text-slate-400">
                              Some services are experiencing issues
                            </div>
                          </div>
                        </>
                      )}
                    </div>

                    {/* Service Status */}
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      {Object.entries(healthRes.data.services || {}).map(([name, status]) => (
                        <div 
                          key={name}
                          className={`p-3 rounded-lg border ${
                            status.ok 
                              ? 'bg-green-500/10 border-green-500/30' 
                              : 'bg-red-500/10 border-red-500/30'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            {status.ok ? (
                              <CheckCircle className="w-4 h-4 text-green-400" />
                            ) : (
                              <AlertTriangle className="w-4 h-4 text-red-400" />
                            )}
                            <span className={`text-sm font-medium ${status.ok ? 'text-green-400' : 'text-red-400'}`}>
                              {name}
                            </span>
                          </div>
                          <div className="text-xs text-slate-400 mt-1">
                            {status.latency_ms}ms
                          </div>
                          {status.error && (
                            <div className="text-xs text-red-400 mt-1">{status.error}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-8 text-slate-500">
                    <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>Health data unavailable</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Risk Feed */}
            <Card>
              <CardHeader>
                <CardTitle>Risk Feed</CardTitle>
              </CardHeader>
              <CardContent>
                <KalshiRiskFeed />
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
};

export default MonitorView;
