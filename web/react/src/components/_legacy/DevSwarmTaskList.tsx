import { useState } from 'react';
import { DevTask } from '../hooks/useDevSwarm';

interface DevSwarmTaskListProps {
  tasks: DevTask[];
  onRefresh: () => void;
}

export default function DevSwarmTaskList({ tasks, onRefresh }: DevSwarmTaskListProps) {
  const [selectedTask, setSelectedTask] = useState<DevTask | null>(null);
  const [filter, setFilter] = useState<string>('all');

  const filteredTasks = tasks.filter(task => {
    if (filter === 'all') return true;
    return task.status === filter;
  });

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-green-400 bg-green-900/20 border-green-500';
      case 'running': return 'text-blue-400 bg-blue-900/20 border-blue-500';
      case 'failed': return 'text-red-400 bg-red-900/20 border-red-500';
      case 'timeout': return 'text-orange-400 bg-orange-900/20 border-orange-500';
      case 'cancelled': return 'text-gray-400 bg-gray-900/20 border-gray-500';
      case 'pending': return 'text-yellow-400 bg-yellow-900/20 border-yellow-500';
      default: return 'text-slate-400 bg-slate-900/20 border-slate-500';
    }
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return 'N/A';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleString();
  };

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800">
      <div className="p-6 border-b border-slate-800">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">Tasks</h2>
          <div className="flex items-center gap-4">
            {/* Filter */}
            <select aria-label="Tasks"
              id="devswarm-task-filter"
              name="taskFilter"
              title="Filter tasks by status"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-3 py-1 text-sm text-white"
            >
              <option value="all">All Tasks</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="pending">Pending</option>
            </select>
            
            <button type="button"
              onClick={onRefresh}
              className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-white rounded text-sm transition-colors"
             title="Refresh">
              ↻ Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-slate-800/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Status</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Description</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Files</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Priority</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Duration</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Cost</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Created</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-slate-400 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filteredTasks.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-6 py-8 text-center text-slate-500">
                  No tasks found
                </td>
              </tr>
            ) : (
              filteredTasks.map(task => (
                <tr 
                  key={task.task_id}
                  className="hover:bg-slate-800/30 cursor-pointer transition-colors"
                  onClick={() => setSelectedTask(task)}
                >
                  <td className="px-6 py-4">
                    <span className={`px-2 py-1 rounded text-xs font-medium border ${getStatusColor(task.status)}`}>
                      {task.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-white max-w-md truncate">
                      {task.description}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-slate-400">
                      {task.target_files.length} file{task.target_files.length !== 1 ? 's' : ''}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-slate-300">P{task.priority}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-slate-400">
                      {formatDuration(task.duration_seconds)}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-slate-400">
                      ${task.cost_usd.toFixed(2)}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-xs text-slate-500">
                      {formatTimestamp(task.created_at)}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <button type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedTask(task);
                      }}
                      className="text-blue-400 hover:text-blue-300 text-sm"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Task Detail Modal */}
      {selectedTask && (
        <div 
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center"
          onClick={() => setSelectedTask(null)}
         role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setSelectedTask(null))(); } }}>
          <div 
            className="bg-slate-900 rounded-xl border border-slate-700 max-w-4xl w-full mx-4 max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
           role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ((e) => e.stopPropagation())(); } }}>
            <div className="p-6 border-b border-slate-800">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-xl font-semibold text-white mb-2">Task Details</h3>
                  <span className={`px-2 py-1 rounded text-xs font-medium border ${getStatusColor(selectedTask.status)}`}>
                    {selectedTask.status}
                  </span>
                </div>
                <button type="button"
                  onClick={() => setSelectedTask(null)}
                  className="text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="p-6 space-y-6">
              <div>
                <h4 className="text-sm font-medium text-slate-400 mb-2">Description</h4>
                <p className="text-white">{selectedTask.description}</p>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400 mb-2">Target Files</h4>
                <div className="space-y-1">
                  {selectedTask.target_files.map((file, i) => (
                    <div key={i} className="text-sm text-slate-300 font-mono bg-slate-800/50 px-3 py-1 rounded">
                      {file}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400 mb-2">Success Criteria</h4>
                <p className="text-slate-300">{selectedTask.success_criteria}</p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h4 className="text-sm font-medium text-slate-400 mb-1">Priority</h4>
                  <p className="text-white">P{selectedTask.priority}</p>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-slate-400 mb-1">Effort</h4>
                  <p className="text-white capitalize">{selectedTask.estimated_effort}</p>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-slate-400 mb-1">Duration</h4>
                  <p className="text-white">{formatDuration(selectedTask.duration_seconds)}</p>
                </div>
                <div>
                  <h4 className="text-sm font-medium text-slate-400 mb-1">Cost</h4>
                  <p className="text-white">${selectedTask.cost_usd.toFixed(4)}</p>
                </div>
              </div>

              {selectedTask.error && (
                <div className="bg-red-900/20 border border-red-500 rounded p-4">
                  <h4 className="text-sm font-medium text-red-400 mb-2">Error</h4>
                  <p className="text-red-300 text-sm">{selectedTask.error}</p>
                </div>
              )}

              {selectedTask.result && (
                <div>
                  <h4 className="text-sm font-medium text-slate-400 mb-2">Result</h4>
                  <pre className="text-xs text-slate-300 bg-slate-800/50 p-4 rounded overflow-x-auto">
                    {JSON.stringify(selectedTask.result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
