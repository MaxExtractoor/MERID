import { useState, useEffect, useRef, useCallback } from 'react';
import { ShieldCheck, ShieldOff, X } from 'lucide-react';
import { useExecutionGate } from '../hooks/useExecutionGate';

interface Toast {
  id: number;
  type: 'blocked' | 'clear';
  message: string;
  hint: string | null;
  timestamp: number;
}

let _nextId = 0;

/**
 * Detects execution gate state transitions and shows a temporary toast.
 * Renders fixed in the bottom-right corner.
 */
export function GateChangeToast() {
  const { blocked, blockSummary, topHint } = useExecutionGate();
  const prevBlocked = useRef<boolean | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  useEffect(() => {
    // Skip the very first render (no transition yet)
    if (prevBlocked.current === null) {
      prevBlocked.current = blocked;
      return;
    }

    // Only fire on actual transitions
    if (blocked === prevBlocked.current) return;
    prevBlocked.current = blocked;

    const id = ++_nextId;
    const toast: Toast = blocked
      ? { id, type: 'blocked', message: blockSummary || 'Execution blocked', hint: topHint, timestamp: Date.now() }
      : { id, type: 'clear', message: 'All safety checks passed — trading permitted', hint: null, timestamp: Date.now() };

    setToasts(prev => [...prev, toast]);

    // Auto-dismiss after 8 seconds
    const timer = setTimeout(() => dismiss(id), 8000);
    return () => clearTimeout(timer);
  }, [blocked, blockSummary, topHint, dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map(toast => (
        <div
          key={toast.id}
          className={`flex items-start gap-2.5 rounded-lg border px-4 py-3 shadow-xl animate-in slide-in-from-right-5 ${
            toast.type === 'blocked'
              ? 'bg-red-950/95 border-red-700/50 text-red-200'
              : 'bg-emerald-950/95 border-emerald-700/50 text-emerald-200'
          }`}
        >
          {toast.type === 'blocked' ? (
            <ShieldOff className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          ) : (
            <ShieldCheck className="w-5 h-5 text-emerald-400 flex-shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold">
              {toast.type === 'blocked' ? 'Execution BLOCKED' : 'Execution CLEAR'}
            </p>
            <p className="text-xs opacity-80 mt-0.5 truncate">{toast.message}</p>
            {toast.hint && (
              <p className="text-[10px] opacity-60 mt-1 italic">→ {toast.hint}</p>
            )}
          </div>
          <button
            type="button"
            onClick={() => dismiss(toast.id)}
            className="p-0.5 rounded hover:bg-white/10 flex-shrink-0"
            aria-label="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
