import { useState } from 'react';
import { DevProposal, SubmitApprovalRequest } from '../hooks/useDevGovernance';
import { PROPOSAL_STATUS } from '../config/constants';

interface DevProposalDetailProps {
  proposal: DevProposal;
  onClose: () => void;
  onApproval: (proposalId: string, req: SubmitApprovalRequest) => Promise<unknown>;
  onStatusChange: (proposalId: string, status: string) => Promise<unknown>;
  onDebateRound?: (proposalId: string, proposerArg: string, challengerArg: string) => Promise<unknown>;
}

const RISK_COLORS: Record<string, string> = {
  low: 'text-green-400 bg-green-900/30 border-green-700',
  medium: 'text-yellow-400 bg-yellow-900/30 border-yellow-700',
  high: 'text-orange-400 bg-orange-900/30 border-orange-700',
  critical: 'text-red-400 bg-red-900/30 border-red-700',
};

const STATUS_COLORS: Record<string, string> = {
  draft: 'text-gray-300 bg-gray-700',
  in_review: 'text-blue-300 bg-blue-900/40',
  approved: 'text-green-300 bg-green-900/40',
  rejected: 'text-red-300 bg-red-900/40',
  scheduled: 'text-purple-300 bg-purple-900/40',
  executing: 'text-yellow-300 bg-yellow-900/40',
  executed: 'text-emerald-300 bg-emerald-900/40',
  rolled_back: 'text-orange-300 bg-orange-900/40',
};

