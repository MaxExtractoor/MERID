/**
 * ToastProvider — zero-dependency toast notification system.
 *
 * Wrap your app with <ToastProvider> and use the `useToast` hook to
 * push notifications from anywhere in the component tree.
 *
 * Usage:
 *   const { toast } = useToast();
 *   toast({ type: 'error', title: 'Fetch failed', message: 'Could not load positions' });
 */

import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { AlertTriangle, CheckCircle, Info, X, XCircle } from '../ui/icons';

// ── Types ────────────────────────────────────────────────────────────

export type ToastType = 'error' | 'warning' | 'success' | 'info';

export interface ToastItem {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  durationMs?: number;
}

export interface ToastOptions {
  type: ToastType;
  title: string;
  message?: string;
  /** Auto-dismiss after this many ms. Default: 5000. Set 0 to persist. */
  durationMs?: number;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

// ── Context ──────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}

// ── Provider ─────────────────────────────────────────────────────────

const MAX_TOASTS = 5;
const DEFAULT_DURATION = 5000;

let nextId = 0;

export default function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const dismissAll = useCallback(() => {
    setToasts([]);
    timersRef.current.forEach(t => clearTimeout(t));
    timersRef.current.clear();
  }, []);

  const toast = useCallback((options: ToastOptions) => {
    const id = `toast-${++nextId}`;
    const item: ToastItem = { id, ...options };

    setToasts(prev => {
      const next = [...prev, item];
      return next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next;
    });

    const duration = options.durationMs ?? DEFAULT_DURATION;
    if (duration > 0) {
      const timer = setTimeout(() => {
        dismiss(id);
      }, duration);
      timersRef.current.set(id, timer);
    }
  }, [dismiss]);

  // Cleanup on unmount
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach(t => clearTimeout(t));
      timers.clear();
    };
  }, []);

  return (
    <ToastContext.Provider value={{ toast, dismiss, dismissAll }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

// ── Rendering ────────────────────────────────────────────────────────

const ICON_MAP: Record<ToastType, typeof AlertTriangle> = {
  error: XCircle,
  warning: AlertTriangle,
  success: CheckCircle,
  info: Info,
};

const COLOR_MAP: Record<ToastType, { border: string; bg: string; icon: string; title: string }> = {
  error:   { border: 'border-red-500/40',    bg: 'bg-red-500/10',    icon: 'text-red-400',    title: 'text-red-200' },
  warning: { border: 'border-amber-500/40',  bg: 'bg-amber-500/10',  icon: 'text-amber-400',  title: 'text-amber-200' },
  success: { border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', icon: 'text-emerald-400', title: 'text-emerald-200' },
  info:    { border: 'border-blue-500/40',   bg: 'bg-blue-500/10',   icon: 'text-blue-400',   title: 'text-blue-200' },
};

function ToastContainer({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm w-full pointer-events-none"
    >
      {toasts.map(t => {
        const Icon = ICON_MAP[t.type];
        const colors = COLOR_MAP[t.type];
        return (
          <div
            key={t.id}
            role="alert"
            className={`pointer-events-auto flex items-start gap-3 rounded-lg border ${colors.border} ${colors.bg} backdrop-blur-md p-3 shadow-lg shadow-black/20 animate-slide-in-right`}
          >
            <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${colors.icon}`} />
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium ${colors.title}`}>{t.title}</p>
              {t.message && (
                <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">{t.message}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              className="flex-shrink-0 text-slate-500 hover:text-slate-300 transition-colors"
              title="Dismiss notification"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
