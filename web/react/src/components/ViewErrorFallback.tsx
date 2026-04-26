/**
 * ViewErrorFallback - Fallback component for ErrorBoundary errors
 * 
 * Provides a user-friendly error display with retry functionality
 * when a view crashes during rendering.
 */

import { AlertTriangle, RefreshCw, Home } from '../ui/icons';

interface ViewErrorFallbackProps {
  viewName?: string;
  error?: Error;
  onRetry?: () => void;
  onGoHome?: () => void;
}

export function ViewErrorFallback({ 
  viewName, 
  error, 
  onRetry, 
  onGoHome 
}: ViewErrorFallbackProps) {
  return (
    <div className="flex h-full min-h-[400px] items-center justify-center p-6">
      <div className="max-w-md w-full rounded-2xl border border-red-500/30 bg-slate-900/90 p-8 text-center shadow-2xl backdrop-blur-sm">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-500/10">
          <AlertTriangle className="h-8 w-8 text-red-400" />
        </div>
        
        <h2 className="text-xl font-semibold text-white mb-2">
          {viewName ? `${viewName} Error` : 'View Error'}
        </h2>
        
        <p className="text-slate-400 mb-4">
          {viewName 
            ? `The ${viewName} view encountered an error and couldn't load.`
            : 'This view encountered an error and couldn\'t load.'}
        </p>
        
        {error?.message && (
          <div className="mb-6 rounded-lg bg-red-500/10 border border-red-500/20 p-3">
            <p className="text-xs text-red-300/80 font-mono break-words">
              {error.message}
            </p>
          </div>
        )}
        
        <div className="flex items-center justify-center gap-3">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Try Again
            </button>
          )}
          
          {onGoHome && (
            <button
              type="button"
              onClick={onGoHome}
              className="flex items-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 transition-colors"
            >
              <Home className="h-4 w-4" />
              Go to Overview
            </button>
          )}
        </div>
        
        <p className="mt-6 text-xs text-slate-500">
          If this error persists, please contact support with the error details above.
        </p>
      </div>
    </div>
  );
}
