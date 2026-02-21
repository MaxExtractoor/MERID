import { useState, useMemo } from 'react';
import { DevProposal } from '../hooks/useDevGovernance';

interface DevProposalBoardProps {
  proposals: DevProposal[];
  onSelect: (proposal: DevProposal) => void;
  onStatusChange?: (id: string, status: string) => void;
}

const STATUS_COLUMNS = [
  { key: 'draft', label: 'Draft', color: 'bg-gray-700' },
  { key: 'in_review', label: 'In Review', color: 'bg-blue-700' },
  { key: 'approved', label: 'Approved', color: 'bg-green-700' },
  { key: 'scheduled', label: 'Scheduled', color: 'bg-purple-700' },
  { key: 'executing', label: 'Executing', color: 'bg-yellow-700' },
  { key: 'executed', label: 'Executed', color: 'bg-emerald-700' },
  { key: 'rejected', label: 'Rejected', color: 'bg-red-700' },
  { key: 'rolled_back', label: 'Rolled Back', color: 'bg-orange-700' },
];

const RISK_COLORS: Record<string, string> = {
  low: 'text-green-400 bg-green-900/30',
  medium: 'text-yellow-400 bg-yellow-900/30',
  high: 'text-orange-400 bg-orange-900/30',
  critical: 'text-red-400 bg-red-900/30',
};

const KIND_LABELS: Record<string, string> = {
  signal_change: 'Signal',
  model_change: 'Model',
  reward_change: 'Reward',
  calibration_change: 'Calibration',
  betting_change: 'Betting',
  slo_change: 'SLO',
  infra_change: 'Infra',
  ui_change: 'UI',
  docs_change: 'Docs',
  config_change: 'Config',
  strategy_change: 'Strategy',
  opticodds_change: 'OpticOdds',
};

type ViewMode = 'kanban' | 'list';

