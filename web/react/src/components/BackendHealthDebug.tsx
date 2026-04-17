/**
 * BackendHealthDebug — Dev-only floating panel showing health state transitions.
 *
 * Only renders when NODE_ENV === 'development'. Toggled via Ctrl+Shift+H.
 * Shows: offline status, consecutive failures, next retry countdown,
 * last success time, and a live log of state transitions.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useBackendHealth } from '../context/BackendHealthContext';
import { Activity, X, ChevronDown, ChevronUp } from 'lucide-react';

interface LogEntry {
  ts: number;
  message: string;
  type: 'success' | 'failure' | 'offline' | 'recovery';
}

const MAX_LOG_ENTRIES = 30;

export default function BackendHealthDebug() {
  // Only render in development.
  if (process.env.NODE_ENV !== 'development') return null;

  return <DebugPanel />;
}

function DebugPanel() {
  const health = useBackendHealth();
  const [visible, setVisible] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [countdownSec, setCountdownSec] = useState<number | null>(null);
  const prevOfflineRef = useRef(health.backendOffline);
  const prevFailuresRef = useRef(health.consecutiveFailures);

  // Track state transitions.
  useEffect(() => {
    const now = Date.now();

    if (health.backendOffline && !prevOfflineRef.current) {
      setLog(prev => [{ ts: now, message: 'Backend went OFFLINE', type: 'offline' as const }, ...prev].slice(0, MAX_LOG_ENTRIES));
    } else if (!health.backendOffline && prevOfflineRef.current) {
      setLog(prev => [{ ts: now, message: 'Backend RECOVERED', type: 'recovery' as const }, ...prev].slice(0, MAX_LOG_ENTRIES));
    }

    if (health.consecutiveFailures > prevFailuresRef.current) {
      setLog(prev => [{ ts: now, message: `Probe failure #${health.consecutiveFailures}`, type: 'failure' as const }, ...prev].slice(0, MAX_LOG_ENTRIES));
    } else if (health.consecutiveFailures === 0 && prevFailuresRef.current > 0) {
      setLog(prev => [{ ts: now, message: 'Probe succeeded \u2014 failures reset', type: 'success' as const }, ...prev].slice(0, MAX_LOG_ENTRIES));
    }

    prevOfflineRef.current = health.backendOffline;
    prevFailuresRef.current = health.consecutiveFailures;
  }, [health.backendOffline, health.consecutiveFailures]);

  // Countdown ticker.
  useEffect(() => {
    if (!visible || !health.nextRetryAt) { setCountdownSec(null); return; }
    const tick = () => {
      const remaining = Math.max(0, Math.ceil((health.nextRetryAt! - Date.now()) / 1000));
      setCountdownSec(remaining);
    };
    tick();
    const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [visible, health.nextRetryAt]);

  // Ctrl+Shift+H to toggle.
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'H') {
      e.preventDefault();
      setVisible(v => !v);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  if (!visible) return null;

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const typeColor: Record<LogEntry['type'], string> = {
    success: 'text-emerald-400',
    failure: 'text-red-400',
    offline: 'text-amber-400',
    recovery: 'text-blue-400',
  };

  return (
    <div className="fixed bottom-4 right-4 z-[9999] w-80 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl text-xs font-mono select-none"
         style={{ pointerEvents: 'auto' }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700 cursor-pointer"
           onClick={() => setCollapsed(c => !c)}>
        <Activity className={`w-3.5 h-3.5 ${health.backendOffline ? 'text-amber-400 animate-pulse' : 'text-emerald-400'}`} />
        <span className="text-slate-300 font-semibold text-[11px] uppercase tracking-wider flex-1">
          Backend Health
        </span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
          health.backendOffline
            ? 'bg-amber-600/30 text-amber-300'
            : 'bg-emerald-600/30 text-emerald-300'
        }`}>
          {health.backendOffline ? 'OFFLINE' : 'ONLINE'}
        </span>
        {collapsed ? <ChevronUp className="w-3 h-3 text-slate-500" /> : <ChevronDown className="w-3 h-3 text-slate-500" />}
        <button type="button" onClick={(e) => { e.stopPropagation(); setVisible(false); }}
                className="text-slate-500 hover:text-slate-300 ml-1">
          <X className="w-3 h-3" />
        </button>
      </div>

      {!collapsed && (
        <>
          {/* Stats */}
          <div className="px-3 py-2 space-y-1 border-b border-slate-800 text-slate-400">
            <div className="flex justify-between">
              <span>Consecutive failures:</span>
              <span className={health.consecutiveFailures > 0 ? 'text-red-400' : 'text-emerald-400'}>
                {health.consecutiveFailures}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Last success:</span>
              <span className="text-slate-300">
                {health.lastSuccessAt ? formatTime(health.lastSuccessAt) : '—'}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Next probe:</span>
              <span className="text-slate-300">
                {countdownSec !== null ? `${countdownSec}s` : '—'}
              </span>
            </div>
          </div>

          {/* Transition log */}
          <div className="px-3 py-2 max-h-40 overflow-y-auto">
            {log.length === 0 ? (
              <div className="text-slate-600 text-center py-2">No transitions yet</div>
            ) : (
              log.map((entry, i) => (
                <div key={i} className="flex gap-2 py-0.5">
                  <span className="text-slate-600 shrink-0">{formatTime(entry.ts)}</span>
                  <span className={typeColor[entry.type]}>{entry.message}</span>
                </div>
              ))
            )}
          </div>

          {/* Actions */}
          <div className="px-3 py-2 border-t border-slate-800 flex gap-2">
            <button type="button" onClick={health.probeNow}
                    className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-[10px] font-semibold">
              Probe Now
            </button>
            <button type="button" onClick={() => setLog([])}
                    className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-[10px] font-semibold">
              Clear Log
            </button>
            <span className="ml-auto text-slate-600 self-center">Ctrl+Shift+H</span>
          </div>
        </>
      )}
    </div>
  );
}
