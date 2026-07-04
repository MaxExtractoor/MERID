/**
 * Monitor — Portfolio Monitoring and PnL Tracking
 * 
 * Purpose: Consolidated monitoring view for portfolio and PnL
 * 
 * Content:
 * - Portfolio summary (balance, cash, portfolio value)
 * - Positions table (market, side, contracts, PnL)
 * - Recent fills (time, market, side, price, PnL)
 * - PnL history (equity curve, performance metrics)
 * - System health (service status, latency)
 * 
 * Data: Portfolio, fills, PnL history, system health (from store)
 * 
 * TODO: Integrate fills from store, add PnL chart
 */

import { useKalshiStore, selectPortfolio, selectSystem } from '../store';
import { Briefcase, Activity, CheckCircle, XCircle, DollarSign, TrendingUp } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const Monitor = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const system = useKalshiStore(selectSystem);
  const positions = portfolio.positions;
  const fills = portfolio.fills;

  // Derived metrics
  const totalExposure = positions.reduce((acc: number, p: any) => acc + Math.abs(p.quantity), 0);
  const totalUnrealizedPnl = positions.reduce((acc: number, p: any) => acc + (p.unrealized_pnl_cents || 0), 0) / 100;
  const totalRealizedPnl = fills.reduce((acc: number, f: any) => acc + (f.pnl_cents || 0), 0) / 100;

  // Generate PnL history data from fills
  const pnlHistory = fills.slice(0, 20).map((fill: any, idx: number) => ({
    time: new Date(fill.filled_at).toLocaleTimeString(),
    pnl: (fill.pnl_cents / 100).toFixed(2),
    cumulative: fills.slice(0, idx + 1).reduce((sum: number, f: any) => sum + (f.pnl_cents / 100), 0).toFixed(2)
  })).reverse();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Briefcase className="w-8 h-8 text-cyan-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Monitor</h1>
            <p className="text-sm text-slate-400">Portfolio tracking and system health</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-xs text-slate-500">Positions</div>
            <div className="text-lg font-bold text-white">{positions.length}</div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Unrealized PnL</div>
            <div
              className={`text-lg font-bold ${totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}
            >
              ${totalUnrealizedPnl.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* PnL Chart */}
      <Card>
        <CardHeader>
          <CardTitle>PnL History</CardTitle>
        </CardHeader>
        <CardContent>
          {pnlHistory.length === 0 ? (
            <div className="text-center py-8 text-slate-500">No PnL data available</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={pnlHistory}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                  labelStyle={{ color: '#f1f5f9' }}
                />
                <Line
                  type="monotone"
                  dataKey="cumulative"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

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
          label="Daily PnL"
          value={`$${portfolio.daily_pnl.toFixed(2)}`}
          color={portfolio.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
          icon={<DollarSign className="w-4 h-4 text-slate-500" />}
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
                    <th className="text-right p-3">Unrealized</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos: any, idx: number) => (
                    <tr key={pos.ticker || idx} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3">
                        <div className="font-medium text-white">{pos.ticker}</div>
                        <div className="text-xs text-slate-500">{pos.outcome}</div>
                      </td>
                      <td className="p-3">
                        <Badge variant={pos.side === 'yes' ? 'success' : 'danger'}>
                          {pos.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="p-3 text-right">{pos.quantity}</td>
                      <td className="p-3 text-right font-mono">¢{pos.avg_entry_price_cents}</td>
                      <td
                        className={`p-3 text-right font-mono ${
                          pos.unrealized_pnl_cents >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        ${(pos.unrealized_pnl_cents / 100).toFixed(2)}
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
                  {fills.slice(0, 10).map((fill: any) => (
                    <tr key={fill.fill_id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 text-xs text-slate-400">
                        {new Date(fill.filled_at).toLocaleTimeString()}
                      </td>
                      <td className="p-3">
                        <div className="font-medium text-white">{fill.ticker}</div>
                      </td>
                      <td className="p-3">
                        <Badge variant={fill.side === 'yes' ? 'success' : 'danger'}>
                          {fill.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="p-3 text-right">{fill.contracts}</td>
                      <td className="p-3 text-right font-mono">¢{fill.price_cents}</td>
                      <td
                        className={`p-3 text-right font-mono ${
                          fill.pnl_cents >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        ${(fill.pnl_cents / 100).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* System Health */}
      <Card>
        <CardHeader>
          <CardTitle>System Health</CardTitle>
        </CardHeader>
        <CardContent>
          {system.health.ok ? (
            <div className="flex items-center gap-3">
              <CheckCircle className="w-8 h-8 text-green-400" />
              <div>
                <div className="font-bold text-green-400">All Systems Operational</div>
                <div className="text-sm text-slate-400">
                  Latency: {system.health.overall_latency_ms}ms
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <XCircle className="w-8 h-8 text-red-400" />
              <div>
                <div className="font-bold text-red-400">System Degraded</div>
                <div className="text-sm text-slate-400">
                  Some services are experiencing issues
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

// Sub-component: MetricCard
interface MetricCardProps {
  label: string;
  value: string | number;
  color?: string;
  icon?: React.ReactNode;
}

const MetricCard: React.FC<MetricCardProps> = ({ label, value, color = 'text-white', icon }) => (
  <div className="bg-slate-800 rounded-lg p-4">
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs text-slate-500">{label}</span>
      {icon}
    </div>
    <div className={`text-2xl font-bold ${color}`}>{value}</div>
  </div>
);

export default Monitor;
