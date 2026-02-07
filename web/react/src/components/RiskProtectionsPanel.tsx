import { useState } from 'react';
import { 
  Shield, 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  RefreshCw, 
  Power,
  AlertOctagon,
  Clock,
  BarChart3
} from 'lucide-react';
import { useRiskProtections, getOverallRiskStatus, isTradingBlocked } from '../hooks/useRiskProtections';
// import { CircuitBreakerState } from '../types/risk';
import { formatDateTime, formatPercent, formatCurrency } from '../utils/formatters';

interface RiskProtectionsPanelProps {
  compact?: boolean;
  onExpand?: () => void;
}

export function RiskProtectionsPanel({ compact = false, onExpand }: RiskProtectionsPanelProps) {
  const { 
    data, 
    loading, 
    error, 
    refetch, 
    resetCircuit, 
    toggleKillSwitch 
  } = useRiskProtections();
  
  const [resetting, setResetting] = useState(false);
  const [toggling, setToggling] = useState(false);

  const handleReset = async () => {
    if (!confirm('Reset circuit breaker? This will allow trading to resume.')) return;
    setResetting(true);
    await resetCircuit();
    setResetting(false);
  };

  const handleToggleKillSwitch = async (action: 'enable' | 'disable') => {
    const confirmMsg = action === 'enable' 
      ? 'EMERGENCY LOCKDOWN: This will BLOCK all trading immediately. Confirm?'
      : 'Disable kill switch and resume trading?';
    if (!confirm(confirmMsg)) return;
    setToggling(true);
    await toggleKillSwitch(action);
    setToggling(false);
  };

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-6 bg-slate-800 rounded mb-4"></div>
        <div className="h-32 bg-slate-800 rounded"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <AlertTriangle className="w-5 h-5" />
          <span className="font-semibold">Risk Protections Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button 
          onClick={refetch}
          className="mt-3 text-sm text-blue-400 hover:text-blue-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const overall = getOverallRiskStatus(data);
  const blocked = isTradingBlocked(data);
  const circuitState = data.circuit_breaker.state;
  const killSwitchEnabled = !data.lockdown.trading_suite_enabled;

  // Compact view for dashboard header
  if (compact) {
    return (
      <div 
        className={`rounded-lg px-4 py-2 cursor-pointer transition-all ${
          overall.status === 'critical' 
            ? 'bg-red-500/20 border border-red-500/50 hover:bg-red-500/30' 
            : overall.status === 'warning'
            ? 'bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30'
            : 'bg-emerald-500/20 border border-emerald-500/50 hover:bg-emerald-500/30'
        }`}
        onClick={onExpand}
      >
        <div className="flex items-center gap-2">
          {overall.status === 'critical' ? (
            <AlertOctagon className="w-4 h-4 text-red-400" />
          ) : overall.status === 'warning' ? (
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          ) : (
            <CheckCircle className="w-4 h-4 text-emerald-400" />
          )}
          <span className={`text-sm font-medium ${
            overall.status === 'critical' ? 'text-red-400' : 
            overall.status === 'warning' ? 'text-amber-400' : 'text-emerald-400'
          }`}>
            {overall.message}
          </span>
        </div>
      </div>
    );
  }

  // Full panel view
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Risk & Protections</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">
            Updated: {formatDateTime(data.timestamp)}
          </span>
          <button 
            onClick={refetch}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
            disabled={loading}
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Status Banner */}
      <div className={`px-6 py-3 ${
        overall.status === 'critical' ? 'bg-red-500/10 border-b border-red-500/30' :
        overall.status === 'warning' ? 'bg-amber-500/10 border-b border-amber-500/30' :
        'bg-emerald-500/10 border-b border-emerald-500/30'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {overall.status === 'critical' ? (
              <AlertOctagon className="w-5 h-5 text-red-400" />
            ) : overall.status === 'warning' ? (
              <AlertTriangle className="w-5 h-5 text-amber-400" />
            ) : (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            )}
            <span className={`font-semibold ${
              overall.status === 'critical' ? 'text-red-400' :
              overall.status === 'warning' ? 'text-amber-400' :
              'text-emerald-400'
            }`}>
              {overall.message}
            </span>
          </div>
          {blocked && (
            <span className="text-xs px-2 py-1 rounded bg-red-500/20 text-red-400 font-medium">
              TRADING BLOCKED
            </span>
          )}
        </div>
      </div>

      <div className="p-6 space-y-6">
        {/* Circuit Breaker Section */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
            <Power className="w-4 h-4" />
            Circuit Breaker
          </h3>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">State</div>
              <div className={`font-semibold ${
                circuitState === 'CLOSED' ? 'text-emerald-400' :
                circuitState === 'OPEN' ? 'text-red-400' :
                'text-amber-400'
              }`}>
                {circuitState}
              </div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Errors / Threshold</div>
              <div className="font-semibold text-white">
                {data.circuit_breaker.error_count} / {data.circuit_breaker.threshold}
              </div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Window</div>
              <div className="font-semibold text-white">
                {data.circuit_breaker.window_seconds}s
              </div>
            </div>
            
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">Cooldown</div>
              <div className="font-semibold text-white">
                {data.circuit_breaker.cooldown_seconds}s
              </div>
            </div>
          </div>

          {circuitState === 'OPEN' && (
            <div className="flex items-center gap-3">
              <button
                onClick={handleReset}
                disabled={resetting}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 rounded-lg text-sm font-medium text-white transition-colors"
              >
                {resetting ? 'Resetting...' : 'Reset Circuit Breaker'}
              </button>
              {data.circuit_breaker.opened_at && (
                <span className="text-xs text-slate-400">
                  Opened: {formatDateTime(data.circuit_breaker.opened_at)}
                </span>
              )}
            </div>
          )}

          {data.circuit_breaker.last_error_at && (
            <div className="text-xs text-slate-500">
              Last error: {formatDateTime(data.circuit_breaker.last_error_at)}
            </div>
          )}
        </div>

        {/* Kill Switch Section */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
            <Shield className="w-4 h-4" />
            Kill Switch / Lockdown
          </h3>
          
          <div className="bg-slate-800/50 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {killSwitchEnabled ? (
                  <XCircle className="w-6 h-6 text-red-400" />
                ) : (
                  <CheckCircle className="w-6 h-6 text-emerald-400" />
                )}
                <div>
                  <div className={`font-semibold ${
                    killSwitchEnabled ? 'text-red-400' : 'text-emerald-400'
                  }`}>
                    {killSwitchEnabled ? 'TRADING DISABLED' : 'Trading Enabled'}
                  </div>
                  <div className="text-xs text-slate-500">
                    Mode: {data.lockdown.global_mode} | Spectator: {data.lockdown.spectator_mode ? 'On' : 'Off'}
                  </div>
                </div>
              </div>
              
              <button
                onClick={() => handleToggleKillSwitch(killSwitchEnabled ? 'disable' : 'enable')}
                disabled={toggling}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  killSwitchEnabled
                    ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                    : 'bg-red-600 hover:bg-red-700 text-white'
                } disabled:opacity-50`}
              >
                {toggling 
                  ? 'Processing...' 
                  : killSwitchEnabled 
                    ? 'Disable Kill Switch' 
                    : 'EMERGENCY LOCKDOWN'}
              </button>
            </div>
            
            {data.lockdown.lockdown_reason && (
              <div className="mt-3 text-sm text-red-400 bg-red-500/10 rounded p-2">
                {data.lockdown.lockdown_reason}
              </div>
            )}
          </div>
        </div>

        {/* Risk Limits Section */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Risk Limits
          </h3>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Daily Loss */}
            <div className="bg-slate-800/50 rounded-lg p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs text-slate-500">Daily Loss Limit</span>
                <span className={`text-sm font-medium ${
                  data.risk_limits.daily_loss_utilization_pct > 90 ? 'text-red-400' :
                  data.risk_limits.daily_loss_utilization_pct > 75 ? 'text-amber-400' :
                  'text-emerald-400'
                }`}>
                  {formatPercent(data.risk_limits.daily_loss_utilization_pct / 100)}
                </span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all ${
                    data.risk_limits.daily_loss_utilization_pct > 90 ? 'bg-red-500' :
                    data.risk_limits.daily_loss_utilization_pct > 75 ? 'bg-amber-500' :
                    'bg-emerald-500'
                  }`}
                  style={{ width: `${Math.min(data.risk_limits.daily_loss_utilization_pct, 100)}%` }}
                />
              </div>
              <div className="mt-2 text-xs text-slate-400">
                {formatCurrency(data.risk_limits.current_daily_pnl)} / {formatCurrency(-data.risk_limits.max_daily_loss_usd)}
              </div>
            </div>

            {/* Per-Symbol Exposure */}
            <div className="bg-slate-800/50 rounded-lg p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs text-slate-500">Max Symbol Exposure</span>
                <span className="text-sm font-medium text-emerald-400">
                  {formatCurrency(data.risk_limits.max_per_symbol_exposure_usd)}
                </span>
              </div>
              <div className="mt-2 text-xs text-slate-400">
                Per-symbol limit for concentration risk
              </div>
            </div>

            {/* Open Orders */}
            <div className="bg-slate-800/50 rounded-lg p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs text-slate-500">Open Orders</span>
                <span className="text-sm font-medium text-white">
                  {data.risk_limits.current_open_orders} / {data.risk_limits.max_open_orders}
                </span>
              </div>
              <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all ${
                    (data.risk_limits.current_open_orders / data.risk_limits.max_open_orders) > 0.9 ? 'bg-amber-500' :
                    'bg-emerald-500'
                  }`}
                  style={{ 
                    width: `${Math.min(
                      (data.risk_limits.current_open_orders / data.risk_limits.max_open_orders) * 100, 
                      100
                    )}%` 
                  }}
                />
              </div>
              <div className="mt-2 text-xs text-slate-400">
                Queue capacity utilization
              </div>
            </div>
          </div>
        </div>

        {/* Recent Events */}
        {data.recent_events.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
              <Clock className="w-4 h-4" />
              Recent Events
            </h3>
            
            <div className="bg-slate-800/30 rounded-lg overflow-hidden max-h-48 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-800/50 text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium">Time</th>
                    <th className="px-3 py-2 text-left text-xs font-medium">Type</th>
                    <th className="px-3 py-2 text-left text-xs font-medium">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {data.recent_events.slice(-10).reverse().map((event, idx) => (
                    <tr key={idx} className="hover:bg-slate-800/30">
                      <td className="px-3 py-2 text-xs text-slate-500">
                        {formatDateTime(event.timestamp)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          event.type.includes('error') ? 'bg-red-500/20 text-red-400' :
                          event.type.includes('reset') ? 'bg-emerald-500/20 text-emerald-400' :
                          'bg-slate-700 text-slate-300'
                        }`}>
                          {event.type}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-400">
                        {JSON.stringify(event.details).slice(0, 50)}...
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Compact card for dashboard
export function RiskProtectionsCard() {
  const { data, loading, error } = useRiskProtections();
  const [expanded, setExpanded] = useState(false);

  if (expanded) {
    return (
      <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-4xl max-h-[90vh] overflow-auto">
          <RiskProtectionsPanel onExpand={() => setExpanded(false)} />
        </div>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-slate-800 animate-pulse">
        <div className="h-4 bg-slate-700 rounded mb-2"></div>
        <div className="h-8 bg-slate-700 rounded"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900/70 rounded-xl p-4 border border-red-800">
        <div className="text-red-400 text-sm">Risk protections unavailable</div>
      </div>
    );
  }

  if (!data) return null;

  const overall = getOverallRiskStatus(data);
  const blocked = isTradingBlocked(data);

  return (
    <div 
      className={`bg-slate-900/70 rounded-xl p-4 border cursor-pointer transition-all ${
        overall.status === 'critical' ? 'border-red-500/50 hover:border-red-500' :
        overall.status === 'warning' ? 'border-amber-500/50 hover:border-amber-500' :
        'border-slate-800 hover:border-slate-600'
      }`}
      onClick={() => setExpanded(true)}
    >
      <div className="flex items-center gap-2 mb-3">
        <Shield className={`w-5 h-5 ${
          overall.status === 'critical' ? 'text-red-400' :
          overall.status === 'warning' ? 'text-amber-400' :
          'text-emerald-400'
        }`} />
        <h3 className="text-sm font-medium text-slate-400">Risk Protections</h3>
        {blocked && (
          <span className="text-xs px-2 py-0.5 bg-red-500/20 text-red-400 rounded">
            BLOCKED
          </span>
        )}
      </div>
      
      <div className="flex items-center gap-2 mb-2">
        {overall.status === 'critical' ? (
          <AlertOctagon className="w-5 h-5 text-red-400" />
        ) : overall.status === 'warning' ? (
          <AlertTriangle className="w-5 h-5 text-amber-400" />
        ) : (
          <CheckCircle className="w-5 h-5 text-emerald-400" />
        )}
        <span className={`text-lg font-semibold ${
          overall.status === 'critical' ? 'text-red-400' :
          overall.status === 'warning' ? 'text-amber-400' :
          'text-emerald-400'
        }`}>
          {overall.message}
        </span>
      </div>
      
      <div className="text-xs text-slate-500">
        Circuit: {data.circuit_breaker?.state || 'N/A'} | 
        Errors: {data.circuit_breaker?.error_count || 0}/{data.circuit_breaker?.threshold || 0}
      </div>
      
      <div className="mt-3 text-xs text-slate-400">
        Click for details and controls
      </div>
    </div>
  );
}
