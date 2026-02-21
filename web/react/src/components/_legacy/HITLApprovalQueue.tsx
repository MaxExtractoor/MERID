import { useState } from 'react';
import { DevProposal, SubmitApprovalRequest } from '../hooks/useDevGovernance';

interface HITLApprovalQueueProps {
  pending: DevProposal[];
  loading: boolean;
  onApproval: (proposalId: string, req: SubmitApprovalRequest) => Promise<unknown>;
  onSelect: (proposal: DevProposal) => void;
  onRefresh: () => void;
}

const RISK_BADGE: Record<string, string> = {
  low: 'bg-green-900/40 text-green-400 border-green-700',
  medium: 'bg-yellow-900/40 text-yellow-400 border-yellow-700',
  high: 'bg-orange-900/40 text-orange-400 border-orange-700',
  critical: 'bg-red-900/40 text-red-400 border-red-700',
};

export default function HITLApprovalQueue({
  pending,
  loading,
  onApproval,
  onSelect,
  onRefresh,
}: HITLApprovalQueueProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [justifications, setJustifications] = useState<Record<string, string>>({});

  const sorted = [...pending].sort((a, b) => {
    const riskOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
    return (riskOrder[a.risk_tier] ?? 4) - (riskOrder[b.risk_tier] ?? 4);
  });

  const handleQuickAction = async (proposalId: string, action: string) => {
    await onApproval(proposalId, {
      reviewer_id: 'human',
      reviewer_role: 'human_reviewer',
      action,
      justification: justifications[proposalId] || '',
    });
    setExpandedId(null);
  };

  const criticalCount = pending.filter(p => p.risk_tier === 'critical').length;
  const highCount = pending.filter(p => p.risk_tier === 'high').length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
            HITL Approval Queue
          </h3>
          <span className="bg-blue-900/40 text-blue-400 text-xs px-2 py-0.5 rounded-full font-medium">
            {pending.length} pending
          </span>
          {criticalCount > 0 && (
            <span className="bg-red-900/40 text-red-400 text-xs px-2 py-0.5 rounded-full font-medium animate-pulse">
              {criticalCount} critical
            </span>
          )}
          {highCount > 0 && (
            <span className="bg-orange-900/40 text-orange-400 text-xs px-2 py-0.5 rounded-full font-medium">
              {highCount} high
            </span>
          )}
        </div>
        <button type="button"
          onClick={onRefresh}
          className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded bg-gray-800 hover:bg-gray-700"
         title="Refresh">
          Refresh
        </button>
      </div>

      {loading && pending.length === 0 && (
        <div className="text-center text-gray-500 py-6 text-sm">Loading pending approvals...</div>
      )}

      {!loading && pending.length === 0 && (
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 text-center">
          <div className="text-green-400 text-lg mb-1">All Clear</div>
          <div className="text-gray-500 text-sm">No proposals awaiting approval</div>
        </div>
      )}

      <div className="space-y-2">
        {sorted.map(proposal => {
          const isExpanded = expandedId === proposal.id;
          return (
            <div
              key={proposal.id}
              className={`bg-gray-800 border rounded-lg transition-colors ${
                proposal.risk_tier === 'critical'
                  ? 'border-red-700/60'
                  : proposal.risk_tier === 'high'
                  ? 'border-orange-700/40'
                  : 'border-gray-700'
              }`}
            >
              <div className="p-3 flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1 min-w-0 cursor-pointer" onClick={() => onSelect(proposal)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => onSelect(proposal))(); } }}>
                  <span className={`text-xs px-2 py-0.5 rounded border font-semibold flex-shrink-0 ${RISK_BADGE[proposal.risk_tier] || ''}`}>
                    {proposal.risk_tier.toUpperCase()}
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm text-white truncate">{proposal.title}</div>
                    <div className="text-xs text-gray-500">
                      {proposal.kind.replace('_', ' ')} · by {proposal.proposer_id} · score {(proposal.risk_score * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                  <button type="button"
                    onClick={() => handleQuickAction(proposal.id, 'approve')}
                    className="px-3 py-1 bg-green-700 text-white text-xs rounded hover:bg-green-600"
                    title="Quick approve"
                  >
                    Approve
                  </button>
                  <button type="button"
                    onClick={() => handleQuickAction(proposal.id, 'reject')}
                    className="px-3 py-1 bg-red-700 text-white text-xs rounded hover:bg-red-600"
                    title="Quick reject"
                  >
                    Reject
                  </button>
                  <button type="button"
                    onClick={() => setExpandedId(isExpanded ? null : proposal.id)}
                    className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded hover:bg-gray-600"
                    title="Expand details"
                  >
                    {isExpanded ? '▲' : '▼'}
                  </button>
                </div>
              </div>

              {isExpanded && (
                <div className="px-3 pb-3 border-t border-gray-700 pt-3 space-y-2">
                  {proposal.description && (
                    <p className="text-xs text-gray-300">{proposal.description}</p>
                  )}
                  {proposal.affected_subsystems.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {proposal.affected_subsystems.map(s => (
                        <span key={s} className="bg-gray-700 text-gray-400 text-xs px-1.5 py-0.5 rounded">{s}</span>
                      ))}
                    </div>
                  )}
                  <div>
                    <textarea aria-label="Text input"
                      value={justifications[proposal.id] || ''}
                      onChange={e => setJustifications(prev => ({ ...prev, [proposal.id]: e.target.value }))}
                      placeholder="Justification (optional)..."
                      rows={2}
                      className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-white mt-1"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button type="button"
                      onClick={() => handleQuickAction(proposal.id, 'approve')}
                      className="px-3 py-1.5 bg-green-600 text-white text-xs rounded hover:bg-green-500"
                    >
                      Approve with Justification
                    </button>
                    <button type="button"
                      onClick={() => handleQuickAction(proposal.id, 'reject')}
                      className="px-3 py-1.5 bg-red-600 text-white text-xs rounded hover:bg-red-500"
                    >
                      Reject with Justification
                    </button>
                    <button type="button"
                      onClick={() => handleQuickAction(proposal.id, 'request_changes')}
                      className="px-3 py-1.5 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-500"
                    >
                      Request Changes
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
