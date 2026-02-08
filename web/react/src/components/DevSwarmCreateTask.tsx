import { useState } from 'react';
import { CreateTaskRequest } from '../hooks/useDevSwarm';

interface DevSwarmCreateTaskProps {
  onSubmit: (task: CreateTaskRequest) => void;
  onCancel: () => void;
}

export default function DevSwarmCreateTask({ onSubmit, onCancel }: DevSwarmCreateTaskProps) {
  const [description, setDescription] = useState('');
  const [targetFiles, setTargetFiles] = useState('');
  const [successCriteria, setSuccessCriteria] = useState('');
  const [priority, setPriority] = useState(1);
  const [estimatedEffort, setEstimatedEffort] = useState<'small' | 'medium' | 'large'>('medium');
  const [timeoutSeconds, setTimeoutSeconds] = useState(1800);
  const [maxCostUsd, setMaxCostUsd] = useState(5.0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    const task: CreateTaskRequest = {
      description,
      target_files: targetFiles.split('\n').map(f => f.trim()).filter(f => f.length > 0),
      success_criteria: successCriteria,
      priority,
      estimated_effort: estimatedEffort,
      timeout_seconds: timeoutSeconds,
      max_cost_usd: maxCostUsd,
    };

    onSubmit(task);
  };

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
      <h2 className="text-xl font-semibold text-white mb-4">Create New Task</h2>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Description */}
        <div>
          <label htmlFor="task-description" className="block text-sm font-medium text-slate-400 mb-2">
            Description *
          </label>
          <textarea
            id="task-description"
            name="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe the task in detail..."
            required
            minLength={10}
            maxLength={2000}
            rows={3}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <div className="text-xs text-slate-500 mt-1">
            {description.length} / 2000 characters
          </div>
        </div>

        {/* Target Files */}
        <div>
          <label htmlFor="target-files" className="block text-sm font-medium text-slate-400 mb-2">
            Target Files * (one per line)
          </label>
          <textarea
            id="target-files"
            name="targetFiles"
            value={targetFiles}
            onChange={(e) => setTargetFiles(e.target.value)}
            placeholder="core/dev_swarm.py&#10;web/api/dev_swarm_routes.py"
            required
            rows={4}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
          />
        </div>

        {/* Success Criteria */}
        <div>
          <label htmlFor="success-criteria" className="block text-sm font-medium text-slate-400 mb-2">
            Success Criteria *
          </label>
          <textarea
            id="success-criteria"
            name="successCriteria"
            value={successCriteria}
            onChange={(e) => setSuccessCriteria(e.target.value)}
            placeholder="All tests pass, code coverage > 80%, linters pass"
            required
            minLength={10}
            maxLength={1000}
            rows={2}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* Priority and Effort */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="task-priority" className="block text-sm font-medium text-slate-400 mb-2">
              Priority
            </label>
            <select
              id="task-priority"
              name="priority"
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
              title="Task priority level"
            >
              <option value={1}>P1 - Critical</option>
              <option value={2}>P2 - High</option>
              <option value={3}>P3 - Medium</option>
              <option value={4}>P4 - Low</option>
              <option value={5}>P5 - Nice to have</option>
            </select>
          </div>

          <div>
            <label htmlFor="estimated-effort" className="block text-sm font-medium text-slate-400 mb-2">
              Estimated Effort
            </label>
            <select
              id="estimated-effort"
              name="estimatedEffort"
              value={estimatedEffort}
              onChange={(e) => setEstimatedEffort(e.target.value as 'small' | 'medium' | 'large')}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
              title="Estimated effort size"
            >
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
          </div>
        </div>

        {/* Timeout and Budget */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="timeout-seconds" className="block text-sm font-medium text-slate-400 mb-2">
              Timeout (seconds)
            </label>
            <input
              id="timeout-seconds"
              name="timeoutSeconds"
              type="number"
              value={timeoutSeconds}
              onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
              min={60}
              max={7200}
              step={60}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            />
            <div className="text-xs text-slate-500 mt-1">
              {Math.round(timeoutSeconds / 60)} minutes max
            </div>
          </div>

          <div>
            <label htmlFor="max-cost-usd" className="block text-sm font-medium text-slate-400 mb-2">
              Max Cost (USD)
            </label>
            <input
              id="max-cost-usd"
              name="maxCostUsd"
              type="number"
              value={maxCostUsd}
              onChange={(e) => setMaxCostUsd(Number(e.target.value))}
              min={0.1}
              max={50}
              step={0.5}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            />
            <div className="text-xs text-slate-500 mt-1">
              LLM API cost limit
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-4">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
          >
            Create Task
          </button>
        </div>
      </form>
    </div>
  );
}
