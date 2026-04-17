import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  TrendingUp,
  Timer,
  Zap
} from '../ui/icons';
import { useLatency, getLatencyColor, getLatencyBarColor, formatLatency, getSloStatus } from '../hooks/useLatency';
import { formatDateTime } from '../utils/formatters';

interface LatencyMetricProps {
  label: string;
  value: number;
  warning: number;
  critical: number;
  showBar?: boolean;
}

function LatencyMetric({ label, value, warning, critical, showBar = true }: LatencyMetricProps) {
  const colorClass = getLatencyColor(value, warning, critical);
  const barColor = getLatencyBarColor(value, warning, critical);
  const percentOfCritical = Math.min((value / critical) * 100, 100);
  
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">{label}</span>
        <span className={`font-semibold ${colorClass}`}>
          {formatLatency(value)}
        </span>
      </div>
      {showBar && (
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-500`}
            style={{ width: `${percentOfCritical}%` }}
          />
        </div>
      )}
    </div>
  );
}

interface LatencyPanelProps {
  compact?: boolean;
}

function LatencyPanel({ compact = false }: LatencyPanelProps) {
  const { data, loading, error, refetch } = useLatency();
  const [showDetails, setShowDetails] = useState(false);

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-6 bg-slate-800 rounded mb-4"></div>
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-slate-800 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <AlertTriangle className="w-5 h-5" />
          <span className="font-semibold">Latency Metrics Unavailable</span>
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

  const { percentiles, thresholds, alert, slo_compliance } = data;
  const safeSlo = slo_compliance ?? { compliant: true, target_p99_ms: 0, current_p99_ms: 0 };
  const sloStatus = getSloStatus(safeSlo.compliant);

  // Compact view for dashboard headers
  if (compact) {
    const hasAlert = alert !== null;
    const isCritical = alert?.severity === 'critical';
    
    return (
      <div
        className={`rounded-lg px-4 py-3 cursor-pointer transition-all ${
          isCritical
            ? 'bg-red-500/20 border border-red-500/50 hover:bg-red-500/30'
            : hasAlert
            ? 'bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30'
            : 'bg-emerald-500/20 border border-emerald-500/50 hover:bg-emerald-500/30'
        }`}
        onClick={refetch}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isCritical ? (
              <AlertTriangle className="w-5 h-5 text-red-400" />
            ) : hasAlert ? (
              <Activity className="w-5 h-5 text-amber-400" />
            ) : (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            )}
            <span className="font-medium">
              {isCritical
                ? `Critical: ${alert?.metric} = ${formatLatency(alert?.value || 0)}`
                : hasAlert
                ? `Warning: ${alert?.metric} = ${formatLatency(alert?.value || 0)}`
                : `p99: ${formatLatency(percentiles.p99_ms)}`}
            </span>
          </div>
          <div className={`text-xs ${sloStatus.color}`}>
            SLO: {sloStatus.text}
          </div>
        </div>
      </div>
    );
  }

  // Full panel view
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-purple-500/10">
            <Activity className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-100">API Latency</h3>
            <p className="text-sm text-slate-500">
              Percentile metrics vs SLO targets
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 
                       text-slate-300 text-sm transition-colors"
          >
            {showDetails ? 'Hide Details' : 'Show Details'}
          </button>
          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 
                       text-slate-300 text-sm transition-colors"
            title="Refresh metrics"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Alert Banner */}
      {alert && (
        <div className={`mb-6 p-4 rounded-lg border ${
          alert.severity === 'critical'
            ? 'bg-red-500/10 border-red-500/50'
            : 'bg-amber-500/10 border-amber-500/50'
        }`}>
          <div className="flex items-center gap-2">
            <AlertTriangle className={`w-5 h-5 ${
              alert.severity === 'critical' ? 'text-red-400' : 'text-amber-400'
            }`} />
            <span className={`font-medium ${
              alert.severity === 'critical' ? 'text-red-400' : 'text-amber-400'
            }`}>
              {alert.severity === 'critical' ? 'Critical Alert' : 'Warning'}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-300">
            {(alert.metric ?? 'p99').toUpperCase()} latency is {formatLatency(alert.value ?? 0)}
            (threshold: {formatLatency(alert.threshold)})
          </p>
        </div>
      )}

      {/* Main Percentiles */}
      <div className="grid grid-cols-3 gap-6 mb-6">
        <div className="bg-slate-800/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <Timer className="w-4 h-4 text-slate-400" />
            <span className="text-sm text-slate-400">p50 (Median)</span>
          </div>
          <div className={`text-2xl font-bold ${getLatencyColor(
            percentiles.p50_ms,
            thresholds.warning_p95_ms,
            thresholds.critical_p95_ms
          )}`}>
            {formatLatency(percentiles.p50_ms)}
          </div>
        </div>
        
        <div className="bg-slate-800/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-slate-400" />
            <span className="text-sm text-slate-400">p95</span>
          </div>
          <div className={`text-2xl font-bold ${getLatencyColor(
            percentiles.p95_ms,
            thresholds.warning_p95_ms,
            thresholds.critical_p95_ms
          )}`}>
            {formatLatency(percentiles.p95_ms)}
          </div>
          <div className="mt-2 text-xs text-slate-500">
            Target: {formatLatency(thresholds.warning_p95_ms)}
          </div>
        </div>
        
        <div className="bg-slate-800/50 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-slate-400" />
            <span className="text-sm text-slate-400">p99 (Tail)</span>
          </div>
          <div className={`text-2xl font-bold ${getLatencyColor(
            percentiles.p99_ms,
            thresholds.warning_p99_ms,
            thresholds.critical_p99_ms
          )}`}>
            {formatLatency(percentiles.p99_ms)}
          </div>
          <div className="mt-2 text-xs text-slate-500">
            SLO: {formatLatency(safeSlo.target_p99_ms)}
          </div>
        </div>
      </div>

      {/* SLO Compliance */}
      <div className="mb-6 p-4 rounded-lg bg-slate-800/30 border border-slate-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle className={`w-5 h-5 ${sloStatus.color}`} />
            <span className="font-medium text-slate-200">SLO Compliance</span>
          </div>
          <span className={`text-sm font-semibold ${sloStatus.color}`}>
            {sloStatus.text}
          </span>
        </div>
        <div className="mt-2 text-sm text-slate-400">
          Target p99: {formatLatency(safeSlo.target_p99_ms)} | 
          Current p99: {formatLatency(safeSlo.current_p99_ms)}
        </div>
      </div>

      {/* Detailed Metrics */}
      {showDetails && (
        <div className="mt-6 pt-6 border-t border-slate-800 space-y-4">
          <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider">
            Detailed Metrics
          </h4>
          
          <LatencyMetric
            label="p50 (Median)"
            value={percentiles.p50_ms}
            warning={thresholds.warning_p95_ms}
            critical={thresholds.critical_p95_ms}
          />
          <LatencyMetric
            label="p95"
            value={percentiles.p95_ms}
            warning={thresholds.warning_p95_ms}
            critical={thresholds.critical_p95_ms}
          />
          <LatencyMetric
            label="p99"
            value={percentiles.p99_ms}
            warning={thresholds.warning_p99_ms}
            critical={thresholds.critical_p99_ms}
          />
          
          <div className="grid grid-cols-3 gap-4 pt-4">
            <div className="text-center">
              <div className="text-sm text-slate-400">Minimum</div>
              <div className="text-lg font-semibold text-slate-200">
                {formatLatency(percentiles.min_ms)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-sm text-slate-400">Average</div>
              <div className="text-lg font-semibold text-slate-200">
                {formatLatency(percentiles.avg_ms)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-sm text-slate-400">Maximum</div>
              <div className="text-lg font-semibold text-slate-200">
                {formatLatency(percentiles.max_ms)}
              </div>
            </div>
          </div>
          
          <div className="text-center text-xs text-slate-500 pt-2">
            Sample count: {data.sample_count.toLocaleString()} | 
            Last updated: {formatDateTime(data.last_updated)}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 flex items-center justify-between">
        <div>
          Thresholds: Warning {formatLatency(thresholds.warning_p99_ms)} | 
          Critical {formatLatency(thresholds.critical_p99_ms)}
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            &lt; Warning
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-amber-400"></span>
            Warning
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400"></span>
            Critical
          </span>
        </div>
      </div>
    </div>
  );
}

export default LatencyPanel;
