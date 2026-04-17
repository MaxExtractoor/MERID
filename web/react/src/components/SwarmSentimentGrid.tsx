/**
 * 5×4 swarm × mood grid (BTC–DOGE × 15m–weekly) from GET /api/v1/kalshi/swarm/grid
 *
 * When agents have not yet published live proposals, the API returns an explicit
 * neutral placeholder (50% prob, 0% confidence, usable=false). We surface that as
 * "no swarm signal" and show mood bus fields when present — not as fake 50¢ quotes.
 */
import { useMemo } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';

type Cell = {
  asset: string;
  timeframe: string;
  swarm_consensus_prob: number;
  swarm_confidence: number;
  swarm_usable: boolean;
  swarm_direction: string;
  swarm_status?: string;
  mood_social?: number | null;
  mood_fg?: number | null;
};

type GridResponse = { cells: Cell[]; ws_timeframe_labels?: Record<string, string> };

const ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'] as const;
const TFS = ['15m', '1h', 'daily', 'weekly'] as const;

function cellColor(c: Cell): string {
  if (!c.swarm_usable) return 'bg-slate-800/60 text-slate-500';
  if (c.swarm_confidence >= 0.6) return 'bg-emerald-500/15 text-emerald-200';
  if (c.swarm_confidence >= 0.35) return 'bg-amber-500/10 text-amber-200';
  return 'bg-slate-700/40 text-slate-300';
}

/** True when we should show live consensus numbers (not neutral placeholder). */
function hasLiveSwarm(c: Cell): boolean {
  return c.swarm_usable === true && c.swarm_confidence > 0.001;
}

function formatFg(v: number | null | undefined): string | null {
  if (v == null || Number.isNaN(v)) return null;
  const scaled = v >= 0 && v <= 1 ? v * 100 : v;
  return `${Math.round(scaled)}`;
}

function formatSocial(v: number | null | undefined): string | null {
  if (v == null || Number.isNaN(v)) return null;
  const pct = Math.abs(v) <= 1 ? v * 100 : v;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`;
}

function MoodBits({ c }: { c: Cell }) {
  const fg = formatFg(c.mood_fg);
  const soc = formatSocial(c.mood_social);
  if (!fg && !soc) return null;
  return (
    <div className="text-[8px] text-slate-400 mt-0.5">
      {[fg && `FG ${fg}`, soc && `X ${soc}`].filter(Boolean).join(' · ')}
    </div>
  );
}

function CellBody({ c }: { c: Cell }) {
  if (!hasLiveSwarm(c)) {
    const status = (c.swarm_status ?? '').toString().toLowerCase();
    const hint = status === 'stale' || status === '' ? 'idle' : status;
    return (
      <div className="leading-tight">
        <div className="text-slate-500 font-mono">—</div>
        <div className="text-[8px] text-slate-500 uppercase tracking-wider" title="No live agent proposals for this cell">
          {hint}
        </div>
        <MoodBits c={c} />
      </div>
    );
  }
  const dir = c.swarm_direction.toLowerCase();
  const dirLabel = dir === 'yes' ? 'YES' : dir === 'no' ? 'NO' : dir === 'neutral' ? 'HOLD' : dir.toUpperCase();
  return (
    <div className="leading-tight">
      <div className="font-mono">P={(c.swarm_consensus_prob * 100).toFixed(0)}%</div>
      <div className="opacity-80">c={(c.swarm_confidence * 100).toFixed(0)}%</div>
      <div className="text-[9px] uppercase">{dirLabel}</div>
      <MoodBits c={c} />
    </div>
  );
}

export default function SwarmSentimentGrid() {
  const { data, loading, error, refetch, backendOffline } = useApiData<GridResponse>(
    API_ENDPOINTS.KALSHI_SWARM_GRID,
    { pollingInterval: 60_000 },
  );

  const matrix = useMemo(() => {
    const m: Record<string, Record<string, Cell | undefined>> = {};
    for (const a of ASSETS) {
      m[a] = {};
      for (const t of TFS) m[a][t] = undefined;
    }
    for (const c of data?.cells ?? []) {
      if (!m[c.asset]) m[c.asset] = {};
      m[c.asset][c.timeframe] = c;
    }
    return m;
  }, [data]);

  const errMsg = error?.message ?? null;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Swarm × mood (5×4)</h3>
          <p className="text-[9px] text-slate-500 mt-0.5">
            Live swarm rows require agent proposals; mood (FG / X) shows when the mood bus has data.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          className="text-[10px] px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 shrink-0"
        >
          Refresh
        </button>
      </div>
      {loading && !data && (
        <div className="text-[10px] text-slate-500">Loading grid…</div>
      )}
      {errMsg && (
        <div className="text-[10px] text-red-400">
          {errMsg}
          {backendOffline && (
            <span className="block text-slate-500 mt-0.5">
              Is the API running at the configured base URL? Check VITE_API_BASE and CORS.
            </span>
          )}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[10px] border-collapse">
          <thead>
            <tr>
              <th className="text-left p-1 text-slate-500 font-normal">Asset</th>
              {TFS.map((tf) => (
                <th key={tf} className="p-1 text-slate-500 font-normal text-center">
                  {tf}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ASSETS.map((a) => (
              <tr key={a}>
                <td className="p-1 font-mono font-semibold text-slate-200">{a}</td>
                {TFS.map((tf) => {
                  const c = matrix[a]?.[tf];
                  return (
                    <td key={`${a}-${tf}`} className={`p-1 text-center rounded ${c ? cellColor(c) : 'bg-slate-900'}`}>
                      {c ? <CellBody c={c} /> : '—'}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