export default function DevProposalBoard({ proposals, onSelect }: DevProposalBoardProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('kanban');
  const [filterRisk, setFilterRisk] = useState<string>('all');
  const [filterKind, setFilterKind] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'updated' | 'risk' | 'consensus'>('updated');

  const filtered = useMemo(() => {
    let result = [...proposals];
    if (filterRisk !== 'all') result = result.filter(p => p.risk_tier === filterRisk);
    if (filterKind !== 'all') result = result.filter(p => p.kind === filterKind);
    result.sort((a, b) => {
      if (sortBy === 'risk') return b.risk_score - a.risk_score;
      if (sortBy === 'consensus') return b.consensus_score - a.consensus_score;
      return b.updated_at - a.updated_at;
    });
    return result;
  }, [proposals, filterRisk, filterKind, sortBy]);

  const grouped = useMemo(() => {
    const map: Record<string, DevProposal[]> = {};
    STATUS_COLUMNS.forEach(col => { map[col.key] = []; });
    filtered.forEach(p => {
      if (map[p.status]) map[p.status].push(p);
    });
    return map;
  }, [filtered]);

  const formatTime = (ts: number) => {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const ProposalCard = ({ proposal }: { proposal: DevProposal }) => (
    <div
      onClick={() => onSelect(proposal)}
      className="bg-gray-800 border border-gray-700 rounded-lg p-3 cursor-pointer hover:border-blue-500 transition-colors mb-2"
     role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => onSelect(proposal))(); } }}>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${RISK_COLORS[proposal.risk_tier] || 'text-gray-400'}`}>
          {proposal.risk_tier.toUpperCase()}
        </span>
        <span className="text-xs text-gray-500">{proposal.id}</span>
      </div>
      <h4 className="text-sm font-medium text-white truncate mb-1">{proposal.title}</h4>
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <span className="bg-gray-700 px-1.5 py-0.5 rounded">{KIND_LABELS[proposal.kind] || proposal.kind}</span>
        {proposal.approvals.length > 0 && (
          <span className="text-green-400">✓{proposal.approvals.filter(a => a.action === 'approve').length}</span>
        )}
        {proposal.debate_rounds.length > 0 && (
          <span className="text-blue-400">💬{proposal.debate_rounds.length}</span>
        )}
      </div>
      <div className="text-xs text-gray-500 mt-1">{formatTime(proposal.updated_at)}</div>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <button type="button"
            onClick={() => setViewMode('kanban')}
            className={`px-3 py-1.5 text-xs rounded font-medium ${viewMode === 'kanban' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300'}`}
          >
            Kanban
          </button>
          <button type="button"
            onClick={() => setViewMode('list')}
            className={`px-3 py-1.5 text-xs rounded font-medium ${viewMode === 'list' ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300'}`}
          >
            List
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <select
            value={filterRisk}
            onChange={e => setFilterRisk(e.target.value)}
            aria-label="Filter by risk tier"
            className="bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600"
          >
            <option value="all">All Risks</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <select
            value={filterKind}
            onChange={e => setFilterKind(e.target.value)}
            aria-label="Filter by proposal kind"
            className="bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600"
          >
            <option value="all">All Kinds</option>
            {Object.entries(KIND_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select aria-label="All Kinds"
            value={sortBy}
            onChange={e => setSortBy(e.target.value as string)}
            aria-label="Sort proposals by"
            className="bg-gray-700 text-gray-300 rounded px-2 py-1 border border-gray-600"
          >
            <option value="updated">Recent</option>
            <option value="risk">Risk Score</option>
            <option value="consensus">Consensus</option>
          </select>
        </div>
      </div>

      {/* Kanban View */}
      {viewMode === 'kanban' && (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {STATUS_COLUMNS.map(col => (
            <div key={col.key} className="min-w-[220px] max-w-[260px] flex-shrink-0">
              <div className={`${col.color} rounded-t-lg px-3 py-2 flex items-center justify-between`}>
                <span className="text-xs font-semibold text-white uppercase">{col.label}</span>
                <span className="text-xs text-white/70 bg-white/10 px-1.5 rounded">
                  {grouped[col.key]?.length || 0}
                </span>
              </div>
              <div className="bg-gray-900/50 rounded-b-lg p-2 min-h-[120px] space-y-0">
                {(grouped[col.key] || []).map(p => (
                  <ProposalCard key={p.id} proposal={p} />
                ))}
                {(grouped[col.key] || []).length === 0 && (
                  <div className="text-xs text-gray-600 text-center py-8">No proposals</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* List View */}
      {viewMode === 'list' && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-700">
                <th className="pb-2 pr-4">ID</th>
                <th className="pb-2 pr-4">Title</th>
                <th className="pb-2 pr-4">Kind</th>
                <th className="pb-2 pr-4">Risk</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Approvals</th>
                <th className="pb-2 pr-4">Debates</th>
                <th className="pb-2">Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => (
                <tr
                  key={p.id}
                  onClick={() => onSelect(p)}
                  className="border-b border-gray-800 hover:bg-gray-800/50 cursor-pointer"
                >
                  <td className="py-2 pr-4 text-xs text-gray-500 font-mono">{p.id}</td>
                  <td className="py-2 pr-4 text-white truncate max-w-[300px]">{p.title}</td>
                  <td className="py-2 pr-4">
                    <span className="bg-gray-700 text-gray-300 text-xs px-1.5 py-0.5 rounded">
                      {KIND_LABELS[p.kind] || p.kind}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${RISK_COLORS[p.risk_tier] || ''}`}>
                      {p.risk_tier}
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-xs text-gray-300">{p.status}</td>
                  <td className="py-2 pr-4 text-xs">
                    <span className="text-green-400">{p.approvals.filter(a => a.action === 'approve').length}</span>
                    <span className="text-gray-600">/</span>
                    <span className="text-red-400">{p.approvals.filter(a => a.action === 'reject').length}</span>
                  </td>
                  <td className="py-2 pr-4 text-xs text-blue-400">{p.debate_rounds.length}</td>
                  <td className="py-2 text-xs text-gray-500">{formatTime(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center text-gray-500 py-8 text-sm">No proposals match filters</div>
          )}
        </div>
      )}
    </div>
  );
}
