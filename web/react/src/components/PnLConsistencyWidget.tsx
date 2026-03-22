import { CheckCircle, AlertTriangle, DollarSign } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { DataAgeBadge } from './DataAgeBadge';
import { HelpPopover } from './HelpPopover';
import { useFeatureFlags } from '../config/featureFlags';

interface PnLSource {
  realized_pnl?: number;
  unrealized_pnl?: number;
  total?: number;
  daily_pnl?: number;
  equity?: number;
  pnl?: number;
  error?: string;
}

interface PnLConsistencyData {
  sources: Record<string, PnLSource>;
  consistent: boolean;
  max_divergence_usd: number;
  threshold_usd: number;
  timestamp: number;
}

export default function PnLConsistencyWidget() {
  const { kalshiOnly } = useFeatureFlags();
  
  const { data, loading, lastUpdated } = useApiData<PnLConsistencyData>(
    kalshiOnly ? '' : API_ENDPOINTS.SYSTEM_PNL_CONSISTENCY,
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  if (loading && !data) return null;
  if (!data) return null;

  const { sources, consistent, max_divergence_usd, threshold_usd } = data;
  const paper = sources.paper_engine;
  const risk = sources.risk_controller;
  const equity = sources.equity_series;

  // Calculate a dynamic threshold suggestion based on portfolio size
  const portfolioSize = Math.abs(paper?.total ?? risk?.daily_pnl ?? equity?.pnl ?? 0);
  const suggestedThreshold = Math.max(5, portfolioSize * 0.01); // 1% of portfolio or $5 minimum
  const thresholdWarning = threshold_usd < suggestedThreshold;

  return (
    <div className={`rounded-lg border px-3 py-2 flex items-center gap-3 text-xs ${
      consistent
        ? 'border-slate-700/50 bg-slate-800/30'
        : 'border-amber-500/40 bg-amber-500/5'
    }`}>
      {consistent ? (
        <CheckCircle className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
      ) : (
        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0 animate-pulse" />
      )}

      <DollarSign className="w-3 h-3 text-slate-500 flex-shrink-0" />

      <HelpPopover title="PnL Consistency">
        <p>Compares PnL across three independent sources to detect accounting drift:</p>
        <ul className="list-disc list-inside mt-1 space-y-0.5 text-slate-400">
          <li><b>Paper Engine</b> — sum of all portfolio PnL from the paper trading system.</li>
          <li><b>Risk Controller</b> — daily PnL tracked by the risk module.</li>
          <li><b>Equity Series</b> — latest PnL from the equity time-series buffer.</li>
        </ul>
        <p className="mt-1">Current threshold: ${threshold_usd.toFixed(2)}. Suggested: ${suggestedThreshold.toFixed(2)} (1% of portfolio or $5 min).</p>
        <p className="mt-1">If sources diverge by more than the threshold, a warning is shown. Large divergence may indicate a bug in position tracking or a missed trade event.</p>
      </HelpPopover>

      <div className="flex items-center gap-4 overflow-x-auto">
        {/* Paper engine */}
        {paper && !paper.error && (
          <span className="whitespace-nowrap">
            <span className="text-slate-500">Paper:</span>{' '}
            <span className={`font-mono font-medium ${(paper.total ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${(paper.total ?? 0).toFixed(2)}
            </span>
          </span>
        )}

        {/* Risk daily */}
        {risk && !risk.error && (
          <span className="whitespace-nowrap">
            <span className="text-slate-500">Risk:</span>{' '}
            <span className={`font-mono font-medium ${(risk.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${(risk.daily_pnl ?? 0).toFixed(2)}
            </span>
          </span>
        )}

        {/* Equity series */}
        {equity && !equity.error && typeof equity.pnl === 'number' && (
          <span className="whitespace-nowrap">
            <span className="text-slate-500">Equity:</span>{' '}
            <span className={`font-mono font-medium ${equity.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${equity.pnl.toFixed(2)}
            </span>
          </span>
        )}
      </div>

      {!consistent && (
        <span className="text-amber-400 font-medium whitespace-nowrap">
          Δ${(max_divergence_usd ?? 0).toFixed(2)}
        </span>
      )}
      {thresholdWarning && (
        <span className="text-orange-400 text-[10px] whitespace-nowrap" title={`Threshold ($${threshold_usd}) may be too low for portfolio size. Consider ${suggestedThreshold.toFixed(2)}`}>
          ⚠ thresh
        </span>
      )}
      <DataAgeBadge lastUpdated={lastUpdated} className="ml-auto" />
    </div>
  );
}
