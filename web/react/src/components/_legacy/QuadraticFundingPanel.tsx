import { useState } from 'react';
import { Coins, FileText, Users, DollarSign, RefreshCw, CheckCircle, Clock, XCircle } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

// ── Types ───────────────────────────────────────────────────────

interface FundingProposal {
  proposal_id: string;
  title: string;
  description: string;
  requested_budget_usd: number;
  target_swarm: string;
  status: string;
  tags: string[];
  owner: string;
  created_at: string;
}

interface RoundSummary {
  round_id: string;
  status: string;
  matching_pool_usd: number;
  total_direct_usd: number;
  total_matched_usd: number;
  total_allocated_usd: number;
  proposal_breakdown: { proposal_id: string; title: string; direct: number; matched: number; total: number }[];
  governance_notes: string[];
  created_at: string;
}

// ── Helpers ─────────────────────────────────────────────────────

function statusBadge(status: string) {
  const map: Record<string, string> = {
    draft: 'bg-slate-500/20 text-slate-400',
    active: 'bg-green-500/20 text-green-400',
    approved: 'bg-blue-500/20 text-blue-400',
    rejected: 'bg-red-500/20 text-red-400',
    funded: 'bg-emerald-500/20 text-emerald-400',
    open: 'bg-green-500/20 text-green-400',
    finalized: 'bg-purple-500/20 text-purple-400',
    cancelled: 'bg-red-500/20 text-red-400',
  };
  return map[status] ?? 'bg-slate-500/20 text-slate-400';
}

function statusIcon(status: string) {
  if (['active', 'approved', 'funded', 'finalized'].includes(status)) return CheckCircle;
  if (['rejected', 'cancelled'].includes(status)) return XCircle;
  return Clock;
}

function usd(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ── Component ───────────────────────────────────────────────────

export default function QuadraticFundingPanel() {
  const { data: proposals, loading: propLoading, error: propError } = useApiData<FundingProposal[]>(
    API_ENDPOINTS.QUADRATIC_FUNDING_PROPOSALS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.INFREQUENT, initialData: [] },
  );
  const { data: rounds } = useApiData<RoundSummary[]>(
    API_ENDPOINTS.QUADRATIC_FUNDING_ROUNDS + '?limit=10',
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.INFREQUENT, initialData: [] },
  );
  const [tab, setTab] = useState<'proposals' | 'rounds'>('proposals');
  const loading = propLoading && (!proposals || proposals.length === 0);
  const error = propError?.message ?? null;

  if (loading) {
    return (
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading quadratic funding data...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-red-300">
        <p className="font-semibold">Error</p>
        <p className="text-sm mt-1 text-red-400">{error}</p>
      </div>
    );
  }

  const pp = proposals ?? [];
  const rr = rounds ?? [];
  const totalMatching = rr.reduce((s, r) => s + r.matching_pool_usd, 0);
  const totalAllocated = rr.reduce((s, r) => s + r.total_allocated_usd, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Coins className="w-5 h-5 text-amber-400" />
          <h3 className="text-lg font-bold text-white">Quadratic Funding</h3>
        </div>
        <button type="button" onClick={() => { /* polling handles refresh */ }} className="p-1.5 rounded hover:bg-slate-700 text-slate-400 hover:text-white" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Proposals', value: pp.length.toString(), icon: FileText, color: 'text-blue-400' },
          { label: 'Rounds', value: rr.length.toString(), icon: Coins, color: 'text-amber-400' },
          { label: 'Total Matching', value: usd(totalMatching), icon: DollarSign, color: 'text-green-400' },
          { label: 'Total Allocated', value: usd(totalAllocated), icon: Users, color: 'text-purple-400' },
        ].map(s => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className={`w-3.5 h-3.5 ${s.color}`} />
                <span className="text-[10px] text-slate-400 uppercase tracking-wider">{s.label}</span>
              </div>
              <p className="text-lg font-bold text-white">{s.value}</p>
            </div>
          );
        })}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-800/50 rounded-lg p-1">
        {(['proposals', 'rounds'] as const).map(t => (
          <button type="button"
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${
              tab === t ? 'bg-slate-700 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t} ({t === 'proposals' ? pp.length : rr.length})
          </button>
        ))}
      </div>

      {/* Proposals tab */}
      {tab === 'proposals' && (
        <div className="space-y-2">
          {pp.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-6">No proposals submitted yet</p>
          ) : (
            pp.map(p => {
              const Icon = statusIcon(p.status);
              return (
                <div key={p.proposal_id} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-4 hover:border-blue-500/30 transition-colors">
                  <div className="flex items-start justify-between mb-1">
                    <h4 className="text-sm font-semibold text-white">{p.title}</h4>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium flex items-center gap-1 ${statusBadge(p.status)}`}>
                      <Icon className="w-3 h-3" /> {p.status}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mb-2 line-clamp-2">{p.description}</p>
                  <div className="flex items-center gap-3 text-[10px] text-slate-500">
                    <span>Budget: <span className="text-white font-medium">{usd(p.requested_budget_usd)}</span></span>
                    <span>Swarm: <span className="text-white">{p.target_swarm}</span></span>
                    {p.owner && <span>Owner: <span className="text-white">{p.owner}</span></span>}
                    {p.tags?.length > 0 && p.tags.map(t => (
                      <span key={t} className="bg-slate-700/50 text-slate-300 px-1.5 py-0.5 rounded">{t}</span>
                    ))}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Rounds tab */}
      {tab === 'rounds' && (
        <div className="space-y-3">
          {rr.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-6">No funding rounds yet</p>
          ) : (
            rr.map(r => (
              <div key={r.round_id} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white font-mono">{r.round_id.slice(0, 12)}...</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${statusBadge(r.status)}`}>
                      {r.status}
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-500">{new Date(r.created_at).toLocaleDateString()}</span>
                </div>
                <div className="grid grid-cols-3 gap-3 mb-3">
                  <div>
                    <p className="text-[10px] text-slate-400">Matching Pool</p>
                    <p className="text-sm font-semibold text-amber-400">{usd(r.matching_pool_usd)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-400">Direct Contributions</p>
                    <p className="text-sm font-semibold text-blue-400">{usd(r.total_direct_usd)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-400">Total Allocated</p>
                    <p className="text-sm font-semibold text-green-400">{usd(r.total_allocated_usd)}</p>
                  </div>
                </div>
                {r.proposal_breakdown.length > 0 && (
                  <div className="border-t border-slate-700/50 pt-2 space-y-1">
                    {r.proposal_breakdown.map(pb => (
                      <div key={pb.proposal_id} className="flex items-center justify-between text-xs">
                        <span className="text-slate-300 truncate max-w-[200px]">{pb.title || pb.proposal_id}</span>
                        <div className="flex gap-3">
                          <span className="text-slate-500">Direct: {usd(pb.direct)}</span>
                          <span className="text-amber-400">Matched: {usd(pb.matched)}</span>
                          <span className="text-white font-medium">{usd(pb.total)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {r.governance_notes.length > 0 && (
                  <div className="border-t border-slate-700/50 pt-2 mt-2">
                    <p className="text-[10px] text-slate-500 mb-1">Governance Notes</p>
                    {r.governance_notes.map((note, i) => (
                      <p key={i} className="text-xs text-slate-400 italic">- {note}</p>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
