import { useState } from 'react';
import { ShieldAlert, ShieldCheck, Pause, Play, Clock, AlertTriangle } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS} from '../config/constants';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

interface HaltStatus {
  can_trade: boolean;
  halted: boolean;
  reason: string | null;
  halt_time: number | null;
  history_count: number;
  history: Array<{
    action: string;
    reason?: string;
    previous_reason?: string;
    resumed_by?: string;
    timestamp: number;
  }>;
  limits: {
    max_daily_loss_pct: number;
    max_drawdown_pct: number;
    circuit_breaker_halt_threshold: number;
  };
}

interface StalenessInfo {
  total_feeds: number;
  stale_count: number;
  paused_instruments: Record<string, string>;
}

export default function TradingHaltBanner() {
  const [loading, setLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: haltStatus, error: haltError, refetch: refetchHalt } = useApiData<HaltStatus>(
    API_ENDPOINTS.RISK_HALT_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  const { data: staleness } = useApiData<StalenessInfo>(
    API_ENDPOINTS.RISK_STALENESS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );

  if (haltError && !haltStatus) {
    return <ErrorBar label="Halt status unavailable" error={haltError} onRetry={refetchHalt} />;
  }

  const handleHalt = async () => {
    if (!confirm('Are you sure you want to HALT all trading?')) return;
    setLoading(true);
    setActionError(null);
    try {
      const haltRes = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_HALT}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason: 'operator_manual_halt' }),
      });
      if (!haltRes.ok) throw new Error(`HTTP ${haltRes.status}`);
      refetchHalt();
    } catch (err) {
      setActionError(`Halt failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  };

  const handleResume = async () => {
    if (!confirm('Are you sure you want to RESUME trading?')) return;
    setLoading(true);
    setActionError(null);
    try {
      const resumeRes = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_RESUME}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ operator: 'operator' }),
      });
      if (!resumeRes.ok) throw new Error(`HTTP ${resumeRes.status}`);
      refetchHalt();
    } catch (err) {
      setActionError(`Resume failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  };

  const isHalted = haltStatus?.halted ?? false;
  const staleCount = staleness?.stale_count ?? 0;
  const pausedInstruments = Object.keys(staleness?.paused_instruments ?? {});

  return (
    <div className="space-y-1">
      {actionError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="truncate">{actionError}</span>
          <button type="button" onClick={() => setActionError(null)} className="ml-auto shrink-0 text-slate-400 hover:text-white" aria-label="Dismiss error">&times;</button>
        </div>
      )}
      {/* Main halt banner */}
      <div
        className={`flex items-center justify-between px-4 py-2 rounded-lg border ${
          isHalted
            ? 'bg-red-900/30 border-red-700 text-red-200'
            : 'bg-emerald-900/20 border-emerald-700/50 text-emerald-300'
        }`}
      >
        <div className="flex items-center gap-3">
          {isHalted ? (
            <ShieldAlert className="w-5 h-5 text-red-400 animate-pulse" />
          ) : (
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          )}
          <div>
            <span className="font-semibold text-sm">
              {isHalted ? 'TRADING HALTED' : 'Trading Active'}
            </span>
            {isHalted && haltStatus?.reason && (
              <span className="ml-2 text-xs text-red-300/80">
                — {haltStatus.reason}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Staleness badge */}
          {staleCount > 0 && (
            <span className="flex items-center gap-1 text-xs bg-amber-900/40 text-amber-300 px-2 py-0.5 rounded">
              <AlertTriangle className="w-3 h-3" />
              {staleCount} stale feed{staleCount > 1 ? 's' : ''}
            </span>
          )}

          {/* History toggle */}
          {(haltStatus?.history_count ?? 0) > 0 && (
            <button type="button"
              onClick={() => setShowHistory(!showHistory)}
              className="text-xs text-slate-400 hover:text-slate-200 px-2 py-0.5 rounded border border-slate-600 hover:border-slate-400"
            >
              <Clock className="w-3 h-3 inline mr-1" />
              {haltStatus?.history_count} events
            </button>
          )}

          {/* Halt / Resume button */}
          {isHalted ? (
            <button type="button"
              onClick={handleResume}
              disabled={loading}
              className="flex items-center gap-1 text-xs font-medium bg-emerald-700 hover:bg-emerald-600 text-white px-3 py-1 rounded disabled:opacity-50"
             title="Resume">
              <Play className="w-3 h-3" />
              Resume
            </button>
          ) : (
            <button type="button"
              onClick={handleHalt}
              disabled={loading}
              className="flex items-center gap-1 text-xs font-medium bg-red-700 hover:bg-red-600 text-white px-3 py-1 rounded disabled:opacity-50"
             title="Halt">
              <Pause className="w-3 h-3" />
              Halt
            </button>
          )}
        </div>
      </div>

      {/* Paused instruments strip */}
      {pausedInstruments.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-1 text-xs text-amber-300/80">
          <span className="text-amber-400 font-medium">Paused:</span>
          {pausedInstruments.map((inst) => (
            <span
              key={inst}
              className="bg-amber-900/30 border border-amber-700/40 px-1.5 py-0.5 rounded"
            >
              {inst}
            </span>
          ))}
        </div>
      )}

      {/* History dropdown */}
      {showHistory && haltStatus?.history && haltStatus.history.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700 rounded-lg p-3 text-xs space-y-1 max-h-40 overflow-y-auto">
          {haltStatus.history
            .slice()
            .reverse()
            .map((entry, i) => (
              <div key={i} className="flex items-center gap-2 text-slate-300">
                <span className="text-slate-500 w-20 shrink-0">
                  {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                </span>
                <span
                  className={
                    entry.action === 'halt'
                      ? 'text-red-400 font-medium'
                      : 'text-emerald-400 font-medium'
                  }
                >
                  {(entry.action ?? '').toUpperCase()}
                </span>
                <span className="text-slate-400 truncate">
                  {entry.reason || entry.previous_reason || ''}
                  {entry.resumed_by ? ` (by ${entry.resumed_by})` : ''}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
