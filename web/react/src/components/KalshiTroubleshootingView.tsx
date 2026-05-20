/**
 * KalshiTroubleshootingView — Troubleshooting View (Phase 5)
 *
 * Shows logs, failures, and reconciliation status for debugging.
 * 
 * Design principles:
 * - Tab-based interface (Logs, Failures, Reconciliation)
 * - Filterable log entries
 * - Error highlighting
 * - Reconciliation status display
 */

import { useState } from 'react';
import {
  FileText,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  Search,
} from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { formatCurrency, fmtTimestamp } from '../utils/formatters';

type TabType = 'logs' | 'failures' | 'reconciliation';

// ── Sub-Components ─────────────────────────────────────────────────────────────

function LogsTab() {
  const { data, loading, error, refetch } = useApiData<{
    logs: Array<{
      id: string;
      timestamp: string;
      level: 'info' | 'warning' | 'error';
      message: string;
      source: string;
    }>;
  }>(
    API_ENDPOINTS.LOGS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.LOGS }
  );

  const [levelFilter, setLevelFilter] = useState<'all' | 'info' | 'warning' | 'error'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredLogs = data?.logs?.filter((log) => {
    const matchesLevel = levelFilter === 'all' || log.level === levelFilter;
    const matchesSearch = searchQuery === '' || 
      log.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.source.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesLevel && matchesSearch;
  }) || [];

  const levelColors = {
    info: 'text-blue-400',
    warning: 'text-amber-400',
    error: 'text-red-400',
  };

  const levelBgColors = {
    info: 'bg-blue-500/10',
    warning: 'bg-amber-500/10',
    error: 'bg-red-500/10',
  };

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 flex-1">
          <Search className="w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search logs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value as any)}
          className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="all">All Levels</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
        </select>
        <button
          onClick={() => refetch()}
          className="p-1.5 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Log List */}
      {loading && !data ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="bg-slate-800/50 rounded p-3 animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-24 mb-2" />
              <div className="h-3 bg-slate-700 rounded w-64" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
          <p className="text-sm text-red-400">Failed to load logs</p>
        </div>
      ) : filteredLogs.length === 0 ? (
        <div className="text-center py-8">
          <FileText className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No logs found</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {filteredLogs.map((log) => (
            <div
              key={log.id}
              className="bg-slate-800/50 rounded-lg p-3 hover:bg-slate-800 transition-colors"
            >
              <div className="flex items-start gap-3">
                <span className={`text-xs font-medium px-2 py-0.5 rounded ${levelBgColors[log.level]} ${levelColors[log.level]} uppercase`}>
                  {log.level}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-200 break-words">{log.message}</p>
                  <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                    <span>{log.source}</span>
                    <span>{fmtTimestamp(log.timestamp)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FailuresTab() {
  const { data, loading, error, refetch } = useApiData<{
    failures: Array<{
      id: string;
      timestamp: string;
      type: string;
      message: string;
      component: string;
      resolved: boolean;
    }>;
  }>(
    API_ENDPOINTS.MONITORING_RISK_EVENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM }
  );

  const [showResolved, setShowResolved] = useState(false);

  const filteredFailures = data?.failures?.filter((f) => 
    showResolved || !f.resolved
  ) || [];

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
            className="rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-blue-500"
          />
          Show resolved
        </label>
        <button
          onClick={() => refetch()}
          className="p-1.5 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Failure List */}
      {loading && !data ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-slate-800/50 rounded p-3 animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-32 mb-2" />
              <div className="h-3 bg-slate-700 rounded w-48" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
          <p className="text-sm text-red-400">Failed to load failures</p>
        </div>
      ) : filteredFailures.length === 0 ? (
        <div className="text-center py-8">
          <CheckCircle className="w-8 h-8 text-green-500 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No failures recorded</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {filteredFailures.map((failure) => (
            <div
              key={failure.id}
              className={`bg-slate-800/50 rounded-lg p-3 ${failure.resolved ? 'opacity-60' : ''}`}
            >
              <div className="flex items-start gap-3">
                <AlertTriangle className={`w-4 h-4 mt-0.5 ${failure.resolved ? 'text-green-400' : 'text-red-400'}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-slate-200">{failure.type}</span>
                    {failure.resolved && (
                      <span className="text-xs px-2 py-0.5 rounded bg-green-500/10 text-green-400">
                        Resolved
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-300 break-words">{failure.message}</p>
                  <div className="flex items-center gap-3 mt-1 text-xs text-slate-500">
                    <span>{failure.component}</span>
                    <span>{fmtTimestamp(failure.timestamp)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReconciliationTab() {
  const { data, loading, error, refetch } = useApiData<{
    status: 'ok' | 'discrepancy' | 'error';
    last_check: string;
    discrepancy_count: number;
    discrepancies: Array<{
      id: string;
      type: string;
      description: string;
      amount_usd: number;
      timestamp: string;
    }>;
  }>(
    API_ENDPOINTS.RECONCILIATION_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM }
  );

  const statusColors = {
    ok: 'text-green-400 bg-green-500/10',
    discrepancy: 'text-amber-400 bg-amber-500/10',
    error: 'text-red-400 bg-red-500/10',
  };

  return (
    <div className="space-y-4">
      {/* Status Header */}
      <div className="bg-slate-800/50 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">Status</span>
            <span className={`text-sm font-medium px-2 py-0.5 rounded ${statusColors[data?.status || 'error']}`}>
              {(data?.status || 'error').toUpperCase()}
            </span>
          </div>
          <button
            onClick={() => refetch()}
            className="p-1.5 bg-slate-700 border border-slate-600 rounded hover:bg-slate-600 transition-colors"
          >
            <RefreshCw className="w-4 h-4 text-slate-400" />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-slate-400 mb-1">Last Check</div>
            <div className="text-sm text-slate-200">
              {data?.last_check ? fmtTimestamp(data.last_check) : 'Never'}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-400 mb-1">Discrepancies</div>
            <div className={`text-sm font-medium ${(data?.discrepancy_count ?? 0) > 0 ? 'text-amber-400' : 'text-green-400'}`}>
              {data?.discrepancy_count || 0}
            </div>
          </div>
        </div>
      </div>

      {/* Discrepancy List */}
      {loading && !data ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-slate-800/50 rounded p-3 animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-32 mb-2" />
              <div className="h-3 bg-slate-700 rounded w-48" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
          <p className="text-sm text-red-400">Failed to load reconciliation status</p>
        </div>
      ) : !data?.discrepancies || data.discrepancies.length === 0 ? (
        <div className="text-center py-8">
          <CheckCircle className="w-8 h-8 text-green-500 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No discrepancies found</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {data.discrepancies.map((disc) => (
            <div key={disc.id} className="bg-slate-800/50 rounded-lg p-3">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-4 h-4 mt-0.5 text-amber-400" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-slate-200">{disc.type}</span>
                    <span className={`text-sm ${disc.amount_usd !== 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {disc.amount_usd !== 0 ? formatCurrency(disc.amount_usd) : 'Balanced'}
                    </span>
                  </div>
                  <p className="text-sm text-slate-300 break-words">{disc.description}</p>
                  <div className="text-xs text-slate-500 mt-1">
                    {fmtTimestamp(disc.timestamp)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────────

export default function KalshiTroubleshootingView() {
  const [activeTab, setActiveTab] = useState<TabType>('logs');

  const tabs = [
    { id: 'logs' as TabType, label: 'Logs', icon: FileText },
    { id: 'failures' as TabType, label: 'Failures', icon: AlertTriangle },
    { id: 'reconciliation' as TabType, label: 'Reconciliation', icon: CheckCircle },
  ];

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-400" />
        <span className="text-sm font-semibold text-slate-200">Troubleshooting</span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 text-sm transition-colors border-b-2 ${
              activeTab === tab.id
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-400 hover:text-slate-300'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-64">
        {activeTab === 'logs' && <LogsTab />}
        {activeTab === 'failures' && <FailuresTab />}
        {activeTab === 'reconciliation' && <ReconciliationTab />}
      </div>
    </div>
  );
}
