import React, { useState, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS, API_BASE_URL, AUTH_TOKEN_KEY } from '../config/constants';
import { formatTs } from '../ui/utils';

interface ReconciliationHistory {
  id: string;
  timestamp: number;
  duration_ms: number;
  checks_total: number;
  checks_passed: number;
  checks_failed: number;
  pnl_delta: number | null;
  blocked: boolean;
  error_message: string | null;
  triggered_by: 'auto' | 'manual';
}

interface ReconciliationMetrics {
  total_runs: number;
  success_rate: number;
  avg_duration_ms: number;
  avg_pnl_delta: number;
  last_run: number | null;
  next_scheduled: number | null;
  failure_patterns: Record<string, number>;
}

const ReconciliationDashboard: React.FC = () => {
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [timeRange, setTimeRange] = useState<'24h' | '7d' | '30d'>('24h');

  // Fetch reconciliation history
  const { data: history, loading: historyLoading, error: historyError, refetch: refetchHistory } = useApiData<{
    runs: ReconciliationHistory[];
    metrics: ReconciliationMetrics;
  }>(
    API_ENDPOINTS.RECONCILIATION_STATUS,
    { 
      pollingInterval: autoRefresh ? DEFAULTS.POLLING_INTERVALS.STANDARD : 0,
      query: { time_range: timeRange }
    }
  );

  const handleManualRun = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RECONCILIATION_RUN}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}`,
        },
        body: JSON.stringify({ trigger_reason: 'manual_dashboard' }),
      });

      if (response.ok) {
        // Refresh data after triggering
        setTimeout(() => refetchHistory(), 1000);
      }
    } catch (error) {
      console.error('Failed to trigger reconciliation:', error);
    }
  }, [refetchHistory]);

  const getStatusColor = (run: ReconciliationHistory) => {
    if (run.error_message) return 'text-red-400';
    if (run.blocked) return 'text-amber-400';
    if (run.checks_failed > 0) return 'text-amber-400';
    return 'text-green-400';
  };

  const getStatusIcon = (run: ReconciliationHistory) => {
    if (run.error_message) return 'alertCircle';
    if (run.blocked) return 'shieldAlert';
    if (run.checks_failed > 0) return 'alertTriangle';
    return 'checkCircle';
  };

  if (historyLoading && !history) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-500">
          <Icon name="loader" size={20} className="w-5 h-5 animate-spin" />
          <span>Loading reconciliation dashboard...</span>
        </div>
      </div>
    );
  }

  if (historyError) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-red-800/50 p-6">
        <div className="flex items-center gap-2 text-red-400">
          <Icon name="alert" size={20} className="w-5 h-5" />
          <span>Failed to load reconciliation data</span>
        </div>
      </div>
    );
  }

  const { runs, metrics } = history || { runs: [], metrics: null };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="refresh" size={20} className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-bold text-white">Reconciliation Dashboard</h2>
        </div>
        
        <div className="flex items-center gap-3">
          {/* Time Range Selector */}
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value as '24h' | '7d' | '30d')}
            className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
          >
            <option value="24h">Last 24h</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </select>
          
          {/* Auto Refresh Toggle */}
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors ${
              autoRefresh 
                ? 'bg-green-600 text-white' 
                : 'bg-slate-700 text-slate-400'
            }`}
          >
            <Icon name="refresh" size={12} className="w-3 h-3" />
            Auto
          </button>
          
          {/* Manual Run Button */}
          <button
            onClick={handleManualRun}
            className="flex items-center gap-1.5 px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
          >
            <Icon name="play" size={12} className="w-3 h-3" />
            Run Now
          </button>
        </div>
      </div>

      {/* Metrics Cards */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Total Runs</div>
            <div className="text-lg font-bold text-white">{metrics.total_runs}</div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Success Rate</div>
            <div className="text-lg font-bold text-green-400">{((metrics.success_rate ?? 0) * 100).toFixed(1)}%</div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Avg Duration</div>
            <div className="text-lg font-bold text-blue-400">
              {((metrics.avg_duration_ms ?? 0) / 1000).toFixed(1)}s
            </div>
          </div>
          
          <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Avg PnL Δ</div>
            <div className={`text-lg font-bold ${
              Math.abs(metrics.avg_pnl_delta ?? 0) > 5 ? 'text-amber-400' : 'text-slate-400'
            }`}>
              ${(metrics.avg_pnl_delta ?? 0).toFixed(2)}
            </div>
          </div>
        </div>
      )}

      {/* Failure Patterns */}
      {metrics?.failure_patterns && Object.keys(metrics.failure_patterns).length > 0 && (
        <div className="bg-amber-900/20 border border-amber-700/30 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-2">
            <Icon name="alertTriangle" size={16} className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-amber-400">Common Failure Patterns</span>
          </div>
          <div className="space-y-1">
            {Object.entries(metrics.failure_patterns).map(([pattern, count]) => (
              <div key={pattern} className="flex items-center justify-between text-xs">
                <span className="text-amber-300">{pattern}</span>
                <span className="text-amber-400 font-mono">{count}x</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Reconciliation History */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-300">Reconciliation History</h3>
        
        {runs.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            No reconciliation runs in selected time range
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {runs.map((run) => (
              <div
                key={run.id}
                className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 cursor-pointer hover:border-slate-600 transition-colors"
                onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon 
                      name={getStatusIcon(run)} 
                      size={16} 
                      className={`w-4 h-4 ${getStatusColor(run)}`} 
                    />
                    <span className="text-sm text-white">{formatTs(run.timestamp)}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      run.triggered_by === 'manual' 
                        ? 'bg-blue-500/20 text-blue-400' 
                        : 'bg-slate-600/40 text-slate-400'
                    }`}>
                      {run.triggered_by}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-3 text-xs">
                    <span className={getStatusColor(run)}>
                      {run.checks_passed}/{run.checks_total} passed
                    </span>
                    <span className="text-slate-500">
                      {(run.duration_ms / 1000).toFixed(1)}s
                    </span>
                    <Icon 
                      name="chevronDown" 
                      size={12} 
                      className={`w-3 h-3 text-slate-500 transition-transform ${
                        expandedRun === run.id ? 'rotate-180' : ''
                      }`} 
                    />
                  </div>
                </div>
                
                {/* Expanded Details */}
                {expandedRun === run.id && (
                  <div className="mt-3 pt-3 border-t border-slate-700/50 space-y-2">
                    {run.error_message && (
                      <div className="bg-red-900/20 rounded p-2">
                        <div className="text-xs text-red-300 font-medium mb-1">Error</div>
                        <div className="text-xs text-red-400">{run.error_message}</div>
                      </div>
                    )}
                    
                    {run.pnl_delta !== null && (
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-slate-400">PnL Delta:</span>
                        <span className={`font-mono ${
                          Math.abs(run.pnl_delta) > 5 ? 'text-amber-400' : 'text-slate-400'
                        }`}>
                          ${run.pnl_delta.toFixed(2)}
                        </span>
                      </div>
                    )}
                    
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">Status:</span>
                      <span className={getStatusColor(run)}>
                        {run.error_message ? 'Error' : run.blocked ? 'Blocked' : run.checks_failed > 0 ? 'Warnings' : 'Success'}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReconciliationDashboard;
