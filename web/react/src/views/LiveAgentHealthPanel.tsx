import { useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import DataTableEnhanced from '../components/DataTableEnhanced';
import { useAgentsHealth } from '../hooks/useAgentsHealth';
import { formatTime } from '../utils/formatters';
import { RefreshCw } from 'lucide-react';

/**
 * Live Agent Health Panel
 * 
 * Displays real-time agent health metrics with:
 * - Summary metric cards (total, online, degraded, offline)
 * - Sortable/filterable data table with agent details
 * - Live WebSocket updates for status changes
 */
export function LiveAgentHealthPanel() {
  const { rows, meta, loading, error, lastUpdated } = useAgentsHealth();

  // Define columns using keyof Row pattern
  const columns = useMemo(() => [
    { key: 'name' as const, label: 'Agent', sortable: true },
    { key: 'role' as const, label: 'Role', sortable: true },
    { key: 'status' as const, label: 'Status', sortable: true },
    { key: 'strategy' as const, label: 'Strategy', sortable: true },
    { key: 'cpuPercent' as const, label: 'CPU %', sortable: true },
    { key: 'memoryMb' as const, label: 'Memory', sortable: true },
    { key: 'taskCount' as const, label: 'Tasks', sortable: true },
    { key: 'latencyMs' as const, label: 'Latency', sortable: true },
    { key: 'lastSeen' as const, label: 'Last Seen', sortable: true },
  ], []);

  if (error) {
    return (
      <div className="p-4 bg-red-900/20 border border-red-700 rounded-lg">
        <h3 className="text-red-400 font-medium">Error loading agent health</h3>
        <p className="text-red-300/70 text-sm mt-1">{error.message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Total Agents"
          value={String(meta.total)}
        />
        <MetricCard
          label="Online"
          value={String(meta.online)}
          status="GOOD"
        />
        <MetricCard
          label="Degraded"
          value={String(meta.degraded)}
          status={meta.degraded > 0 ? 'WARNING' : 'GOOD'}
        />
        <MetricCard
          label="Offline"
          value={String(meta.offline)}
          status={meta.offline > 0 ? 'BAD' : 'GOOD'}
        />
      </div>

      {/* Last Updated Indicator */}
      {lastUpdated && (
        <div className="flex items-center gap-2 text-sm text-slate-400 px-1">
          <RefreshCw className="w-3 h-3" />
          <span>Last updated: {formatTime(lastUpdated.toISOString())}</span>
        </div>
      )}

      {/* Agent Data Table */}
      {loading ? (
        <div className="p-8 text-center text-slate-400">Loading agents...</div>
      ) : (
        <DataTableEnhanced
          data={rows}
          columns={columns}
          pageSize={10}
        />
      )}
    </div>
  );
}
