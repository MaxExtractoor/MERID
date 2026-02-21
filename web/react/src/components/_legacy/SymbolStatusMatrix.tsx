import { useState, useMemo } from 'react';
import { Activity, Filter, ArrowUpDown, Lightbulb } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { HelpPopover } from './HelpPopover';

interface SymbolRow {
  symbol: string;
  feed_state: string;
  age_seconds: number | null;
  threshold_seconds: number | null;
  group: string;
  critical: boolean;
  venue: string;
  venue_state: string;
  tradeable: string;
  reasons: string[];
  hint: string | null;
}

interface SymbolStatusData {
  symbols: SymbolRow[];
  gate_state: string;
  summary: {
    total: number;
    allowed: number;
    reduce_only: number;
    blocked: number;
    with_issues: number;
  };
  timestamp: number;
}

type SortKey = 'symbol' | 'feed_state' | 'venue_state' | 'tradeable';

const FEED_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  fresh:   { bg: 'bg-green-500/15', text: 'text-green-400', label: 'Fresh' },
  warning: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Aging' },
  stale:   { bg: 'bg-red-500/15',   text: 'text-red-400',   label: 'Stale' },
  no_data: { bg: 'bg-slate-700/50', text: 'text-slate-500', label: 'No Data' },
};

const VENUE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  up:       { bg: 'bg-green-500/15', text: 'text-green-400', label: 'Up' },
  degraded: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Degraded' },
  down:     { bg: 'bg-red-500/15',   text: 'text-red-400',   label: 'Down' },
  unknown:  { bg: 'bg-slate-700/50', text: 'text-slate-500', label: 'Unknown' },
};

const TRADE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  allowed:     { bg: 'bg-green-500/15', text: 'text-green-400', label: 'Allowed' },
  reduce_only: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Reduce Only' },
  blocked:     { bg: 'bg-red-500/15',   text: 'text-red-400',   label: 'Blocked' },
};

const SORT_ORDER: Record<string, Record<string, number>> = {
  feed_state:  { stale: 3, warning: 2, no_data: 1, fresh: 0 },
  venue_state: { down: 3, degraded: 2, unknown: 1, up: 0 },
  tradeable:   { blocked: 3, reduce_only: 2, allowed: 0 },
};

