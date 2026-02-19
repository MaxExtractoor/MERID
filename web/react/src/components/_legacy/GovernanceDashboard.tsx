import React from 'react';
import { GovernanceMetrics } from '../hooks/useDevGovernance';

interface GovernanceDashboardProps {
  metrics: GovernanceMetrics | null;
  loading: boolean;
  onRefresh: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-600',
  in_review: 'bg-blue-600',
  approved: 'bg-green-600',
  rejected: 'bg-red-600',
  scheduled: 'bg-purple-600',
  executing: 'bg-yellow-600',
  executed: 'bg-emerald-600',
  rolled_back: 'bg-orange-600',
};

const RISK_COLORS: Record<string, string> = {
  low: 'bg-green-600',
  medium: 'bg-yellow-600',
  high: 'bg-orange-600',
  critical: 'bg-red-600',
};

function GovernanceDashboard({ metrics, loading, onRefresh }: GovernanceDashboardProps) {
  if (!metrics) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 text-center text-gray-500 text-sm">
        {loading ? 'Loading governance metrics...' : 'No governance data available'}
      </div>
    );
  }

  const tiles = [
    { label: 'Total Proposals', value: metrics.total_proposals, color: 'text-white' },
    { label: 'This Week', value: metrics.proposals_this_week, color: 'text-blue-400' },
    { label: 'Approval Rate', value: `${(metrics.approval_rate * 100).toFixed(0)}%`, color: metrics.approval_rate >= 0.7 ? 'text-green-400' : 'text-yellow-400' },
    { label: 'Regression Rate', value: `${(metrics.regression_rate * 100).toFixed(1)}%`, color: metrics.regression_rate <= 0.05 ? 'text-green-400' : 'text-red-400' },
    { label: 'Avg Decision Time', value: formatDuration(metrics.avg_time_to_decision_s), color: 'text-gray-300' },
    { label: 'Guardrail Blocks', value: metrics.guardrail_blocks, color: metrics.guardrail_blocks > 0 ? 'text-orange-400' : 'text-green-400' },
    { label: 'Agent-Initiated', value: `${(metrics.agent_initiated_ratio * 100).toFixed(0)}%`, color: 'text-purple-400' },
    { label: 'Human-Initiated', value: `${(metrics.human_initiated_ratio * 100).toFixed(0)}%`, color: 'text-blue-400' },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Governance Overview</h3>
        <button type="button"
          onClick={onRefresh}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-gray-800 hover:bg-gray-700"
         title="Refresh">
          Refresh
        </button>
      </div>

      {/* Metric Tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {tiles.map(tile => (
          <div key={tile.label} className="bg-gray-800 border border-gray-700 rounded-lg p-3">
            <div className={`text-xl font-bold ${tile.color}`}>{tile.value}</div>
            <div className="text-xs text-gray-400 mt-0.5">{tile.label}</div>
          </div>
        ))}
      </div>

      {/* Distribution Charts */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Status Distribution */}
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h4 className="text-xs font-semibold text-gray-400 uppercase mb-3">By Status</h4>
          <div className="space-y-2">
            {Object.entries(metrics.proposals_by_status).map(([status, count]) => (
              <DistributionBar
                key={status}
                label={status.replace('_', ' ')}
                count={count}
                total={metrics.total_proposals}
                color={STATUS_COLORS[status] || 'bg-gray-600'}
              />
            ))}
          </div>
        </div>

        {/* Risk Distribution */}
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h4 className="text-xs font-semibold text-gray-400 uppercase mb-3">By Risk Tier</h4>
          <div className="space-y-2">
            {Object.entries(metrics.proposals_by_risk).map(([risk, count]) => (
              <DistributionBar
                key={risk}
                label={risk}
                count={count}
                total={metrics.total_proposals}
                color={RISK_COLORS[risk] || 'bg-gray-600'}
              />
            ))}
          </div>
        </div>

        {/* Kind Distribution */}
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <h4 className="text-xs font-semibold text-gray-400 uppercase mb-3">By Kind</h4>
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {Object.entries(metrics.proposals_by_kind)
              .sort(([, a], [, b]) => b - a)
              .map(([kind, count]) => (
                <DistributionBar
                  key={kind}
                  label={kind.replace('_change', '')}
                  count={count}
                  total={metrics.total_proposals}
                  color="bg-blue-600"
                />
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function DistributionBar({
  label,
  count,
  total,
  color,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-0.5">
        <span className="text-gray-300 capitalize">{label}</span>
        <span className="text-gray-400">{count}</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(0)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

const MemoizedGovernanceDashboard = React.memo(GovernanceDashboard);
MemoizedGovernanceDashboard.displayName = 'GovernanceDashboard';
export default MemoizedGovernanceDashboard;
