/**
 * KalshiCompactOverview — Compact Overview Panel (Phase 2)
 *
 * Simplified overview using canonical state model.
 * Shows only essential operational state: system status, capital, market activity, risk, grid.
 * 
 * Design principles:
 * - Single source of truth from /api/v1/kalshi/ui-state
 * - Progressive disclosure: summary first, details on drill-down
 * - Minimal actionable controls only
 * - Real-time updates via WebSocket (future)
 */

import {
  Activity,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Shield,
  Zap,
  XCircle,
  CheckCircle,
  AlertTriangle,
  Clock,
  Wifi,
  WifiOff,
} from '../ui/icons';
import { useKalshiUIState } from '../hooks/useKalshiUIState';
import KalshiModeBadge from './KalshiModeBadge';
import { formatCurrency, formatPercent } from '../utils/formatters';

// ── Sub-Components ─────────────────────────────────────────────────────────────

function SystemStatusCard({ system }: { system: any }) {
  const gateColor = system.execution_gate === 'clear' ? 'text-green-400' 
                   : system.execution_gate === 'limited' ? 'text-amber-400' 
                   : 'text-red-400';
  const gateBg = system.execution_gate === 'clear' ? 'bg-green-500/10' 
                : system.execution_gate === 'limited' ? 'bg-amber-500/10' 
                : 'bg-red-500/10';

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-slate-200">System Status</span>
        </div>
        <KalshiModeBadge />
      </div>

      <div className="space-y-2">
        {/* Execution Gate */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Execution Gate</span>
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${gateBg} ${gateColor}`}>
            {system.execution_gate.toUpperCase()}
          </span>
        </div>

        {/* Kill Switch */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Kill Switch</span>
          {system.kill_switch_active ? (
            <div className="flex items-center gap-1">
              <XCircle className="w-3 h-3 text-red-400" />
              <span className="text-xs font-medium text-red-400">ACTIVE</span>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-green-400" />
              <span className="text-xs font-medium text-green-400">CLEAR</span>
            </div>
          )}
        </div>

        {/* Venue Health */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Venue</span>
          {system.venue_healthy ? (
            <div className="flex items-center gap-1">
              <CheckCircle className="w-3 h-3 text-green-400" />
              <span className="text-xs font-medium text-green-400">Healthy</span>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <XCircle className="w-3 h-3 text-red-400" />
              <span className="text-xs font-medium text-red-400">Unhealthy</span>
            </div>
          )}
        </div>

        {/* Reconciliation */}
        {system.reconciliation_status !== 'ok' && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Reconciliation</span>
            <span className="text-xs font-medium text-amber-400">
              {system.reconciliation_status.toUpperCase()} ({system.reconciliation_discrepancy_count})
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function CapitalCard({ capital }: { capital: any }) {
  const drawdownColor = capital.drawdown_tier === 'normal' ? 'text-green-400'
                      : capital.drawdown_tier === 'warning' ? 'text-amber-400'
                      : capital.drawdown_tier === 'downsize' ? 'text-orange-400'
                      : 'text-red-400';

  const pnlColor = capital.daily_pnl_usd >= 0 ? 'text-green-400' : 'text-red-400';
  const PnlIcon = capital.daily_pnl_usd >= 0 ? TrendingUp : TrendingDown;

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <DollarSign className="w-4 h-4 text-green-400" />
        <span className="text-sm font-semibold text-slate-200">Capital</span>
      </div>

      <div className="space-y-2">
        {/* Total Value */}
        <div>
          <div className="text-xs text-slate-400 mb-1">Total Value</div>
          <div className="text-xl font-bold text-white">
            {formatCurrency(capital.total_value_usd)}
          </div>
        </div>

        {/* Daily PnL */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Daily PnL</span>
          <div className={`flex items-center gap-1 ${pnlColor}`}>
            <PnlIcon className="w-3 h-3" />
            <span className="text-xs font-medium">
              {formatCurrency(capital.daily_pnl_usd)} ({formatPercent(capital.daily_pnl_pct)})
            </span>
          </div>
        </div>

        {/* Drawdown */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Drawdown</span>
          <span className={`text-xs font-medium ${drawdownColor}`}>
            {formatPercent(capital.drawdown_pct)} ({capital.drawdown_tier.toUpperCase()})
          </span>
        </div>

        {/* Notional Utilization */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Notional Used</span>
          <span className="text-xs font-medium text-slate-200">
            {formatCurrency(capital.notional_used_usd)} / {formatCurrency(capital.notional_limit_usd)} 
            ({formatPercent(capital.notional_utilization_pct)})
          </span>
        </div>
      </div>
    </div>
  );
}

function MarketActivityCard({ markets }: { markets: any }) {
  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Zap className="w-4 h-4 text-purple-400" />
        <span className="text-sm font-semibold text-slate-200">Market Activity</span>
      </div>

      <div className="space-y-2">
        {/* Positions */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Open Positions</span>
          <span className="text-xs font-medium text-slate-200">{markets.open_position_count}</span>
        </div>

        {/* Orders */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Open Orders</span>
          <span className="text-xs font-medium text-slate-200">{markets.open_order_count}</span>
        </div>

        {/* Active Markets */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Active Markets</span>
          <span className="text-xs font-medium text-slate-200">{markets.active_market_count}</span>
        </div>

        {/* Recent Fills */}
        {markets.recent_fills.length > 0 && (
          <div className="pt-2 border-t border-slate-800">
            <div className="text-xs text-slate-400 mb-2">Recent Fills</div>
            <div className="space-y-1 max-h-20 overflow-y-auto">
              {markets.recent_fills.slice(0, 3).map((fill: any) => (
                <div key={fill.fill_id} className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">{fill.ticker}</span>
                  <span className={`${fill.pnl_usd >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatCurrency(fill.pnl_usd)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function RiskCard({ risk }: { risk: any }) {
  const alertCount = risk.unacknowledged_alert_count;
  const hasAlerts = alertCount > 0;

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-slate-200">Risk</span>
        </div>
        {hasAlerts && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-500/20 text-red-400">
            {alertCount} Alert{alertCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div className="space-y-2">
        {/* Daily Loss */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Daily Loss</span>
          <span className="text-xs font-medium text-slate-200">
            {formatCurrency(risk.daily_loss_usd)} / {formatCurrency(risk.daily_loss_limit_usd)}
          </span>
        </div>

        {/* Breaches */}
        {risk.breach_count > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Active Breaches</span>
            <span className="text-xs font-medium text-red-400">{risk.breach_count}</span>
          </div>
        )}

        {/* Recent Alerts */}
        {risk.recent_alerts.length > 0 && (
          <div className="pt-2 border-t border-slate-800">
            <div className="text-xs text-slate-400 mb-2">Recent Alerts</div>
            <div className="space-y-1 max-h-20 overflow-y-auto">
              {risk.recent_alerts.slice(0, 3).map((alert: any) => (
                <div key={alert.id} className="flex items-start gap-2 text-xs">
                  <AlertTriangle className={`w-3 h-3 mt-0.5 flex-shrink-0 ${
                    alert.level === 'critical' ? 'text-red-400' 
                    : alert.level === 'warning' ? 'text-amber-400' 
                    : 'text-blue-400'
                  }`} />
                  <span className="text-slate-300 line-clamp-2">{alert.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function GridCard({ grid }: { grid: any }) {
  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-semibold text-slate-200">Agent Grid</span>
        </div>
        {grid.running ? (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">
            RUNNING
          </span>
        ) : (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
            STOPPED
          </span>
        )}
      </div>

      <div className="space-y-2">
        {/* Agents */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Active Agents</span>
          <span className="text-xs font-medium text-slate-200">
            {grid.active_agent_count} / {grid.agent_count}
          </span>
        </div>

        {/* Cycles */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Cycles Run</span>
          <span className="text-xs font-medium text-slate-200">{grid.cycles_run}</span>
        </div>

        {/* Fill Rate */}
        {grid.fill_rate_pct !== null && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Fill Rate</span>
            <span className="text-xs font-medium text-slate-200">{formatPercent(grid.fill_rate_pct)}</span>
          </div>
        )}

        {/* Errors */}
        {grid.error_count > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">Recent Errors</span>
            <span className="text-xs font-medium text-red-400">{grid.error_count}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────────

export default function KalshiCompactOverview() {
  const { state, loading, error, lastUpdated, refetch, connectionStatus } = useKalshiUIState({
    pollingInterval: 10000, // 10 seconds
  });

  const connectionIcon = connectionStatus === 'connected' ? Wifi : WifiOff;
  const connectionColor = connectionStatus === 'connected' ? 'text-green-400' 
                        : connectionStatus === 'connecting' ? 'text-amber-400'
                        : connectionStatus === 'error' ? 'text-red-400'
                        : 'text-slate-500';

  if (loading && !state) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="bg-slate-900/50 rounded-xl border border-slate-800 p-4 animate-pulse">
            <div className="h-4 bg-slate-800 rounded w-24 mb-3" />
            <div className="h-8 bg-slate-800 rounded w-32 mb-2" />
            <div className="h-4 bg-slate-800 rounded w-20" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-4">
        <div className="flex items-center gap-2 text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span className="font-medium">Error loading state</span>
        </div>
        <p className="text-sm text-red-300 mt-2">{error}</p>
        <button
          onClick={refetch}
          className="mt-3 text-xs text-red-400 hover:text-red-300 underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-4">
        <p className="text-sm text-slate-400">No state available</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header with refresh and connection status */}
      <div className="flex items-center justify-between px-4">
        <h2 className="text-lg font-bold text-slate-100">Kalshi Overview</h2>
        <div className="flex items-center gap-3">
          {/* Connection status */}
          <div className={`flex items-center gap-1 text-xs ${connectionColor}`}>
            {connectionIcon === Wifi ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            <span className="capitalize">{connectionStatus}</span>
          </div>
          {lastUpdated && (
            <span className="text-xs text-slate-500">
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={refetch}
            className="text-xs text-slate-400 hover:text-slate-300 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 px-4">
        <SystemStatusCard system={state.system} />
        <CapitalCard capital={state.capital} />
        <MarketActivityCard markets={state.markets} />
        <RiskCard risk={state.risk} />
        <GridCard grid={state.grid} />
      </div>
    </div>
  );
}
