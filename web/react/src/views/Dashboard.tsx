/**
 * Dashboard — Single Pane of Glass for Operator
 * 
 * Purpose: Operator-centric dashboard with system health, kill switch, key metrics
 * 
 * Content:
 * - System health (Kalshi, PM spot, execution guard)
 * - Kill switch status (quick activate/reset)
 * - Key metrics (balance, PnL, positions, agents running)
 * - Quick actions (start/stop grid, refresh catalog)
 * - Recent alerts (risk breaches, errors)
 * - 15m alignment status (series tickers, coverage)
 * 
 * Data: System health, kill switch, key metrics, alerts (all from store)
 */

import { useEffect, useRef, useState } from 'react';
import { useKalshiStore, selectPortfolio, selectRisk, selectGrid, selectSystem, selectConnected } from '../store';
import { LayoutDashboard, ShieldAlert, Activity, DollarSign, Briefcase, AlertTriangle } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { ConfirmModal } from '../components/ConfirmModal';
import { AGENT_ENDPOINTS, haltEntries, postJson, releaseEntries } from '../agents/api';
import Kalshi15mAlignmentPanel from '../components/Kalshi15mAlignmentPanel';
import Kalshi15mHealthPanel from '../components/Kalshi15mHealthPanel';

// Kalshi kill-switch POST takes `activate` as a QUERY param (verified in
// kalshi_api.py — the JSON body field `active` is ignored by FastAPI).
const setKalshiKillSwitch = (activate: boolean) =>
  postJson<Record<string, unknown>>(`${AGENT_ENDPOINTS.KILL_SWITCH}?activate=${activate}`);

