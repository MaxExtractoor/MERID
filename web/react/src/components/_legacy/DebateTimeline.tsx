import React from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface DebateEntry {
  debate_id: string;
  symbol: string;
  status: string;
  proposer_stance: string;
  challenger_stance: string;
  arbiter_verdict: string | null;
  debate_lift: number | null;
  timestamp: string;
}

function DebateTimeline() {
  const { data, loading, error, refetch } = useApiData<{ debates: DebateEntry[]; count: number }>(
    API_ENDPOINTS.PREDICTION_DEBATES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const debates = data?.debates ?? [];

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Icon name={"messageSquare" as any} size={16} className="w-4 h-4 text-blue-400" />
          Debate Timeline
          {data?.count != null && <span className="text-xs text-slate-500">({data.count})</span>}
        </h2>
        <button type="button" onClick={() => refetch()} title="Refresh debate timeline"
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors">
          <Icon name="refresh" size={14} className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-xs text-red-400 mb-2">
          <Icon name="alert" size={12} className="w-3 h-3" /> {error.message ?? 'Failed to load debates'}
        </div>
      )}

      {debates.length === 0 && !loading && (
        <div className="text-center py-6 text-slate-500 text-xs">No debates yet</div>
      )}

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {debates.map(d => (
          <div key={d.debate_id} className="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-800/40 hover:bg-slate-800/70 transition-colors">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-xs font-mono text-slate-300 truncate">{d.symbol}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                d.status === 'resolved' ? 'bg-emerald-500/20 text-emerald-300'
                : d.status === 'active' ? 'bg-blue-500/20 text-blue-300'
                : 'bg-slate-600/30 text-slate-400'
              }`}>{d.status}</span>
            </div>
            <div className="flex items-center gap-3 text-[10px] text-slate-500">
              {d.debate_lift != null && (
                <span className="flex items-center gap-0.5">
                  <Icon name="trophy" size={12} className="w-3 h-3 text-amber-400" />
                  {(d.debate_lift * 100).toFixed(1)}%
                </span>
              )}
              <span>{new Date(d.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

DebateTimeline.displayName = 'DebateTimeline';
export default React.memo(DebateTimeline);
