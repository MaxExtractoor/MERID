import { useState, useEffect, useCallback } from 'react';
import { ShieldAlert, ShieldCheck, Pause, Play, Clock, AlertTriangle } from 'lucide-react';

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
  const [haltStatus, setHaltStatus] = useState<HaltStatus | null>(null);
  const [staleness, setStaleness] = useState<StalenessInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const [haltRes, staleRes] = await Promise.all([
        fetch('/api/v1/risk/halt-status'),
        fetch('/api/v1/risk/staleness'),
      ]);
      if (haltRes.ok) setHaltStatus(await haltRes.json());
      if (staleRes.ok) setStaleness(await staleRes.json());
    } catch {
      // Fallback: show unknown state
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleHalt = async () => {
    if (!confirm('Are you sure you want to HALT all trading?')) return;
    setLoading(true);
    try {
      await fetch('/api/v1/risk/halt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'operator_manual_halt' }),
      });
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const handleResume = async () => {
    if (!confirm('Are you sure you want to RESUME trading?')) return;
    setLoading(true);
    try {
      await fetch('/api/v1/risk/resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operator: 'operator' }),
      });
      await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const isHalted = haltStatus?.halted ?? false;
  const staleCount = staleness?.stale_count ?? 0;
  const pausedInstruments = Object.keys(staleness?.paused_instruments ?? {});

  return (
    <div className="space-y-1">
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
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="text-xs text-slate-400 hover:text-slate-200 px-2 py-0.5 rounded border border-slate-600 hover:border-slate-400"
            >
              <Clock className="w-3 h-3 inline mr-1" />
              {haltStatus?.history_count} events
            </button>
          )}

          {/* Halt / Resume button */}
          {isHalted ? (
            <button
              onClick={handleResume}
              disabled={loading}
              className="flex items-center gap-1 text-xs font-medium bg-emerald-700 hover:bg-emerald-600 text-white px-3 py-1 rounded disabled:opacity-50"
            >
              <Play className="w-3 h-3" />
              Resume
            </button>
          ) : (
            <button
              onClick={handleHalt}
              disabled={loading}
              className="flex items-center gap-1 text-xs font-medium bg-red-700 hover:bg-red-600 text-white px-3 py-1 rounded disabled:opacity-50"
            >
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
                  {entry.action.toUpperCase()}
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
