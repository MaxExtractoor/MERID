/**
 * AgentsTab - Agent configuration
 * 
 * Agent configuration section of Settings view.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

export function AgentsTab() {
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white">Agent Configuration</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor="max-concurrent-agents" className="block text-sm font-medium text-slate-400 mb-2">Max Concurrent Agents</label>
          <input aria-label="Max Concurrent Agents"
            id="max-concurrent-agents"
            name="maxConcurrentAgents"
            type="number"
            min="1"
            max="20"
            defaultValue="5"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="5"
          />
        </div>

        <div>
          <label htmlFor="agent-timeout" className="block text-sm font-medium text-slate-400 mb-2">Agent Timeout (seconds)</label>
          <input aria-label="Agent Timeout (seconds)"
            id="agent-timeout"
            name="agentTimeout"
            type="number"
            min="10"
            max="300"
            defaultValue="60"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="60"
          />
        </div>

        <div>
          <label htmlFor="min-confidence" className="block text-sm font-medium text-slate-400 mb-2">Min Confidence Threshold</label>
          <input aria-label="Min Confidence Threshold"
            id="min-confidence"
            name="minConfidence"
            type="number"
            min="0"
            max="1"
            step="0.05"
            defaultValue="0.6"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="0.6"
          />
        </div>

        <div>
          <label htmlFor="consensus-threshold" className="block text-sm font-medium text-slate-400 mb-2">Consensus Threshold</label>
          <input aria-label="Consensus Threshold"
            id="consensus-threshold"
            name="consensusThreshold"
            type="number"
            min="0.5"
            max="1"
            step="0.05"
            defaultValue="0.7"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="0.7"
          />
        </div>

        <div>
          <label htmlFor="max-retries" className="block text-sm font-medium text-slate-400 mb-2">Max Retries</label>
          <input aria-label="Max Retries"
            id="max-retries"
            name="maxRetries"
            type="number"
            min="1"
            max="10"
            defaultValue="3"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="3"
          />
        </div>

        <div>
          <label htmlFor="refresh-interval" className="block text-sm font-medium text-slate-400 mb-2">Refresh Interval (seconds)</label>
          <input aria-label="Refresh Interval (seconds)"
            id="refresh-interval"
            name="refreshInterval"
            type="number"
            min="5"
            max="60"
            defaultValue="10"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="10"
          />
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-md font-medium text-white">Agent Features</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* LEGACY REMOVAL: Swarm coordination removed - swarm consensus not used in 15m stack */}
          <label className="flex items-center gap-3">
            <input aria-label="Enable decision explainability"
              id="decision-explainability"
              name="decisionExplainability"
              type="checkbox"
              defaultChecked
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Enable decision explainability</span>
          </label>
          <label className="flex items-center gap-3">
            <input aria-label="Auto-restart failed agents"
              id="auto-restart-agents"
              name="autoRestartAgents"
              type="checkbox"
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Auto-restart failed agents</span>
          </label>
          <label className="flex items-center gap-3">
            <input aria-label="Log all agent decisions"
              id="log-agent-decisions"
              name="logAgentDecisions"
              type="checkbox"
              defaultChecked
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Log all agent decisions</span>
          </label>
        </div>
      </div>
    </div>
  );
}
