import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBarProps {
  label: string;
  error: Error | null;
  onRetry?: () => void;
}

/**
 * Minimal inline error bar for components using useApiData.
 * Shows only when error is non-null. Displays error.message safely.
 */
export default function ErrorBar({ label, error, onRetry }: ErrorBarProps) {
  if (!error) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
      <AlertTriangle className="w-4 h-4 shrink-0" />
      <span className="truncate">{label}: {error?.message ?? 'Unknown error'}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="ml-auto shrink-0 text-slate-400 hover:text-white"
          title="Retry"
          aria-label="Retry"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
