import React from 'react';
import { AgentGovernanceStats } from '../hooks/useDevGovernance';

interface DevAgentRosterProps {
  agentStats: AgentGovernanceStats[];
}

function DevAgentRoster({ agentStats }: DevAgentRosterProps) {
  if (agentStats.length === 0) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 text-center text-gray-500 text-sm">
        No agent governance data yet
      </div>
    );
  }

  const sorted = [...agentStats].sort((a, b) => b.proposals_created - a.proposals_created);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Agent Governance Roster</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {sorted.map(agent => {
          const successRate = agent.proposals_created > 0
            ? ((agent.proposals_executed / agent.proposals_created) * 100).toFixed(0)
            : '0';
          const isHuman = !agent.agent_id.startsWith('agent_') && !agent.agent_id.startsWith('coder_') && !agent.agent_id.startsWith('tester_');

          return (
            <div
              key={agent.agent_id}
              className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-gray-600 transition-colors"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${
                    isHuman ? 'bg-blue-900/50 text-blue-400' : 'bg-purple-900/50 text-purple-400'
                  }`}>
                    {isHuman ? 'H' : 'A'}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-white">{agent.agent_id}</div>
                    <div className="text-xs text-gray-500">{isHuman ? 'Human' : 'Agent'}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-gray-400">Risk Avg</div>
                  <div className={`text-sm font-bold ${
                    agent.avg_risk_score < 0.3 ? 'text-green-400' :
                    agent.avg_risk_score < 0.6 ? 'text-yellow-400' :
                    agent.avg_risk_score < 0.8 ? 'text-orange-400' : 'text-red-400'
                  }`}>
                    {(agent.avg_risk_score * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <StatCell label="Created" value={agent.proposals_created} color="text-white" />
                <StatCell label="Approved" value={agent.proposals_approved} color="text-green-400" />
                <StatCell label="Rejected" value={agent.proposals_rejected} color="text-red-400" />
                <StatCell label="Executed" value={agent.proposals_executed} color="text-emerald-400" />
                <StatCell label="Reverted" value={agent.proposals_rolled_back} color="text-orange-400" />
                <StatCell label="Reviews" value={agent.reviews_given} color="text-blue-400" />
              </div>

              {/* Success bar */}
              <div className="mt-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-400">Execution Rate</span>
                  <span className="text-gray-300">{successRate}%</span>
                </div>
                <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-500 rounded-full transition-all"
                    style={{ width: `${successRate}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-gray-900/50 rounded px-2 py-1">
      <div className={`text-sm font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

const MemoizedDevAgentRoster = React.memo(DevAgentRoster);
MemoizedDevAgentRoster.displayName = 'DevAgentRoster';
export default MemoizedDevAgentRoster;
