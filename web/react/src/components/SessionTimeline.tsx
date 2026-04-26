import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import { Clock, AlertCircle, Info, AlertTriangle, Zap } from '../ui/icons';

interface SessionLogEntry {
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'debug';
  component: string;
  message: string;
  metadata?: {
    event_id?: string;
    [key: string]: unknown;
  };
}

interface SessionLogsResponse {
  logs: SessionLogEntry[];
  total: number;
}

const getLevelIcon = (level: string) => {
  switch (level) {
    case 'error':
      return <AlertCircle className="w-4 h-4 text-red-400" />;
    case 'warning':
      return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
    case 'info':
      return <Info className="w-4 h-4 text-blue-400" />;
    default:
      return <Clock className="w-4 h-4 text-slate-400" />;
  }
};

const getLevelColor = (level: string) => {
  switch (level) {
    case 'error':
      return 'border-red-500/20 bg-red-500/5';
    case 'warning':
      return 'border-yellow-500/20 bg-yellow-500/5';
    case 'info':
      return 'border-blue-500/20 bg-blue-500/5';
    default:
      return 'border-slate-500/20 bg-slate-500/5';
  }
};

const formatTimestamp = (timestamp: string) => {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  } catch {
    return timestamp;
  }
};

export default function SessionTimeline() {
  const { data, loading, error, lastUpdated } = useApiData<SessionLogsResponse>(
    API_ENDPOINTS.SYSTEM_SESSION_LOG,
    { pollingInterval: 30000 } // Poll every 30s
  );

  if (loading && !data) {
    return (
      <div className="bg-slate-900/60 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="w-5 h-5 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-200">Session Timeline</h3>
        </div>
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} data-testid="skeleton" className="animate-pulse">
              <div className="flex items-start gap-3">
                <div className="w-4 h-4 bg-slate-700 rounded-full mt-1"></div>
                <div className="flex-1 space-y-1">
                  <div className="h-3 bg-slate-700 rounded w-3/4"></div>
                  <div className="h-2 bg-slate-700 rounded w-1/2"></div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900/60 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-4">
          <Clock className="w-5 h-5 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-200">Session Timeline</h3>
        </div>
        <div className="text-center text-slate-400 py-4">
          <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Failed to load session logs</p>
        </div>
      </div>
    );
  }

  const logs = data?.logs || [];

  return (
    <div className="bg-slate-900/60 rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-200">Session Timeline</h3>
        </div>
        <div className="flex items-center gap-1 text-xs text-slate-400">
          <Zap className="w-3 h-3" />
          <span>{logs.length} events</span>
          {lastUpdated && (
            <span className="ml-2 text-slate-500">
              {new Intl.DateTimeFormat('en-US', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: true,
                timeZone: 'UTC',
              }).format(new Date(lastUpdated))}
            </span>
          )}
        </div>
      </div>

      <div className="space-y-3 max-h-96 overflow-y-auto">
        {logs.length === 0 ? (
          <div className="text-center text-slate-400 py-8">
            <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No session events yet</p>
          </div>
        ) : (
          logs.map((log, index) => (
            <div key={`${log.timestamp}-${index}`} className="flex items-start gap-3 group">
              {/* Timeline dot */}
              <div className={`w-3 h-3 rounded-full border-2 mt-1 flex-shrink-0 ${getLevelColor(log.level)}`}>
                <div className="w-full h-full rounded-full opacity-60">
                  {getLevelIcon(log.level)}
                </div>
              </div>

              {/* Log content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-slate-300 uppercase tracking-wider">
                    {log.component
                      .replace(/_/g, ' ')
                      .replace(/\b\w/g, (c) => c.toUpperCase())}
                  </span>
                  <span className="text-xs text-slate-500">
                    {formatTimestamp(log.timestamp)}
                  </span>
                </div>
                <p className="text-sm text-slate-200 leading-relaxed">
                  {log.message}
                </p>
                {log.metadata && Object.keys(log.metadata).length > 0 && (
                  <div className="mt-2 text-xs text-slate-400">
                    <details className="group/details">
                      <summary className="cursor-pointer hover:text-slate-300 transition-colors">
                        Metadata
                      </summary>
                      <pre className="mt-1 p-2 bg-slate-800/50 rounded text-xs overflow-x-auto">
                        {JSON.stringify(log.metadata, null, 2)}
                      </pre>
                    </details>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