const Dashboard = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const inFlightRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<null | { kind: 'activate' | 'reset' | 'halt' | 'release' }>(null);

  // Fetch initial data on mount (WebSocket disabled - using API polling)
  useEffect(() => {
    refreshAll();
    // Poll every 30 seconds
    const interval = setInterval(() => {
      refreshAll();
    }, 30000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  // Select data from store
  const portfolio = useKalshiStore(selectPortfolio);
  const risk = useKalshiStore(selectRisk);
  const grid = useKalshiStore(selectGrid);
  const system = useKalshiStore(selectSystem);
  const connected = useKalshiStore(selectConnected);

  // Derived metrics
  const positionsCount = portfolio.positions?.length || 0;
  const agentsRunning = grid.agents?.filter(a => a.running).length || 0;
  const recentAlerts = risk.alerts?.slice(0, 5) || [];
  const entryHalted = system.live?.entry_halted === true;

  // Safety-critical mutations: synchronous in-flight guard + confirm + refresh.
  const runAction = async (kind: 'activate' | 'reset' | 'halt' | 'release') => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      if (kind === 'activate') await setKalshiKillSwitch(true);
      else if (kind === 'reset') await setKalshiKillSwitch(false);
      else if (kind === 'halt') await haltEntries('operator_halt');
      else await releaseEntries();
      await refreshAll(); // authoritative state after mutation
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlightRef.current = false;
      setBusy(false);
    }
  };
  
  // Per-asset metrics for 5-asset crypto stack
  const assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];
  const perAssetMetrics = assets.map(asset => {
    const assetPositions = portfolio.positions?.filter(p => p.ticker.includes(asset)) || [];
    const assetPnL = assetPositions.reduce((sum, p) => sum + (p.unrealized_pnl_cents / 100), 0);
    return {
      asset,
      positions: assetPositions.length,
      pnl: assetPnL,
    };
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="w-8 h-8 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-sm text-slate-400">System overview and quick actions</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={connected ? 'success' : 'danger'}>
            {connected ? 'Connected' : 'Disconnected'}
          </Badge>
        </div>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Balance"
          value={connected ? `$${(portfolio.balance || 0).toFixed(2)}` : '---'}
          icon={<DollarSign className="w-5 h-5 text-slate-500" />}
          color={portfolio.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <MetricCard
          label="Daily PnL"
          value={connected ? `$${(portfolio.daily_pnl || 0).toFixed(2)}` : '---'}
          icon={<Activity className="w-5 h-5 text-slate-500" />}
          color={portfolio.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <MetricCard
          label="Positions"
          value={positionsCount}
          icon={<Briefcase className="w-5 h-5 text-slate-500" />}
        />
        <MetricCard
          label="Agents Running"
          value={agentsRunning}
          icon={<Activity className="w-5 h-5 text-slate-500" />}
        />
      </div>

      {/* Per-Asset Metrics */}
      <Card>
        <CardHeader>
          <CardTitle>Per-Asset Performance (BTC, ETH, SOL, XRP, DOGE)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            {perAssetMetrics.map(({ asset, positions, pnl }) => (
              <div key={asset} className="p-4 rounded-lg border border-slate-700 bg-slate-800/50">
                <div className="text-sm text-slate-400 mb-1">{asset}</div>
                <div className="text-lg font-bold tabular-nums">{positions} pos</div>
                <div className={`text-sm tabular-nums ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 15m Alignment Status */}
      <Card>
        <CardHeader>
          <CardTitle>15m Kalshi Alignment Status</CardTitle>
        </CardHeader>
        <CardContent>
          <Kalshi15mAlignmentPanel />
        </CardContent>
      </Card>

      {/* 15m Health Status */}
      <Card>
        <CardHeader>
          <CardTitle>15m Kalshi Health Status</CardTitle>
        </CardHeader>
        <CardContent>
          <Kalshi15mHealthPanel />
        </CardContent>
      </Card>

      {/* Kill Switch Status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-red-400" />
            Kill Switch Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">
              Waiting for backend connection...
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
                    {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
                  </Badge>
                  {risk.kill_switch_reason && (
                    <span className="text-sm text-slate-400">{risk.kill_switch_reason}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  {risk.kill_switch_active ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setConfirmAction({ kind: 'reset' })}
                      disabled={busy}
                    >
                      {busy ? 'Working...' : 'Reset Kill Switch'}
                    </Button>
                  ) : (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => setConfirmAction({ kind: 'activate' })}
                      disabled={busy}
                    >
                      {busy ? 'Working...' : 'Activate Kill Switch'}
                    </Button>
                  )}
                </div>
              </div>
              <div className="flex items-center justify-between border-t border-slate-700/60 pt-3">
                <div className="flex items-center gap-3">
                  <Badge variant={entryHalted ? 'warning' : 'success'}>
                    {system.live?.state ?? 'UNKNOWN'}
                  </Badge>
                  <span className="text-sm text-slate-400">Live entries</span>
                </div>
                <div className="flex gap-2">
                  {entryHalted ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setConfirmAction({ kind: 'release' })}
                      disabled={busy}
                    >
                      {busy ? 'Working...' : 'Release Entries'}
                    </Button>
                  ) : (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => setConfirmAction({ kind: 'halt' })}
                      disabled={busy}
                    >
                      {busy ? 'Working...' : 'Halt Entries'}
                    </Button>
                  )}
                </div>
              </div>
              {actionError && (
                <div className="text-xs text-red-400 break-words">Error: {actionError}</div>
              )}
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
          {!connected ? (
            <div className="text-center py-4 text-slate-500">
              Waiting for backend connection...
            </div>
          ) : Object.keys(system.health.services || {}).length === 0 ? (
            <div className="text-center py-4 text-slate-500">
              No health data available
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {Object.entries(system.health.services || {}).map(([name, service]) => (
                <div
                  key={name}
                  className={`p-3 rounded-lg border ${
                    service.ok
                      ? 'bg-green-500/10 border-green-500/30'
                      : 'bg-red-500/10 border-red-500/30'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-2 h-2 rounded-full ${
                        service.ok ? 'bg-green-400' : 'bg-red-400'
                      }`}
                    />
                    <span className={`text-sm font-medium ${service.ok ? 'text-green-400' : 'text-red-400'}`}>
                      {name}
                    </span>
                  </div>
                  <div className="text-xs text-slate-400 mt-1">{service.latency_ms}ms</div>
                  {service.error && (
                    <div className="text-xs text-red-400 mt-1">{service.error}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Alerts */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-yellow-400" />
            Recent Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">
              Waiting for backend connection...
            </div>
          ) : recentAlerts.length === 0 ? (
            <div className="text-center py-4 text-slate-500">No recent alerts</div>
          ) : (
            <div className="space-y-2">
              {recentAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className={`p-3 rounded-lg border ${
                    alert.severity === 'critical'
                      ? 'bg-red-500/10 border-red-500/30'
                      : 'bg-yellow-500/10 border-yellow-500/30'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white">{alert.message}</span>
                    <Badge variant={alert.severity === 'critical' ? 'danger' : 'warning'}>
                      {alert.severity}
                    </Badge>
                  </div>
                  <div className="text-xs text-slate-400 mt-1">
                    {new Date(alert.timestamp).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmModal
        isOpen={confirmAction !== null}
        title={
          confirmAction?.kind === 'activate' ? 'Activate Kill Switch'
            : confirmAction?.kind === 'reset' ? 'Reset Kill Switch'
            : confirmAction?.kind === 'halt' ? 'Halt Live Entries'
            : 'Release Live Entries'
        }
        message={
          confirmAction?.kind === 'activate'
            ? 'Activate the Kalshi kill switch? This halts all trading immediately.'
            : confirmAction?.kind === 'reset'
              ? 'Reset the kill switch? Trading remains subject to runtime halt gates.'
              : confirmAction?.kind === 'halt'
                ? 'Halt new live entries? Exits and cancellations remain active.'
                : 'Release live entries? Entries resume only if all safety gates pass.'
        }
        confirmText="Confirm"
        confirmVariant={confirmAction?.kind === 'activate' || confirmAction?.kind === 'halt' ? 'danger' : 'primary'}
        onConfirm={() => {
          const kind = confirmAction?.kind;
          setConfirmAction(null);
          if (kind) void runAction(kind);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
};

// Sub-component: MetricCard
interface DashboardMetricCardProps {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  color?: string;
}

const MetricCard: React.FC<DashboardMetricCardProps> = ({ label, value, icon, color = 'text-white' }) => (
  <Card>
    <CardContent className="p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-slate-500">{label}</span>
        {icon}
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </CardContent>
  </Card>
);

export default Dashboard;
