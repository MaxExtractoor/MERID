import React, { useState } from "react";
import { RefreshCw } from 'lucide-react';
import { useApiData } from "../hooks/useApiData";
import { API_BASE_URL, API_ENDPOINTS, LOG_LEVELS, DEFAULTS, AUTH_TOKEN_KEY } from "../config/constants";
import { formatDateTime } from "../utils/formatters";
import DataTableEnhanced from "../components/DataTableEnhanced";
import ErrorAlert from "../components/ErrorAlert";
import EmptyState from "../components/EmptyState";

interface LogEntry {
  id: string;
  timestamp: string;
  level: keyof typeof LOG_LEVELS;
  component: string;
  message: string;
  details?: Record<string, unknown>;
  stackTrace?: string;
  userId?: string;
  sessionId?: string;
  requestId?: string;
}

interface LogStats {
  totalLogs: number;
  errorCount: number;
  warnCount: number;
  infoCount: number;
  debugCount: number;
  last24hCount: number;
  componentCounts: Record<string, number>;
}

export default function Logs() {
  const [selectedLevel, setSelectedLevel] = useState<string>("all");
  const [selectedComponent, setSelectedComponent] = useState<string>("all");
  const [showDetails, setShowDetails] = useState(false);
  const [selectedLog, _setSelectedLog] = useState<LogEntry | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [clearStatus, setClearStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [refreshInterval, setRefreshInterval] = useState(5000);

  // Fetch logs data
  const { data: logs, loading: logsLoading, error: logsError, refetch } = useApiData<LogEntry[]>(
    API_ENDPOINTS.LOGS,
    { 
      pollingInterval: autoRefresh ? DEFAULTS.POLLING_INTERVALS.LOGS : undefined,
      transform: (raw) => {
        const payload = Array.isArray(raw) ? (raw as LogEntry[]) : [];
        // Sort by timestamp descending
        return [...payload].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      }
    }
  );

  // Fetch log stats
  const { data: stats } = useApiData<LogStats>(
    API_ENDPOINTS.LOGS_STATS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.LOG_STATS }
  );

  const isLoading = logsLoading && !logs && !stats;

  const filteredLogs = React.useMemo(() => {
    const source = logs ?? [];
    return source.filter(log => {
      const levelMatch = selectedLevel === "all" || log.level === selectedLevel;
      const componentMatch = selectedComponent === "all" || log.component === selectedComponent;
      return levelMatch && componentMatch;
    });
  }, [logs, selectedLevel, selectedComponent]);

  const components = React.useMemo(() => {
    const source = logs ?? [];
    return [...new Set(source.map(log => log.component))].sort();
  }, [logs]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading logs…</span>
      </div>
    );
  }

  if (logsError && !logs) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">System Logs</h1>
        <ErrorAlert message="Failed to load logs" onRetry={refetch} />
      </div>
    );
  }

  if (logs && logs.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">System Logs</h1>
        <EmptyState title="No logs yet" message="System logs will appear here as activity occurs." />
      </div>
    );
  }

  const getLevelColor = (level: string) => {
    switch (level) {
      case "error": return "text-red-500";
      case "warn": return "text-amber-500";
      case "info": return "text-blue-500";
      case "debug": return "text-slate-500";
      default: return "text-slate-500";
    }
  };

  const getLevelIcon = (level: string) => {
    switch (level) {
      case "error": return "❌";
      case "warn": return "⚠️";
      case "info": return "ℹ️";
      case "debug": return "🔍";
      default: return "📝";
    }
  };

  const getLevelBgColor = (level: string) => {
    switch (level) {
      case "error": return "bg-red-500/10 border-red-500/20";
      case "warn": return "bg-amber-500/10 border-amber-500/20";
      case "info": return "bg-blue-500/10 border-blue-500/20";
      case "debug": return "bg-slate-500/10 border-slate-500/20";
      default: return "bg-slate-500/10 border-slate-500/20";
    }
  };

  const columns: Array<{
    key: keyof LogEntry;
    label: string;
    sortable?: boolean;
    render?: (value: unknown, row: LogEntry) => React.ReactNode;
  }> = [
    {
      key: "timestamp" as keyof LogEntry,
      label: "Timestamp",
      sortable: true,
      render: (value: unknown) => {
        const timestamp = typeof value === "string" ? value : "";
        return timestamp ? formatDateTime(timestamp) : "-";
      },
    },
    {
      key: "level" as keyof LogEntry,
      label: "Level",
      render: (value: unknown) => {
        const level = typeof value === "string" ? value : "";
        return (
        <span className={`px-2 py-1 rounded text-xs font-medium ${getLevelBgColor(level)} ${getLevelColor(level)}`}>
          {getLevelIcon(level)} {level.toUpperCase()}
        </span>
        );
      },
    },
    {
      key: "component" as keyof LogEntry,
      label: "Component",
      sortable: true,
      render: (value: unknown) => (
        <span className="px-2 py-1 rounded text-xs font-medium bg-purple-500/10 border-purple-500/20 text-purple-500">
          {typeof value === "string" ? value : String(value ?? "")}
        </span>
      ),
    },
    {
      key: "message" as keyof LogEntry,
      label: "Message",
      render: (value: unknown, row: LogEntry) => (
        <div className="max-w-md">
          <div className="text-white">{typeof value === "string" ? value : String(value ?? "")}</div>
          {row.details && (
            <div className="text-xs text-slate-400 mt-1">
              {JSON.stringify(row.details, null, 2)}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "id" as keyof LogEntry,
      label: "Actions",
      render: (_value: unknown, row: LogEntry) => (
        <button type="button"
          onClick={() => {
            _setSelectedLog(row);
            setShowDetails(true);
          }}
          className="text-blue-400 hover:text-blue-300"
        >
          View Details
        </button>
      ),
    },
  ];

  const handleExportLogs = () => {
    const csvContent = [
      ["Timestamp", "Level", "Component", "Message", "User ID", "Session ID", "Request ID"],
      ...filteredLogs.map(log => [
        log.timestamp,
        log.level,
        log.component,
        log.message,
        log.userId || "",
        log.sessionId || "",
        log.requestId || "",
      ]),
    ].map(row => row.join(","));

    const blob = new Blob([csvContent.join('\n')], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `logs_${new Date().toISOString().split("T")[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleClearLogs = async () => {
    setClearStatus(null);
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.LOGS_CLEAR}`, {
        method: "DELETE",
        headers: {
          "Authorization": `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}`,
        },
      });

      if (!response.ok) {
        throw new Error("Failed to clear logs");
      }

      setClearStatus({ type: 'success', message: 'Logs cleared successfully' });
      setTimeout(() => setClearStatus(null), DEFAULTS.POLLING_INTERVALS.STANDARD);
      refetch();
    } catch (error) {
      setClearStatus({ type: 'error', message: 'Failed to clear logs. Please try again.' });
    }
  };

  return (
    <div className="space-y-6">
      {/* Mutation Feedback */}
      {clearStatus && (
        <div className={`rounded-lg px-4 py-3 text-sm ${
          clearStatus.type === 'success'
            ? 'bg-emerald-900/20 border border-emerald-500/30 text-emerald-300'
            : 'bg-red-900/20 border border-red-500/30 text-red-300'
        }`}>
          {clearStatus.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Logs</h1>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">Auto-refresh:</span>
            <button type="button"
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-3 py-1 rounded text-sm font-medium ${
                autoRefresh 
                  ? "bg-green-600 text-white" 
                  : "bg-slate-700 text-slate-300"
              }`}
            >
              {autoRefresh ? "ON" : "OFF"}
            </button>
          </div>
          
          <div className="flex items-center gap-2">
            <label htmlFor="log-refresh-interval" className="text-sm text-slate-400">Refresh:</label>
            <select aria-label="Refresh:"
              id="log-refresh-interval"
              name="refreshInterval"
              title="Set refresh interval"
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
              className="px-3 py-1 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
            >
              <option value={1000}>1s</option>
              <option value={5000}>5s</option>
              <option value={10000}>10s</option>
              <option value={30000}>30s</option>
            </select>
          </div>

          <button type="button"
            onClick={handleExportLogs}
            className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm font-medium transition-colors"
           title="Export CSV">
            Export CSV
          </button>

          <button type="button"
            onClick={handleClearLogs}
            className="px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors"
           title="Clear Logs">
            Clear Logs
          </button>
        </div>
      </div>

      {/* Stats Summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-2xl font-bold text-white">{stats.totalLogs.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Total Logs</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-2xl font-bold text-red-500">{stats.errorCount.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Errors</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-2xl font-bold text-amber-500">{stats.warnCount.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Warnings</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-2xl font-bold text-blue-500">{stats.infoCount.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Info</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-2xl font-bold text-slate-500">{stats.debugCount.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Debug</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div>
          <label htmlFor="log-level-filter" className="text-sm font-medium text-slate-400">Level:</label>
          <select aria-label="Level:"
            id="log-level-filter"
            name="logLevel"
            title="Filter by log level"
            value={selectedLevel}
            onChange={(e) => setSelectedLevel(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Levels</option>
            <option value="error">Error</option>
            <option value="warn">Warning</option>
            <option value="info">Info</option>
            <option value="debug">Debug</option>
          </select>
        </div>

        <div>
          <label htmlFor="log-component-filter" className="text-sm font-medium text-slate-400">Component:</label>
          <select aria-label="Debug"
            id="log-component-filter"
            name="logComponent"
            title="Filter by component"
            value={selectedComponent}
            onChange={(e) => setSelectedComponent(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Components</option>
            {components.map(component => (
              <option key={component} value={component}>{component}</option>
            ))}
          </select>
        </div>

        <div className="text-sm text-slate-400">
          Showing {filteredLogs.length} of {logs?.length || 0} logs
        </div>
      </div>

      {/* Component Summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Object.entries(stats.componentCounts).slice(0, 8).map(([component, count]) => (
            <div key={component} className="bg-slate-800 rounded-lg p-4 border border-slate-700">
              <div className="text-lg font-bold text-white">{count}</div>
              <div className="text-sm text-slate-400">{component}</div>
            </div>
          ))}
        </div>
      )}

      {/* Logs Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Log Entries</h2>
        <DataTableEnhanced
          data={filteredLogs}
          columns={columns}
          pageSize={25}
          showPagination
          showFilter
        />
      </div>

      {/* Log Detail Modal */}
      {showDetails && selectedLog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 max-w-4xl max-h-[90vh] overflow-y-auto w-full mx-4">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Log Details</h2>
              <button type="button"
                onClick={() => setShowDetails(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-semibold text-white mb-2">Basic Information</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-sm text-slate-400">Timestamp</span>
                    <div className="text-white">{formatDateTime(selectedLog.timestamp)}</div>
                  </div>
                  <div>
                    <span className="text-sm text-slate-400">Level</span>
                    <div className={`px-2 py-1 rounded text-xs font-medium ${getLevelBgColor(selectedLog.level)} ${getLevelColor(selectedLog.level)}`}>
                      {getLevelIcon(selectedLog.level)} {(selectedLog.level ?? '').toUpperCase()}
                    </div>
                  </div>
                  <div>
                    <span className="text-sm text-slate-400">Component</span>
                    <div className="text-white">{selectedLog.component}</div>
                  </div>
                  <div>
                    <span className="text-sm text-slate-400">User ID</span>
                    <div className="text-white">{selectedLog.userId || "N/A"}</div>
                  </div>
                  <div>
                    <span className="text-sm text-slate-400">Session ID</span>
                    <div className="text-white">{selectedLog.sessionId || "N/A"}</div>
                  </div>
                  <div>
                    <span className="text-sm text-slate-400">Request ID</span>
                    <div className="text-white font-mono text-xs">{selectedLog.requestId || "N/A"}</div>
                  </div>
                </div>
              </div>

              <div>
                <h3 className="text-lg font-semibold text-white mb-2">Message</h3>
                <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                  <pre className="text-slate-300 whitespace-pre-wrap text-sm">
                    {selectedLog.message}
                  </pre>
                </div>
              </div>

              {selectedLog.details && (
                <div>
                  <h3 className="text-lg font-semibold text-white mb-2">Additional Details</h3>
                  <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                    <pre className="text-slate-300 whitespace-pre-wrap text-sm">
                      {JSON.stringify(selectedLog.details, null, 2)}
                    </pre>
                  </div>
                </div>
              )}

              {selectedLog.stackTrace && (
                <div>
                  <h3 className="text-lg font-semibold text-white mb-2">Stack Trace</h3>
                  <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                    <pre className="text-slate-300 whitespace-pre-wrap text-xs font-mono">
                      {selectedLog.stackTrace}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
