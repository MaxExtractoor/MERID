import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface RouterStatus {
  running: boolean;
  tick_count: number;
  error_count: number;
  last_tick_ts: number | null;
  uptime_seconds: number | null;
  error?: string;
}

interface RouterMetrics {
  counters: Record<string, number>;
  gauges: Record<string, number>;
}

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];

function tagCountsForSymbol(counters: Record<string, number>, symbol: string): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [key, val] of Object.entries(counters)) {
    // key format: "merid_crypto_selected_markets_total,{symbol},{tag}"
    const parts = key.split(',');
    if (parts.length === 3 && parts[0] === 'merid_crypto_selected_markets_total' && parts[1] === symbol) {
      result[parts[2]] = val;
    }
  }
  return result;
}

export default function CryptoAlertStatusPanel() {
  const { data: status } = useApiData<RouterStatus>(
    API_ENDPOINTS.CRYPTO_ALERTS_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.CRYPTO_ALERTS }
  );
  const { data: metrics } = useApiData<RouterMetrics>(
    API_ENDPOINTS.CRYPTO_ALERTS_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.CRYPTO_ALERTS }
  );

  const counters = metrics?.counters ?? {};

  const riskTotal = Object.entries(counters)
    .filter(([k]) => k.startsWith('merid_risk_alerts_total'))
    .reduce((s, [, v]) => s + v, 0);

  const selTotal = Object.entries(counters)
    .filter(([k]) => k.startsWith('merid_crypto_selected_markets_total'))
    .reduce((s, [, v]) => s + v, 0);

  const isRunning = status?.running ?? false;

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">Crypto Alert Router</h3>
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
          isRunning ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
        }`}>
          {isRunning ? 'RUNNING' : 'STOPPED'}
        </span>
      </div>

      {status?.error && !isRunning && (
        <p className="text-xs text-red-400 mb-2 truncate">{status.error}</p>
      )}

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="text-center">
          <p className="text-lg font-bold text-slate-100">{status?.tick_count ?? '—'}</p>
          <p className="text-xs text-slate-500">Ticks</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-amber-400">{riskTotal || '—'}</p>
          <p className="text-xs text-slate-500">Risk Alerts</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-sky-400">{selTotal || '—'}</p>
          <p className="text-xs text-slate-500">Mkt Selected</p>
        </div>
      </div>

      <div className="space-y-1">
        {SYMBOLS.map(sym => {
          const tags = tagCountsForSymbol(counters, sym);
          const total = Object.values(tags).reduce((s, v) => s + v, 0);
          if (total === 0) return null;
          return (
            <div key={sym} className="flex items-center gap-2 text-xs">
              <span className="w-10 text-slate-400 font-mono">{sym}</span>
              <div className="flex flex-wrap gap-1">
                {Object.entries(tags).map(([tag, cnt]) => (
                  <span key={tag} className="px-1.5 py-0.5 bg-slate-700 text-slate-300 rounded text-[10px]">
                    {tag} ×{cnt}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {status?.last_tick_ts && (
        <p className="text-[10px] text-slate-600 mt-2">
          Last tick {new Date(status.last_tick_ts * 1000).toLocaleTimeString()}
          {status.error_count ? ` · ${status.error_count} err` : ''}
        </p>
      )}
    </div>
  );
}