function StatusCell({ value, styles }: { value: string; styles: Record<string, { bg: string; text: string; label: string }> }) {
  const s = styles[value] ?? { bg: 'bg-slate-700/50', text: 'text-slate-500', label: value };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold ${s.bg} ${s.text}`}>
      {s.label}
    </span>
  );
}

export default function SymbolStatusMatrix() {
  const [sortKey, setSortKey] = useState<SortKey>('tradeable');
  const [sortDesc, setSortDesc] = useState(true);
  const [issuesOnly, setIssuesOnly] = useState(false);

  const { data, loading } = useApiData<SymbolStatusData>(
    '/api/v1/system/symbol-status',
    { pollingInterval: 10000 },
  );

  const rows = useMemo(() => {
    if (!data?.symbols) return [];
    let items = [...data.symbols];

    if (issuesOnly) {
      items = items.filter(r => r.tradeable !== 'allowed' || r.feed_state !== 'fresh' || r.venue_state !== 'up');
    }

    items.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'symbol') {
        cmp = a.symbol.localeCompare(b.symbol);
      } else {
        const order = SORT_ORDER[sortKey] ?? {};
        cmp = (order[a[sortKey]] ?? 0) - (order[b[sortKey]] ?? 0);
      }
      return sortDesc ? -cmp : cmp;
    });

    return items;
  }, [data?.symbols, sortKey, sortDesc, issuesOnly]);

  const summary = data?.summary;

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc(!sortDesc);
    else { setSortKey(key); setSortDesc(true); }
  };

  const SortHeader = ({ label, field, className = '' }: { label: string; field: SortKey; className?: string }) => (
    <th
      className={`px-3 py-2 text-left text-[10px] font-medium text-slate-400 cursor-pointer select-none hover:text-slate-200 whitespace-nowrap uppercase tracking-wide ${className}`}
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown className={`w-2.5 h-2.5 ${sortKey === field ? 'opacity-100' : 'opacity-30'}`} />
      </span>
    </th>
  );

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">Symbol Status</h3>
          <HelpPopover title="Symbol Status Matrix">
            <p>Shows per-symbol trading readiness by combining price feed freshness, venue health, and execution gate state.</p>
            <p className="mt-1 font-medium text-slate-200">Columns:</p>
            <ul className="list-disc list-inside mt-1 space-y-0.5 text-slate-400">
              <li><b>Feed</b> — Fresh / Aging / Stale based on staleness thresholds.</li>
              <li><b>Venue</b> — Up / Degraded / Down from circuit breaker state.</li>
              <li><b>Tradeable</b> — Allowed / Reduce Only / Blocked combining all factors.</li>
            </ul>
          </HelpPopover>
        </div>
        <div className="flex items-center gap-3">
          {summary && (
            <div className="flex items-center gap-2 text-[10px]">
              <span className="text-green-400">{summary.allowed} ok</span>
              {summary.reduce_only > 0 && <span className="text-amber-400">{summary.reduce_only} limited</span>}
              {summary.blocked > 0 && <span className="text-red-400">{summary.blocked} blocked</span>}
            </div>
          )}
          <button
            type="button"
            onClick={() => setIssuesOnly(!issuesOnly)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
              issuesOnly ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-500 hover:text-slate-300'
            }`}
          >
            <Filter className="w-2.5 h-2.5" />
            Issues only
          </button>
        </div>
      </div>

      {/* Table */}
      {loading && !data ? (
        <div className="text-center text-slate-600 py-6 text-xs">Loading symbol status...</div>
      ) : rows.length === 0 ? (
        <div className="text-center text-slate-600 py-6 text-xs">
          {issuesOnly ? 'No symbols with issues' : 'No symbols tracked'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700/50">
                <SortHeader label="Symbol" field="symbol" />
                <th className="px-3 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wide">Group</th>
                <SortHeader label="Feed" field="feed_state" />
                <th className="px-3 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wide">Age</th>
                <th className="px-3 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wide">Venue</th>
                <SortHeader label="Venue State" field="venue_state" />
                <SortHeader label="Tradeable" field="tradeable" />
                <th className="px-3 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wide">Info</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {rows.map(row => (
                <tr key={row.symbol} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-3 py-1.5 font-mono text-slate-200">
                    {row.symbol}
                    {row.critical && <span className="ml-1 text-[9px] text-red-400/60">★</span>}
                  </td>
                  <td className="px-3 py-1.5 text-slate-500 capitalize">{row.group}</td>
                  <td className="px-3 py-1.5"><StatusCell value={row.feed_state} styles={FEED_STYLES} /></td>
                  <td className="px-3 py-1.5 font-mono text-slate-500">
                    {row.age_seconds != null ? `${row.age_seconds.toFixed(0)}s` : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-slate-500 capitalize">{row.venue}</td>
                  <td className="px-3 py-1.5"><StatusCell value={row.venue_state} styles={VENUE_STYLES} /></td>
                  <td className="px-3 py-1.5"><StatusCell value={row.tradeable} styles={TRADE_STYLES} /></td>
                  <td className="px-3 py-1.5">
                    {row.reasons.length > 0 && (
                      <span className="text-slate-500 truncate block max-w-[160px]" title={row.reasons.join('; ')}>
                        {row.reasons[0]}
                      </span>
                    )}
                    {row.hint && (
                      <span className="flex items-center gap-0.5 text-[9px] text-blue-400/60 italic mt-0.5" title={row.hint}>
                        <Lightbulb className="w-2 h-2 flex-shrink-0" />
                        <span className="truncate max-w-[140px]">{row.hint}</span>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
