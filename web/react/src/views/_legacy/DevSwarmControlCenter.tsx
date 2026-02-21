import { useState } from 'react';
import {
  useDevProposals,
  useDevApprovals,
  useGovernanceDashboard,
  DevProposal,
} from '../hooks/useDevGovernance';
import DevProposalBoard from '../components/DevProposalBoard';
import DevProposalDetail from '../components/DevProposalDetail';
import DevAgentRoster from '../components/DevAgentRoster';
import GovernanceDashboard from '../components/GovernanceDashboard';
import HITLApprovalQueue from '../components/HITLApprovalQueue';
import CodeQualityPanel from '../components/CodeQualityPanel';
import AssistantPanel from '../components/AssistantPanel';

type Tab = 'overview' | 'proposals' | 'approvals' | 'agents' | 'quality' | 'audit' | 'assistant';

export default function DevSwarmControlCenter() {
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [selectedProposal, setSelectedProposal] = useState<DevProposal | null>(null);

  const {
    proposals,
    fetchProposals,
    updateStatus,
  } = useDevProposals(10000);

  const {
    pending,
    loading: approvalsLoading,
    fetchPending,
    submitApproval,
    addDebateRound,
  } = useDevApprovals();

  const {
    metrics,
    agentStats,
    auditLog,
    loading: dashLoading,
    refreshAll,
  } = useGovernanceDashboard(15000);

  const tabs: { key: Tab; label: string; badge?: number }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'proposals', label: 'Proposals', badge: proposals.length },
    { key: 'approvals', label: 'HITL Queue', badge: pending.length },
    { key: 'agents', label: 'Agent Roster', badge: agentStats.length },
    { key: 'quality', label: 'Code Quality' },
    { key: 'audit', label: 'Audit Log', badge: auditLog.length },
    { key: 'assistant', label: 'Assistant' },
  ];

  const formatTime = (ts: number) => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dev Swarm Control Center</h1>
          <p className="text-sm text-gray-400 mt-1">
            Governance, approvals, debates, and observability for autonomous dev agents
          </p>
        </div>
        <div className="flex items-center gap-2">
          {pending.length > 0 && (
            <span className="bg-red-900/40 text-red-400 text-xs px-3 py-1 rounded-full font-medium animate-pulse">
              {pending.length} pending approval{pending.length !== 1 ? 's' : ''}
            </span>
          )}
          <button type="button"
            onClick={() => {
              fetchProposals();
              fetchPending();
              refreshAll();
            }}
            className="px-3 py-1.5 bg-gray-700 text-gray-300 text-xs rounded hover:bg-gray-600"
          >
            Refresh All
          </button>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex border-b border-gray-700">
        {tabs.map(tab => (
          <button type="button"
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === tab.key
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                activeTab === tab.key ? 'bg-blue-900/50 text-blue-300' : 'bg-gray-700 text-gray-400'
              }`}>
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <GovernanceDashboard
            metrics={metrics}
            loading={dashLoading}
            onRefresh={refreshAll}
          />
          {pending.length > 0 && (
            <HITLApprovalQueue
              pending={pending}
              loading={approvalsLoading}
              onApproval={submitApproval}
              onSelect={setSelectedProposal}
              onRefresh={fetchPending}
            />
          )}
        </div>
      )}

      {activeTab === 'proposals' && (
        <DevProposalBoard
          proposals={proposals}
          onSelect={setSelectedProposal}
          onStatusChange={(id, status) => updateStatus(id, status)}
        />
      )}

      {activeTab === 'approvals' && (
        <HITLApprovalQueue
          pending={pending}
          loading={approvalsLoading}
          onApproval={submitApproval}
          onSelect={setSelectedProposal}
          onRefresh={fetchPending}
        />
      )}

      {activeTab === 'agents' && (
        <DevAgentRoster agentStats={agentStats} />
      )}

      {activeTab === 'quality' && (
        <CodeQualityPanel proposals={proposals} auditLog={auditLog} />
      )}

      {activeTab === 'audit' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Audit Log</h3>
            <span className="text-xs text-gray-500">{auditLog.length} events</span>
          </div>
          {auditLog.length === 0 ? (
            <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 text-center text-gray-500 text-sm">
              No audit events recorded yet
            </div>
          ) : (
            <div className="space-y-1">
              {auditLog.map(evt => (
                <div
                  key={evt.id}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 flex items-center justify-between text-sm"
                >
                  <div className="flex items-center gap-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      evt.event_type.includes('approve') ? 'bg-green-900/30 text-green-400' :
                      evt.event_type.includes('reject') ? 'bg-red-900/30 text-red-400' :
                      evt.event_type.includes('create') ? 'bg-blue-900/30 text-blue-400' :
                      evt.event_type.includes('execute') ? 'bg-emerald-900/30 text-emerald-400' :
                      evt.event_type.includes('rollback') ? 'bg-orange-900/30 text-orange-400' :
                      'bg-gray-700 text-gray-300'
                    }`}>
                      {evt.event_type}
                    </span>
                    <span className="text-gray-300">{evt.actor_id}</span>
                    <span className="text-gray-500">({evt.actor_type})</span>
                    {evt.proposal_id && (
                      <span className="text-xs text-gray-500 font-mono">{evt.proposal_id}</span>
                    )}
                  </div>
                  <span className="text-xs text-gray-500">{formatTime(evt.timestamp)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'assistant' && (
        <AssistantPanel defaultContext="dev" />
      )}

      {/* Proposal Detail Modal */}
      {selectedProposal && (
        <DevProposalDetail
          proposal={selectedProposal}
          onClose={() => setSelectedProposal(null)}
          onApproval={async (proposalId, req) => {
            const result = await submitApproval(proposalId, req);
            if (result) {
              setSelectedProposal(result.proposal);
              fetchProposals();
            }
            return result;
          }}
          onStatusChange={async (proposalId, status) => {
            const result = await updateStatus(proposalId, status);
            if (result) {
              setSelectedProposal(result);
              fetchPending();
            }
            return result;
          }}
          onDebateRound={async (proposalId, proposerArg, challengerArg) => {
            const result = await addDebateRound(proposalId, proposerArg, challengerArg);
            if (result) {
              const updated = proposals.find(p => p.id === proposalId);
              if (updated) setSelectedProposal({ ...updated });
              fetchProposals();
            }
            return result;
          }}
        />
      )}
    </div>
  );
}
