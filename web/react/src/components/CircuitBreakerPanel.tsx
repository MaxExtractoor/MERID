import { useState } from 'react';
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Shield,
  Activity,
  Clock,
  Zap,
  Server
} from '../ui/icons';
import { useCircuitBreaker, getCircuitBreakerColor, formatCircuitBreakerState } from '../hooks/useCircuitBreaker';
import { formatDateTime } from '../utils/formatters';
import type { CircuitBreakerDetail, CircuitBreakerState } from '../hooks/useCircuitBreaker';

interface CircuitBreakerCardProps {
  breaker: CircuitBreakerDetail;
  onReset?: () => void;
  resetting?: boolean;
}

function CircuitBreakerCard({ breaker, onReset, resetting }: CircuitBreakerCardProps) {
  const colorClass = getCircuitBreakerColor(breaker.state);
  
  const getIcon = (state: CircuitBreakerState) => {
    switch (state) {
      case 'CLOSED':
        return <CheckCircle className="w-5 h-5" />;
      case 'HALF_OPEN':
        return <AlertTriangle className="w-5 h-5" />;
      case 'OPEN':
        return <XCircle className="w-5 h-5" />;
      default:
        return <Activity className="w-5 h-5" />;
    }
  };

  const getServiceIcon = (name: string) => {
    if (name.includes('rest') || name.includes('api')) return <Server className="w-4 h-4" />;
    if (name.includes('ws') || name.includes('websocket')) return <Zap className="w-4 h-4" />;
    if (name.includes('order')) return <Activity className="w-4 h-4" />;
    return <Shield className="w-4 h-4" />;
  };

  return (
    <div className={`rounded-lg border p-4 ${colorClass}`}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-full bg-current/10`}>
            {getIcon(breaker.state)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              {getServiceIcon(breaker.name)}
              <span className="font-semibold capitalize">
                {breaker.name.replace(/_/g, ' ').replace(/-/g, ' ')}
              </span>
            </div>
            <div className="text-sm mt-1">
              {formatCircuitBreakerState(breaker.state)}
            </div>
          </div>
        </div>
        
        {breaker.state !== 'CLOSED' && onReset && (
          <button
            onClick={onReset}
            disabled={resetting}
            className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 
                       text-slate-300 text-sm transition-colors disabled:opacity-50"
            title="Reset circuit breaker"
          >
            <RefreshCw className={`w-4 h-4 ${resetting ? 'animate-spin' : ''}`} />
            <span>{resetting ? 'Resetting...' : 'Reset'}</span>
          </button>
        )}
      </div>

      {/* Metrics */}
      <div className="mt-4 grid grid-cols-3 gap-4 text-sm">
        <div>
          <div className="text-slate-500">Calls</div>
          <div className="font-medium">{breaker.total_calls.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-slate-500">Failures</div>
          <div className={`font-medium ${breaker.failure_count > 0 ? 'text-red-400' : ''}`}>
            {breaker.failure_count.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-slate-500">Blocked</div>
          <div className={`font-medium ${breaker.blocked_calls > 0 ? 'text-amber-400' : ''}`}>
            {breaker.blocked_calls.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Threshold info */}
      <div className="mt-3 text-xs text-slate-500">
        Threshold: {breaker.failure_threshold} failures / {breaker.recovery_timeout_seconds}s recovery
      </div>

      {/* Last activity */}
      {(breaker.last_failure_time || breaker.last_success_time) && (
        <div className="mt-3 pt-3 border-t border-current/10 text-xs text-slate-500">
          {breaker.last_failure_time && (
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              Last failure: {formatDateTime(breaker.last_failure_time)}
            </div>
          )}
          {breaker.last_transition_time && (
            <div className="flex items-center gap-1 mt-1">
              <Activity className="w-3 h-3" />
              Last transition: {formatDateTime(breaker.last_transition_time)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface CircuitBreakerPanelProps {
  compact?: boolean;
  showSummary?: boolean;
}

function CircuitBreakerPanel({ compact = false, showSummary = true }: CircuitBreakerPanelProps) {
  const { data, loading, error, refetch, resetBreaker } = useCircuitBreaker();
  const [resettingBreaker, setResettingBreaker] = useState<string | null>(null);

  const handleReset = async (name: string) => {
    setResettingBreaker(name);
    await resetBreaker(name);
    setResettingBreaker(null);
  };

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-6 bg-slate-800 rounded mb-4"></div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-slate-800 rounded"></div>
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
          <span className="font-semibold">Circuit Breaker Status Unavailable</span>
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

  if (!data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-amber-800/50 p-6">
        <div className="flex items-center gap-2 text-amber-400 mb-1">
          <AlertTriangle className="w-5 h-5" />
          <span className="font-semibold">Circuit Breaker Status Unknown</span>
        </div>
        <p className="text-sm text-slate-400">No data received — breaker state cannot be determined.</p>
      </div>
    );
  }

  const { summary, kalshi_specific } = data;

  // Compact view for dashboard headers
  if (compact) {
    const hasOpen = summary.open_count > 0;
    const hasHalfOpen = summary.half_open_count > 0;
    
    return (
      <div
        className={`rounded-lg px-4 py-3 cursor-pointer transition-all ${
          hasOpen
            ? 'bg-red-500/20 border border-red-500/50 hover:bg-red-500/30'
            : hasHalfOpen
            ? 'bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30'
            : 'bg-emerald-500/20 border border-emerald-500/50 hover:bg-emerald-500/30'
        }`}
        onClick={refetch}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {hasOpen ? (
              <XCircle className="w-5 h-5 text-red-400" />
            ) : hasHalfOpen ? (
              <AlertTriangle className="w-5 h-5 text-amber-400" />
            ) : (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            )}
            <span className="font-medium">
              {hasOpen
                ? `${summary.open_count} Circuit Breaker${summary.open_count > 1 ? 's' : ''} Open`
                : hasHalfOpen
                ? `${summary.half_open_count} Testing Recovery`
                : 'All Circuits Healthy'}
            </span>
          </div>
          <div className="text-xs text-slate-400">
            {summary.closed_count}/{summary.total_breakers} healthy
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
          <div className="p-2 rounded-lg bg-blue-500/10">
            <Shield className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-100">Circuit Breaker Status</h3>
            <p className="text-sm text-slate-500">
              Real-time fault tolerance monitoring
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 
                     text-slate-300 text-sm transition-colors"
          title="Refresh status"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Refresh</span>
        </button>
      </div>

      {/* Summary stats */}
      {showSummary && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-slate-800/50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-slate-100">{summary?.total_breakers ?? 0}</div>
            <div className="text-xs text-slate-500">Total</div>
          </div>
          <div className="bg-emerald-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-emerald-400">{summary?.closed_count ?? 0}</div>
            <div className="text-xs text-slate-500">Healthy</div>
          </div>
          <div className="bg-amber-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-amber-400">{summary?.half_open_count ?? 0}</div>
            <div className="text-xs text-slate-500">Testing</div>
          </div>
          <div className="bg-red-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-400">{summary?.open_count ?? 0}</div>
            <div className="text-xs text-slate-500">Open</div>
          </div>
        </div>
      )}

      {/* Kalshi-specific breakers */}
      <div className="space-y-4">
        <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider">
          Kalshi Services
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {kalshi_specific?.rest_client && (
            <CircuitBreakerCard
              breaker={kalshi_specific.rest_client}
              onReset={() => handleReset(kalshi_specific.rest_client.name)}
              resetting={resettingBreaker === kalshi_specific.rest_client.name}
            />
          )}
          {kalshi_specific?.websocket && (
            <CircuitBreakerCard
              breaker={kalshi_specific.websocket}
              onReset={() => handleReset(kalshi_specific.websocket.name)}
              resetting={resettingBreaker === kalshi_specific.websocket.name}
            />
          )}
          {kalshi_specific?.order_placement && (
            <CircuitBreakerCard
              breaker={kalshi_specific.order_placement}
              onReset={() => handleReset(kalshi_specific.order_placement.name)}
              resetting={resettingBreaker === kalshi_specific.order_placement.name}
            />
          )}
        </div>
      </div>

      {/* All breakers */}
      {data?.breakers?.length > 3 && (
        <div className="mt-6 space-y-4">
          <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider">
            All Circuit Breakers
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data?.breakers?.map((breaker) => (
              <CircuitBreakerCard
                key={breaker.name}
                breaker={breaker}
                onReset={() => handleReset(breaker.name)}
                resetting={resettingBreaker === breaker.name}
              />
            ))}
          </div>
        </div>
      )}

      {/* Footer info */}
      <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 flex items-center justify-between">
        <div>
          Last updated: {formatDateTime(summary?.last_updated)}
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            Closed = Healthy
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-amber-400"></span>
            Half-Open = Testing
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400"></span>
            Open = Blocking
          </span>
        </div>
      </div>
    </div>
  );
}

export default CircuitBreakerPanel;
