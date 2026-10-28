/**
 * Risk View — Risk Analytics and Sizing
 *
 * All values render straight from the store (populated by /api/v1/kalshi/risk,
 * /api/v1/kalshi/kill-switch, /api/v1/live-runtime-state). Mutations go through
 * ConfirmModal + a synchronous in-flight guard, then await refreshAll() — no
 * optimistic state.
 */

import { useEffect, useRef, useState } from 'react';
import { useKalshiStore, selectRisk, selectSystem, selectConnected } from '../store';
import { Gauge, ShieldAlert, TrendingDown } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { ConfirmModal } from '../components/ConfirmModal';
import { AGENT_ENDPOINTS, haltEntries, postJson, releaseEntries } from '../agents/api';

// Kill-switch POST takes `activate` as a query param (verified in kalshi_api.py).
const setKalshiKillSwitch = (activate: boolean) =>
  postJson<Record<string, unknown>>(`${AGENT_ENDPOINTS.KILL_SWITCH}?activate=${activate}`);

type ActionKind = 'activate' | 'reset' | 'halt' | 'release';

const Risk = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const risk = useKalshiStore(selectRisk);
  const system = useKalshiStore(selectSystem);
  const connected = useKalshiStore(selectConnected);
  const inFlightRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<ActionKind | null>(null);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(() => { void refreshAll(); }, 30000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  const entryHalted = system.live?.entry_halted === true;

  const runAction = async (kind: ActionKind) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      if (kind === 'activate') await setKalshiKillSwitch(true);
      else if (kind === 'reset') await setKalshiKillSwitch(false);
      else if (kind === 'halt') await haltEntries('operator_halt');
      else await releaseEntries();
      await refreshAll();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlightRef.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Gauge className="w-8 h-8 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Risk</h1>
            <p className="text-sm text-slate-400">Risk analytics and sizing</p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-red-400" />
            Kill Switch &amp; Live Entries
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
                    Kill switch {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
                  </Badge>
                  {risk.kill_switch_reason && (
                    <span className="text-sm text-slate-400">{risk.kill_switch_reason}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={risk.kill_switch_active ? 'outline' : 'danger'}
                    disabled={busy || risk.kill_switch_active}
                    onClick={() => setConfirmAction('activate')}
                  >
                    Activate
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !risk.kill_switch_active}
                    onClick={() => setConfirmAction('reset')}
                  >
                    Reset
                  </Button>
                </div>
              </div>
              <div className="flex items-center justify-between border-t border-slate-700/60 pt-4">
                <div className="flex items-center gap-3">
                  <Badge variant={entryHalted ? 'warning' : 'success'}>
                    {system.live?.state ?? 'UNKNOWN'}
                  </Badge>
                  {system.live?.reason && (
                    <span className="text-sm text-slate-400">{system.live.reason}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy || entryHalted}
                    onClick={() => setConfirmAction('halt')}
                  >
                    Halt Entries
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || !entryHalted}
                    onClick={() => setConfirmAction('release')}
                  >
                    Release Entries
                  </Button>
                </div>
              </div>
              {actionError && (
                <div className="text-xs text-red-400 break-words">Error: {actionError}</div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risk Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              <RiskRow label="Daily PnL">
                <span className={risk.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  ${risk.daily_pnl.toFixed(2)}
                </span>
              </RiskRow>
              <RiskRow label="Realized / Unrealized">
                <span className="text-white">
                  ${risk.realized_pnl.toFixed(2)} / ${risk.unrealized_pnl.toFixed(2)}
                </span>
              </RiskRow>
              <RiskRow label="Drawdown">
                <span className="text-white">{risk.drawdown_pct.toFixed(2)}%</span>
              </RiskRow>
              <RiskRow label="Total Notional">
                <span className="text-white">${risk.total_notional.toFixed(2)}</span>
              </RiskRow>
              <RiskRow label="Open Markets / Daily Trades">
                <span className="text-white">{risk.open_market_count} / {risk.daily_trades}</span>
              </RiskRow>
              <RiskRow label="Win Rate">
                <span className="text-white">{risk.win_rate_pct.toFixed(1)}%</span>
              </RiskRow>
              <RiskRow label="Sharpe / Profit Factor">
                <span className="text-white">
                  {risk.sharpe_ratio.toFixed(2)} / {risk.profit_factor.toFixed(2)}
                </span>
              </RiskRow>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configured Limits</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : Object.keys(risk.limits).length === 0 ? (
            <div className="text-center py-4 text-slate-500">No limits reported by backend</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
              {risk.limits.max_notional_usd != null && (
                <RiskRow label="Max Notional">
                  <span className="text-white">${risk.limits.max_notional_usd.toFixed(2)}</span>
                </RiskRow>
              )}
              {risk.limits.max_open_markets != null && (
                <RiskRow label="Max Open Markets">
                  <span className="text-white">{risk.limits.max_open_markets}</span>
                </RiskRow>
              )}
              {risk.limits.daily_loss_limit != null && (
                <RiskRow label="Daily Loss Limit">
                  <span className="text-white">${risk.limits.daily_loss_limit.toFixed(2)}</span>
                </RiskRow>
              )}
              {risk.limits.max_drawdown_pct != null && (
                <RiskRow label="Max Drawdown">
                  <span className="text-white">{risk.limits.max_drawdown_pct.toFixed(1)}%</span>
                </RiskRow>
              )}
              {risk.limits.max_orders_per_minute != null && (
                <RiskRow label="Max Orders / Min">
                  <span className="text-white">{risk.limits.max_orders_per_minute}</span>
                </RiskRow>
              )}
              {risk.limits.max_orders_per_hour != null && (
                <RiskRow label="Max Orders / Hour">
                  <span className="text-white">{risk.limits.max_orders_per_hour}</span>
                </RiskRow>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingDown className="w-5 h-5 text-yellow-400" />
            Recent Alerts
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : risk.alerts.length === 0 ? (
            <div className="text-center py-4 text-slate-500">No recent alerts</div>
          ) : (
            <div className="space-y-2">
              {risk.alerts.map((alert) => (
                <div key={alert.id} className="p-3 rounded-lg border border-slate-700">
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
          confirmAction === 'activate' ? 'Activate Kill Switch'
            : confirmAction === 'reset' ? 'Reset Kill Switch'
            : confirmAction === 'halt' ? 'Halt Live Entries'
            : 'Release Live Entries'
        }
        message={
          confirmAction === 'activate'
            ? 'Activate the Kalshi kill switch? This halts all trading immediately.'
            : confirmAction === 'reset'
              ? 'Reset the kill switch? Trading remains subject to runtime halt gates.'
              : confirmAction === 'halt'
                ? 'Halt new live entries? Exits and cancellations remain active.'
                : 'Release live entries? Entries resume only if all safety gates pass.'
        }
        confirmText="Confirm"
        confirmVariant={confirmAction === 'activate' || confirmAction === 'halt' ? 'danger' : 'primary'}
        onConfirm={() => {
          const kind = confirmAction;
          setConfirmAction(null);
          if (kind) void runAction(kind);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
};

const RiskRow = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex items-center justify-between">
    <span className="text-slate-400">{label}</span>
    {children}
  </div>
);

export default Risk;