export default function DevProposalDetail({
  proposal,
  onClose,
  onApproval,
  onStatusChange,
  onDebateRound,
}: DevProposalDetailProps) {
  const [activeTab, setActiveTab] = useState<'summary' | 'approvals' | 'debates' | 'metrics' | 'audit'>('summary');
  const [reviewerId, setReviewerId] = useState('human');
  const [justification, setJustification] = useState('');
  const [debateProposer, setDebateProposer] = useState('');
  const [debateChallenger, setDebateChallenger] = useState('');

  const formatTime = (ts: number | null) => {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString();
  };

  const approveCount = proposal.approvals.filter(a => a.action === 'approve').length;
  const rejectCount = proposal.approvals.filter(a => a.action === 'reject').length;
  const meetsApprovalThreshold = proposal.meets_approval_threshold ?? approveCount >= 1;

  const handleApproval = async (action: string) => {
    await onApproval(proposal.id, {
      reviewer_id: reviewerId,
      reviewer_role: 'human_reviewer',
      action,
      justification,
    });
    setJustification('');
  };

  const handleDebate = async () => {
    if (onDebateRound && debateProposer && debateChallenger) {
      await onDebateRound(proposal.id, debateProposer, debateChallenger);
      setDebateProposer('');
      setDebateChallenger('');
    }
  };

  const tabs = [
    { key: 'summary', label: 'Summary' },
    { key: 'approvals', label: `Approvals (${proposal.approvals.length})` },
    { key: 'debates', label: `Debates (${proposal.debate_rounds.length})` },
    { key: 'metrics', label: `Metrics (${proposal.metrics.length})` },
  ] as const;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`text-xs px-2 py-0.5 rounded font-semibold border ${RISK_COLORS[proposal.risk_tier] || ''}`}>
                {proposal.risk_tier.toUpperCase()}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[proposal.status] || 'bg-gray-700 text-gray-300'}`}>
                {proposal.status.replace('_', ' ')}
              </span>
              <span className="text-xs text-gray-500 font-mono">{proposal.id}</span>
            </div>
            <h2 className="text-lg font-semibold text-white truncate">{proposal.title}</h2>
            <div className="flex items-center gap-3 text-xs text-gray-400 mt-1">
              <span>by {proposal.proposer_id}</span>
              <span>owner: {proposal.owner_id}</span>
              <span>created: {formatTime(proposal.created_at)}</span>
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-white text-xl ml-4" title="Close">&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-700 px-4">
          {tabs.map(tab => (
            <button type="button"
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Summary Tab */}
          {activeTab === 'summary' && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <InfoField label="Kind" value={proposal.kind} />
                <InfoField label="Risk Score" value={`${(proposal.risk_score * 100).toFixed(0)}%`} />
                <InfoField label="Rollout Strategy" value={proposal.rollout_strategy} />
                <InfoField label="Consensus Score" value={`${(proposal.consensus_score * 100).toFixed(0)}%`} />
                <InfoField label="Target" value={proposal.target || '—'} />
                <InfoField label="Branch" value={proposal.branch_ref || '—'} />
              </div>
              {proposal.description && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 uppercase mb-1">Description</h4>
                  <p className="text-sm text-gray-300 whitespace-pre-wrap">{proposal.description}</p>
                </div>
              )}
              {proposal.diff_summary && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 uppercase mb-1">Diff Summary</h4>
                  <pre className="text-xs text-gray-300 bg-gray-800 rounded p-3 overflow-x-auto">{proposal.diff_summary}</pre>
                </div>
              )}
              {proposal.affected_subsystems.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 uppercase mb-1">Affected Subsystems</h4>
                  <div className="flex flex-wrap gap-1">
                    {proposal.affected_subsystems.map(s => (
                      <span key={s} className="bg-gray-700 text-gray-300 text-xs px-2 py-0.5 rounded">{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {proposal.tags.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 uppercase mb-1">Tags</h4>
                  <div className="flex flex-wrap gap-1">
                    {proposal.tags.map(t => (
                      <span key={t} className="bg-blue-900/30 text-blue-400 text-xs px-2 py-0.5 rounded">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Quick Actions */}
              <div className="border-t border-gray-700 pt-4">
                <h4 className="text-xs font-semibold text-gray-400 uppercase mb-2">Actions</h4>
                <div className="flex flex-wrap gap-2">
                  {proposal.status === PROPOSAL_STATUS.DRAFT && (
                    <button type="button"
                      onClick={() => onStatusChange(proposal.id, 'in_review')}
                      className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-500"
                    >
                      Submit for Review
                    </button>
                  )}
                  {proposal.status === PROPOSAL_STATUS.APPROVED && (
                    <button type="button"
                      onClick={() => onStatusChange(proposal.id, 'scheduled')}
                      className="px-3 py-1.5 bg-purple-600 text-white text-xs rounded hover:bg-purple-500"
                    >
                      Schedule
                    </button>
                  )}
                  {proposal.status === PROPOSAL_STATUS.SCHEDULED && (
                    <button type="button"
                      onClick={() => onStatusChange(proposal.id, 'executing')}
                      className="px-3 py-1.5 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-500"
                    >
                      Execute
                    </button>
                  )}
                  {proposal.status === PROPOSAL_STATUS.EXECUTING && (
                    <button type="button"
                      onClick={() => onStatusChange(proposal.id, 'executed')}
                      className="px-3 py-1.5 bg-emerald-600 text-white text-xs rounded hover:bg-emerald-500"
                    >
                      Mark Executed
                    </button>
                  )}
                  {(proposal.status === PROPOSAL_STATUS.EXECUTED || proposal.status === PROPOSAL_STATUS.EXECUTING) && (
                    <button type="button"
                      onClick={() => onStatusChange(proposal.id, 'rolled_back')}
                      className="px-3 py-1.5 bg-red-600 text-white text-xs rounded hover:bg-red-500"
                    >
                      Rollback
                    </button>
                  )}
                </div>
              </div>
            </>
          )}

          {/* Approvals Tab */}
          {activeTab === 'approvals' && (
            <>
              <div className="flex items-center gap-4 mb-4">
                <div className="bg-gray-800 rounded-lg px-4 py-2 text-center">
                  <div className="text-lg font-bold text-green-400">{approveCount}</div>
                  <div className="text-xs text-gray-400">Approved</div>
                </div>
                <div className="bg-gray-800 rounded-lg px-4 py-2 text-center">
                  <div className="text-lg font-bold text-red-400">{rejectCount}</div>
                  <div className="text-xs text-gray-400">Rejected</div>
                </div>
                <div className="bg-gray-800 rounded-lg px-4 py-2 text-center">
                  <div className={`text-lg font-bold ${meetsApprovalThreshold ? 'text-green-400' : 'text-yellow-400'}`}>
                    {meetsApprovalThreshold ? 'Yes' : 'No'}
                  </div>
                  <div className="text-xs text-gray-400">Threshold Met</div>
                </div>
              </div>

              {/* Existing approvals */}
              <div className="space-y-2">
                {proposal.approvals.map(a => (
                  <div key={a.id} className="bg-gray-800 rounded-lg p-3 flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold ${a.action === 'approve' ? 'text-green-400' : a.action === 'reject' ? 'text-red-400' : 'text-yellow-400'}`}>
                          {a.action.toUpperCase()}
                        </span>
                        <span className="text-xs text-gray-400">by {a.reviewer_id}</span>
                        <span className="text-xs text-gray-500">({a.reviewer_role})</span>
                      </div>
                      {a.justification && <p className="text-xs text-gray-300 mt-1">{a.justification}</p>}
                    </div>
                    <span className="text-xs text-gray-500">{formatTime(a.timestamp)}</span>
                  </div>
                ))}
              </div>

              {/* Submit approval form */}
              {(proposal.status === PROPOSAL_STATUS.IN_REVIEW || proposal.status === PROPOSAL_STATUS.DRAFT) && (
                <div className="border-t border-gray-700 pt-4 space-y-3">
                  <h4 className="text-xs font-semibold text-gray-400 uppercase">Submit Review</h4>
                  <input type="text" value={reviewerId} onChange={e => setReviewerId(e.target.value)} aria-label="Reviewer ID" placeholder="Reviewer ID" className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-white" />
                  <textarea aria-label="Text input"
                    value={justification}
                    onChange={e => setJustification(e.target.value)}
                    placeholder="Justification (optional)"
                    rows={2}
                    className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-white"
                  />
                  <div className="flex gap-2">
                    <button type="button"
                      onClick={() => handleApproval('approve')}
                      className="px-4 py-1.5 bg-green-600 text-white text-xs rounded hover:bg-green-500"
                    >
                      Approve
                    </button>
                    <button type="button"
                      onClick={() => handleApproval('reject')}
                      className="px-4 py-1.5 bg-red-600 text-white text-xs rounded hover:bg-red-500"
                    >
                      Reject
                    </button>
                    <button type="button"
                      onClick={() => handleApproval('request_changes')}
                      className="px-4 py-1.5 bg-yellow-600 text-white text-xs rounded hover:bg-yellow-500"
                    >
                      Request Changes
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Debates Tab */}
          {activeTab === 'debates' && (
            <>
              <div className="space-y-3">
                {proposal.debate_rounds.map(dr => (
                  <div key={dr.round_number} className="bg-gray-800 rounded-lg p-3">
                    <div className="text-xs text-gray-400 mb-2 font-semibold">Round {dr.round_number}</div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="text-xs text-green-400 font-medium mb-1">Proposer</div>
                        <p className="text-xs text-gray-300">{dr.proposer_argument}</p>
                      </div>
                      <div>
                        <div className="text-xs text-red-400 font-medium mb-1">Challenger</div>
                        <p className="text-xs text-gray-300">{dr.challenger_argument}</p>
                      </div>
                    </div>
                    {dr.evidence_refs.length > 0 && (
                      <div className="mt-2 text-xs text-gray-500">
                        Evidence: {dr.evidence_refs.join(', ')}
                      </div>
                    )}
                    <div className="text-xs text-gray-600 mt-1">{formatTime(dr.timestamp)}</div>
                  </div>
                ))}
                {proposal.debate_rounds.length === 0 && (
                  <div className="text-center text-gray-500 py-6 text-sm">No debate rounds yet</div>
                )}
              </div>

              {/* Add debate round */}
              {onDebateRound && (
                <div className="border-t border-gray-700 pt-4 space-y-3">
                  <h4 className="text-xs font-semibold text-gray-400 uppercase">Add Debate Round</h4>
                  <textarea aria-label="Text input"
                    value={debateProposer}
                    onChange={e => setDebateProposer(e.target.value)}
                    placeholder="Proposer argument..."
                    rows={2}
                    className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-white"
                  />
                  <textarea aria-label="Text input"
                    value={debateChallenger}
                    onChange={e => setDebateChallenger(e.target.value)}
                    placeholder="Challenger argument..."
                    rows={2}
                    className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-white"
                  />
                  <button type="button"
                    onClick={handleDebate}
                    disabled={!debateProposer || !debateChallenger}
                    className="px-4 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-500 disabled:opacity-50"
                   title="Submit Round">
                    Submit Round
                  </button>
                </div>
              )}
            </>
          )}

          {/* Metrics Tab */}
          {activeTab === 'metrics' && (
            <>
              {proposal.metrics.length > 0 ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-400 border-b border-gray-700">
                      <th className="pb-2 pr-4">Metric</th>
                      <th className="pb-2 pr-4">Baseline</th>
                      <th className="pb-2 pr-4">Expected</th>
                      <th className="pb-2 pr-4">Actual</th>
                      <th className="pb-2">Improved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposal.metrics.map((m, i) => (
                      <tr key={i} className="border-b border-gray-800">
                        <td className="py-2 pr-4 text-white">{m.metric_name}</td>
                        <td className="py-2 pr-4 text-gray-300">{m.baseline_value.toFixed(4)} {m.unit}</td>
                        <td className="py-2 pr-4 text-gray-300">{m.expected_value.toFixed(4)} {m.unit}</td>
                        <td className="py-2 pr-4 text-gray-300">{m.actual_value !== null ? `${m.actual_value.toFixed(4)} ${m.unit}` : '—'}</td>
                        <td className="py-2">
                          {m.improved === true && <span className="text-green-400 text-xs">Yes</span>}
                          {m.improved === false && <span className="text-red-400 text-xs">No</span>}
                          {m.improved === null && <span className="text-gray-500 text-xs">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="text-center text-gray-500 py-6 text-sm">No metrics attached</div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function InfoField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-400 font-medium">{label}</div>
      <div className="text-sm text-white">{value}</div>
    </div>
  );
}
