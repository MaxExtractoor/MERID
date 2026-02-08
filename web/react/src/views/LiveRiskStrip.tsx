import { useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import { useRiskMetrics } from '../hooks/useRiskMetrics';
import { useRiskProtections, getOverallRiskStatus } from '../hooks/useRiskProtections';
import { formatCurrency, formatPercent, formatTime } from '../utils/formatters';
import { RefreshCw, AlertTriangle, Shield, AlertOctagon } from 'lucide-react';

/**
 * Live Risk Strip
 *
 * Displays real-time risk metrics with:
 * - Compact row of metric cards (P&L, Drawdown, Margin, Top Exposure, Circuit Breaker)
 * - Live WebSocket updates for threshold breaches and PnL changes
 * - Alert indicator for active risk alerts
 * - Circuit breaker status integration
 */
export function LiveRiskStrip() {
  const { metrics, alerts, loading, error, lastUpdated } = useRiskMetrics();
  const { data: protections } = useRiskProtections();

  // Find top exposure symbol
  const topExposure = useMemo(() => {
    if (!metrics.exposure || typeof metrics.exposure !== 'object') return null;
    const entries = Object.entries(metrics.exposure);
    if (entries.length === 0) return null;
    return entries.sort((a, b) => {
      const aTotal = (a[1]?.long || 0) + (a[1]?.short || 0);
      const bTotal = (b[1]?.long || 0) + (b[1]?.short || 0);
      return bTotal - aTotal;
    })[0];
  }, [metrics.exposure]);

  // Count alerts by severity
  const safeAlerts = alerts || [];
  const alertCounts = useMemo(() => {
    return {
      critical: safeAlerts.filter(a => a.severity === 'CRITICAL').length,
      warning: safeAlerts.filter(a => a.severity === 'WARNING').length,
      info: safeAlerts.filter(a => a.severity === 'INFO').length,
    };
  }, [safeAlerts]);

  // Get circuit breaker status
  const circuitStatus = useMemo(() => {
    if (!protections) return null;
    return getOverallRiskStatus(protections);
  }, [protections]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4 animate-pulse">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="bg-slate-800 rounded-lg p-4 h-20" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-700 rounded-lg p-4">
        <p className="text-red-400 text-sm">Risk data unavailable</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Risk Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        <MetricCard
          label="Total P&L"
          value={formatCurrency(metrics.totalPnL)}
          status={metrics.totalPnL >= 0 ? 'GOOD' : 'BAD'}
          delta={metrics.totalPnL}
        />
        <MetricCard
          label="Daily Drawdown"
          value={formatPercent(metrics.dailyDrawdown / 100)}
          status={metrics.dailyDrawdown > 5 ? 'BAD' : metrics.dailyDrawdown > 2 ? 'WARNING' : 'GOOD'}
        />
        <MetricCard
          label="Margin Utilization"
          value={formatPercent(metrics.marginUtilizationPercent / 100)}
          status={metrics.marginUtilizationPercent > 80 ? 'BAD' : metrics.marginUtilizationPercent > 50 ? 'WARNING' : 'GOOD'}
        />
        <MetricCard
          label="Max Drawdown"
          value={formatPercent(metrics.maxDrawdown / 100)}
          status={metrics.maxDrawdown > 10 ? 'BAD' : metrics.maxDrawdown > 5 ? 'WARNING' : 'GOOD'}
        />
        <MetricCard
          label={topExposure ? `Exposure: ${topExposure[0]}` : 'Top Exposure'}
          value={topExposure ? formatCurrency((topExposure[1]?.long || 0) + (topExposure[1]?.short || 0)) : '-'}
          status="GOOD"
        />
        {/* Circuit Breaker Status */}
        <div 
          className={`rounded-lg p-4 border cursor-pointer transition-all ${
            circuitStatus?.status === 'critical' ? 'bg-red-900/30 border-red-500/50' :
            circuitStatus?.status === 'warning' ? 'bg-amber-900/30 border-amber-500/50' :
            'bg-emerald-900/30 border-emerald-500/50'
          }`}
        >
          <div className="flex items-center gap-2 mb-1">
            {circuitStatus?.status === 'critical' ? (
              <AlertOctagon className="w-4 h-4 text-red-400" />
            ) : circuitStatus?.status === 'warning' ? (
              <AlertTriangle className="w-4 h-4 text-amber-400" />
            ) : (
              <Shield className="w-4 h-4 text-emerald-400" />
            )}
            <span className="text-xs text-slate-400">Circuit Breaker</span>
          </div>
          <div className={`text-lg font-semibold ${
            circuitStatus?.status === 'critical' ? 'text-red-400' :
            circuitStatus?.status === 'warning' ? 'text-amber-400' :
            'text-emerald-400'
          }`}>
            {protections?.circuit_breaker?.state || 'Unknown'}
          </div>
          <div className="text-xs text-slate-500">
            {protections?.circuit_breaker?.error_count || 0} errors
          </div>
        </div>
      </div>

      {/* Alerts & Last Updated */}
      <div className="flex items-center justify-between px-1">
        {/* Alert Summary */}
        {(alertCounts.critical > 0 || alertCounts.warning > 0 || circuitStatus?.status === 'critical') && (
          <div className="flex items-center gap-2">
            <AlertTriangle className={`w-4 h-4 ${
              alertCounts.critical > 0 || circuitStatus?.status === 'critical' ? 'text-red-500' : 'text-amber-500'
            }`} />
            <span className={`text-sm ${
              alertCounts.critical > 0 || circuitStatus?.status === 'critical' ? 'text-red-400' : 'text-amber-400'
            }`}>
              {alertCounts.critical > 0 || circuitStatus?.status === 'critical'
                ? `${alertCounts.critical + (circuitStatus?.status === 'critical' ? 1 : 0)} critical`
                : `${alertCounts.warning} warning${alertCounts.warning > 1 ? 's' : ''}`}
            </span>
          </div>
        )}

        {/* Last Updated */}
        {lastUpdated && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw className="w-3 h-3" />
            <span>{formatTime(lastUpdated.toISOString())}</span>
          </div>
        )}
      </div>
    </div>
  );
}
