/**
 * Risk View — Risk Analytics and Sizing
 */

import { useEffect } from 'react';
import { useKalshiStore, selectRisk, selectConnected } from '../store';
import { Gauge, ShieldAlert, TrendingDown } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';

const Risk = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const risk = useKalshiStore(selectRisk);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

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
            Kill Switch Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="flex items-center gap-3">
              <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
                {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
              </Badge>
              {risk.kill_switch_reason && (
                <span className="text-sm text-slate-400">{risk.kill_switch_reason}</span>
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
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Daily PnL</span>
                <span className={`text-white ${risk.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${risk.daily_pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Drawdown</span>
                <span className="text-white">{risk.drawdown_pct.toFixed(2)}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Total Notional</span>
                <span className="text-white">${risk.total_notional.toFixed(2)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Kelly Fraction</span>
                <span className="text-white">{(risk.sizing_metrics.kelly_fraction * 100).toFixed(2)}%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Vol Scale</span>
                <span className="text-white">{risk.sizing_metrics.vol_scale.toFixed(2)}x</span>
              </div>
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
    </div>
  );
};

export default Risk;
