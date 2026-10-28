/**
 * Logs View — MERID trading-loop tick log
 *
 * Data: GET /api/v1/loop/tick-log → {ticks: [...], count}
 * (The old /api/v1/logs route does not exist on the backend.)
 */

import { useState } from 'react';
import { FileText, Filter, Search } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { apiUrl } from '../config/apiBase';
import { useApiQuery } from '../hooks/useTanStackQuery';

interface TickEntry {
  tick?: number;
  ts?: number;
  duration_ms?: number;
  actions?: string[];
  plans?: { generated?: number; executed?: number; blocked?: number };
  guard?: { kill_switch?: boolean };
  error?: string;
}

interface TickLogResponse {
  ticks: TickEntry[];
  count: number;
}

interface LogsViewLogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'warning' | 'error';
  component: string;
  message: string;
}

const toLogEntry = (t: TickEntry, idx: number): LogsViewLogEntry => {
  const kill = t.guard?.kill_switch === true;
  const blocked = Number(t.plans?.blocked ?? 0);
  const level: LogsViewLogEntry['level'] = t.error ? 'error' : (kill || blocked > 0 ? 'warning' : 'info');
  const parts = [`tick ${t.tick ?? idx}`];
  if (t.actions && t.actions.length > 0) parts.push(t.actions.join(', '));
  if (t.plans) {
    parts.push(
      `plans gen=${t.plans.generated ?? 0} exec=${t.plans.executed ?? 0} blocked=${blocked}`
    );
  }
  if (t.duration_ms != null) parts.push(`${t.duration_ms}ms`);
  if (kill) parts.push('KILL SWITCH ACTIVE');
  if (t.error) parts.push(`error: ${t.error}`);
  const ts = typeof t.ts === 'number' ? t.ts * (t.ts > 1e12 ? 1 : 1000) : NaN;
  return {
    id: `tick-${t.tick ?? idx}-${t.ts ?? 0}`,
    timestamp: Number.isFinite(ts) ? new Date(ts).toISOString() : new Date().toISOString(),
    level,
    component: 'merid-loop',
    message: parts.join(' · '),
  };
};

const Logs = () => {
  const [levelFilter, setLevelFilter] = useState<'all' | 'info' | 'warning' | 'error'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const { data, isLoading, error } = useApiQuery<TickLogResponse>(
    apiUrl('/api/v1/loop/tick-log?limit=200'),
    { refetchInterval: 10_000, staleTime: 5_000 }
  );

  const logs = (data?.ticks ?? []).map(toLogEntry);

  const filteredLogs = logs.filter((log: LogsViewLogEntry) => {
    if (levelFilter !== 'all' && log.level !== levelFilter) return false;
    if (searchQuery && !log.message.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const getLevelColor = (level: string): 'danger' | 'warning' | 'success' => {
    switch (level) {
      case 'error': return 'danger';
      case 'warning': return 'warning';
      default: return 'success';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileText className="w-8 h-8 text-cyan-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Logs</h1>
            <p className="text-sm text-slate-400">Trading-loop tick log (live)</p>
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Loop Tick Log</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-500" />
              <select
                value={levelFilter}
                onChange={(e) => setLevelFilter(e.target.value as typeof levelFilter)}
                className="bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600"
                aria-label="Filter by log level"
              >
                <option value="all">All Levels</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="error">Error</option>
              </select>
            </div>
            <div className="flex items-center gap-2 flex-1">
              <Search className="w-4 h-4 text-slate-500" />
              <input
                type="text"
                placeholder="Search logs..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600"
                aria-label="Search logs"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="text-center py-8 text-slate-500">Loading tick log...</div>
          ) : error ? (
            <div className="text-center py-8 text-red-400" role="alert">{String(error)}</div>
          ) : logs.length === 0 ? (
            <div className="text-center py-8 text-slate-500">No tick log entries</div>
          ) : filteredLogs.length === 0 ? (
            <div className="text-center py-8 text-slate-500">No entries match the current filters</div>
          ) : (
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-slate-800">
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3">Timestamp</th>
                    <th className="text-left p-3">Level</th>
                    <th className="text-left p-3">Component</th>
                    <th className="text-left p-3">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLogs.map((log: LogsViewLogEntry) => (
                    <tr key={log.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 text-xs text-slate-400 font-mono">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="p-3">
                        <Badge variant={getLevelColor(log.level)}>{log.level.toUpperCase()}</Badge>
                      </td>
                      <td className="p-3 text-xs text-slate-400">{log.component}</td>
                      <td className="p-3 text-white">{log.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Logs;
