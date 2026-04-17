/**
 * Compact tagged vs untagged realized PnL / fees / hit-rate by asset (swarm audit).
 */
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

type AssetRow = {
  trade_count_tagged: number;
  trade_count_untagged: number;
  realized_pnl_tagged: number;
  realized_pnl_untagged: number;
  fees_tagged: number;
  fees_untagged: number;
  hit_rate_tagged: number;
  hit_rate_untagged: number;
};

type PnlPayload = {
  by_asset: Record<string, AssetRow>;
  totals: AssetRow & { net_pnl_tagged?: number; net_pnl_untagged?: number };
};

const ASSETS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'] as const;

export default function SentimentPnLStrip() {
  const slow = { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW };
  const res = useApiData<PnlPayload>(API_ENDPOINTS.KALSHI_SENTIMENT_PNL, slow);
  const d = res.data;
  if (!d?.by_asset) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs text-slate-500">
        Sentiment PnL — loading…
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 overflow-x-auto">
      <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-300 uppercase tracking-wide">Sentiment PnL</span>
        <span className="text-[10px] text-slate-500">tagged = decision_trace_id</span>
      </div>
      <table className="w-full text-[11px] text-slate-300">
        <thead>
          <tr className="text-slate-500 border-b border-slate-800/80">
            <th className="text-left py-1.5 pl-3 font-medium">Asset</th>
            <th className="text-right font-medium">Trades T/U</th>
            <th className="text-right font-medium">Hit% T/U</th>
            <th className="text-right font-medium pr-3">PnL T/U</th>
          </tr>
        </thead>
        <tbody>
          {ASSETS.map((a) => {
            const row = d.by_asset[a];
            if (!row) {
              return (
                <tr key={a} className="border-b border-slate-800/40">
                  <td className="py-1 pl-3 text-slate-400">{a}</td>
                  <td colSpan={3} className="text-slate-600">—</td>
                </tr>
              );
            }
            return (
              <tr key={a} className="border-b border-slate-800/40 hover:bg-slate-900/40">
                <td className="py-1 pl-3 font-mono text-slate-200">{a}</td>
                <td className="text-right tabular-nums">
                  {row.trade_count_tagged} / {row.trade_count_untagged}
                </td>
                <td className="text-right tabular-nums">
                  {(row.hit_rate_tagged * 100).toFixed(0)}% / {(row.hit_rate_untagged * 100).toFixed(0)}%
                </td>
                <td className="text-right pr-3 tabular-nums">
                  <span className={row.realized_pnl_tagged >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {row.realized_pnl_tagged.toFixed(2)}
                  </span>
                  {' / '}
                  <span className={row.realized_pnl_untagged >= 0 ? 'text-emerald-400/80' : 'text-rose-400/80'}>
                    {row.realized_pnl_untagged.toFixed(2)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
