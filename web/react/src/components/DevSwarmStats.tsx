import React from 'react';
import { DevSwarmStats as Stats, DevAgent } from '../hooks/useDevSwarm';

interface DevSwarmStatsProps {
  stats: Stats;
  agents: DevAgent[];
}

function DevSwarmStats({ stats, agents }: DevSwarmStatsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Active Tasks */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-400">Active Tasks</h3>
          <div className={`w-2 h-2 rounded-full ${stats.active_tasks > 0 ? 'bg-blue-500 animate-pulse' : 'bg-slate-600'}`}></div>
        </div>
        <div className="text-3xl font-bold text-white">{stats.active_tasks}</div>
        <div className="text-xs text-slate-500 mt-1">
          Running now
        </div>
      </div>

      {/* Success Rate */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-400">Success Rate</h3>
        </div>
        <div className="text-3xl font-bold text-white">
          {(stats.success_rate * 100).toFixed(1)}%
        </div>
        <div className="text-xs text-slate-500 mt-1">
          {stats.completed} / {stats.total_tasks} completed
        </div>
      </div>

      {/* Average Duration */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-400">Avg Duration</h3>
        </div>
        <div className="text-3xl font-bold text-white">
          {stats.avg_duration_seconds < 60 
            ? `${Math.round(stats.avg_duration_seconds)}s`
            : `${Math.round(stats.avg_duration_seconds / 60)}m`
          }
        </div>
        <div className="text-xs text-slate-500 mt-1">
          Per task
        </div>
      </div>

      {/* Daily Cost */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-400">Daily Cost</h3>
        </div>
        <div className="text-3xl font-bold text-white">
          ${stats.daily_cost_usd.toFixed(2)}
        </div>
        <div className="text-xs text-slate-500 mt-1">
          ${stats.cost_budget_remaining.toFixed(2)} remaining
        </div>
      </div>

      {/* Task Breakdown */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 lg:col-span-2">
        <h3 className="text-sm font-medium text-slate-400 mb-3">Task Status Breakdown</h3>
        <div className="grid grid-cols-4 gap-3">
          <div>
            <div className="text-green-400 text-2xl font-bold">{stats.completed}</div>
            <div className="text-xs text-slate-500">Completed</div>
          </div>
          <div>
            <div className="text-red-400 text-2xl font-bold">{stats.failed}</div>
            <div className="text-xs text-slate-500">Failed</div>
          </div>
          <div>
            <div className="text-orange-400 text-2xl font-bold">{stats.timeout}</div>
            <div className="text-xs text-slate-500">Timeout</div>
          </div>
          <div>
            <div className="text-gray-400 text-2xl font-bold">{stats.cancelled}</div>
            <div className="text-xs text-slate-500">Cancelled</div>
          </div>
        </div>
      </div>

      {/* Registered Agents */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 lg:col-span-2">
        <h3 className="text-sm font-medium text-slate-400 mb-3">Registered Agents</h3>
        {agents.length === 0 ? (
          <div className="text-sm text-slate-500">No agents registered</div>
        ) : (
          <div className="space-y-2">
            {agents.map((agent) => (
              <div key={agent.name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-green-500"></div>
                  <span className="text-white font-medium">{agent.name}</span>
                  <span className="text-slate-500">({agent.role})</span>
                </div>
                <span className="text-slate-400 text-xs">{agent.llm_model}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const MemoizedDevSwarmStats = React.memo(DevSwarmStats);
MemoizedDevSwarmStats.displayName = 'DevSwarmStats';
export default MemoizedDevSwarmStats;
