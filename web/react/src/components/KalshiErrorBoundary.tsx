/**
 * KalshiErrorBoundary - Kalshi-branded error boundary for views
 * 
 * Provides a user-friendly error display with Kalshi branding
 * when a view crashes during rendering.
 * 
 * Tier 5: Add error boundaries to all views with Kalshi-branded errors
 */

import React, { ErrorInfo } from "react";
import { AlertTriangle, RefreshCw, Home, Activity } from '../ui/icons';
import { logUiError } from '../utils/logger';

interface KalshiErrorBoundaryProps {
  children: React.ReactNode;
  viewName?: string;
  onGoHome?: () => void;
}

interface KalshiErrorBoundaryState {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

export default class KalshiErrorBoundary extends React.Component<
  KalshiErrorBoundaryProps,
  KalshiErrorBoundaryState
> {
  state: KalshiErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(error: Error): Partial<KalshiErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ errorInfo: info });
    logUiError('KalshiErrorBoundary', 'View crashed during render', error, {
      viewName: this.props.viewName ?? 'unknown',
      componentStack: info.componentStack ?? undefined,
    });
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: undefined, errorInfo: undefined });
  };

  handleGoHome = () => {
    if (this.props.onGoHome) {
      this.props.onGoHome();
    } else {
      window.location.hash = '#/overview';
    }
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const { viewName } = this.props;
    const { error } = this.state;

    return (
      <div className="flex h-full min-h-[400px] items-center justify-center p-6">
        <div className="max-w-md w-full rounded-2xl border border-purple-500/30 bg-slate-900/90 p-8 text-center shadow-2xl backdrop-blur-sm">
          {/* Kalshi-branded icon */}
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-purple-500/10">
            <AlertTriangle className="h-8 w-8 text-purple-400" />
          </div>
          
          {/* Error title */}
          <h2 className="text-xl font-semibold text-white mb-2 flex items-center justify-center gap-2">
            <Activity className="w-5 h-5 text-purple-400" />
            {viewName ? `${viewName} Error` : 'View Error'}
          </h2>
          
          {/* Error message */}
          <p className="text-slate-400 mb-4">
            {viewName 
              ? `The ${viewName} view encountered an error and couldn't load.`
              : 'This view encountered an error and couldn\'t load.'}
          </p>
          
          {/* Technical details */}
          {error?.message && (
            <div className="mb-6 rounded-lg bg-purple-500/10 border border-purple-500/20 p-3">
              <p className="text-xs text-purple-300/80 font-mono break-words">
                {error.message}
              </p>
            </div>
          )}
          
          {/* Action buttons */}
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={this.handleRetry}
              className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
              Try Again
            </button>
            
            <button
              type="button"
              onClick={this.handleGoHome}
              className="flex items-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600 transition-colors"
            >
              <Home className="h-4 w-4" />
              Go to Overview
            </button>
          </div>
          
          {/* Support message */}
          <p className="mt-6 text-xs text-slate-500">
            If this error persists, please contact support with the error details above.
          </p>
        </div>
      </div>
    );
  }
}
