/**
 * Single-row swarm consensus for the selected catalog market (crypto).
 */
import { useEffect, useState } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';
import { AUTH_TOKEN_KEY } from '../config/constants';

type Props = {
  asset: string | null;
  timeframe: string | null;
};

export default function MarketSwarmConsensusBar({ asset, timeframe }: Props) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!asset || !timeframe) {
      setData(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const url = `${API_BASE_URL}${API_ENDPOINTS.KALSHI_CONSENSUS(asset, timeframe)}`;
        const tok = localStorage.getItem(AUTH_TOKEN_KEY);
        const headers: HeadersInit = { Accept: 'application/json' };
        if (tok) headers.Authorization = `Bearer ${tok}`;
        const r = await fetch(url, { headers, credentials: 'include' });
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        if (!cancelled) setData(j);
      } catch {
        if (!cancelled) setData(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [asset, timeframe]);

  if (!asset || !timeframe) return null;

  if (!data || (data as { error?: string }).error) {
    return (
      <div className="text-[10px] text-slate-500 px-2 py-1 rounded bg-slate-900/50 border border-slate-800">
        Swarm: — (no data)
      </div>
    );
  }

  const usable = Boolean((data as { swarm_usable?: boolean }).swarm_usable);
  const conf = Number((data as { consensus_confidence?: number }).consensus_confidence ?? 0);
  const dir = String((data as { consensus_direction?: string }).consensus_direction ?? '—');
  const prob = Number((data as { consensus_probability?: number }).consensus_probability ?? 0.5);

  return (
    <div className="text-[10px] px-2 py-1.5 rounded bg-slate-900/60 border border-slate-700 space-y-0.5">
      <div className="text-slate-500 uppercase tracking-wide">Swarm consensus</div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-slate-200">
        <span>{dir.toUpperCase()} @ {(prob * 100).toFixed(0)}¢</span>
        <span className="text-slate-400">conf {(conf * 100).toFixed(0)}%</span>
        <span className={usable ? 'text-emerald-400' : 'text-slate-500'}>
          {usable ? 'sizing OK' : 'no conviction'}
        </span>
      </div>
    </div>
  );
}
