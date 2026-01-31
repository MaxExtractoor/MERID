import { useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import { useRiskMetrics } from '../hooks/useRiskMetrics';
import { formatCurrency, formatPercent, formatTime } from '../utils/formatters';
import { RefreshCw, AlertTriangle } from 'lucide-react';

/**
 * Live Risk Strip
 *
 * Displays real-time risk metrics with:
 * - Compact row of metric cards (P&L, Drawdown, Margin, Top Exposure)
 * - Live WebSocket updates for threshold breaches and PnL changes
 * - Alert indicator for active risk alerts
 */
export function LiveRiskStrip() {
  const { metrics, alerts, loading, error, lastUpdated } = useRiskMetrics();

  // Find top exposure symbol
  const topExposure = useMemo(() => {
    const entries = Object.entries(metrics.exposure);
    if (entries.length === 0) return null;
    return entries.sort((a, b) => {
      const aTotal = a[1].long + a[1].short;
      const bTotal = b[1].long + b[1].short;
      return bTotal - aTotal;
    })[0];
  }, [metrics.exposure]);

  // Count alerts by severity
  const alertCounts = useMemo(() => {
    return {
      critical: alerts.filter(a => a.severity === 'CRITICAL').length,
      warning: alerts.filter(a => a.severity === 'WARNING').length,
      info: alerts.filter(a => a.severity === 'INFO').length,
    };
  }, [alerts]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 animate-pulse">
        {[...Array(5)].map((_, i) => (
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
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
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
          value={topExposure ? formatCurrency(topExposure[1].long + topExposure[1].short) : '-'}
          status="GOOD"
        />
      </div>

      {/* Alerts & Last Updated */}
      <div className="flex items-center justify-between px-1">
        {/* Alert Summary */}
        {(alertCounts.critical > 0 || alertCounts.warning > 0) && (
          <div className="flex items-center gap-2">
            <AlertTriangle className={`w-4 h-4 ${
              alertCounts.critical > 0 ? 'text-red-500' : 'text-amber-500'
            }`} />
            <span className={`text-sm ${
              alertCounts.critical > 0 ? 'text-red-400' : 'text-amber-400'
            }`}>
              {alertCounts.critical > 0
                ? `${alertCounts.critical} critical alert${alertCounts.critical > 1 ? 's' : ''}`
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
