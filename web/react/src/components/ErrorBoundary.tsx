import React, { ErrorInfo } from "react";
import { AlertTriangle, RefreshCw } from '../ui/icons';
import { logUiError } from '../utils/logger';

type ErrorCategory = 'network' | 'render' | 'state' | 'unknown';
type ErrorSeverity = 'low' | 'medium' | 'high' | 'critical';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  viewName?: string;
  enhanced?: boolean;
  fallback?: React.ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo, componentStack: string) => void;
  maxRetries?: number;
  enableRetry?: boolean;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
  retryCount: number;
}

// Error categorization (enhanced mode)
const categorizeError = (error: Error): ErrorCategory => {
  if (error.message?.includes('Network') || error.message?.includes('fetch')) return 'network';
  if (error.message?.includes('Cannot read property') || error.message?.includes('undefined')) return 'render';
  if (error.message?.includes('setState') || error.message?.includes('hook')) return 'state';
  return 'unknown';
};

const getErrorSeverity = (error: Error): ErrorSeverity => {
  const category = categorizeError(error);
  if (category === 'network') return 'medium';
  if (category === 'render') return 'high';
  if (category === 'state') return 'critical';
  return 'low';
};

const getUserFriendlyMessage = (_error: Error, category: ErrorCategory): string => {
  switch (category) {
    case 'network': return 'A network connection issue occurred. Please check your connection and try again.';
    case 'render': return 'A display issue occurred. The component has been reset.';
    case 'state': return 'An internal state issue occurred. The component has been reset.';
    default: return 'An unexpected error occurred. The component has been reset.';
  }
};

export default class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = {
    hasError: false,
    retryCount: 0,
  };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ errorInfo: info });
    logUiError('ErrorBoundary', 'View crashed during render', error, {
      viewName: this.props.viewName ?? 'unknown',
      componentStack: info.componentStack ?? undefined,
    });
    this.props.onError?.(error, info, info.componentStack ?? '');
  }

  handleRetry = () => {
    const maxRetries = this.props.maxRetries ?? 3;
    if (this.state.retryCount < maxRetries) {
      this.setState(prev => ({ hasError: false, error: undefined, retryCount: prev.retryCount + 1 }));
    }
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const { enhanced, fallback, maxRetries = 3, enableRetry = true } = this.props;
    const { error, retryCount } = this.state;

    // Custom fallback if provided
    if (fallback) return <>{fallback}</>;

    // Enhanced error UI
    if (enhanced && error) {
      const category = categorizeError(error);
      const severity = getErrorSeverity(error);
      const userMessage = getUserFriendlyMessage(error, category);
      const canRetry = enableRetry && retryCount < maxRetries;

      const getSeverityColor = () => {
        switch (severity) {
          case 'critical': return 'text-red-400 border-red-500/30 bg-red-500/10';
          case 'high': return 'text-orange-400 border-orange-500/30 bg-orange-500/10';
          case 'medium': return 'text-amber-400 border-amber-500/30 bg-amber-500/10';
          default: return 'text-gray-400 border-gray-500/30 bg-gray-500/10';
        }
      };

      return (
        <div className={`rounded-xl p-6 border ${getSeverityColor()} m-4`}>
          <div className="flex items-center gap-3 mb-4">
            <AlertTriangle className="h-6 w-6" />
            <h3 className="text-lg font-semibold">Component Error</h3>
          </div>
          <div className="mb-4">
            <p className="text-sm text-gray-300 mb-2">{userMessage}</p>
            <details className="text-xs text-gray-400">
              <summary className="cursor-pointer hover:text-gray-300 mb-2">Technical Details</summary>
              <div className="mt-2 space-y-2">
                <div><strong>Type:</strong> {category}</div>
                <div><strong>Severity:</strong> {severity}</div>
                <div><strong>Message:</strong> {error.message}</div>
              </div>
            </details>
          </div>
          <div className="flex items-center gap-3">
            {canRetry && (
              <button onClick={this.handleRetry} className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded">
                <RefreshCw className="h-4 w-4" /> Retry ({retryCount}/{maxRetries})
              </button>
            )}
            <button onClick={this.handleReload} className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded">
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    // Base error UI
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-md rounded-2xl border border-red-500/30 bg-slate-900/70 p-6 text-center shadow-xl">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10">
            <AlertTriangle className="h-6 w-6 text-red-400" />
          </div>
          <h2 className="text-lg font-semibold text-white">View error</h2>
          <p className="mt-2 text-sm text-slate-400">
            {this.props.viewName ? `The ${this.props.viewName} view crashed.` : "This view crashed."}
          </p>
          {error?.message && <p className="mt-2 text-xs text-red-300/80">{error.message}</p>}
          <div className="mt-4 flex items-center justify-center gap-2">
            <button onClick={this.handleRetry} className="inline-flex items-center gap-2 rounded-lg border border-slate-700/60 bg-slate-800/80 px-3 py-2 text-xs text-slate-200 hover:border-slate-600/80">
              <RefreshCw className="h-3.5 w-3.5" /> Try again
            </button>
            <button onClick={this.handleReload} className="inline-flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200 hover:border-red-400/60">
              Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}
